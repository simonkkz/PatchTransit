"""Atomic report writes must not follow output-file symlinks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from patchtransit.report import atomic_write


class AtomicWriteSymlink(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def link_to(self, target: Path, name: str) -> Path:
        link = self.root / name
        try:
            link.symlink_to(target.name)
        except OSError as exc:
            self.skipTest(f"Symbolic links unavailable: {exc}")
        return link

    def test_existing_symlink_is_replaced_not_followed(self):
        important = self.root / "important.txt"
        important.write_text("preserve this content", encoding="utf-8")
        output = self.link_to(important, "report.json")
        atomic_write(output, "new report")
        self.assertEqual("preserve this content", important.read_text(encoding="utf-8"))
        self.assertFalse(output.is_symlink())
        self.assertEqual("new report", output.read_text(encoding="utf-8"))

    def test_broken_symlink_is_replaced_without_creating_target(self):
        missing = self.root / "missing.txt"
        output = self.link_to(missing, "report.html")
        atomic_write(output, "report")
        self.assertFalse(missing.exists())
        self.assertFalse(output.is_symlink())
        self.assertEqual("report", output.read_text(encoding="utf-8"))

    def test_parent_directory_symlink_is_supported(self):
        target = self.root / "real"
        target.mkdir()
        link = self.root / "alias"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Directory symlinks unavailable: {exc}")
        atomic_write(link / "nested" / "result.txt", "content")
        self.assertEqual("content", (target / "nested" / "result.txt").read_text())
