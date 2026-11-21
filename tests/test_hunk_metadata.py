"""Git patch hunk headers are delimited by LF, not arbitrary control bytes."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import patch_metadata


class PatchHunkMetadata(unittest.TestCase):
    def test_embedded_carriage_return_does_not_create_fake_hunk(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=repo, capture_output=True, check=True
                ).stdout

            for args in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
            ):
                git(*args)
            source = repo / "file.txt"
            source.write_bytes(b"old\r@@ fake hunk\n")
            git("add", "file.txt")
            git("commit", "-qm", "base")
            source.write_bytes(b"new\r@@ fake hunk\n")
            patch = Path(temp) / "update.patch"
            patch.write_bytes(git("diff", "--binary"))
            self.assertIn(b"\r@@ fake hunk", patch.read_bytes())
            metadata = patch_metadata(patch)
            self.assertEqual(1, metadata["hunks"])
            self.assertEqual(["file.txt"], metadata["files"])
            self.assertEqual(
                (1, 1), (metadata["added_lines"], metadata["removed_lines"])
            )
