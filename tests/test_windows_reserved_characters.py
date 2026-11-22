"""Windows-unrepresentable Git paths must fail preflight on every host."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from patchtransit.core import (
    PatchTransitError,
    _member_path,
    _path_safe,
    _safe_target,
    export_tree,
    repository,
)


class WindowsReservedCharacters(unittest.TestCase):
    def test_git_paths_and_symlink_targets_reject_reserved_characters(self):
        for char in '<>"|?*':
            with self.subTest(char=char):
                name = f"nested/file{char}name.txt"
                self.assertFalse(_path_safe(name))
                with self.assertRaisesRegex(PatchTransitError, "Unsafe path"):
                    _member_path(name)
                with self.assertRaisesRegex(PatchTransitError, "unsafe target"):
                    _safe_target(PurePosixPath("nested"), f"file{char}name.txt")

    def test_git_paths_and_symlink_targets_reject_ascii_controls(self):
        for point in range(32):
            with self.subTest(point=point):
                name = f"nested/file{chr(point)}name.txt"
                if os.name == "nt" or point == 0:
                    self.assertFalse(_path_safe(name))
                    with self.assertRaises(PatchTransitError):
                        _member_path(name)
                    with self.assertRaises(PatchTransitError):
                        _safe_target(
                            PurePosixPath("nested"), f"file{chr(point)}name.txt"
                        )
                else:
                    self.assertTrue(_path_safe(name))
                    _safe_target(PurePosixPath("nested"), f"file{chr(point)}name.txt")

    def test_valid_punctuation_and_unicode_remain_supported(self):
        for name in (
            "nested/name + (draft) !.txt",
            "nested/école.txt",
            "nested/[version] {final} = #.txt",
        ):
            with self.subTest(name=name):
                self.assertTrue(_path_safe(name))
                self.assertEqual(name, _member_path(name).as_posix())

    @unittest.skipIf(os.name == "nt", "Windows cannot create reserved filenames")
    def test_committed_tree_with_windows_reserved_name_fails_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            for args in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
            ):
                subprocess.run(
                    ["git", *args], cwd=repo, capture_output=True, check=True
                )
            (repo / "broken?.txt").write_text("contents\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "."], cwd=repo, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-qm", "base"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            checkout, tree = repository(repo, "HEAD")
            destination = root / "candidate"
            destination.mkdir()
            with self.assertRaisesRegex(PatchTransitError, "Unsafe path"):
                export_tree(checkout, tree, destination)
