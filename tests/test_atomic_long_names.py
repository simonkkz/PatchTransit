"""Atomic output should work even when destination filenames approach NAME_MAX."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from patchtransit.report import atomic_write


class AtomicLongNames(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform.startswith("linux"), "Requires a POSIX 255-byte component limit"
    )
    def test_long_destination_name_still_writes_atomically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / ("r" * 250)
            output.write_text("original content", encoding="utf-8")
            atomic_write(output, "new report content")
            self.assertEqual("new report content", output.read_text(encoding="utf-8"))
            self.assertEqual([output.name], [entry.name for entry in root.iterdir()])

    def test_existing_file_is_replaced_without_temporary_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "report.json"
            output.write_text("old content", encoding="utf-8")
            atomic_write(output, '{"ok":true}')
            self.assertEqual('{"ok":true}', output.read_text(encoding="utf-8"))
            self.assertEqual(["report.json"], [entry.name for entry in root.iterdir()])
