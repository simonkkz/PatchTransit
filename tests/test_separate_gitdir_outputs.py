"""Git metadata can live in directories that are not literally named '.git'."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.cli import main


class SeparateGitDirOutputSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.metadata = self.root / "repository-private-metadata"
        subprocess.run(
            ("git", "init", "-q", "--separate-git-dir", str(self.metadata)),
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        for args in (
            ("git", "config", "user.name", "Fixture"),
            ("git", "config", "user.email", "fixture@example.invalid"),
        ):
            subprocess.run(args, cwd=self.repo, check=True, capture_output=True)
        source = self.repo / "code.txt"
        source.write_text("old\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        source.write_text("new\n", encoding="utf-8")
        self.patch_file = self.root / "change.patch"
        self.patch_file.write_bytes(self.git("diff", "--binary"))

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def cli(
        self,
        action: str,
        destination: Path,
        flag: str = "--json",
        repo: Path | None = None,
    ) -> tuple[int, str]:
        stderr = io.StringIO()
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
        ):
            status = main(
                [
                    action,
                    str(self.patch_file),
                    "--repo",
                    str(repo or self.repo),
                    flag,
                    str(destination),
                ]
            )
        return status, stderr.getvalue()

    def test_verify_cannot_overwrite_config_in_separate_git_dir(self):
        config = self.metadata / "config"
        original = config.read_bytes()
        code, error = self.cli("verify", config)
        self.assertEqual(2, code)
        self.assertIn("Git control path", error)
        self.assertEqual(original, config.read_bytes())

    def test_standalone_inspect_with_repo_blocks_separate_git_dir(self):
        config = self.metadata / "config"
        original = config.read_bytes()
        code, error = self.cli("inspect", config)
        self.assertEqual(2, code)
        self.assertIn("Git control path", error)
        self.assertEqual(original, config.read_bytes())

    def test_index_cannot_be_overwritten(self):
        index = self.metadata / "index"
        original = index.read_bytes()
        code, error = self.cli("verify", index, flag="--diff")
        self.assertEqual(2, code)
        self.assertIn("Git control path", error)
        self.assertEqual(original, index.read_bytes())

    def test_nested_worktree_directory_uses_absolute_git_common_dir(self):
        nested = self.repo / "nested"
        nested.mkdir()
        config = self.metadata / "config"
        code, error = self.cli("verify", config, repo=nested)
        self.assertEqual(2, code)
        self.assertIn("Git control path", error)

    def test_linked_worktree_common_gitdir_is_protected(self):
        linked = self.root / "linked"
        self.git("worktree", "add", "-qb", "linked-branch", str(linked))
        config = self.metadata / "config"
        original = config.read_bytes()
        code, error = self.cli("verify", config, repo=linked)
        self.assertEqual(2, code)
        self.assertIn("Git control path", error)
        self.assertEqual(original, config.read_bytes())

    def test_standalone_inspect_outside_a_checkout_still_succeeds(self):
        destination = self.root / "inspection.json"
        status, error = self.cli("inspect", destination, repo=self.root)
        self.assertEqual((0, ""), (status, error))
        self.assertEqual(1, json.loads(destination.read_text())["hunks"])

    def test_regular_reports_remain_allowed(self):
        output = self.repo / "reports" / "json-result.txt"
        status, error = self.cli("verify", output)
        self.assertEqual((0, ""), (status, error))
        self.assertEqual("changed", json.loads(output.read_text())["verdict"])
