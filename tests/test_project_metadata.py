"""Distribution metadata points to real project resources and supported runtimes."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from patchtransit import __version__


class ProjectMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.metadata = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]

    def test_package_version_matches_library_version(self):
        self.assertEqual(__version__, self.metadata["version"])

    def test_project_links_have_explicit_https_destinations(self):
        urls = self.metadata["urls"]
        self.assertEqual(
            {"Homepage", "Source", "Issues", "Releases", "Changelog"}, set(urls)
        )
        self.assertEqual("https://simonkkz.github.io/PatchTransit/", urls["Homepage"])
        for key in ("Source", "Issues", "Releases", "Changelog"):
            with self.subTest(key=key):
                self.assertTrue(
                    urls[key].startswith("https://github.com/simonkkz/PatchTransit")
                )

    def test_supported_python_versions_have_classifiers(self):
        classifiers = set(self.metadata["classifiers"])
        for minor in range(11, 16):
            with self.subTest(python_version=f"3.{minor}"):
                self.assertIn(
                    f"Programming Language :: Python :: 3.{minor}", classifiers
                )
        self.assertEqual(">=3.11", self.metadata["requires-python"])
