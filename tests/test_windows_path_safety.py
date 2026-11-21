"""Reject unsafe Windows path spellings before archive extraction or git apply."""

from __future__ import annotations

import unittest
from pathlib import PurePosixPath

from patchtransit.core import PatchTransitError, _member_path, _path_safe, _safe_target


class WindowsPathSafety(unittest.TestCase):
    def test_archive_rejects_windows_drive_and_unc_names(self):
        for name in (
            "D:/outside.txt",
            "C:relative.txt",
            r"..\..\outside.txt",
            r"\\server\share\outside.txt",
            "work/evil:stream",
            "dir/.GIT/config",
            "dir/con.txt",
            "dir/NUL",
            "dir/LPT1.txt",
            "trailing./file.txt",
            "name. ",
        ):
            with self.subTest(name=name), self.assertRaises(PatchTransitError):
                _member_path(name)

    def test_symlink_targets_cannot_escape_via_windows_paths(self):
        parent = PurePosixPath("nested/folder")
        for name in (
            "D:/outside.txt",
            r"..\..\..\outside.txt",
            r"\\server\share\secret.txt",
            "../CON",
            "link:alternate",
        ):
            with self.subTest(name=name), self.assertRaises(PatchTransitError):
                _safe_target(parent, name)
        _safe_target(parent, "../inside.txt")
        _safe_target(parent, "../../root.txt")

    def test_git_patch_paths_follow_same_rules(self):
        for name in (
            "D:/outside.txt",
            r"nested\outside.txt",
            "nested/.GiT/config",
            "nested/COM3",
            "nested/file.txt:stream",
            "nested/trailing.",
        ):
            with self.subTest(name=name):
                self.assertFalse(_path_safe(name))
        for name in ("src/module.py", "docs/file with spaces.txt", "café.txt"):
            with self.subTest(name=name):
                self.assertTrue(_path_safe(name))
