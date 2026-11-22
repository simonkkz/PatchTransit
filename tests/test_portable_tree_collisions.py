"""Git path aliases must not depend on case-sensitive host filesystem behavior."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import (
    PatchTransitError,
    _register_portable_path,
    export_tree,
    inventory,
    repository,
)


class PortableTreeCollisions(unittest.TestCase):
    def test_file_and_directory_aliases_are_detected(self):
        for names in (
            ("README.md", "readme.md"),
            ("Pkg/src.py", "pkg/other.py"),
            ("a/b.txt", "A/C.txt"),
            ("café.txt", "cafe\u0301.txt"),
            ("Z/One", "z/Two"),
        ):
            with self.subTest(names=names):
                seen: dict[str, str] = {}
                _register_portable_path(names[0], seen)
                with self.assertRaisesRegex(PatchTransitError, "paths collide"):
                    _register_portable_path(names[1], seen)

    def test_distinct_valid_paths_and_repeated_prefixes(self):
        seen: dict[str, str] = {}
        for name in (
            "pkg/one.py",
            "pkg/two.py",
            "PkgOther/a.py",
            "unicøde/ファイル.txt",
        ):
            _register_portable_path(name, seen)
        self.assertIn("pkg/one.py", seen)
        self.assertIn("pkg/two.py", seen)

    @unittest.skipIf(os.name == "nt", "Windows cannot create two case-alias files")
    def test_committed_git_tree_rejects_distinct_case_alias_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=repo, capture_output=True, check=True
                ).stdout

            for args in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
                ("config", "core.ignorecase", "false"),
            ):
                git(*args)
            (repo / "Foo.txt").write_bytes(b"one")
            (repo / "foo.txt").write_bytes(b"two")
            if (repo / "Foo.txt").read_bytes() == (repo / "foo.txt").read_bytes():
                self.skipTest("Case-insensitive filesystem")
            git("add", ".")
            git("commit", "-qm", "conflicting names")
            checked_out, tree = repository(repo, "HEAD")
            exported = root / "exported"
            exported.mkdir()
            with self.assertRaisesRegex(PatchTransitError, "paths collide"):
                export_tree(checked_out, tree, exported)
            with self.assertRaisesRegex(PatchTransitError, "paths collide"):
                inventory(repo)

    @unittest.skipIf(os.name == "nt", "Windows cannot create two case-alias files")
    def test_candidate_inventory_rejects_case_alias_directory_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Folder").mkdir()
            try:
                (root / "folder").mkdir()
            except FileExistsError:
                self.skipTest("Case-insensitive filesystem")
            (root / "Folder" / "a.txt").write_bytes(b"one")
            (root / "folder" / "b.txt").write_bytes(b"two")
            if (root / "Folder" / "a.txt").exists() and (
                root / "folder" / "a.txt"
            ).exists():
                self.skipTest("Case-insensitive filesystem")
            with self.assertRaisesRegex(PatchTransitError, "paths collide"):
                inventory(root)
