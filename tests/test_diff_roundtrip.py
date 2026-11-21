"""Human-readable diffs must faithfully reconstruct tricky text file changes."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import compare_inventories


class DiffRoundtrip(unittest.TestCase):
    def test_effective_unified_diff_applies_exactly(self):
        cases = (
            (b"old", b"new"),
            (b"old\n", b"new"),
            (b"old", b"new\n"),
            (b"old\n", b"new\n"),
            (b"alpha\nunchanged", b"beta\nunchanged"),
            (b"a\vOLD\n", b"a\vNEW\n"),
            (b"a\fOLD\n", b"a\fNEW\n"),
            ("caf\u00e9\u0085OLD\n".encode(), "caf\u00e9\u0085NEW\n".encode()),
        )
        for before, after in cases:
            with (
                self.subTest(before=before, after=after),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                (root / "sample.txt").write_bytes(before)
                changes, preview = compare_inventories(
                    {"sample.txt": ("file", before)},
                    {"sample.txt": ("file", after)},
                )
                applied = subprocess.run(
                    ["git", "apply", "-"],
                    cwd=root,
                    input=preview.encode(),
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(1, len(changes))
                self.assertEqual(0, applied.returncode, applied.stderr.decode())
                self.assertEqual(after, (root / "sample.txt").read_bytes())

    def test_missing_final_lf_is_marked_in_preview(self):
        _, preview = compare_inventories(
            {"sample.txt": ("file", b"old")},
            {"sample.txt": ("file", b"new")},
        )
        self.assertEqual(2, preview.count("\\ No newline at end of file"))
        self.assertIn("-old\n\\ No newline at end of file\n", preview)
        self.assertIn("+new\n\\ No newline at end of file\n", preview)
