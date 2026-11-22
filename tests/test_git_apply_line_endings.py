"""System Git settings must not change the files compared by PatchTransit."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import _git_env, apply_patch, evaluate, sha256_bytes


class GitApplyLineEndings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
            ("config", "core.autocrlf", "false"),
        ):
            self.git(*args)
        self.before = b"first\nsecond\n"
        self.after = b"first\nchanged\n"
        source = self.repo / "file.txt"
        source.write_bytes(self.before)
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        source.write_bytes(self.after)
        self.patchfile = self.root / "patch.diff"
        self.patchfile.write_bytes(self.git("diff", "--binary"))
        self.git("restore", "file.txt")

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def test_apply_ignores_autocrlf_inherited_from_git_config(self):
        original_git_env = _git_env

        def autocrlf_environment() -> dict[str, str]:
            return {
                **original_git_env(),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.autocrlf",
                "GIT_CONFIG_VALUE_0": "true",
            }

        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "file.txt").write_bytes(self.before)
        with patch("patchtransit.core._git_env", side_effect=autocrlf_environment):
            apply_patch(candidate, self.patchfile)
        self.assertEqual(self.after, (candidate / "file.txt").read_bytes())

    def test_evidence_hash_is_independent_of_git_autocrlf(self):
        original_git_env = _git_env

        def autocrlf_environment() -> dict[str, str]:
            return {
                **original_git_env(),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.autocrlf",
                "GIT_CONFIG_VALUE_0": "true",
            }

        with patch("patchtransit.core._git_env", side_effect=autocrlf_environment):
            report = evaluate(self.repo, "HEAD", None, self.patchfile)
        self.assertEqual("changed", report["verdict"])
        self.assertEqual(sha256_bytes(self.after), report["changes"][0]["after_sha256"])
        self.assertIn("+changed\n", report["effective_diff"])
        self.assertNotIn("\r", report["effective_diff"])
