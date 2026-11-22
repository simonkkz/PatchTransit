"""A stuck Git child must not block streaming tree export indefinitely."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, export_tree


class GitExportDeadline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(("git", "init", "-q"), cwd=self.repo, check=True)
        (self.repo / "tracked.txt").write_text("tracked\n")
        subprocess.run(("git", "add", "."), cwd=self.repo, check=True)
        self.tree = (
            subprocess.run(
                ("git", "write-tree"), cwd=self.repo, capture_output=True, check=True
            )
            .stdout.decode()
            .strip()
        )

    def verify_deadline(self, blocked_git: str):
        original_popen = subprocess.Popen
        created: list[subprocess.Popen[bytes]] = []

        def launch(argv: list[str], **kwargs):
            if argv[0] == "git" and argv[1] == blocked_git:
                argv = [sys.executable, "-c", "import time; time.sleep(10)"]
            proc = original_popen(argv, **kwargs)
            created.append(proc)
            return proc

        started = time.monotonic()
        with (
            patch("patchtransit.core.subprocess.Popen", side_effect=launch),
            self.assertRaisesRegex(PatchTransitError, "timed out"),
        ):
            export_tree(self.repo, self.tree, self.root / "out", timeout=1)
        self.assertLess(time.monotonic() - started, 4.0)
        self.assertEqual(2, len(created))
        for proc in created:
            self.assertIsNotNone(proc.poll())
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if pipe is not None:
                    self.assertTrue(pipe.closed)

    def test_ls_tree_stalls_before_first_record(self):
        self.verify_deadline("ls-tree")

    def test_cat_file_stalls_before_blob_header(self):
        self.verify_deadline("cat-file")


if __name__ == "__main__":
    unittest.main()
