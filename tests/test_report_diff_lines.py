"""The HTML diff renderer should split on LF, not arbitrary Unicode separators."""

from __future__ import annotations

import unittest

from patchtransit.report import html_report


class ReportDiffLines(unittest.TestCase):
    def result(self, text: str) -> dict:
        return {
            "verdict": "changed",
            "base_tree": "0" * 40,
            "old_patch": {"hunks": 1},
            "new_patch": {"hunks": 1},
            "old_state_sha256": "a" * 64,
            "new_state_sha256": "b" * 64,
            "changes": [],
            "effective_diff": text,
            "checks": None,
        }

    def test_vertical_tab_form_feed_and_nel_remain_inside_diff_lines(self):
        diff = "@@ -1 +1 @@\n-old\vpart\n+new\fpart\n+title\u0085text\n"
        markup = html_report(self.result(diff))
        self.assertIn(r'<span class="removed">-old\x0bpart</span>', markup)
        self.assertIn(r'<span class="added">+new\x0cpart</span>', markup)
        self.assertIn(r'<span class="added">+title\x85text</span>', markup)

    def test_empty_diff_shows_empty_state(self):
        markup = html_report(self.result(""))
        self.assertIn("No changed lines.", markup)

    def test_no_final_lf_keeps_final_line(self):
        markup = html_report(self.result("+trailing line"))
        self.assertIn('<span class="added">+trailing line</span>', markup)
