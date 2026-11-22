"""Missing working directories and executables require distinct errors."""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys
import tempfile
import unittest

from patchtransit.cli import main
from patchtransit.core import PatchTransitError, repository, run


class MissingWorkingDirectory(unittest.TestCase):
    def test_missing_working_directory_does_not_claim_executable_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "deleted-repo"
            with self.assertRaisesRegex(
                PatchTransitError, "Working directory is not a directory"
            ) as error:
                run([sys.executable, "-c", "pass"], cwd=path)
            self.assertIn("deleted-repo", str(error.exception))
            self.assertNotIn("Required executable not found", str(error.exception))

    def test_cli_prints_missing_repository_instead_of_missing_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = pathlib.Path(tmp) / "missing-repo"
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                status = main(["verify", "not-read.patch", "--repo", str(missing)])
            self.assertEqual(2, status)
            self.assertIn("Working directory is not a directory", error.getvalue())
            self.assertNotIn("Required executable not found", error.getvalue())

    def test_file_as_working_directory_reports_correct_cause(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "file.txt"
            path.write_text("contents", encoding="utf-8")
            with self.assertRaisesRegex(
                PatchTransitError, "Working directory is not a directory"
            ):
                run([sys.executable, "-c", "pass"], cwd=path)

    def test_repository_missing_path_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "repo"
            with self.assertRaisesRegex(
                PatchTransitError, "Working directory is not a directory"
            ):
                repository(path, "HEAD")

    def test_missing_executable_in_existing_directory_is_still_identified(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesRegex(PatchTransitError, "Required executable not found"),
        ):
            run(["patchtransit-executable-does-not-exist"], cwd=pathlib.Path(tmp))
