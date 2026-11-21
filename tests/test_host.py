"""The host as Firefox runs it: a process speaking native messaging.

Each test stands in for the extension on the host's stdin and stdout
and for the CLI on its socket, in a scratch XDG_RUNTIME_DIR.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tabctl.client import TabctlError, find_socket, send_request
from tabctl.host import LENGTH, encode_native

SRC = Path(__file__).resolve().parent.parent / "src"


def read_frame(stream) -> dict:
    (size,) = LENGTH.unpack(stream.read(LENGTH.size))
    return json.loads(stream.read(size))


def send_frame(host: subprocess.Popen, message: dict) -> None:
    host.stdin.write(encode_native(message))
    host.stdin.flush()


def make_raw_tab(tab_id: int, url: str) -> dict:
    return {
        "id": tab_id,
        "windowId": 1,
        "index": tab_id,
        "groupId": -1,
        "url": url,
        "title": "",
        "active": False,
        "pinned": False,
        "lastAccessed": 1,
    }


class Host(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        self.addCleanup(self.runtime.cleanup)
        self.rules = Path(self.runtime.name) / "config/tabctl/groups.toml"
        self.env = {
            **os.environ,
            "XDG_RUNTIME_DIR": self.runtime.name,
            "XDG_CONFIG_HOME": str(self.rules.parent.parent),
            "PYTHONPATH": str(SRC),
        }
        self.sock = find_socket(self.env)

    def start_host(self) -> subprocess.Popen:
        host = subprocess.Popen(
            [sys.executable, "-m", "tabctl", "native-host", "manifest", "id"],
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Cleanups run last first: kill, then close the pipes and wait.
        self.addCleanup(host.__exit__, None, None, None)
        self.addCleanup(host.kill)
        return host

    def write_rules(self, text: str) -> None:
        self.rules.parent.mkdir(parents=True)
        self.rules.write_text(text)

    def test_says_hello_then_relays_a_request_and_its_reply(self):
        host = self.start_host()
        self.assertIn("hello", read_frame(host.stdout))
        results = []
        cli = threading.Thread(
            target=lambda: results.append(
                send_request(self.sock, "list", {"x": 1})
            )
        )
        cli.start()
        request = read_frame(host.stdout)
        self.assertEqual((request["cmd"], request["args"]), ("list", {"x": 1}))
        host.stdin.write(
            encode_native({"id": request["id"], "ok": True, "result": [42]})
        )
        host.stdin.flush()
        cli.join(5)
        self.assertEqual(results, [[42]])

    def test_an_error_from_the_extension_reaches_the_cli(self):
        host = self.start_host()
        read_frame(host.stdout)
        errors = []

        def ask():
            try:
                send_request(self.sock, "open", {})
            except TabctlError as error:
                errors.append(str(error))

        cli = threading.Thread(target=ask)
        cli.start()
        request = read_frame(host.stdout)
        host.stdin.write(
            encode_native({"id": request["id"], "ok": False, "error": "no"})
        )
        host.stdin.flush()
        cli.join(5)
        self.assertEqual(errors, ["no"])

    def test_a_second_host_leaves_the_first_alone(self):
        first = self.start_host()
        read_frame(first.stdout)
        second = self.start_host()
        self.assertEqual(second.wait(5), 1)
        self.assertIn(b"already listens", second.stderr.read())
        self.assertIsNone(first.poll())

    def test_exits_and_removes_its_socket_when_firefox_lets_go(self):
        host = self.start_host()
        read_frame(host.stdout)
        self.assertTrue(self.sock.exists())
        host.stdin.close()
        self.assertEqual(host.wait(5), 0)
        self.assertFalse(self.sock.exists())

    def test_replaces_a_socket_left_by_a_dead_host(self):
        host = self.start_host()
        read_frame(host.stdout)
        host.kill()
        host.wait()
        self.assertTrue(self.sock.exists())
        again = self.start_host()
        self.assertIn("hello", read_frame(again.stdout))

    def test_without_a_host_the_cli_says_firefox_is_not_connected(self):
        with self.assertRaisesRegex(TabctlError, "not connected"):
            send_request(self.sock, "list", {})

    def test_puts_a_tab_whose_address_changed_in_its_rules_group(self):
        self.write_rules(
            '[[group]]\ntitle = "docs"\ncolor = "green"\n'
            'urls = ["https://docs.*"]\n'
        )
        host = self.start_host()
        read_frame(host.stdout)
        send_frame(host, {"event": "url", "tabId": 7})
        request = read_frame(host.stdout)
        self.assertEqual(request["cmd"], "list")
        listing = {
            "windows": [{"id": 1, "focused": True, "incognito": False}],
            "groups": [],
            "tabs": [
                make_raw_tab(7, "https://docs.python.org/"),
                make_raw_tab(8, "https://docs.rs/"),
            ],
        }
        send_frame(host, {"id": request["id"], "ok": True, "result": listing})
        request = read_frame(host.stdout)
        self.assertEqual(
            (request["cmd"], request["args"]),
            (
                "group",
                {
                    "tabIds": [7],
                    "windowId": 1,
                    "title": "docs",
                    "color": "green",
                    "collapsed": None,
                },
            ),
        )

    def test_a_broken_rules_file_leaves_the_host_relaying(self):
        self.write_rules("[[group]\n")
        host = self.start_host()
        read_frame(host.stdout)
        send_frame(host, {"event": "url", "tabId": 7})
        cli = threading.Thread(
            target=send_request, args=(self.sock, "ls-probe", {}), daemon=True
        )
        cli.start()
        self.assertEqual(read_frame(host.stdout)["cmd"], "ls-probe")

    def test_a_silent_extension_times_out(self):
        host = self.start_host()
        read_frame(host.stdout)
        start = time.monotonic()
        with self.assertRaisesRegex(TabctlError, "did not answer"):
            send_request(self.sock, "list", {})
        self.assertLess(time.monotonic() - start, 6)


if __name__ == "__main__":
    unittest.main()
