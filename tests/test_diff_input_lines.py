"""Bound diff algorithm inputs independently from file bytes and output lines."""

from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from patchtransit.core import _line_count, _preview_complete, compare_inventories


class DiffInputLineBudget(unittest.TestCase):
    def test_counts_empty_unterminated_and_lf_terminated_lines(self):
        for content, count in (
            (b"", 0),
            (b"a", 1),
            (b"a\n", 1),
            (b"\n\n", 2),
            (b"a\nb", 2),
            (b"a\nb\n", 2),
        ):
            with self.subTest(content=content):
                self.assertEqual(count, _line_count(content))

    def test_high_line_count_reverts_to_hashes_without_running_difflib(self):
        before = b"same\n" * 15 + b"old\n"
        after = b"same\n" * 15 + b"new\n"
        left = {"generated.txt": ("file", before)}
        right = {"generated.txt": ("file", after)}
        with (
            patch("patchtransit.core.MAX_DIFF_TEXT_LINES", 10),
            patch(
                "patchtransit.core.difflib.unified_diff",
                side_effect=AssertionError("would allocate lines"),
            ),
        ):
            changes, preview = compare_inventories(left, right)
            self.assertFalse(_preview_complete(changes, left, right, preview))
        self.assertEqual(1, len(changes))
        self.assertEqual("generated.txt", changes[0]["path"])
        self.assertEqual(
            hashlib.sha256(before).hexdigest(), changes[0]["before_sha256"]
        )
        self.assertEqual(hashlib.sha256(after).hexdigest(), changes[0]["after_sha256"])
        self.assertIn("high-line-count contents differ", preview)
        self.assertIn("hashes in JSON", preview)

    def test_exactly_at_limit_remains_a_text_diff(self):
        left = {"file.txt": ("file", b"a\nb\nc\n")}
        right = {"file.txt": ("file", b"a\nb\nd\n")}
        with patch("patchtransit.core.MAX_DIFF_TEXT_LINES", 3):
            changes, preview = compare_inventories(left, right)
            self.assertTrue(_preview_complete(changes, left, right, preview))
        self.assertEqual(1, len(changes))
        self.assertIn("@@ ", preview)
        self.assertIn("+d\n", preview)

    def test_unterminated_final_line_counts_toward_cap(self):
        left = {"file.txt": ("file", b"a\nb\nc")}
        right = {"file.txt": ("file", b"a\nb\nd")}
        with patch("patchtransit.core.MAX_DIFF_TEXT_LINES", 2):
            changes, preview = compare_inventories(left, right)
            self.assertFalse(_preview_complete(changes, left, right, preview))
        self.assertIn("high-line-count", preview)

    def test_binary_high_line_count_does_not_allocate_lines(self):
        left = {"file.txt": ("file", b"\n" * 200_000 + b"original")}
        right = {"file.txt": ("file", b"\n" * 200_000 + b"changed")}
        with patch(
            "patchtransit.core.difflib.unified_diff",
            side_effect=AssertionError("unbounded text diff"),
        ):
            changes, preview = compare_inventories(left, right)
        self.assertEqual(1, len(changes))
        self.assertIn("high-line-count", preview)
        self.assertFalse(_preview_complete(changes, left, right, preview))
