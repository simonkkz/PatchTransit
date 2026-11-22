"""Symlink chains may escape a candidate even if each link is lexically safe."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import (
    PatchTransitError,
    evaluate,
    export_tree,
    inventory,
    repository,
)


@unittest.skipIf(
    sys.platform == "win32", "Creating symlinks may require Windows privileges"
)
class SymlinkChainSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate = self.root / "candidate"
        (self.candidate / "dir").mkdir(parents=True)

    def add_escape(self, base: Path) -> None:
        (base / "dir").mkdir(exist_ok=True)
        (base / "dir" / "up").symlink_to("..")
        (base / "dir" / "escape").symlink_to("up/../outside")

    def test_inventory_rejects_indirect_lexically_safe_escape(self):
        self.add_escape(self.candidate)
        # Both links pass a per-link depth check, but the second resolves outside.
        self.assertEqual(
            (self.root / "outside").resolve(),
            (self.candidate / "dir" / "escape").resolve(),
        )
        with self.assertRaisesRegex(
            PatchTransitError, "symlink chain escapes checkout"
        ):
            inventory(self.candidate)

    def test_valid_multi_link_chain_to_in_tree_file_is_supported(self):
        (self.candidate / "file.txt").write_text("inside\n", encoding="utf-8")
        (self.candidate / "dir" / "up").symlink_to("..")
        (self.candidate / "dir" / "alias").symlink_to("up/file.txt")
        result = inventory(self.candidate)
        self.assertEqual("up/file.txt", result["dir/alias"][1])
        self.assertEqual(
            (self.candidate / "file.txt").resolve(),
            (self.candidate / "dir" / "alias").resolve(),
        )

    def test_cyclic_symlink_chain_is_rejected(self):
        (self.candidate / "cycle-a").symlink_to("cycle-b")
        (self.candidate / "cycle-b").symlink_to("cycle-a")
        with self.assertRaisesRegex(
            PatchTransitError, "Cannot resolve candidate symlink"
        ):
            inventory(self.candidate)

    def test_committed_tree_with_indirect_escape_is_rejected(self):
        repo = self.root / "repo"
        repo.mkdir()

        def git(*args: str) -> bytes:
            return subprocess.run(
                ("git", *args), cwd=repo, capture_output=True, check=True
            ).stdout

        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            git(*args)
        (repo / "file.txt").write_text("base\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "base")
        self.add_escape(repo)
        git("add", ".")
        patch = self.root / "update.patch"
        patch.write_bytes(git("diff", "--cached", "--binary"))
        with self.assertRaisesRegex(
            PatchTransitError, "symlink chain escapes checkout"
        ):
            evaluate(repo, "HEAD", None, patch)
        git("commit", "-qm", "malicious symlink chain")
        checkout = self.root / "export"
        checkout.mkdir()
        resolved, tree = repository(repo, "HEAD")
        with self.assertRaisesRegex(
            PatchTransitError, "symlink chain escapes checkout"
        ):
            export_tree(resolved, tree, checkout)
