"""Git must not interpret a relative patch filename as an option."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import apply_patch, patch_metadata


class HyphenPrefixedPatchPaths(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
            ("config", "core.autocrlf", "false"),
        ):
            self.git(*args)
        self.source = self.repo / "source.txt"
        self.source.write_bytes(b"before\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.source.write_bytes(b"after\n")
        self.patch_bytes = self.git("diff", "--binary")
        self.git("restore", "source.txt")

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def test_relative_hyphen_prefixed_patch_names_are_not_git_options(self):
        for name in ("-change.patch", "--unsafe-paths", "-z"):
            with self.subTest(name=name):
                self.source.write_bytes(b"before\n")
                (self.repo / name).write_bytes(self.patch_bytes)
                original_cwd = Path.cwd()
                try:
                    os.chdir(self.repo)
                    metadata = patch_metadata(Path(name))
                    self.assertEqual(["source.txt"], metadata["files"])
                    self.assertEqual(
                        (1, 1), (metadata["added_lines"], metadata["removed_lines"])
                    )
                    apply_patch(self.repo, Path(name))
                finally:
                    os.chdir(original_cwd)
                self.assertEqual(b"after\n", self.source.read_bytes())

    def test_absolute_paths_still_apply(self):
        file = self.repo / "-absolute.patch"
        file.write_bytes(self.patch_bytes)
        metadata = patch_metadata(file)
        self.assertEqual(["source.txt"], metadata["files"])
        apply_patch(self.repo, file)
        self.assertEqual(b"after\n", self.source.read_bytes())
