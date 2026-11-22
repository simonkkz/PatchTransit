"""The internal command runner validates timeout values before spawning Git."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, git, run


class GitRunnerTimeoutValidation(unittest.TestCase):
    def test_absurdly_large_timeout_is_reported_as_normal_error(self):
        for timeout in (10**400, 0, -10):
            with (
                self.subTest(timeout=str(timeout)[:20]),
                patch("patchtransit.core.subprocess.Popen") as launch,
                self.assertRaises(PatchTransitError),
            ):
                run(["git", "--version"], timeout=timeout)
            launch.assert_not_called()

    def test_git_helper_uses_the_same_range_validation(self):
        with patch("patchtransit.core.subprocess.Popen") as launch:
            with self.assertRaisesRegex(PatchTransitError, "numeric range"):
                git(["--version"], Path.cwd(), timeout=10**400)
            launch.assert_not_called()

    def test_normal_timeout_still_executes_git(self):
        completed = run(["git", "--version"], timeout=10)
        self.assertEqual(0, completed.returncode)
        self.assertTrue(completed.stdout.startswith(b"git version "))

    def test_non_git_commands_also_reject_unrepresentable_timeout(self):
        with self.assertRaisesRegex(PatchTransitError, "numeric range"):
            run(["python", "-V"], timeout=10**400)
