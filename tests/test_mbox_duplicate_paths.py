"""An mbox containing repeated changes should report each touched path once."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import inspect_patch, patch_metadata


class MultiCommitPatchPaths(unittest.TestCase):
    def test_format_patch_aggregates_unique_paths_and_all_line_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=repo, check=True, capture_output=True
                ).stdout

            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            target = repo / "source.txt"
            for index in range(3):
                target.write_text(f"revision-{index}\n", encoding="utf-8")
                git("add", "source.txt")
                git("commit", "-qm", f"revision {index}")

            mbox = root / "history.patch"
            mbox.write_bytes(git("format-patch", "-2", "--stdout"))
            metadata = patch_metadata(mbox)
            self.assertEqual(["source.txt"], metadata["files"])
            self.assertEqual(2, metadata["added_lines"])
            self.assertEqual(2, metadata["removed_lines"])
            self.assertEqual(2, metadata["hunks"])
            self.assertEqual(metadata, inspect_patch(mbox))
