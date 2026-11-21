"""Malformed UTF-8 in tracked POSIX filenames must not break evidence output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import evaluate
from patchtransit.report import atomic_write, html_report, json_report


@unittest.skipUnless(
    sys.platform.startswith("linux"),
    "Filesystem must support malformed UTF-8 filenames",
)
class NonUtf8GitPaths(unittest.TestCase):
    def test_non_utf8_path_roundtrips_in_json_and_displays_in_html(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=root, check=True, capture_output=True
                ).stdout

            for args in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
            ):
                git(*args)
            raw_name = b"caf\xc3\xa9-\xff.txt"
            original = os.fsencode(root) + b"/" + raw_name
            with open(original, "wb") as output:
                output.write(b"old\n")
            git("add", ".")
            git("commit", "-qm", "base")
            with open(original, "wb") as output:
                output.write(b"new\n")
            patch = Path(temp) / "change.patch"
            patch.write_bytes(git("diff", "--binary"))
            report = evaluate(root, "HEAD", None, patch)
            filename = os.fsdecode(raw_name)
            self.assertEqual(filename, report["changes"][0]["path"])

            json_text = json_report(report)
            json_file = Path(temp) / "report.json"
            atomic_write(json_file, json_text)
            self.assertEqual(
                filename, json.loads(json_file.read_text())["changes"][0]["path"]
            )
            self.assertIn("caf\u00e9-", json_text)
            self.assertIn(r"\udcff", json_text)
            self.assertNotIn("\udcff", json_text)

            html_text = html_report(report)
            html_file = Path(temp) / "report.html"
            atomic_write(html_file, html_text)
            self.assertIn(r"caf\u00e9-\xff.txt".replace(r"\u00e9", "é"), html_text)
            self.assertNotIn("\udcff", html_text)
            self.assertIn("Effective diff", html_file.read_text())

    def test_binary_fallback_quotes_non_utf8_path_in_effective_diff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=root, check=True, capture_output=True
                ).stdout

            for args in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
            ):
                git(*args)
            raw_name = b"binary-\xfe.bin"
            original = os.fsencode(root) + b"/" + raw_name
            with open(original, "wb") as output:
                output.write(b"\x00old\n")
            git("add", ".")
            git("commit", "-qm", "base")
            with open(original, "wb") as output:
                output.write(b"\x00new\n")
            patch = Path(temp) / "change.patch"
            patch.write_bytes(git("diff", "--binary"))
            result = evaluate(root, "HEAD", None, patch)
            preview = result["effective_diff"]
            self.assertIn(r"binary-\376.bin", preview)
            self.assertNotIn("\udcfe", preview)
            output_path = Path(temp) / "effective.patch"
            atomic_write(output_path, preview)
            self.assertIn(r"binary-\376.bin", output_path.read_text())

    def test_normal_unicode_remains_unescaped_in_readable_json(self):
        text = json_report({"name": "café ☃"})
        self.assertIn("café ☃", text)
        self.assertEqual("café ☃", json.loads(text)["name"])
