"""Explicit report paths must not overwrite Git control files and refs."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.cli import main


class GitControlOutputProtection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (
            ("git", "init", "-q"),
            ("git", "config", "user.name", "Fixture"),
            ("git", "config", "user.email", "fixture@example.invalid"),
        ):
            subprocess.run(args, cwd=self.repo, capture_output=True, check=True)
        source = self.repo / "source.txt"
        source.write_text("old\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        source.write_text("new\n", encoding="utf-8")
        self.input_patch = self.root / "change.patch"
        self.input_patch.write_bytes(self.git("diff", "--binary"))

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def invoke(
        self, flag: str, destination: Path, *, action: str = "verify"
    ) -> tuple[int, str]:
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(output),
        ):
            status = main(
                [
                    action,
                    str(self.input_patch),
                    "--repo",
                    str(self.repo),
                    flag,
                    str(destination),
                ]
            )
        return status, output.getvalue()

    def test_json_output_cannot_replace_git_config(self):
        config = self.repo / ".git" / "config"
        original = config.read_bytes()
        status, error = self.invoke("--json", config)
        self.assertEqual(2, status)
        self.assertIn("cannot target a .git control path", error)
        self.assertEqual(original, config.read_bytes())
        git_root = Path(self.git("rev-parse", "--show-toplevel").decode().strip())
        self.assertEqual(self.repo.resolve(), git_root.resolve())

    def test_index_and_ref_outputs_are_rejected(self):
        control = self.repo / ".git"
        for flag, target in (
            ("--diff", control / "index"),
            ("--html", control / "refs" / "heads" / "main"),
            ("--json", control / "config"),
        ):
            with self.subTest(flag=flag, destination=str(target)):
                original = target.read_bytes() if target.exists() else None
                status, error = self.invoke(flag, target)
                self.assertEqual(2, status)
                self.assertIn(".git control path", error)
                if original is not None:
                    self.assertEqual(original, target.read_bytes())
                else:
                    self.assertFalse(target.exists())

    def test_symlinked_parent_into_git_control_directory_is_rejected(self):
        alias = self.root / "alias"
        try:
            alias.symlink_to(self.repo / ".git", target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        config = self.repo / ".git" / "config"
        original = config.read_bytes()
        status, error = self.invoke("--json", alias / "config")
        self.assertEqual(2, status)
        self.assertIn(".git control path", error)
        self.assertEqual(original, config.read_bytes())

    def test_normal_report_destination_inside_repository_remains_allowed(self):
        target = self.repo / "reports" / "report.json"
        status, error = self.invoke("--json", target)
        self.assertEqual((0, ""), (status, error))
        self.assertEqual("changed", json.loads(target.read_text())["verdict"])
