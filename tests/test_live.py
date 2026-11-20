"""The launcher runs the checkout it names, under both its names."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tabctl import __version__
from tabctl.host import LENGTH

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "scripts" / "tabctl-live"


def run(command, **env):
    return subprocess.run(
        [str(command), *env.pop("args", ["--version"])],
        env={
            **{k: v for k, v in os.environ.items() if k != "TABCTL_SRC"},
            **env,
        },
        # A pipe, as Firefox gives the host, closed at once.
        input=b"",
        capture_output=True,
        check=False,
        timeout=10,
    )


class Launcher(unittest.TestCase):
    def test_runs_the_tree_it_sits_in(self):
        out = run(LIVE)
        self.assertEqual(out.stdout.decode().strip(), f"tabctl {__version__}")

    def test_refuses_a_missing_tree(self):
        out = run(LIVE, TABCTL_SRC="/nonexistent")
        self.assertEqual(out.returncode, 1)
        self.assertIn(b"no checkout at /nonexistent", out.stderr)

    def test_installed_copy_runs_its_checkout_and_hosts_by_name(self):
        with tempfile.TemporaryDirectory() as scratch:
            bin_dir = Path(scratch) / "bin"
            bin_dir.mkdir()
            installed = bin_dir / "tabctl"
            installed.write_text(
                LIVE.read_text().replace(
                    'DEFAULT_ROOT="@ROOT@"', f'DEFAULT_ROOT="{ROOT}"', 1
                )
            )
            installed.chmod(0o755)
            host = bin_dir / "tabctl-native-host"
            host.symlink_to("tabctl")
            self.assertEqual(run(installed).returncode, 0)
            # With stdin closed the host greets, finds Firefox gone and
            # exits.
            out = run(
                host,
                args=["manifest.json", "tabctl@jaeho.dev"],
                XDG_RUNTIME_DIR=scratch,
            )
            self.assertEqual(out.returncode, 0, out.stderr)
            (size,) = LENGTH.unpack(out.stdout[: LENGTH.size])
            self.assertIn(b"hello", out.stdout[LENGTH.size :][:size])


if __name__ == "__main__":
    unittest.main()
