"""Git filenames and error messages must not inject terminal escape sequences."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.cli import _terminal_safe, main
from patchtransit.core import PatchTransitError


class TerminalEscaping(unittest.TestCase):
    def test_control_bidi_and_undecodable_bytes_are_escaped(self):
        raw = "name\x1b[31m\r\n\t\x7f\x9b\u202e\udcff-end.txt"
        result = _terminal_safe(raw)
        self.assertNotIn("\x1b", result)
        self.assertNotIn("\r", result)
        self.assertNotIn("\n", result)
        self.assertNotIn("\t", result)
        self.assertNotIn("\u202e", result)
        self.assertNotIn("\udcff", result)
        self.assertIn(r"\x1b[31m\x0d\x0a\x09\x7f\x9b\u202e\xff", result)

    def test_printable_unicode_remains_readable(self):
        name = "normal/école/日本語/notes.txt"
        self.assertEqual(name, _terminal_safe(name))

    def test_errors_cannot_emit_terminal_controls(self):
        output = io.StringIO()
        with (
            patch(
                "patchtransit.cli._validate_outputs",
                side_effect=PatchTransitError("bad\x1b[31m\npath"),
            ),
            contextlib.redirect_stderr(output),
        ):
            status = main(["inspect", "nonexistent.patch"])
        self.assertEqual(2, status)
        self.assertNotIn("\x1b", output.getvalue())
        self.assertIn(r"bad\x1b[31m\x0apath", output.getvalue())

    @unittest.skipIf(
        os.name == "nt", "Windows prohibits C0 control bytes in file names"
    )
    def test_cli_inspection_and_report_paths_do_not_print_ansi_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=repo, capture_output=True, check=True
                ).stdout

            for args in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
            ):
                git(*args)
            (repo / "baseline.txt").write_text("base\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "base")
            unsafe_name = "danger\x1b[31mRED\x1b[0m.txt"
            (repo / unsafe_name).write_text("created\n", encoding="utf-8")
            git("add", "-A")
            patch_file = root / "new.patch"
            patch_file.write_bytes(git("diff", "--cached", "--binary"))
            inspect_output = io.StringIO()
            with contextlib.redirect_stdout(inspect_output):
                self.assertEqual(0, main(["inspect", str(patch_file)]))
            self.assertNotIn("\x1b", inspect_output.getvalue())
            self.assertIn(r"danger\x1b[31mRED\x1b[0m.txt", inspect_output.getvalue())

            report_file = root / "report\x1b[32m.json"
            verify_output = io.StringIO()
            with contextlib.redirect_stdout(verify_output):
                status = main(
                    [
                        "verify",
                        str(patch_file),
                        "--repo",
                        str(repo),
                        "--json",
                        str(report_file),
                    ]
                )
            self.assertEqual(0, status)
            self.assertNotIn("\x1b", verify_output.getvalue())
            self.assertIn(r"report\x1b[32m.json", verify_output.getvalue())
            self.assertIn(r"danger\x1b[31mRED", verify_output.getvalue())
            evidence = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(unsafe_name, evidence["changes"][0]["path"])
