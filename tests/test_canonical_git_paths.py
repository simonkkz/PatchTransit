"""Reject non-canonical paths before pathlib normalizes away their components."""

from __future__ import annotations

import unittest
from pathlib import PurePosixPath

from patchtransit.core import PatchTransitError, _member_path, _path_safe, _safe_target


class CanonicalGitPathComponents(unittest.TestCase):
    def test_dots_empty_components_and_trailing_slashes_are_rejected(self):
        for name in (
            ".",
            "./file.txt",
            "dir/./file.txt",
            "dir//file.txt",
            "dir/",
            "dir//",
            "dir/../other.txt",
            "dir/..",
            "/absolute.txt",
            "",
        ):
            with self.subTest(name=name):
                self.assertFalse(_path_safe(name))
                with self.assertRaises(PatchTransitError):
                    _member_path(name)

    def test_legitimate_paths_and_hidden_files_remain_supported(self):
        for name in (
            "file.txt",
            "nested/deep/file.txt",
            ".hidden",
            "dir/.hidden-file",
            "a-b/c_d.txt",
            "unicøde/ファイル.txt",
        ):
            with self.subTest(name=name):
                self.assertTrue(_path_safe(name))
                self.assertEqual(name, _member_path(name).as_posix())

    def test_symlink_relative_targets_may_still_have_dot_components(self):
        parent = PurePosixPath("dir/nested")
        for target in ("./file.txt", "../sibling.txt", "../../root.txt"):
            with self.subTest(target=target):
                _safe_target(parent, target)
        with self.assertRaises(PatchTransitError):
            _safe_target(parent, "../../../outside.txt")
