"""A rendered effective diff preview is not always an applicable patch."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit import core
from patchtransit.cli import main
from patchtransit.report import html_report, json_report


class EffectiveDiffCompleteness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

        def git(*args: str) -> bytes:
            return subprocess.run(
                ("git", *args), cwd=self.repo, capture_output=True, check=True
            ).stdout

        self.git = git
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            git(*args)
        (self.repo / "source.txt").write_bytes(b"old\n")
        git("add", ".")
        git("commit", "-qm", "base")

    def make_patch(self, new_data: bytes) -> Path:
        (self.repo / "source.txt").write_bytes(new_data)
        path = self.root / "new.patch"
        path.write_bytes(self.git("diff", "--binary"))
        return path

    def test_text_change_produces_complete_preview(self):
        result = core.evaluate(self.repo, "HEAD", None, self.make_patch(b"new\n"))
        self.assertTrue(result["diff_preview_complete"])
        self.assertTrue(json.loads(json_report(result))["diff_preview_complete"])
        self.assertNotIn("not a complete applicable patch", html_report(result))

    def test_binary_change_is_flagged_as_incomplete(self):
        result = core.evaluate(
            self.repo, "HEAD", None, self.make_patch(b"new\x00binary")
        )
        self.assertFalse(result["diff_preview_complete"])
        self.assertIn("not a complete applicable patch", html_report(result))
        self.assertIn("binary/large contents differ", result["effective_diff"])

    def test_truncated_diff_is_flagged_as_incomplete(self):
        changed = {"source.txt": ("file", b"old\n")}
        replacement = {"source.txt": ("file", b"new\n")}
        with patch("patchtransit.core.MAX_DIFF_LINES", 2):
            changes, text = core.compare_inventories(changed, replacement)
        self.assertIn("diff truncated", text)
        self.assertFalse(core._preview_complete(changes, changed, replacement, text))

    def test_invalid_utf8_and_symlink_previews_are_incomplete(self):
        for original, replacement in (
            (("file", b"old"), ("file", b"new\xff")),
            (("link", "before"), ("link", "after")),
        ):
            left, right = {"x": original}, {"x": replacement}
            changes, text = core.compare_inventories(left, right)
            self.assertFalse(core._preview_complete(changes, left, right, text))

    def test_cli_warns_when_writing_an_incomplete_diff_preview(self):
        report = core.evaluate(
            self.repo, "HEAD", None, self.make_patch(b"new\x00binary")
        )
        output = io.StringIO()
        errors = io.StringIO()
        destination = self.root / "effective.patch"
        with (
            patch("patchtransit.cli.evaluate", return_value=report),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            status = main(["verify", "ignored.patch", "--diff", str(destination)])
        self.assertEqual(0, status)
        self.assertTrue(destination.exists())
        self.assertIn("Effective diff preview", output.getvalue())
        self.assertIn("omits some changes", errors.getvalue())
