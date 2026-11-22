from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, apply_patch, patch_metadata


class PatchEntryBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(("git", "init", "-q"), cwd=self.repo, check=True)

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def test_many_files_fail_before_apply(self):
        for index in range(6):
            (self.repo / f"new-{index}.txt").touch()
        self.git("add", ".")
        diff = self.root / "many.patch"
        diff.write_bytes(self.git("diff", "--cached", "--binary"))
        target = self.root / "candidate"
        target.mkdir()
        with patch("patchtransit.core.MAX_TREE_ENTRIES", 3):
            with self.assertRaisesRegex(PatchTransitError, "maximum entry count"):
                patch_metadata(diff)
            with self.assertRaisesRegex(PatchTransitError, "maximum entry count"):
                apply_patch(target, diff)
        self.assertEqual([], list(target.iterdir()))

    def test_limit_is_inclusive(self):
        for index in range(3):
            (self.repo / f"new-{index}.txt").touch()
        self.git("add", ".")
        diff = self.root / "three.patch"
        diff.write_bytes(self.git("diff", "--cached", "--binary"))
        target = self.root / "candidate"
        target.mkdir()
        with patch("patchtransit.core.MAX_TREE_ENTRIES", 3):
            self.assertEqual(3, len(patch_metadata(diff)["files"]))
            apply_patch(target, diff)
        self.assertEqual(3, len(list(target.iterdir())))

    def test_rename_counts_one_change(self):
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        source = self.repo / "before.txt"
        source.write_text("text\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.git("mv", "before.txt", "after.txt")
        diff = self.root / "rename.patch"
        diff.write_bytes(self.git("diff", "--cached", "-M"))
        with patch("patchtransit.core.MAX_TREE_ENTRIES", 1):
            metadata = patch_metadata(diff)
        self.assertEqual({"before.txt", "after.txt"}, set(metadata["files"]))


if __name__ == "__main__":
    unittest.main()
