from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, export_tree


class GitDescendants(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(("git", "init", "-q"), cwd=self.repo, check=True)
        (self.repo / "file.txt").write_text("tracked\n")
        subprocess.run(("git", "add", "."), cwd=self.repo, check=True)
        self.tree = (
            subprocess.run(
                ("git", "write-tree"), cwd=self.repo, capture_output=True, check=True
            )
            .stdout.decode()
            .strip()
        )

    def verify_deadline(self, command: str, parent_delay: float):
        parent_code = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],"
            "stdout=sys.stdout,stderr=sys.stderr); "
            f"time.sleep({parent_delay})"
        )
        original = subprocess.Popen

        def launch(argv: list[str], **kwargs):
            if argv[:2] == ["git", command]:
                argv = [sys.executable, "-c", parent_code]
                kwargs["cwd"] = Path.cwd()
            return original(argv, **kwargs)

        start = time.monotonic()
        with (
            patch("patchtransit.core.subprocess.Popen", side_effect=launch),
            self.assertRaisesRegex(PatchTransitError, "timed out"),
        ):
            export_tree(self.repo, self.tree, self.root / "candidate", timeout=1)
        self.assertLess(time.monotonic() - start, 4.0)

    def test_tree_reader(self):
        self.verify_deadline("ls-tree", 10)

    def test_exited_tree_reader(self):
        self.verify_deadline("ls-tree", 0.3)

    def test_blob_reader(self):
        self.verify_deadline("cat-file", 10)
