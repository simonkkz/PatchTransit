"""Arbitrary-size CLI timeout integers must never crash with OverflowError."""

from __future__ import annotations

import contextlib
import io
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchtransit.cli import main
from patchtransit.core import PatchTransitError, _timeout_seconds, execute


class TimeoutRange(unittest.TestCase):
    def test_huge_timeout_has_clear_error_instead_of_overflow(self):
        with self.assertRaisesRegex(PatchTransitError, "supported numeric range"):
            _timeout_seconds(10**400)
        with (
            tempfile.TemporaryDirectory() as temp,
            self.assertRaisesRegex(PatchTransitError, "supported numeric range"),
        ):
            execute([sys.executable, "-V"], Path(temp), 10**400)

    def test_positive_and_zero_bounds(self):
        for invalid in (0, -1, -(10**400)):
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(PatchTransitError, "must be positive"),
            ):
                _timeout_seconds(invalid)
        for valid in (1, 120, 10**30):
            with self.subTest(valid=valid):
                seconds = _timeout_seconds(valid)
                self.assertGreater(seconds, 0)
                self.assertTrue(math.isfinite(seconds))

    def test_cli_rejects_unrepresentable_timeout_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            for args in (
                ("git", "init", "-q"),
                ("git", "config", "user.name", "Fixture"),
                ("git", "config", "user.email", "fixture@example.invalid"),
            ):
                subprocess.run(args, cwd=repo, check=True, capture_output=True)
            (repo / "source.txt").write_text("old\n")
            subprocess.run(("git", "add", "."), cwd=repo, check=True)
            subprocess.run(("git", "commit", "-qm", "base"), cwd=repo, check=True)
            (repo / "source.txt").write_text("new\n")
            diff = subprocess.run(
                ("git", "diff"), cwd=repo, capture_output=True, check=True
            ).stdout
            patch_file = Path(temp) / "change.patch"
            patch_file.write_bytes(diff)
            stderr = io.StringIO()
            with (
                contextlib.redirect_stderr(stderr),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = main(
                    [
                        "verify",
                        str(patch_file),
                        "--repo",
                        str(repo),
                        "--execute",
                        "--command",
                        "python -V",
                        "--timeout",
                        str(10**400),
                    ]
                )
            self.assertEqual(2, status)
            self.assertIn("supported numeric range", stderr.getvalue())

    def test_valid_timeout_still_runs_opted_in_command(self):
        with tempfile.TemporaryDirectory() as temp:
            result = execute([sys.executable, "-c", "print(123)"], Path(temp), 30)
        self.assertEqual(0, result["exit_code"])
        self.assertIsNone(result.get("error"))
