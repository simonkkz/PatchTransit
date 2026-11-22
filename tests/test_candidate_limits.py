"""Candidate patches may grow trees beyond the limits enforced for the Git base."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, evaluate, inventory


class CandidateSizeLimits(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_inventory_rejects_one_oversized_file(self):
        root = self.root / "candidate"
        root.mkdir()
        (root / "large.txt").write_bytes(b"X" * 65)
        with (
            patch("patchtransit.core.MAX_FILE_BYTES", 64),
            self.assertRaisesRegex(
                PatchTransitError, "Candidate file exceeds size limit"
            ),
        ):
            inventory(root)

    def test_inventory_rejects_aggregate_size_over_limit(self):
        root = self.root / "candidate"
        root.mkdir()
        (root / "one.txt").write_bytes(b"A" * 20)
        (root / "two.txt").write_bytes(b"B" * 20)
        with (
            patch("patchtransit.core.MAX_FILE_BYTES", 64),
            patch("patchtransit.core.MAX_ARCHIVE_BYTES", 32),
            self.assertRaisesRegex(PatchTransitError, "total safety size limit"),
        ):
            inventory(root)

    def test_symlink_target_length_checked_after_patch(self):
        root = self.root / "candidate"
        root.mkdir()
        try:
            (root / "link").symlink_to("too-long-for-cap")
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        with (
            patch("patchtransit.core.MAX_SYMLINK_BYTES", 8),
            self.assertRaisesRegex(PatchTransitError, "symlink target is too long"),
        ):
            inventory(root)

    def test_patch_expanding_file_beyond_cap_is_rejected(self):
        repo = self.root / "repo"
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
        source = repo / "code.py"
        source.write_bytes(b"a = 0\n")
        git("add", ".")
        git("commit", "-qm", "base")
        source.write_bytes(b"result = 'much more content'\n")
        updated_patch = self.root / "change.patch"
        updated_patch.write_bytes(git("diff", "--binary"))
        with (
            patch("patchtransit.core.MAX_FILE_BYTES", 20),
            self.assertRaisesRegex(
                PatchTransitError, "Candidate file exceeds size limit"
            ),
        ):
            evaluate(repo, "HEAD", None, updated_patch)
