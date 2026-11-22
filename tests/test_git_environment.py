"""Inherited GIT_* variables must not redirect a PatchTransit repository lookup."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import _git_env, evaluate, repository, run


class GitEnvironmentIsolation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo_a = self.create_repo("first", "repository A\n")
        self.repo_b = self.create_repo("second", "repository B\n")

    def create_repo(self, name: str, contents: str) -> Path:
        repo = self.root / name
        repo.mkdir()
        for args in (
            ("git", "init", "-q"),
            ("git", "config", "user.name", "Fixture"),
            ("git", "config", "user.email", "fixture@example.invalid"),
        ):
            subprocess.run(args, cwd=repo, check=True, capture_output=True)
        (repo / "data.txt").write_text(contents, encoding="utf-8")
        subprocess.run(("git", "add", "."), cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ("git", "commit", "-qm", "base"), cwd=repo, check=True, capture_output=True
        )
        return repo

    def contaminated_env(self) -> dict[str, str]:
        return {
            "GIT_DIR": str(self.repo_a / ".git"),
            "GIT_WORK_TREE": str(self.repo_a),
            "GIT_INDEX_FILE": str(self.repo_a / ".git" / "index"),
            "GIT_OBJECT_DIRECTORY": str(self.repo_a / ".git" / "objects"),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.ignorecase",
            "GIT_CONFIG_VALUE_0": "true",
        }

    def test_repository_ignores_unrelated_git_dir_and_worktree(self):
        expected_root, expected_tree = repository(self.repo_b, "HEAD")
        with patch.dict(os.environ, self.contaminated_env()):
            actual_root, actual_tree = repository(self.repo_b, "HEAD")
        self.assertEqual(expected_root, actual_root)
        self.assertEqual(expected_tree, actual_tree)
        self.assertNotEqual(self.repo_a, actual_root)

    def test_exporter_and_candidate_comparison_ignore_foreign_git_objects(self):
        with patch.dict(os.environ, self.contaminated_env()):
            result = evaluate(self.repo_b, "HEAD", None, None)
        self.assertEqual("identical", result["verdict"])
        self.assertEqual(0, result["changed_files"])
        self.assertEqual(repository(self.repo_b, "HEAD")[1], result["base_tree"])

    def test_raw_git_subprocess_runs_in_clean_environment(self):
        with patch.dict(os.environ, self.contaminated_env()):
            result = run(["git", "rev-parse", "--show-toplevel"], cwd=self.repo_b)
        self.assertEqual(0, result.returncode)
        self.assertEqual(
            self.repo_b.resolve(), Path(os.fsdecode(result.stdout.rstrip(b"\n")))
        )

    def test_git_env_keeps_normal_environment_and_disables_lazy_fetch(self):
        with patch.dict(
            os.environ, {**self.contaminated_env(), "PATCHTRANSIT_TEST": "enabled"}
        ):
            cleaned = _git_env()
        self.assertEqual("enabled", cleaned["PATCHTRANSIT_TEST"])
        self.assertEqual("1", cleaned["GIT_NO_LAZY_FETCH"])
        self.assertEqual("0", cleaned["GIT_TERMINAL_PROMPT"])
        for name in self.contaminated_env():
            self.assertNotIn(name, cleaned)
