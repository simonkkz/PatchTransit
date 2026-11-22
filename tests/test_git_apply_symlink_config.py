"""External Git symlink settings must not rewrite Git links as regular files."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import _git_env, apply_patch, evaluate, sha256_bytes


@unittest.skipIf(os.name == "nt", "Symlinks may require Windows privileges")
class GitApplySymlinkConfig(unittest.TestCase):
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
        ):
            self.git(*args)
        (self.repo / "base.txt").write_bytes(b"original\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        (self.repo / "alias").symlink_to("base.txt")
        self.git("add", "alias")
        self.patchfile = self.root / "symlink.patch"
        self.patchfile.write_bytes(self.git("diff", "--cached", "--binary"))

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ["git", *args], cwd=self.repo, capture_output=True, check=True
        ).stdout

    @staticmethod
    def environment_with_symlinks_disabled() -> dict[str, str]:
        return {
            **_git_env(),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.symlinks",
            "GIT_CONFIG_VALUE_0": "false",
        }

    def test_direct_apply_retains_symlink_with_global_git_override(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "base.txt").write_bytes(b"original\n")
        with patch(
            "patchtransit.core._git_env",
            side_effect=self.environment_with_symlinks_disabled,
        ):
            apply_patch(candidate, self.patchfile)
        alias = candidate / "alias"
        self.assertTrue(alias.is_symlink())
        self.assertEqual("base.txt", os.readlink(alias))

    def test_comparison_state_is_independent_of_global_git_symlinks(self):
        baseline = evaluate(self.repo, "HEAD", None, self.patchfile)
        with patch(
            "patchtransit.core._git_env",
            side_effect=self.environment_with_symlinks_disabled,
        ):
            overridden = evaluate(self.repo, "HEAD", None, self.patchfile)
        self.assertEqual("changed", overridden["verdict"])
        self.assertEqual(baseline["new_state_sha256"], overridden["new_state_sha256"])
        self.assertEqual(baseline["changes"], overridden["changes"])
        self.assertEqual(
            sha256_bytes(b"symlink\x00base.txt"),
            overridden["changes"][0]["after_sha256"],
        )
