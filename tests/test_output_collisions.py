"""Report destinations must not silently overwrite each other or source patches."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.cli import main


class ReportOutputCollisions(unittest.TestCase):
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
        source = self.repo / "a.txt"
        source.write_text("initial\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        source.write_text("modified\n", encoding="utf-8")
        self.patch = self.root / "input.patch"
        self.patch.write_bytes(self.git("diff", "--binary"))

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def invoke(self, *extra: str, action: str = "verify") -> tuple[int, str]:
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = main([action, str(self.patch), "--repo", str(self.repo), *extra])
        return result, stderr.getvalue()

    def test_rejects_duplicate_report_destinations_without_writing(self):
        output = self.root / "report.out"
        code, error = self.invoke("--json", str(output), "--html", str(output))
        self.assertEqual(2, code)
        self.assertIn("same output path", error)
        self.assertFalse(output.exists())

    def test_rejects_collision_through_normalized_parent(self):
        alias_parent = self.root / "folder"
        alias_parent.mkdir()
        same = alias_parent / ".." / "report.out"
        code, error = self.invoke(
            "--json", str(self.root / "report.out"), "--diff", str(same)
        )
        self.assertEqual(2, code)
        self.assertIn("same output path", error)

    def test_casefold_output_collisions_are_rejected_before_writing(self):
        upper = self.root / "Evidence.JSON"
        lower = self.root / "evidence.json"
        code, error = self.invoke("--json", str(upper), "--html", str(lower))
        self.assertEqual(2, code)
        self.assertIn("same output path", error)
        self.assertFalse(upper.exists())
        self.assertFalse(lower.exists())

    def test_unicode_normalization_output_collisions_are_rejected(self):
        composed = self.root / "caf\u00e9.json"
        decomposed = self.root / "cafe\u0301.json"
        code, error = self.invoke("--json", str(composed), "--diff", str(decomposed))
        self.assertEqual(2, code)
        self.assertIn("same output path", error)
        self.assertFalse(composed.exists())
        self.assertFalse(decomposed.exists())

    def test_input_patch_case_alias_cannot_be_a_report_destination(self):
        original = self.patch.read_bytes()
        alias = self.root / "INPUT.PATCH"
        code, error = self.invoke("--json", str(alias))
        self.assertEqual(2, code)
        self.assertIn("overwrite an input patch", error)
        self.assertEqual(original, self.patch.read_bytes())

    def test_inspect_cannot_overwrite_input_patch(self):
        original = self.patch.read_bytes()
        code, error = self.invoke("--json", str(self.patch), action="inspect")
        self.assertEqual(2, code)
        self.assertIn("overwrite an input patch", error)
        self.assertEqual(original, self.patch.read_bytes())

    def test_verify_cannot_overwrite_input_patch_with_diff(self):
        original = self.patch.read_bytes()
        code, error = self.invoke("--diff", str(self.patch))
        self.assertEqual(2, code)
        self.assertIn("overwrite an input patch", error)
        self.assertEqual(original, self.patch.read_bytes())

    def test_existing_output_symlink_is_replaced_not_followed(self):
        output = self.root / "report.json"
        try:
            output.symlink_to(self.patch)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        original = self.patch.read_bytes()
        code, error = self.invoke("--json", str(output))
        self.assertEqual((0, ""), (code, error))
        self.assertFalse(output.is_symlink())
        self.assertEqual(original, self.patch.read_bytes())
        self.assertEqual("changed", json.loads(output.read_text())["verdict"])
