"""The documented demo must work on Linux, macOS and Windows without Bash."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CrossPlatformDemo(unittest.TestCase):
    def test_disposable_python_demo_generates_all_three_evidence_files(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "reports with spaces"
            environment = {**os.environ, "PYTHONPATH": str(project / "src")}
            result = subprocess.run(
                (
                    sys.executable,
                    str(project / "examples" / "demo.py"),
                    "--output-dir",
                    str(output),
                ),
                cwd=temporary,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("PatchTransit | CHANGED | 1 effective files", result.stdout)
            self.assertIn(str(output / "demo.html"), result.stdout)
            self.assertEqual(
                {"demo.html", "demo.json", "demo.diff"},
                {path.name for path in output.iterdir()},
            )
            report = json.loads((output / "demo.json").read_text(encoding="utf-8"))
            self.assertEqual("changed", report["verdict"])
            self.assertTrue(report["diff_preview_complete"])
            self.assertEqual(1, report["changed_files"])
            self.assertEqual(["calc.py"], [item["path"] for item in report["changes"]])
            preview = (output / "demo.diff").read_text(encoding="utf-8")
            self.assertIn("-    return 2", preview)
            self.assertIn("+    return 3", preview)
            self.assertIn("Effective diff preview", (output / "demo.html").read_text())

    def test_demo_ignores_inherited_foreign_git_repository_overrides(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            foreign = root / "unrelated-user-repository"
            foreign.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=foreign, check=True, capture_output=True
                ).stdout

            for args in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
            ):
                git(*args)
            tracked = foreign / "user-work.txt"
            tracked.write_bytes(b"original user content\n")
            git("add", ".")
            git("commit", "-qm", "original user commit")
            before_head = git("rev-parse", "HEAD")
            before_config = (foreign / ".git" / "config").read_bytes()
            before_status = git("status", "--porcelain")
            environment = {
                **os.environ,
                "PYTHONPATH": str(project / "src"),
                "GIT_DIR": str(foreign / ".git"),
                "GIT_WORK_TREE": str(foreign),
                "GIT_INDEX_FILE": str(foreign / ".git" / "index"),
            }
            output = root / "reports"
            result = subprocess.run(
                (
                    sys.executable,
                    str(project / "examples" / "demo.py"),
                    "--output-dir",
                    str(output),
                ),
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(before_head, git("rev-parse", "HEAD"))
            self.assertEqual(before_config, (foreign / ".git" / "config").read_bytes())
            self.assertEqual(before_status, git("status", "--porcelain"))
            self.assertEqual(b"original user content\n", tracked.read_bytes())
            self.assertTrue((output / "demo.json").is_file())

    def test_documentation_mentions_native_windows_invocation(self):
        project = Path(__file__).resolve().parents[1]
        readme = (project / "README.md").read_text(encoding="utf-8")
        self.assertIn("python examples/demo.py", readme)
        self.assertIn(r".\.venv\Scripts\Activate.ps1", readme)
        self.assertIn("--output-dir", readme)
