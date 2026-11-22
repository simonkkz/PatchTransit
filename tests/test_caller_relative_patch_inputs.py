"""Git patch operands must refer to the same file opened by Python."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import apply_patch, patch_metadata


class CallerRelativePatchInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for argv in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
            ("config", "core.autocrlf", "false"),
        ):
            self.git(*argv)
        self.target = self.repo / "before.txt"
        self.target.write_bytes(b"old value\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.target.write_bytes(b"new value\n")
        self.patch = self.git("diff", "--binary")
        self.git("restore", "before.txt")

    def git(self, *argv: str) -> bytes:
        return subprocess.run(
            ("git", *argv), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def check_relative_patch(self, name: str) -> None:
        (self.root / name).write_bytes(self.patch)
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            metadata = patch_metadata(Path(name))
            self.assertEqual(["before.txt"], metadata["files"])
            self.assertEqual(
                (1, 1), (metadata["added_lines"], metadata["removed_lines"])
            )
            apply_patch(self.repo, Path(name))
        finally:
            os.chdir(original_cwd)
        self.assertEqual(b"new value\n", self.target.read_bytes())

    def test_patch_relative_to_caller_not_candidate_tree(self):
        self.check_relative_patch("change.patch")

    def test_literal_dash_filename_is_not_git_stdin(self):
        self.check_relative_patch("-")

    def test_nested_relative_patch_outside_candidate_tree(self):
        (self.root / "patches").mkdir()
        self.check_relative_patch("patches/old-to-new.patch")
