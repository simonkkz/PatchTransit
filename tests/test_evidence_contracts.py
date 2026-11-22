"""Runtime evidence is compatible with the exported static Python types."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from typing import is_typeddict

from patchtransit.core import evaluate, inspect_patch, patch_metadata
from patchtransit.models import (
    ChangedFile,
    CommandEvidence,
    ComparisonEvidence,
    PatchMetadata,
    VerificationChecks,
)
from patchtransit.report import json_report


class TypedEvidenceContracts(unittest.TestCase):
    def test_evidence_models_are_typeddicts(self):
        for model in (
            ChangedFile,
            CommandEvidence,
            ComparisonEvidence,
            PatchMetadata,
            VerificationChecks,
        ):
            with self.subTest(model=model.__name__):
                self.assertTrue(is_typeddict(model))
        self.assertEqual(
            {"exit_code", "duration_ms"}, CommandEvidence.__required_keys__
        )
        self.assertEqual(
            {"timeout", "error", "stdout_sha256", "stderr_sha256"},
            CommandEvidence.__optional_keys__,
        )

    def test_comparison_and_patch_metadata_have_documented_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
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
            source = repo / "main.py"
            source.write_text("a = 1\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "base")
            source.write_text("a = 2\n", encoding="utf-8")
            patch_file = Path(temp) / "changes.patch"
            patch_file.write_bytes(git("diff", "--binary"))
            metadata = inspect_patch(patch_file)
            self.assertEqual(set(PatchMetadata.__required_keys__), set(metadata))
            self.assertEqual(metadata, patch_metadata(patch_file))
            result = evaluate(repo, "HEAD", None, patch_file)
            self.assertEqual(set(ComparisonEvidence.__required_keys__), set(result))
            self.assertEqual(1, result["schema"])
            self.assertEqual(None, result["checks"])
            self.assertEqual(1, result["changed_files"])
            self.assertEqual(
                set(ChangedFile.__required_keys__), set(result["changes"][0])
            )
            rendered = json.loads(json_report(result))
            self.assertEqual(result["verdict"], rendered["verdict"])
            self.assertEqual(
                rendered, json.loads(json_report(MappingProxyType(result)))
            )
