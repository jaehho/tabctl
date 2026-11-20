"""The CLI's side of the host's socket."""

import json
import os
import socket
import tempfile
from collections.abc import Mapping
from pathlib import Path

REQUEST_TIMEOUT_S = 6.0


class TabctlError(Exception):
    """A request that the host or Firefox could not carry out."""


def find_socket(environ: Mapping[str, str]) -> Path:
    """Where the host listens, under XDG_RUNTIME_DIR when it is set."""
    runtime = environ.get("XDG_RUNTIME_DIR") or (
        Path(tempfile.gettempdir()) / f"tabctl-{os.getuid()}"
    )
    return Path(runtime) / "tabctl" / "host.sock"


def send_request(
    path: Path,
    command: str,
    args: dict,
    *,
    timeout: float = REQUEST_TIMEOUT_S,
):
    """Send one request through the host and return Firefox's result."""
    line = json.dumps({"cmd": command, "args": args}).encode() + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(path))
            sock.sendall(line)
            reply_line = sock.makefile("rb").readline()
    except (FileNotFoundError, ConnectionRefusedError):
        raise TabctlError(
            "Firefox is not connected: is it running, with the tabctl "
            "extension installed?"
        ) from None
    except TimeoutError:
        raise TabctlError(f"no answer within {timeout:g} s") from None
    if not reply_line:
        raise TabctlError("the host closed the connection without answering")
    reply = json.loads(reply_line)
    if not reply.get("ok"):
        raise TabctlError(reply.get("error", "Firefox gave no reason"))
    return reply.get("result")
