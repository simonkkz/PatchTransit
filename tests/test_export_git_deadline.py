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

    def test_watchdog_continues_if_kill_races_with_child_exit(self):
        original_popen = subprocess.Popen
        children: list[subprocess.Popen[bytes]] = []

        def launch(argv: list[str], **kwargs):
            if argv[:2] in (["git", "ls-tree"], ["git", "cat-file"]):
                argv = [sys.executable, "-c", "import time; time.sleep(10)"]
            process = original_popen(argv, **kwargs)
            children.append(process)
            if len(children) == 1:
                original_kill = process.kill

                def racing_kill():
                    original_kill()
                    process.wait(timeout=5)
                    raise ProcessLookupError("process exited during kill")

                process.kill = racing_kill
            return process

        with (
            patch("patchtransit.core.subprocess.Popen", side_effect=launch),
            self.assertRaisesRegex(PatchTransitError, "timed out"),
        ):
            export_tree(self.repo, self.tree, self.root / "out", timeout=1)
        self.assertEqual(2, len(children))
        for child in children:
            self.assertIsNotNone(child.poll())

    def test_other_git_parse_errors_remain_distinct_from_timeouts(self):
        original_popen = subprocess.Popen

        def launch(argv: list[str], **kwargs):
            if argv[:2] == ["git", "ls-tree"]:
                argv = [
                    sys.executable,
                    "-c",
                    "import sys;sys.stdout.buffer.write(b'invalid\\x00')",
                ]
            return original_popen(argv, **kwargs)

        with (
            patch("patchtransit.core.subprocess.Popen", side_effect=launch),
            self.assertRaisesRegex(PatchTransitError, "Invalid Git tree entry"),
        ):
            export_tree(self.repo, self.tree, self.root / "out", timeout=3)

    @unittest.skipIf(sys.platform == "win32", "Windows symlink creation is restricted")
    def test_deadline_also_bounds_symlink_validation(self):
        (self.repo / "link.txt").symlink_to("tracked.txt")
        subprocess.run(("git", "add", "link.txt"), cwd=self.repo, check=True)
        tree = (
            subprocess.run(
                ("git", "write-tree"), cwd=self.repo, capture_output=True, check=True
            )
            .stdout.decode()
            .strip()
        )
        destination = self.root / "symlink-candidate"
        destination.mkdir()

        def slow_check(*_args):
            time.sleep(1.25)

        with (
            patch("patchtransit.core._safe_resolved_symlink", side_effect=slow_check),
            self.assertRaisesRegex(PatchTransitError, "timed out"),
        ):
            export_tree(self.repo, tree, destination, timeout=1)


if __name__ == "__main__":
    unittest.main()
