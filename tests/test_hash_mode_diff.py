"""Mode-only changes in hash-only inventory files are fully applicable diffs."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import _preview_complete, compare_inventories


class HashOnlyModeChanges(unittest.TestCase):
    def setUp(self):
        self.content = b"\x00" * 4096
        self.digest = hashlib.sha256(self.content).hexdigest()

    def test_hash_only_permission_change_needs_no_placeholder(self):
        before = {"binary.dat": ("filehash", self.digest)}
        after = {"binary.dat": ("filehash+x", self.digest)}
        changes, preview = compare_inventories(before, after)
        self.assertEqual(1, len(changes))
        self.assertEqual(False, changes[0]["before_executable"])
        self.assertEqual(True, changes[0]["after_executable"])
        self.assertEqual(
            "diff --git a/binary.dat b/binary.dat\nold mode 100644\nnew mode 100755\n",
            preview,
        )
        self.assertTrue(_preview_complete(changes, before, after, preview))

    def test_mixed_inline_and_hash_modes_are_also_complete(self):
        before = {"binary.dat": ("file", self.content)}
        after = {"binary.dat": ("filehash+x", self.digest)}
        changes, preview = compare_inventories(before, after)
        self.assertEqual(1, len(changes))
        self.assertTrue(_preview_complete(changes, before, after, preview))
        self.assertIn("new mode 100755", preview)
        self.assertNotIn("hashes in JSON", preview)

    def test_changed_large_binary_remains_incomplete(self):
        before = {"binary.dat": ("filehash", self.digest)}
        after = {"binary.dat": ("filehash+x", hashlib.sha256(b"changed").hexdigest())}
        changes, preview = compare_inventories(before, after)
        self.assertFalse(_preview_complete(changes, before, after, preview))
        self.assertIn("hashes in JSON", preview)

    def test_reverse_mode_only_change_is_complete(self):
        before = {"binary.dat": ("filehash+x", self.digest)}
        after = {"binary.dat": ("filehash", self.digest)}
        changes, preview = compare_inventories(before, after)
        self.assertTrue(_preview_complete(changes, before, after, preview))
        self.assertIn("old mode 100755", preview)
        self.assertIn("new mode 100644", preview)

    @unittest.skipIf(
        os.name == "nt", "Windows filesystems may not preserve POSIX file modes"
    )
    def test_hash_only_mode_patch_applies_and_preserves_binary_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "binary.dat"
            path.write_bytes(self.content)
            path.chmod(0o644)
            before = {"binary.dat": ("filehash", self.digest)}
            after = {"binary.dat": ("filehash+x", self.digest)}
            changes, preview = compare_inventories(before, after)
            self.assertTrue(_preview_complete(changes, before, after, preview))
            result = subprocess.run(
                ("git", "apply", "-"),
                cwd=temp,
                input=preview.encode(),
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                0, result.returncode, result.stderr.decode(errors="replace")
            )
            self.assertEqual(self.content, path.read_bytes())
            self.assertTrue(path.stat().st_mode & 0o111)
