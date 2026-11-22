"""Resolving a Git ref in a partial clone must not trigger lazy network fetches."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import PatchTransitError, repository


@unittest.skipIf(
    sys.platform == "win32", "Local file:// partial clone paths vary on Windows"
)
class OfflinePartialTrees(unittest.TestCase):
    def test_missing_tree_stays_missing_after_repository_lookup(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            source.mkdir()

            def git(
                *args: str, cwd: Path = source, check: bool = True
            ) -> subprocess.CompletedProcess[bytes]:
                return subprocess.run(
                    ("git", *args), cwd=cwd, check=check, capture_output=True
                )

            for args in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
                ("config", "uploadpack.allowFilter", "true"),
            ):
                git(*args)
            (source / "file.txt").write_text("committed\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "base")
            clone = base / "partial"
            result = git(
                "clone",
                "-q",
                "--filter=tree:0",
                "--no-checkout",
                source.as_uri(),
                str(clone),
                cwd=base,
                check=False,
            )
            if result.returncode:
                self.skipTest("Local Git tree-filter partial cloning is unavailable")

            oid = git("rev-parse", "HEAD^{tree}", cwd=source).stdout.decode().strip()
            offline_env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}

            def tree_present() -> bool:
                return (
                    subprocess.run(
                        ("git", "cat-file", "-e", oid),
                        cwd=clone,
                        env=offline_env,
                        check=False,
                        capture_output=True,
                    ).returncode
                    == 0
                )

            if tree_present():
                self.skipTest("Clone received Git trees despite the tree:0 filter")
            with self.assertRaisesRegex(
                PatchTransitError, "locally|Git command failed"
            ):
                repository(clone, "HEAD")
            self.assertFalse(
                tree_present(), "Repository inspection lazily fetched a Git tree"
            )
