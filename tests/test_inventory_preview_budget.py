"""Bound inline candidate inventories without changing effective tree evidence."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import compare_inventories, evaluate, inventory


class InventoryPreviewBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_small_files_downgrade_to_hashes_at_aggregate_preview_limit(self):
        tree = self.root / "candidate"
        tree.mkdir()
        for filename in ("b.txt", "a.txt", "c.txt"):
            (tree / filename).write_bytes(filename.encode()[:5])
        with patch("patchtransit.core.MAX_INVENTORY_PREVIEW_BYTES", 10):
            result = inventory(tree)
        self.assertEqual(("file", b"a.txt"), result["a.txt"])
        self.assertEqual(("file", b"b.txt"), result["b.txt"])
        self.assertEqual(
            ("filehash", hashlib.sha256(b"c.txt").hexdigest()), result["c.txt"]
        )

    def test_zero_byte_files_do_not_consume_preview_budget(self):
        tree = self.root / "candidate"
        tree.mkdir()
        (tree / "a.txt").write_bytes(b"")
        (tree / "b.txt").write_bytes(b"X")
        with patch("patchtransit.core.MAX_INVENTORY_PREVIEW_BYTES", 1):
            result = inventory(tree)
        self.assertEqual(("file", b""), result["a.txt"])
        self.assertEqual(("file", b"X"), result["b.txt"])

    def test_budget_change_keeps_same_state_hash_and_verdict(self):
        repo = self.root / "repo"
        repo.mkdir()

        def git(*args: str) -> bytes:
            return subprocess.run(
                ("git", *args), cwd=repo, check=True, capture_output=True
            ).stdout

        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            git(*args)
        for name in ("a.txt", "b.txt", "c.txt"):
            (repo / name).write_bytes(b"S" * 30)
        git("add", ".")
        git("commit", "-qm", "base")
        normal = evaluate(repo, "HEAD", None, None)
        with patch("patchtransit.core.MAX_INVENTORY_PREVIEW_BYTES", 35):
            bounded = evaluate(repo, "HEAD", None, None)
        self.assertEqual(normal["old_state_sha256"], bounded["old_state_sha256"])
        self.assertEqual(normal["new_state_sha256"], bounded["new_state_sha256"])
        self.assertEqual("identical", bounded["verdict"])
        self.assertEqual([], bounded["changes"])

    def test_same_digest_has_no_false_change_between_inline_and_hash(self):
        data = b"repeated contents"
        changes, preview = compare_inventories(
            {"x.txt": ("file", data)},
            {"x.txt": ("filehash", hashlib.sha256(data).hexdigest())},
        )
        self.assertEqual([], changes)
        self.assertEqual("", preview)

    def test_changed_file_beyond_preview_budget_remains_in_manifest(self):
        old = {"x.txt": ("filehash", hashlib.sha256(b"before").hexdigest())}
        new = {"x.txt": ("filehash", hashlib.sha256(b"after").hexdigest())}
        changes, preview = compare_inventories(old, new)
        self.assertEqual(["x.txt"], [item["path"] for item in changes])
        self.assertIn("hashes in JSON", preview)
