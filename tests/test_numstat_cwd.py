from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import PatchTransitError, evaluate, patch_metadata


class NumstatCwd(unittest.TestCase):
    def test_subdirectory_does_not_hide_patch_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            nested = repo / "pkg"
            nested.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=repo, capture_output=True, check=True
                ).stdout

            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            outside = repo / "outside.txt"
            outside.write_text("before\n")
            git("add", ".")
            git("commit", "-qm", "base")
            outside.write_text("after\n")
            safe = root / "safe.patch"
            safe.write_bytes(git("diff", "--binary"))
            unsafe = root / "unsafe.patch"
            unsafe.write_text(
                "diff --git a/.git/config b/.git/config\n"
                "--- a/.git/config\n"
                "+++ b/.git/config\n"
                "@@ -1 +1 @@\n"
                "-before\n"
                "+after\n"
            )

            old_cwd = Path.cwd()
            try:
                os.chdir(nested)
                metadata = patch_metadata(safe)
                self.assertEqual(["outside.txt"], metadata["files"])
                self.assertEqual(
                    (1, 1), (metadata["added_lines"], metadata["removed_lines"])
                )
                report = evaluate(nested, "HEAD", None, safe)
                self.assertEqual(["outside.txt"], report["new_patch"]["files"])
                self.assertEqual(1, report["changed_files"])
                with self.assertRaisesRegex(PatchTransitError, "unsafe path"):
                    patch_metadata(unsafe)
            finally:
                os.chdir(old_cwd)
