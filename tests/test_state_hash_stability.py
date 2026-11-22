"""State fingerprints should depend on filesystem contents, not preview storage."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import compare_inventories, evaluate


class StateHashStability(unittest.TestCase):
    def test_preview_threshold_does_not_change_state_sha256(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            for args in (
                ("git", "init", "-q"),
                ("git", "config", "user.name", "Fixture"),
                ("git", "config", "user.email", "fixture@example.invalid"),
            ):
                subprocess.run(args, cwd=root, check=True, capture_output=True)
            (root / "data.txt").write_bytes(b"Z" * 128)
            subprocess.run(("git", "add", "."), cwd=root, check=True)
            subprocess.run(("git", "commit", "-qm", "base"), cwd=root, check=True)

            normal = evaluate(root, "HEAD", None, None)
            with patch("patchtransit.core.MAX_DIFF_TEXT_BYTES", 32):
                hash_only = evaluate(root, "HEAD", None, None)
            self.assertEqual(normal["base_tree"], hash_only["base_tree"])
            self.assertEqual(normal["old_state_sha256"], hash_only["old_state_sha256"])
            self.assertEqual(normal["new_state_sha256"], hash_only["new_state_sha256"])
            self.assertEqual("identical", normal["verdict"])
            self.assertEqual("identical", hash_only["verdict"])

    def test_inline_bytes_and_hashed_content_compare_as_identical(self):
        data = b"the same bytes\n"
        digest = hashlib.sha256(data).hexdigest()
        changes, effective = compare_inventories(
            {"a.txt": ("file", data)},
            {"a.txt": ("filehash", digest)},
        )
        self.assertEqual([], changes)
        self.assertEqual("", effective)

    def test_executable_bit_difference_is_still_detected(self):
        data = b"the same bytes\n"
        digest = hashlib.sha256(data).hexdigest()
        changes, diff = compare_inventories(
            {"a.sh": ("file", data)},
            {"a.sh": ("filehash+x", digest)},
        )
        self.assertEqual(1, len(changes))
        self.assertEqual(False, changes[0]["before_executable"])
        self.assertEqual(True, changes[0]["after_executable"])
        self.assertIn("old mode 100644", diff)
        self.assertIn("new mode 100755", diff)
