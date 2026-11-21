"""Patch-created symlinks must satisfy the same safety rules as base-tree links."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import PatchTransitError, evaluate, inventory


@unittest.skipIf(sys.platform == "win32", "Symlinks may require elevated privileges")
class PatchedSymlinkSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (
            ("git", "init", "-q"),
            ("git", "config", "user.name", "Fixture"),
            ("git", "config", "user.email", "fixture@example.invalid"),
        ):
            subprocess.run(args, cwd=self.repo, capture_output=True, check=True)
        (self.repo / "file.txt").write_text("safe\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def patch_with_symlink(self, name: str, target: str) -> Path:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        self.git("add", name)
        patch = self.root / "change.patch"
        patch.write_bytes(self.git("diff", "--cached", "--binary"))
        return patch

    def test_absolute_target_from_patch_is_rejected(self):
        patch = self.patch_with_symlink("external", "/etc/passwd")
        with self.assertRaisesRegex(PatchTransitError, "absolute target"):
            evaluate(self.repo, "HEAD", None, patch)

    def test_relative_escape_from_patch_is_rejected(self):
        patch = self.patch_with_symlink("nested/escape", "../../secrets")
        with self.assertRaisesRegex(PatchTransitError, "escapes checkout"):
            evaluate(self.repo, "HEAD", None, patch)

    def test_valid_internal_symlink_from_patch_is_preserved(self):
        patch = self.patch_with_symlink("alias", "file.txt")
        result = evaluate(self.repo, "HEAD", None, patch)
        self.assertEqual("changed", result["verdict"])
        self.assertEqual("alias", result["changes"][0]["path"])

    def test_inventory_rejects_existing_external_symlink(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "external").symlink_to("/etc/passwd")
        with self.assertRaisesRegex(PatchTransitError, "absolute target"):
            inventory(candidate)

    def test_broken_internal_symlink_is_allowed(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "missing").symlink_to("file-not-here")
        self.assertEqual("file-not-here", inventory(candidate)["missing"][1])
