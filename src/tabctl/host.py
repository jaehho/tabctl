"""The native messaging host: it relays the CLI's requests to Firefox.

Firefox starts it when the extension connects and stops it when the
port closes. Firefox and the host trade JSON objects, each behind its
length as a 4-byte unsigned integer in native byte order. The CLI
reaches the host through a Unix socket, one JSON object per line each
way: {"cmd", "args"} in, {"ok", "result" | "error"} out.
"""

import asyncio
import itertools
import json
import signal
import socket
import struct
import sys
from collections.abc import Callable
from pathlib import Path

from tabctl import __version__

LENGTH = struct.Struct("=I")
REPLY_TIMEOUT_S = 4.0


class HostRunningError(Exception):
    """Another live host already listens on the socket."""


def encode_native(message: dict) -> bytes:
    """Frame message for Firefox: its length, then its JSON."""
    body = json.dumps(message).encode()
    return LENGTH.pack(len(body)) + body


async def read_native(reader: asyncio.StreamReader) -> dict:
    """The next message from Firefox.

    Raises asyncio.IncompleteReadError once Firefox closes the pipe.
    """
    (size,) = LENGTH.unpack(await reader.readexactly(LENGTH.size))
    return json.loads(await reader.readexactly(size))


class Relay:
    """Requests sent to the extension, each awaiting its reply by id."""

    def __init__(self, send: Callable[[dict], None]):
        self._send = send
        self._ids = itertools.count(1)
        self._waiting: dict[int, asyncio.Future] = {}

    async def ask(self, command: str, args: dict, *, timeout: float):
        """Send one request and return the extension's reply to it."""
        request_id = next(self._ids)
        reply = asyncio.get_running_loop().create_future()
        self._waiting[request_id] = reply
        try:
            self._send({"id": request_id, "cmd": command, "args": args})
            return await asyncio.wait_for(reply, timeout)
        finally:
            self._waiting.pop(request_id, None)

    def settle(self, message: dict) -> None:
        """Hand a reply from the extension to the request it answers."""
        reply = self._waiting.get(message.get("id"))
        if reply is not None and not reply.done():
            reply.set_result(message)


async def answer_request(relay: Relay, line: bytes, *, timeout: float):
    """The reply to one request line from the CLI."""
    try:
        request = json.loads(line)
        command, args = request["cmd"], request.get("args", {})
    except (ValueError, KeyError, TypeError) as error:
        return {"ok": False, "error": f"bad request: {error!r}"}
    try:
        reply = await relay.ask(command, args, timeout=timeout)
    except TimeoutError:
        return {
            "ok": False,
            "error": f"Firefox did not answer within {timeout:g} s",
        }
    except OSError as error:
        return {"ok": False, "error": f"cannot reach Firefox: {error}"}
    return {k: reply[k] for k in ("ok", "result", "error") if k in reply}


def claim_socket(path: Path) -> socket.socket:
    """A socket listening at path, for this user only.

    A socket file left by a host that died is replaced. Raises
    HostRunningError when a live host answers there.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(str(path))
            except (ConnectionRefusedError, FileNotFoundError):
                path.unlink(missing_ok=True)
            else:
                raise HostRunningError(
                    f"a tabctl host already listens at {path}"
                )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen()
    return listener


async def run_host(path: Path, *, timeout: float = REPLY_TIMEOUT_S) -> None:
    """Relay requests on the socket at path until Firefox lets go."""
    loop = asyncio.get_running_loop()
    from_firefox = asyncio.StreamReader()
    await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(from_firefox), sys.stdin.buffer
    )

    def send(message: dict) -> None:
        sys.stdout.buffer.write(encode_native(message))
        sys.stdout.buffer.flush()

    relay = Relay(send)

    async def serve(reader, writer):
        try:
            line = await reader.readline()
            reply = await answer_request(relay, line, timeout=timeout)
            writer.write(json.dumps(reply).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()

    async def pass_replies():
        while True:
            try:
                relay.settle(await read_native(from_firefox))
            except asyncio.IncompleteReadError:
                return

    server = await asyncio.start_unix_server(serve, sock=claim_socket(path))
    stop = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    send({"hello": __version__})
    tasks = {
        asyncio.create_task(pass_replies()),
        asyncio.create_task(stop.wait()),
    }
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        server.close()
        path.unlink(missing_ok=True)
