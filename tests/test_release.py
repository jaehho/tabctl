"""What installed copies poll for updates, as committed.

Firefox skips a malformed update manifest without a word, so its
shape is checked here, along with the manifest's pointer to it.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_UPDATES = (
    "https://raw.githubusercontent.com/jaehho/tabctl/main/updates.json"
)
RELEASE_LINK = re.compile(
    r"https://github\.com/jaehho/tabctl/releases/download/"
    r"v(?P<tag>[\d.]+)/tabctl-(?P<file>[\d.]+)\.xpi"
)


def version_key(text):
    return tuple(int(n) for n in text.split("."))


class UpdateManifest(unittest.TestCase):
    def setUp(self):
        manifest = json.loads((ROOT / "extension/manifest.json").read_text())
        self.gecko = manifest["browser_specific_settings"]["gecko"]
        self.version = manifest["version"]
        self.updates = json.loads((ROOT / "updates.json").read_text())

    def test_the_extension_polls_this_repo(self):
        self.assertEqual(self.gecko["update_url"], RAW_UPDATES)

    def test_lists_the_extension_by_its_id(self):
        self.assertEqual(list(self.updates["addons"]), [self.gecko["id"]])

    def test_each_entry_names_its_release_and_hash(self):
        entries = self.updates["addons"][self.gecko["id"]]["updates"]
        for entry in entries:
            with self.subTest(entry["version"]):
                link = RELEASE_LINK.fullmatch(entry["update_link"])
                self.assertIsNotNone(link, entry["update_link"])
                self.assertEqual(link["tag"], entry["version"])
                self.assertEqual(link["file"], entry["version"])
                self.assertRegex(entry["update_hash"], r"sha256:[0-9a-f]{64}")
        versions = [version_key(e["version"]) for e in entries]
        self.assertEqual(versions, sorted(set(versions)))

    def test_lists_nothing_newer_than_the_tree(self):
        entries = self.updates["addons"][self.gecko["id"]]["updates"]
        for entry in entries:
            self.assertLessEqual(
                version_key(entry["version"]), version_key(self.version)
            )


if __name__ == "__main__":
    unittest.main()
