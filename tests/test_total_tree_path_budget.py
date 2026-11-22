"""Aggregate path size is independently bounded from file bytes and entry count."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import (
    PatchTransitError,
    evaluate,
    export_tree,
    inventory,
    repository,
)


class AggregateTreePathBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_inventory_rejects_many_zero_byte_names(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        for filename in ("one.txt", "two.txt", "three.txt", "four.txt"):
            (candidate / filename).touch()
        with (
            patch("patchtransit.core.MAX_TREE_PATH_BYTES", 20),
            self.assertRaisesRegex(PatchTransitError, "cumulative pathname size limit"),
        ):
            inventory(candidate)

    def test_multibyte_name_uses_encoded_path_bytes(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "é.txt").touch()
        with (
            patch("patchtransit.core.MAX_TREE_PATH_BYTES", 5),
            self.assertRaisesRegex(PatchTransitError, "cumulative pathname size limit"),
        ):
            inventory(candidate)
        with patch("patchtransit.core.MAX_TREE_PATH_BYTES", 6):
            self.assertIn("é.txt", inventory(candidate))

    def test_git_tree_export_rejects_aggregate_path_overflow(self):
        repo = self.root / "repo"
        self.init_repo(repo)
        for name in ("alpha.txt", "bravo.txt", "charlie.txt"):
            (repo / name).touch()
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        root, tree = repository(repo, "HEAD")
        output = self.root / "output"
        output.mkdir()
        with (
            patch("patchtransit.core.MAX_TREE_PATH_BYTES", 20),
            self.assertRaisesRegex(PatchTransitError, "cumulative pathname size limit"),
        ):
            export_tree(root, tree, output)

    def test_new_files_after_patch_are_checked_against_budget(self):
        repo = self.root / "repo"
        self.init_repo(repo)
        (repo / "source.txt").write_bytes(b"base\n")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        for name in ("second.txt", "third.txt"):
            (repo / name).touch()
        self.git(repo, "add", "-A")
        patch_file = self.root / "add.patch"
        patch_file.write_bytes(self.git(repo, "diff", "--cached", "--binary"))
        with (
            patch("patchtransit.core.MAX_TREE_PATH_BYTES", 20),
            self.assertRaisesRegex(PatchTransitError, "cumulative pathname size limit"),
        ):
            evaluate(repo, "HEAD", None, patch_file)

    def test_exact_limit_is_accepted(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        for name in ("a.txt", "b.txt", "c.txt"):
            (candidate / name).touch()
        with patch("patchtransit.core.MAX_TREE_PATH_BYTES", 15):
            self.assertEqual(3, len(inventory(candidate)))

    @staticmethod
    def git(repo: Path, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=repo, capture_output=True, check=True
        ).stdout

    def init_repo(self, repo: Path) -> None:
        repo.mkdir()
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            self.git(repo, *args)
