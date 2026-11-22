"""Submodule gitlinks are not materialized by a working-tree git apply."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import PatchTransitError, evaluate, inspect_patch, patch_metadata


class GitlinkPatchPreflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.module = self.repo / "vendor" / "module"
        self.module.mkdir(parents=True)
        for directory in (self.repo, self.module):
            self.git(directory, "init", "-q")
            self.git(directory, "config", "user.name", "Fixture")
            self.git(directory, "config", "user.email", "fixture@example.invalid")
        (self.repo / "readme.txt").write_text("base\n", encoding="utf-8")
        self.git(self.repo, "add", "readme.txt")
        self.git(self.repo, "commit", "-qm", "base")
        (self.module / "module.txt").write_text("first\n", encoding="utf-8")
        self.git(self.module, "add", ".")
        self.git(self.module, "commit", "-qm", "first")

    def git(self, directory: Path, *args: str) -> bytes:
        return subprocess.run(
            ["git", *args], cwd=directory, capture_output=True, check=True
        ).stdout

    def write_patch(self) -> Path:
        patch = self.root / "changes.patch"
        patch.write_bytes(self.git(self.repo, "diff", "--cached", "--binary"))
        return patch

    def test_added_gitlink_rejected_before_identity_comparison(self):
        self.git(self.repo, "add", "vendor/module")
        patch = self.write_patch()
        self.assertIn(b"new file mode 160000", patch.read_bytes())
        with self.assertRaisesRegex(PatchTransitError, "submodules are unsupported"):
            evaluate(self.repo, "HEAD", None, patch)
        with self.assertRaisesRegex(PatchTransitError, "submodules are unsupported"):
            inspect_patch(patch)

    def test_modified_gitlink_is_detected_by_index_mode(self):
        self.git(self.repo, "add", "vendor/module")
        self.git(self.repo, "commit", "-qm", "add gitlink")
        (self.module / "module.txt").write_text("second\n", encoding="utf-8")
        self.git(self.module, "add", ".")
        self.git(self.module, "commit", "-qm", "second")
        self.git(self.repo, "add", "vendor/module")
        patch = self.write_patch()
        self.assertIn(b" 160000\n", patch.read_bytes())
        with self.assertRaisesRegex(PatchTransitError, "submodules are unsupported"):
            patch_metadata(patch)

    def test_deleted_gitlink_is_rejected(self):
        self.git(self.repo, "add", "vendor/module")
        self.git(self.repo, "commit", "-qm", "add gitlink")
        self.git(self.repo, "rm", "--cached", "vendor/module")
        patch = self.write_patch()
        self.assertIn(b"deleted file mode 160000", patch.read_bytes())
        with self.assertRaisesRegex(PatchTransitError, "submodules are unsupported"):
            patch_metadata(patch)

    def test_metadata_like_file_contents_remain_valid(self):
        contents = "index 1234567..abcdef0 160000\nnew file mode 160000\n"
        (self.repo / "readme.txt").write_text(contents, encoding="utf-8")
        self.git(self.repo, "add", "readme.txt")
        patch = self.write_patch()
        self.assertEqual(["readme.txt"], patch_metadata(patch)["files"])
        outcome = evaluate(self.repo, "HEAD", None, patch)
        self.assertEqual("changed", outcome["verdict"])
