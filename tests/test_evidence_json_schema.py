"""The published schema must validate both current and original schema-1 evidence."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from patchtransit.core import evaluate
from patchtransit.report import json_report


class EvidenceJSONSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.schema_path = (
            Path(__file__).resolve().parents[1] / "docs" / "evidence-v1.schema.json"
        )
        cls.schema = json.loads(cls.schema_path.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(cls.schema)
        repo = cls.root / "repo"
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
        file = repo / "source.txt"
        file.write_bytes(b"old\n")
        git("add", ".")
        git("commit", "-qm", "base")
        file.write_bytes(b"new\n")
        patch = cls.root / "change.patch"
        patch.write_bytes(git("diff", "--binary"))
        cls.evidence = json.loads(json_report(evaluate(repo, "HEAD", None, patch)))
        cls.checked = json.loads(
            json_report(
                evaluate(repo, "HEAD", None, patch, command=[sys.executable, "-V"])
            )
        )

    def test_schema_is_valid_draft_2020_12(self):
        Draft202012Validator.check_schema(self.schema)
        self.assertEqual(
            "https://json-schema.org/draft/2020-12/schema", self.schema["$schema"]
        )
        self.assertEqual(
            "https://simonkkz.github.io/PatchTransit/evidence-v1.schema.json",
            self.schema["$id"],
        )
        self.assertEqual(1, self.schema["properties"]["schema"]["const"])

    def test_current_comparison_evidence_passes_validation(self):
        self.validator.validate(self.evidence)
        self.assertEqual("changed", self.evidence["verdict"])
        self.assertEqual(1, self.evidence["changed_files"])
        self.assertTrue(self.evidence["diff_preview_complete"])

    def test_evidence_with_verification_results_passes_validation(self):
        self.validator.validate(self.checked)
        self.assertEqual(0, self.checked["checks"]["old"]["exit_code"])
        self.assertEqual(0, self.checked["checks"]["new"]["exit_code"])
        self.assertEqual("changed", self.checked["verdict"])

    def test_original_schema_1_optional_fields_remain_optional(self):
        old_format = copy.deepcopy(self.evidence)
        old_format.pop("diff_preview_complete")
        for change in old_format["changes"]:
            change.pop("before_executable")
            change.pop("after_executable")
        self.validator.validate(old_format)
        self.assertNotIn("diff_preview_complete", old_format)

    def test_additive_future_fields_remain_forward_compatible(self):
        extended = copy.deepcopy(self.evidence)
        extended["example_future_field"] = {"x": 1}
        extended["changes"][0]["example_extension"] = True
        extended["old_patch"]["another_extension"] = "allowed"
        self.validator.validate(extended)

    def test_unsupported_schema_version_is_rejected(self):
        modified = {**self.evidence, "schema": 2}
        self.assertFalse(self.validator.is_valid(modified))

    def test_invalid_hash_and_oid_formats_are_rejected(self):
        for changed in (
            {"old_state_sha256": "not-a-hash"},
            {"base_tree": "deadbeef"},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(self.validator.is_valid({**self.evidence, **changed}))

    def test_wrong_changed_file_fields_are_rejected(self):
        modified = copy.deepcopy(self.evidence)
        modified["changes"][0]["change"] = "renamed"
        self.assertFalse(self.validator.is_valid(modified))
        modified["changes"][0]["change"] = "modified"
        modified["changes"][0]["after_sha256"] = 7
        self.assertFalse(self.validator.is_valid(modified))

    def test_missing_required_metadata_and_negative_counts_are_rejected(self):
        modified = copy.deepcopy(self.evidence)
        modified["new_patch"].pop("hunks")
        self.assertFalse(self.validator.is_valid(modified))
        modified = {**self.evidence, "changed_files": -1}
        self.assertFalse(self.validator.is_valid(modified))

    def test_invalid_verification_result_is_rejected(self):
        modified = copy.deepcopy(self.checked)
        modified["checks"]["old"]["duration_ms"] = -7
        self.assertFalse(self.validator.is_valid(modified))
        modified["checks"]["old"]["duration_ms"] = 0
        modified["checks"]["new"].pop("exit_code")
        self.assertFalse(self.validator.is_valid(modified))

    def test_landing_page_links_to_locally_available_schema(self):
        website = (self.schema_path.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="./evidence-v1.schema.json"', website)
        self.assertTrue(self.schema_path.is_file())
