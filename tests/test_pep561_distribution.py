"""The package declares its existing type annotations to downstream tools."""

from __future__ import annotations

import tomllib
import unittest
from importlib.resources import files
from pathlib import Path


class PEP561Distribution(unittest.TestCase):
    def test_source_package_has_empty_pep561_marker(self):
        marker = files("patchtransit").joinpath("py.typed")
        self.assertTrue(marker.is_file())
        self.assertEqual("", marker.read_text(encoding="utf-8"))

    def test_setuptools_declares_the_type_marker_as_package_data(self):
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn(
            "py.typed", project["tool"]["setuptools"]["package-data"]["patchtransit"]
        )
