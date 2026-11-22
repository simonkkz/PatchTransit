"""An unknown home directory in CLI arguments must yield a normal usage error."""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.cli import main


class UnresolvableHomePaths(unittest.TestCase):
    def test_unknown_home_in_input_repo_and_report_paths(self):
        unknown = "~patchtransit-unknown-user-2026"
        original_expanduser = Path.expanduser

        def expand(path: Path) -> Path:
            if str(path).startswith(unknown):
                raise RuntimeError("Could not determine home directory.")
            return original_expanduser(path)

        requests = (
            ["inspect", f"{unknown}/patch.diff"],
            ["inspect", "missing.patch", "--json", f"{unknown}/result.json"],
            ["verify", "missing.patch", "--repo", f"{unknown}/repo"],
            ["verify", "missing.patch", "--html", f"{unknown}/result.html"],
            ["verify", "missing.patch", "--diff", f"{unknown}/result.diff"],
        )
        with patch.object(Path, "expanduser", expand):
            for argv in requests:
                with self.subTest(argv=argv):
                    errors = io.StringIO()
                    with contextlib.redirect_stderr(errors):
                        status = main(argv)
                    self.assertEqual(2, status)
                    self.assertIn("Cannot expand home directory", errors.getvalue())
