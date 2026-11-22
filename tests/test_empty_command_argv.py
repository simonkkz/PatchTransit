"""Requesting a verification command with no executable must fail visibly."""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.cli import main
from patchtransit.core import PatchTransitError, evaluate, execute, run


class EmptyCommandVectors(unittest.TestCase):
    def test_internal_runner_rejects_empty_argv_without_spawning(self):
        for argv in ([], [""], ["", "--version"]):
            with (
                self.subTest(argv=argv),
                patch("patchtransit.core.subprocess.Popen") as launch,
                self.assertRaisesRegex(PatchTransitError, "specify an executable"),
            ):
                run(argv)
            launch.assert_not_called()

    def test_verification_runner_rejects_empty_argv(self):
        for argv in ([], [""], ["", "-V"]):
            with (
                self.subTest(argv=argv),
                self.assertRaisesRegex(
                    PatchTransitError, "Verification command must specify"
                ),
            ):
                execute(argv, Path.cwd(), timeout=15)

    def test_python_evaluate_distinguishes_none_from_explicit_empty_argv(self):
        for argv in ([], [""], ["", "-V"]):
            with (
                self.subTest(argv=argv),
                self.assertRaisesRegex(
                    PatchTransitError, "Verification command must specify"
                ),
            ):
                evaluate(Path.cwd(), "HEAD", None, None, command=argv)

    def test_cli_empty_quoted_executable_is_a_normal_usage_error(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            code = main(["verify", "example.patch", "--execute", "--command", '""'])
        self.assertEqual(2, code)
        self.assertIn(
            "Verification command must specify an executable", output.getvalue()
        )
