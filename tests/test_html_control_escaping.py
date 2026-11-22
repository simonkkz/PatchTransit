"""HTML evidence must not render attacker-controlled formatting characters."""

from __future__ import annotations

import unittest

from patchtransit.report import html_report


class HTMLControlEscaping(unittest.TestCase):
    def result(self) -> dict:
        return {
            "verdict": "changed",
            "base_tree": "0" * 40,
            "old_patch": {"hunks": 0},
            "new_patch": {"hunks": 1},
            "old_state_sha256": "a" * 64,
            "new_state_sha256": "b" * 64,
            "changes": [
                {
                    "path": "visible\u202eexe.py<&\x1b",
                    "change": "modified",
                    "before_sha256": None,
                    "after_sha256": None,
                    "before_executable": None,
                    "after_executable": None,
                }
            ],
            "effective_diff": "+ab\u200dcd\x1b[31m\n+unicode\u2028separator\n",
            "checks": {
                "command": ["python", "-c", "print('x')\u2066"],
                "old": {"exit_code": 0, "duration_ms": 1},
                "new": {"exit_code": 0, "duration_ms": 1},
            },
        }

    def test_html_escapes_bidi_controls_ansi_and_unicode_line_separators(self):
        page = html_report(self.result())
        for control in ("\u202e", "\u2066", "\u200d", "\u2028", "\x1b"):
            with self.subTest(control=f"U+{ord(control):04X}"):
                self.assertNotIn(control, page)
        self.assertIn(r"visible\u202eexe.py&lt;&amp;\x1b", page)
        self.assertIn(r"+ab\u200dcd\x1b[31m", page)
        self.assertIn(r"+unicode\u2028separator", page)
        self.assertIn(r"print(&#x27;x&#x27;)\u2066", page)

    def test_normal_unicode_and_html_escapes_still_render_correctly(self):
        data = self.result()
        data["changes"][0]["path"] = "日本語/é emoji 🌍.txt"
        page = html_report(data)
        self.assertIn("日本語/é emoji 🌍.txt", page)
        self.assertNotIn("<script>", page)
