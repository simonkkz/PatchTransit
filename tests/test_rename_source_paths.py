"""Renames have two paths; both must be included and checked in inspection."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import PatchTransitError, evaluate, patch_metadata


class RenameSourcePaths(unittest.TestCase):
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
        (self.repo / "old name.txt").write_text(
            "".join(f"line {i}\n" for i in range(10)), encoding="utf-8"
        )
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, check=True, capture_output=True
        ).stdout

    def test_rename_includes_both_old_and_new_paths(self):
        self.git("mv", "old name.txt", "new name.txt")
        diff = self.root / "rename.patch"
        diff.write_bytes(self.git("diff", "--cached", "-M"))
        inspected = patch_metadata(diff)
        self.assertEqual(["new name.txt", "old name.txt"], inspected["files"])
        self.assertEqual((0, 0), (inspected["added_lines"], inspected["removed_lines"]))
        effective = evaluate(self.repo, "HEAD", None, diff)
        self.assertEqual(
            {"old name.txt", "new name.txt"}, {c["path"] for c in effective["changes"]}
        )
        self.assertEqual("changed", effective["verdict"])

    def test_modified_rename_keeps_forward_line_counts(self):
        self.git("mv", "old name.txt", "new name.txt")
        (self.repo / "new name.txt").write_text(
            "".join("changed\n" if i == 2 else f"line {i}\n" for i in range(10)),
            encoding="utf-8",
        )
        self.git("add", "-A")
        diff = self.root / "renamed-modified.patch"
        diff.write_bytes(self.git("diff", "--cached", "-M"))
        metadata = patch_metadata(diff)
        self.assertEqual({"old name.txt", "new name.txt"}, set(metadata["files"]))
        self.assertEqual((1, 1), (metadata["added_lines"], metadata["removed_lines"]))

    def test_unsafe_rename_source_cannot_hide_behind_safe_target(self):
        patch_file = self.root / "unsafe-rename.patch"
        patch_file.write_text(
            "diff --git a/.git/config b/safe.txt\n"
            "similarity index 100%\n"
            "rename from .git/config\n"
            "rename to safe.txt\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PatchTransitError, "unsafe path.*.git/config"):
            patch_metadata(patch_file)

    def test_unsafe_windows_device_rename_source_is_rejected(self):
        patch_file = self.root / "windows-alias.patch"
        patch_file.write_text(
            "diff --git a/COM¹.txt b/safe.txt\n"
            "similarity index 100%\n"
            "rename from COM¹.txt\n"
            "rename to safe.txt\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PatchTransitError, "unsafe path"):
            patch_metadata(patch_file)

    def test_simple_modification_still_reports_one_file(self):
        (self.repo / "old name.txt").write_text("updated\n", encoding="utf-8")
        diff = self.root / "modified.patch"
        diff.write_bytes(self.git("diff"))
        self.assertEqual(["old name.txt"], patch_metadata(diff)["files"])
