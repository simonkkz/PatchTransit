"""Inherited GIT_* variables must not redirect a PatchTransit repository lookup."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import _git_env, evaluate, execute, repository, run


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

    def test_opt_in_verification_command_cannot_inherit_foreign_git_repository(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        # Without environment isolation, Git would resolve repo_a rather than
        # fail inside this candidate with no Git directory.
        script = (
            "import os,subprocess,sys; "
            "result=subprocess.run(['git','rev-parse','--show-toplevel'],"
            "capture_output=True); "
            "sys.exit(0 if result.returncode != 0 and "
            "os.environ.get('PATCHTRANSIT_TEST') == 'enabled' and "
            "not any(key.startswith('GIT_') for key in os.environ) else 1)"
        )
        with patch.dict(
            os.environ, {**self.contaminated_env(), "PATCHTRANSIT_TEST": "enabled"}
        ):
            result = execute([sys.executable, "-c", script], candidate, timeout=5)
        self.assertEqual(0, result["exit_code"])
        self.assertFalse(result.get("timeout", False))

    def test_verification_pwd_matches_candidate_directory(self):
        candidate = self.root / "candidate with spaces"
        candidate.mkdir()
        original_pwd = self.root / "unrelated"
        original_pwd.mkdir()
        script = (
            "import os,sys; sys.exit(0 if os.environ.get('PWD') == os.getcwd() else 3)"
        )
        with patch.dict(os.environ, {"PWD": str(original_pwd)}):
            result = execute([sys.executable, "-c", script], candidate, timeout=5)
        self.assertEqual(0, result["exit_code"])

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
