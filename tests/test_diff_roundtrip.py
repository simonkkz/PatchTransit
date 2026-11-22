"""Human-readable diffs must faithfully reconstruct tricky text file changes."""

from __future__ import annotations

import random
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
                    ["git", "-c", "core.autocrlf=false", "apply", "-"],
                    cwd=root,
                    input=preview.encode(),
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(1, len(changes))
                self.assertEqual(0, applied.returncode, applied.stderr.decode())
                self.assertEqual(after, (root / "sample.txt").read_bytes())

    def test_deterministic_text_patch_roundtrips(self):
        """Property-style cases guard newline and Unicode edge interactions."""
        rng = random.Random(0xC0FFEE)
        alphabet = ("a", "B", "x", "0", "1", " ", "\t", "\r", "\v", "\f", "é", "☃")
        for index in range(85):

            def payload() -> bytes:
                lines = [
                    "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 14)))
                    for _ in range(rng.randrange(0, 5))
                ]
                return ("\n".join(lines) + rng.choice(("", "\n", "\n\n"))).encode()

            before = payload() if rng.random() >= 0.18 else None
            after = payload() if rng.random() >= 0.18 else None
            if before is None and after is None:
                after = b""
            if before == after:
                after = (after or b"") + b"extra\n"
            with self.subTest(case=index), tempfile.TemporaryDirectory() as tmp:
                filename = Path(tmp) / "example.txt"
                if before is not None:
                    filename.write_bytes(before)
                left = {"example.txt": ("file", before)} if before is not None else {}
                right = {"example.txt": ("file", after)} if after is not None else {}
                changes, diff = compare_inventories(left, right)
                self.assertEqual(1, len(changes))
                applied = subprocess.run(
                    ("git", "-c", "core.autocrlf=false", "apply", "-"),
                    cwd=tmp,
                    input=diff.encode(),
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    0, applied.returncode, applied.stderr.decode(errors="replace")
                )
                actual = filename.read_bytes() if filename.exists() else None
                self.assertEqual(after, actual)

    def test_missing_final_lf_is_marked_in_preview(self):
        _, preview = compare_inventories(
            {"sample.txt": ("file", b"old")},
            {"sample.txt": ("file", b"new")},
        )
        self.assertEqual(2, preview.count("\\ No newline at end of file"))
        self.assertIn("-old\n\\ No newline at end of file\n", preview)
        self.assertIn("+new\n\\ No newline at end of file\n", preview)
