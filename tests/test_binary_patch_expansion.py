"""Binary patch expansion must be bounded before Git inflates its data."""

from __future__ import annotations

import random
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, evaluate, patch_metadata


class BinaryPatchSizePreflight(unittest.TestCase):
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
        (self.repo / "README.md").write_bytes(b"base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ["git", *args], cwd=self.repo, capture_output=True, check=True
        ).stdout

    def test_literal_expansion_is_rejected_without_invoking_git(self):
        (self.repo / "new.bin").write_bytes(b"\0" * 16384)
        self.git("add", "new.bin")
        source = self.root / "literal.patch"
        source.write_bytes(self.git("diff", "--cached", "--binary"))
        self.assertIn(b"literal 16384", source.read_bytes())
        with (
            patch("patchtransit.core.MAX_FILE_BYTES", 4096),
            patch(
                "patchtransit.core.run", side_effect=AssertionError("Git was invoked")
            ),
            self.assertRaisesRegex(PatchTransitError, "Binary patch exceeds maximum"),
        ):
            patch_metadata(source)

    def create_delta_patch(self) -> Path:
        source = b"\0" + random.Random(123).randbytes(4095)
        binary = self.repo / "original.bin"
        binary.write_bytes(source)
        self.git("add", "original.bin")
        self.git("commit", "-qm", "track binary")
        binary.write_bytes(source + b"\0")
        destination = self.root / "delta.patch"
        destination.write_bytes(self.git("diff", "--binary"))
        self.assertIn(b"GIT binary patch\ndelta ", destination.read_bytes())
        return destination

    def test_delta_target_size_is_checked_not_only_encoded_instruction_size(self):
        source = self.create_delta_patch()
        self.assertLess(source.stat().st_size, 4096)
        with (
            patch("patchtransit.core.MAX_FILE_BYTES", 4096),
            patch(
                "patchtransit.core.run", side_effect=AssertionError("Git was invoked")
            ),
            self.assertRaisesRegex(PatchTransitError, "Binary patch exceeds maximum"),
        ):
            patch_metadata(source)

    def test_valid_delta_under_limit_remains_applicable(self):
        source = self.create_delta_patch()
        with patch("patchtransit.core.MAX_FILE_BYTES", 4097):
            metadata = patch_metadata(source)
            result = evaluate(self.repo, "HEAD", None, source)
        self.assertEqual(["original.bin"], metadata["files"])
        self.assertEqual("changed", result["verdict"])
        self.assertEqual(1, result["changed_files"])

    def test_binary_patch_aggregate_limit_is_checked_before_git(self):
        for i in range(5):
            (self.repo / f"file-{i}.bin").write_bytes(b"\0" * 512)
        self.git("add", ".")
        source = self.root / "many.patch"
        source.write_bytes(self.git("diff", "--cached", "--binary"))
        self.assertLess(source.stat().st_size, 2000)
        with (
            patch("patchtransit.core.MAX_FILE_BYTES", 1024),
            patch("patchtransit.core.MAX_ARCHIVE_BYTES", 2000),
            patch(
                "patchtransit.core.run", side_effect=AssertionError("Git was invoked")
            ),
            self.assertRaisesRegex(PatchTransitError, "total safety size limit"),
        ):
            patch_metadata(source)

    def test_malformed_binary_encoding_fails_with_project_error(self):
        source = self.create_delta_patch()
        data = source.read_bytes()
        marker = b"GIT binary patch\n"
        start = data.index(marker) + len(marker)
        header_end = data.index(b"\n", start) + 1
        encoded_end = data.index(b"\n", header_end)
        encoded = data[header_end:encoded_end]
        replacement = encoded[:1] + b"~" * (len(encoded) - 1)
        source.write_bytes(data[:header_end] + replacement + data[encoded_end:])
        with self.assertRaisesRegex(PatchTransitError, "Invalid patch syntax"):
            patch_metadata(source)

    def test_text_lines_resembling_binary_headers_do_not_trigger_limit(self):
        (self.repo / "README.md").write_bytes(b"literal 999999999\n")
        source = self.root / "text.patch"
        source.write_bytes(self.git("diff"))
        with patch("patchtransit.core.MAX_FILE_BYTES", 4096):
            metadata = patch_metadata(source)
        self.assertEqual(["README.md"], metadata["files"])
