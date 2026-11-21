"""Evidence and evaluated candidate trees must use the same immutable patch bytes."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit import core


class ImmutablePatchInputs(unittest.TestCase):
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
        self.source = self.repo / "file.txt"
        self.source.write_text("base\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def test_mutating_external_patch_after_snapshot_does_not_change_result(self):
        self.source.write_text("first revision\n", encoding="utf-8")
        first = self.git("diff", "--binary")
        self.source.write_text("second revision\n", encoding="utf-8")
        replacement = self.git("diff", "--binary")
        external = self.root / "patch.diff"
        external.write_bytes(first)
        original_export = core.export_tree

        def mutate_source(*args):
            external.write_bytes(replacement)
            return original_export(*args)

        with patch("patchtransit.core.export_tree", side_effect=mutate_source):
            result = core.evaluate(self.repo, "HEAD", None, external)
        self.assertEqual(
            hashlib.sha256(first).hexdigest(), result["new_patch"]["sha256"]
        )
        self.assertIn("+first revision", result["effective_diff"])
        self.assertNotIn("second revision", result["effective_diff"])

    def test_patch_metadata_streams_instead_of_loading_complete_patch(self):
        self.source.write_text("change\n", encoding="utf-8")
        external = self.root / "patch.diff"
        data = self.git("diff", "--binary")
        external.write_bytes(data)
        with patch.object(
            Path, "read_bytes", side_effect=AssertionError("unbounded read")
        ):
            metadata = core.patch_metadata(external)
        self.assertEqual(hashlib.sha256(data).hexdigest(), metadata["sha256"])
        self.assertEqual(len(data), metadata["bytes"])
        self.assertEqual(1, metadata["hunks"])

    def test_patch_size_cap_applies_before_candidate_extraction(self):
        self.source.write_text("change\n", encoding="utf-8")
        external = self.root / "patch.diff"
        external.write_bytes(self.git("diff", "--binary"))
        with (
            patch("patchtransit.core.MAX_ARCHIVE_BYTES", 10),
            self.assertRaisesRegex(core.PatchTransitError, "maximum accepted size"),
        ):
            core.evaluate(self.repo, "HEAD", None, external)
