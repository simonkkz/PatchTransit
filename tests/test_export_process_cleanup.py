"""Exporter must release its first Git process if the second fails to start."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import export_tree


class ExportProcessCleanup(unittest.TestCase):
    def test_failed_cat_file_launch_reaps_ls_tree_and_closes_pipes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(("git", "init", "-q"), cwd=repo, check=True)
            (repo / "tracked.txt").write_bytes(b"fixture\n")
            subprocess.run(("git", "add", "."), cwd=repo, check=True)
            root_tree = (
                subprocess.run(
                    ("git", "write-tree"), cwd=repo, capture_output=True, check=True
                )
                .stdout.decode()
                .strip()
            )
            original_popen = subprocess.Popen
            created: list[subprocess.Popen[bytes]] = []

            def launch(args: list[str], **kwargs):
                if args[:3] == ["git", "cat-file", "--batch"]:
                    raise OSError("cannot launch cat-file")
                process = original_popen(args, **kwargs)
                created.append(process)
                return process

            with (
                patch("patchtransit.core.subprocess.Popen", side_effect=launch),
                self.assertRaisesRegex(OSError, "cannot launch cat-file"),
            ):
                export_tree(repo, root_tree, root / "candidate")

            self.assertEqual(1, len(created))
            tree_proc = created[0]
            self.assertIsNotNone(tree_proc.poll())
            self.assertTrue(tree_proc.stdout is not None and tree_proc.stdout.closed)
            self.assertTrue(tree_proc.stderr is not None and tree_proc.stderr.closed)
