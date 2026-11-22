"""Thousands of empty blobs must not bypass tree size resource bounds."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, export_tree, inventory, repository


class EntryCountLimits(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_inventory_rejects_many_zero_byte_files(self):
        path = self.root / "candidate"
        path.mkdir()
        for index in range(12):
            (path / f"empty-{index:02d}.txt").touch()
        with (
            patch("patchtransit.core.MAX_TREE_ENTRIES", 8),
            self.assertRaisesRegex(PatchTransitError, "maximum entry count"),
        ):
            inventory(path)

    def test_git_tree_export_rejects_many_empty_blobs(self):
        repo = self.root / "repo"
        repo.mkdir()

        def git(*args: str) -> bytes:
            return subprocess.run(
                ("git", *args), cwd=repo, check=True, capture_output=True
            ).stdout

        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            git(*args)
        for index in range(12):
            (repo / f"empty-{index:02d}.txt").touch()
        git("add", ".")
        git("commit", "-qm", "base")
        original, tree = repository(repo, "HEAD")
        destination = self.root / "export"
        destination.mkdir()
        with (
            patch("patchtransit.core.MAX_TREE_ENTRIES", 8),
            self.assertRaisesRegex(PatchTransitError, "maximum entry count"),
        ):
            export_tree(original, tree, destination)
        self.assertLessEqual(len(list(destination.iterdir())), 8)

    def test_small_trees_remain_supported(self):
        path = self.root / "small"
        path.mkdir()
        for index in range(3):
            (path / f"file-{index}").touch()
        with patch("patchtransit.core.MAX_TREE_ENTRIES", 3):
            result = inventory(path)
        self.assertEqual(3, len(result))
