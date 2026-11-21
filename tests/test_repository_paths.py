"""Preserve filesystem path bytes when resolving a Git repository root."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import repository


@unittest.skipIf(
    os.name == "nt", "Windows does not support trailing whitespace in paths"
)
class RepositoryPaths(unittest.TestCase):
    def test_root_with_trailing_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("repo ", "repo\t", "repo\n", "repo \t"):
                with self.subTest(name=repr(name)):
                    root = Path(tmp) / name
                    root.mkdir()
                    for args in (
                        ("git", "init", "-q"),
                        ("git", "config", "user.name", "Fixture"),
                        ("git", "config", "user.email", "fixture@example.invalid"),
                    ):
                        subprocess.run(args, cwd=root, check=True, capture_output=True)
                    (root / "file.txt").write_text("value\n", encoding="utf-8")
                    subprocess.run(
                        ("git", "add", "file.txt"),
                        cwd=root,
                        check=True,
                        capture_output=True,
                    )
                    subprocess.run(
                        ("git", "commit", "-qm", "base"),
                        cwd=root,
                        check=True,
                        capture_output=True,
                    )
                    resolved, tree = repository(root, "HEAD")
                    self.assertEqual(root.resolve(), resolved)
                    self.assertEqual(40, len(tree))
