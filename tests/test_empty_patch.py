"""A literal zero-byte patch is a valid no-op; malformed nonempty patches are not."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.cli import main
from patchtransit.core import (
    PatchTransitError,
    apply_patch,
    evaluate,
    inspect_patch,
    patch_metadata,
)
from patchtransit.report import json_report


class EmptyGitPatches(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            self.git(*args)
        (self.repo / "main.py").write_bytes(b"original\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.empty = self.root / "empty.patch"
        self.empty.touch()

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, check=True, capture_output=True
        ).stdout

    def test_empty_patch_has_digest_and_zero_counts(self):
        with patch(
            "patchtransit.core._patch_numstat",
            side_effect=AssertionError("Git called on empty"),
        ):
            metadata = patch_metadata(self.empty)
        self.assertEqual(hashlib.sha256(b"").hexdigest(), metadata["sha256"])
        self.assertEqual(0, metadata["bytes"])
        self.assertEqual([], metadata["files"])
        self.assertEqual(
            (0, 0, 0),
            (metadata["added_lines"], metadata["removed_lines"], metadata["hunks"]),
        )
        self.assertIsNone(patch_metadata(None)["sha256"])
        self.assertEqual(metadata, inspect_patch(self.empty))

    def test_empty_patch_can_be_verified_against_git_base(self):
        report = evaluate(self.repo, "HEAD", None, self.empty)
        self.assertEqual("identical", report["verdict"])
        self.assertEqual(0, report["changed_files"])
        self.assertTrue(report["diff_preview_complete"])
        self.assertEqual(report["old_state_sha256"], report["new_state_sha256"])
        self.assertIsNone(report["old_patch"]["sha256"])
        self.assertEqual(hashlib.sha256(b"").hexdigest(), report["new_patch"]["sha256"])
        self.assertEqual("identical", json.loads(json_report(report))["verdict"])

    def test_two_distinct_empty_files_compare_identical(self):
        second = self.root / "another-empty.patch"
        second.touch()
        report = evaluate(self.repo, "HEAD", self.empty, second)
        self.assertEqual("identical", report["verdict"])
        self.assertEqual([], report["changes"])

    def test_empty_patch_vs_real_patch_shows_real_change(self):
        (self.repo / "main.py").write_bytes(b"modified\n")
        real = self.root / "change.patch"
        real.write_bytes(self.git("diff", "--binary"))
        report = evaluate(self.repo, "HEAD", self.empty, real)
        self.assertEqual("changed", report["verdict"])
        self.assertEqual(["main.py"], [item["path"] for item in report["changes"]])

    def test_empty_patch_can_run_opted_in_verification(self):
        report = evaluate(
            self.repo,
            "HEAD",
            None,
            self.empty,
            command=[sys.executable, "-c", "print(123)"],
        )
        self.assertEqual("identical", report["verdict"])
        self.assertEqual(0, report["checks"]["old"]["exit_code"])
        self.assertEqual(0, report["checks"]["new"]["exit_code"])

    def test_cli_inspection_and_verify_support_zero_byte_file(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["inspect", str(self.empty)])
        self.assertEqual(0, code)
        self.assertIn("Hunks: 0", stdout.getvalue())
        report_path = self.root / "evidence.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(
                [
                    "verify",
                    str(self.empty),
                    "--repo",
                    str(self.repo),
                    "--json",
                    str(report_path),
                ]
            )
        self.assertEqual(0, code)
        self.assertEqual("identical", json.loads(report_path.read_text())["verdict"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO support required")
    def test_direct_apply_rejects_fifo_even_though_it_has_zero_file_size(self):
        fifo = self.root / "source.fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(PatchTransitError, "regular file"):
            apply_patch(self.repo, fifo)

    def test_direct_apply_rejects_directory_even_if_stat_size_is_zero(self):
        with self.assertRaisesRegex(
            PatchTransitError, "regular file|Cannot open patch"
        ):
            apply_patch(self.repo, self.root)

    def test_nonempty_garbage_and_whitespace_are_still_invalid(self):
        for text in (b"garbage", b"\n", b"  \n", b"--- not a git diff\n"):
            with self.subTest(raw=text):
                malformed = self.root / "malformed.patch"
                malformed.write_bytes(text)
                with self.assertRaisesRegex(PatchTransitError, "Invalid patch syntax"):
                    patch_metadata(malformed)
                with self.assertRaisesRegex(PatchTransitError, "Patch did not apply"):
                    apply_patch(self.repo, malformed)
