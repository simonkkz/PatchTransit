"""CLI responses, error handling, and explicit execution consent."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.cli import main


class CliBehavior(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (
            ("git", "init", "-q"),
            ("git", "config", "user.name", "Fixture"),
            ("git", "config", "user.email", "fixture@example.invalid"),
        ):
            subprocess.run(args, cwd=self.repo, check=True, capture_output=True)
        self.source = self.repo / "app.py"
        self.source.write_text("value=1\n", encoding="utf-8")
        subprocess.run(
            ("git", "add", "app.py"), cwd=self.repo, check=True, capture_output=True
        )
        subprocess.run(
            ("git", "commit", "-qm", "base"),
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        self.patch = self.root / "new.patch"
        self.source.write_text("value=2\n", encoding="utf-8")
        result = subprocess.run(
            ("git", "diff", "--binary"), cwd=self.repo, check=True, capture_output=True
        )
        self.patch.write_bytes(result.stdout)
        self.source.write_text("value=1\n", encoding="utf-8")

    def call(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def verify(self, *more: str) -> tuple[int, str, str]:
        return self.call("verify", str(self.patch), "--repo", str(self.repo), *more)

    def test_inspect_prints_metadata_and_writes_json(self):
        output = self.root / "metadata.json"
        code, out, err = self.call("inspect", str(self.patch), "--json", str(output))
        self.assertEqual(0, code)
        self.assertEqual("", err)
        self.assertIn("Files: 1  Hunks: 1  Lines: +1 -1", out)
        self.assertIn("app.py", out)
        doc = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(self.patch.read_bytes()).hexdigest(), doc["sha256"]
        )
        self.assertEqual(["app.py"], doc["files"])
        self.assertEqual("value=1\n", self.source.read_text(encoding="utf-8"))

    def test_quoted_home_paths_work_for_all_actions(self):
        (self.root / "first.patch").write_bytes(b"")
        with patch.dict(
            os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root)}
        ):
            code, _, err = self.call(
                "inspect", "~/new.patch", "--json", "~/inspected.json"
            )
            self.assertEqual((0, ""), (code, err))
            self.assertEqual(
                ["app.py"],
                json.loads((self.root / "inspected.json").read_text())["files"],
            )

            code, _, err = self.call(
                "verify",
                "~/new.patch",
                "--repo",
                "~/repo",
                "--json",
                "~/verified.json",
            )
            self.assertEqual((0, ""), (code, err))
            self.assertEqual(
                "changed",
                json.loads((self.root / "verified.json").read_text())["verdict"],
            )

            code, _, err = self.call(
                "compare", "~/first.patch", "~/new.patch", "--repo", "~/repo"
            )
            self.assertEqual((0, ""), (code, err))
        self.assertEqual("value=1\n", self.source.read_text(encoding="utf-8"))

    def test_inspect_rejects_unsafe_path(self):
        self.patch.write_bytes(
            b"diff --git a/../../outside b/../../outside\n"
            b"--- a/../../outside\n+++ b/../../outside\n@@ -0,0 +1 @@\n+BAD\n"
        )
        code, out, err = self.call("inspect", str(self.patch))
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("patchtransit:", err)

    def test_verify_outputs_reports_without_touching_repo(self):
        report, patch = self.root / "proof.json", self.root / "effective.patch"
        code, out, err = self.verify("--json", str(report), "--diff", str(patch))
        self.assertEqual((0, ""), (code, err))
        self.assertIn("CHANGED", out)
        self.assertIn("+value=2", patch.read_text(encoding="utf-8"))
        self.assertEqual(
            "changed", json.loads(report.read_text(encoding="utf-8"))["verdict"]
        )
        self.assertEqual("value=1\n", self.source.read_text(encoding="utf-8"))

    def test_verify_requires_positive_timeout(self):
        code, _, err = self.verify("--timeout", "0")
        self.assertEqual(2, code)
        self.assertIn("--timeout must be positive", err)

    def test_execution_requires_command(self):
        code, _, err = self.verify("--execute")
        self.assertEqual(2, code)
        self.assertIn("--execute requires --command", err)

    def test_command_requires_opt_in(self):
        code, _, err = self.verify("--command", "python -V")
        self.assertEqual(2, code)
        self.assertIn("Execution is opt-in", err)

    def test_rejects_empty_command(self):
        code, _, err = self.verify("--execute", "--command", "   ")
        self.assertEqual(2, code)
        self.assertIn("Empty --command", err)

    @unittest.skipIf(
        os.name == "nt", "Windows CRT treats unmatched quotes as literal grouping"
    )
    def test_handles_unbalanced_command_quote(self):
        code, _, err = self.verify("--execute", "--command", "'")
        self.assertEqual(2, code)
        self.assertIn("No closing quotation", err)

    def test_invalid_repository_is_an_error(self):
        code, _, err = self.call(
            "verify", str(self.patch), "--repo", str(self.root / "missing")
        )
        self.assertEqual(2, code)
        self.assertIn("patchtransit:", err)

    def test_invalid_base_is_an_error(self):
        code, _, err = self.verify("--base", "this-ref-does-not-exist")
        self.assertEqual(2, code)
        self.assertIn("patchtransit:", err)

    def test_command_regression_sets_nonzero_exit(self):
        code_string = (
            "import pathlib,sys;sys.exit("
            'pathlib.Path("app.py").read_text().strip() != "value=1")'
        )
        arguments = (sys.executable, "-c", code_string)
        command = (
            subprocess.list2cmdline(arguments)
            if os.name == "nt"
            else shlex.join(arguments)
        )
        code, out, err = self.verify("--execute", "--command", command)
        self.assertEqual((1, ""), (code, err))
        self.assertIn("REGRESSION", out)
        self.assertIn("Checks: old=0 new=1", out)

    def test_command_improvement_sets_success_exit(self):
        code_string = (
            "import pathlib,sys;sys.exit("
            'pathlib.Path("app.py").read_text().strip() != "value=2")'
        )
        arguments = (sys.executable, "-c", code_string)
        command = (
            subprocess.list2cmdline(arguments)
            if os.name == "nt"
            else shlex.join(arguments)
        )
        code, out, err = self.verify("--execute", "--command", command)
        self.assertEqual((0, ""), (code, err))
        self.assertIn("IMPROVEMENT", out)
        self.assertIn("Checks: old=1 new=0", out)
