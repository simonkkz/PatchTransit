"""Filesystem enumeration errors must not silently omit candidate data."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, inventory


class InventoryWalkErrors(unittest.TestCase):
    def test_directory_scan_failure_propagates_as_project_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "candidate"
            nested = root / "nested"
            nested.mkdir(parents=True)
            (nested / "hidden.txt").write_bytes(b"must not be omitted")
            original_scandir = os.scandir

            def simulated_scandir(path):
                if Path(path) == nested:
                    raise PermissionError("simulated nested directory access denied")
                return original_scandir(path)

            with (
                patch("patchtransit.core.os.scandir", side_effect=simulated_scandir),
                self.assertRaisesRegex(
                    PatchTransitError,
                    "Cannot inspect candidate directory.*access denied",
                ),
            ):
                inventory(root)

    def test_normal_nested_tree_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "candidate"
            nested = root / "nested"
            nested.mkdir(parents=True)
            (nested / "file.txt").write_bytes(b"tracked\n")
            self.assertIn("nested/file.txt", inventory(root))
