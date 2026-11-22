"""The published evidence schema is available unchanged in installed packages."""

from __future__ import annotations

import json
import tomllib
import unittest
from importlib.resources import files
from pathlib import Path


class OfflineEvidenceJSONSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Path(__file__).resolve().parents[1]
        cls.published = cls.project / "docs" / "evidence-v1.schema.json"
        cls.resource = files("patchtransit").joinpath("evidence-v1.schema.json")

    def test_resource_is_identical_to_pages_schema(self):
        self.assertTrue(self.resource.is_file())
        self.assertEqual(self.published.read_bytes(), self.resource.read_bytes())

    def test_resource_is_valid_utf8_json_with_correct_identity(self):
        schema = json.loads(self.resource.read_text(encoding="utf-8"))
        self.assertEqual(
            "https://json-schema.org/draft/2020-12/schema", schema["$schema"]
        )
        self.assertEqual(
            "https://simonkkz.github.io/PatchTransit/evidence-v1.schema.json",
            schema["$id"],
        )
        self.assertEqual(1, schema["properties"]["schema"]["const"])

    def test_setuptools_includes_schema_as_package_data(self):
        metadata = tomllib.loads(
            (self.project / "pyproject.toml").read_text(encoding="utf-8")
        )
        package_data = metadata["tool"]["setuptools"]["package-data"]["patchtransit"]
        self.assertIn("evidence-v1.schema.json", package_data)
        self.assertIn("py.typed", package_data)
