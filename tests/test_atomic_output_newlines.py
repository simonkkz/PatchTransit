"""Evidence written on Windows must preserve its exact LF framing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from patchtransit.report import atomic_write


class AtomicOutputNewlines(unittest.TestCase):
    def test_exported_diff_preserves_original_lf_bytes_on_every_platform(self):
        contents = (
            "diff --git a/example.txt b/example.txt\n"
            "--- old/example.txt\n"
            "+++ new/example.txt\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "evidence.diff"
            atomic_write(destination, contents)
            self.assertEqual(contents.encode("utf-8"), destination.read_bytes())
            self.assertNotIn(b"\r\n", destination.read_bytes())

    def test_preexisting_crlf_in_content_is_not_implicitly_rewritten(self):
        original = "line one\r\nline two\nlast"
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "mixed-output.txt"
            atomic_write(destination, original)
            self.assertEqual(original.encode("utf-8"), destination.read_bytes())
