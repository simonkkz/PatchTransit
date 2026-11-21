"""Execution errors and timeouts must be identifiable in human-readable reports."""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from patchtransit.cli import main
from patchtransit.report import html_report


class CheckStatusDisplay(unittest.TestCase):
    def result(self, old: dict, new: dict) -> dict:
        return {
            "verdict": "regression",
            "changed_files": 1,
            "base_tree": "0" * 40,
            "changes": [],
            "old_patch": {"hunks": 1},
            "new_patch": {"hunks": 1},
            "old_state_sha256": "1" * 64,
            "new_state_sha256": "2" * 64,
            "effective_diff": "",
            "checks": {
                "command": ["python", "-c", "print('<safe>')"],
                "old": old,
                "new": new,
            },
        }

    def test_html_distinguishes_timeout_and_output_limit(self):
        result = self.result(
            {"exit_code": None, "timeout": True, "duration_ms": 1025},
            {"exit_code": None, "error": "OutputLimitExceeded", "duration_ms": 99},
        )
        markup = html_report(result)
        self.assertIn("Timed out", markup)
        self.assertIn("Error: OutputLimitExceeded", markup)
        self.assertNotIn("Exit None", markup)
        self.assertIn("print(&#x27;&lt;safe&gt;&#x27;)", markup)

    def test_html_includes_command_output_digests(self):
        output_sha = "a" * 64
        result = self.result(
            {
                "exit_code": 0,
                "duration_ms": 17,
                "stdout_sha256": output_sha,
                "stderr_sha256": "b" * 64,
            },
            {"exit_code": 2, "duration_ms": 29},
        )
        markup = html_report(result)
        self.assertIn("Exit 0", markup)
        self.assertIn("Exit 2", markup)
        self.assertIn(f"stdout SHA-256: <code>{output_sha}</code>", markup)
        self.assertIn("stderr SHA-256", markup)

    def test_cli_reports_timeout_instead_of_exit_none(self):
        result = self.result(
            {"exit_code": 0, "duration_ms": 12},
            {"exit_code": None, "timeout": True, "duration_ms": 1100},
        )
        output = io.StringIO()
        with (
            patch("patchtransit.cli.evaluate", return_value=result),
            contextlib.redirect_stdout(output),
        ):
            code = main(["verify", "patch.diff", "--execute", "--command", "python -V"])
        self.assertEqual(1, code)
        self.assertIn("Checks: old=0 new=timeout", output.getvalue())

    def test_cli_reports_process_error_instead_of_exit_none(self):
        result = self.result(
            {"exit_code": None, "error": "FileNotFoundError", "duration_ms": 1},
            {"exit_code": 0, "duration_ms": 10},
        )
        result["verdict"] = "improvement"
        output = io.StringIO()
        with (
            patch("patchtransit.cli.evaluate", return_value=result),
            contextlib.redirect_stdout(output),
        ):
            code = main(["verify", "patch.diff", "--execute", "--command", "python -V"])
        self.assertEqual(0, code)
        self.assertIn("Checks: old=error:FileNotFoundError new=0", output.getvalue())
