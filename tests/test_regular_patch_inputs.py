"""Only regular patch files may be inspected or snapshotted."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit import core
from patchtransit.cli import main
from patchtransit.core import PatchTransitError, inspect_patch, patch_metadata


class RegularPatchInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        repo = self.root / "repo"
        repo.mkdir()

        def git(*args: str) -> bytes:
            return subprocess.run(
                ("git", *args), cwd=repo, check=True, capture_output=True
            ).stdout

        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            git(*args)
        source = repo / "a.txt"
        source.write_text("original\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "base")
        source.write_text("updated\n", encoding="utf-8")
        self.patch_file = self.root / "change.patch"
        self.patch_file.write_bytes(git("diff", "--binary"))

    def test_regular_patch_and_symlink_to_regular_file_are_allowed(self):
        original = patch_metadata(self.patch_file)
        self.assertEqual(1, original["hunks"])
        linked = self.root / "linked.patch"
        try:
            linked.symlink_to(self.patch_file)
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        self.assertEqual(original["sha256"], inspect_patch(linked)["sha256"])

    def test_directory_input_is_rejected(self):
        with self.assertRaisesRegex(
            PatchTransitError, "must be a regular file|Cannot open patch"
        ):
            patch_metadata(self.root)

    @unittest.skipUnless(
        sys.platform.startswith("linux"), "Requires POSIX FIFO support"
    )
    def test_fifo_without_writer_is_rejected_without_blocking(self):
        fifo = self.root / "input.fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(PatchTransitError, "must be a regular file"):
            inspect_patch(fifo)

    def test_preflight_rejects_oversized_sparse_file(self):
        huge = self.root / "large.patch"
        with huge.open("wb") as stream:
            stream.truncate(128)
        with (
            patch("patchtransit.core.MAX_ARCHIVE_BYTES", 64),
            self.assertRaisesRegex(PatchTransitError, "maximum accepted size"),
        ):
            patch_metadata(huge)

    def test_inspect_snapshot_is_stable_if_source_changes_after_copy(self):
        original_bytes = self.patch_file.read_bytes()
        original_copy = core._snapshot_patch

        def change_original_after_copy(source: Path, destination: Path) -> Path:
            result = original_copy(source, destination)
            source.write_bytes(b"not a valid patch anymore\n")
            return result

        with patch(
            "patchtransit.core._snapshot_patch", side_effect=change_original_after_copy
        ):
            report = inspect_patch(self.patch_file)
        self.assertEqual(len(original_bytes), report["bytes"])
        self.assertEqual(1, report["hunks"])
        self.assertEqual(b"not a valid patch anymore\n", self.patch_file.read_bytes())

    def test_inspect_cli_does_not_require_original_file_after_snapshot(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["inspect", str(self.patch_file)])
        self.assertEqual(0, result)
        self.assertIn("Hunks: 1", output.getvalue())
