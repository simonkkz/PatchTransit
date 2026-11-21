"""Check that the text preview can recreate regular file lifecycle changes."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import compare_inventories


class FileLifecycleDiffs(unittest.TestCase):
    def roundtrip(
        self,
        filename: str,
        before: tuple[str, bytes] | None,
        after: tuple[str, bytes] | None,
    ) -> str:
        left = {filename: before} if before else {}
        right = {filename: after} if after else {}
        changes, diff = compare_inventories(left, right)
        self.assertEqual(1, len(changes))
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            if before:
                dest.write_bytes(before[1])
                if sys.platform != "win32":
                    dest.chmod(0o755 if before[0].endswith("+x") else 0o644)
            outcome = subprocess.run(
                ["git", "-c", "core.autocrlf=false", "apply", "-"],
                cwd=tmp,
                input=diff.encode("utf-8"),
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, outcome.returncode, outcome.stderr.decode())
            self.assertEqual(after is not None, dest.exists())
            if after:
                self.assertEqual(after[1], dest.read_bytes())
                if sys.platform != "win32":
                    self.assertEqual(
                        after[0].endswith("+x"), bool(dest.stat().st_mode & 0o111)
                    )
        return diff

    def test_new_regular_files(self):
        for content in (b"", b"new\n", b"no final newline", b"first\r\nsecond\r\n"):
            with self.subTest(content=content):
                diff = self.roundtrip("data.txt", None, ("file", content))
                self.assertIn("new file mode 100644", diff)
                self.assertIn("diff --git", diff)

    def test_deleted_regular_files(self):
        for content in (b"", b"old\n", b"no final newline", b"first\r\nsecond\r\n"):
            with self.subTest(content=content):
                diff = self.roundtrip("data.txt", ("file", content), None)
                self.assertIn("deleted file mode 100644", diff)

    @unittest.skipIf(
        sys.platform == "win32", "Windows does not track executable file mode"
    )
    def test_added_and_deleted_executable_files(self):
        self.roundtrip("script.sh", None, ("file+x", b"#!/bin/sh\n"))
        self.roundtrip("script.sh", ("file+x", b"#!/bin/sh\n"), None)
        self.roundtrip("script.sh", None, ("file+x", b""))
        self.roundtrip("script.sh", ("file+x", b""), None)

    def test_names_with_spaces_or_utf8(self):
        for filename in ("a space.txt", "café notes.txt", "folder/nested file.txt"):
            with self.subTest(filename=filename):
                self.roundtrip(filename, None, ("file", b"contents\n"))
                self.roundtrip(filename, ("file", b"contents\n"), None)

    @unittest.skipIf(
        sys.platform == "win32", "Windows filenames cannot contain quotes or newlines"
    )
    def test_git_quoted_pathnames(self):
        for filename in ('a"quote.txt', "line\nbreak.txt", "tab\tname.txt"):
            with self.subTest(filename=filename):
                self.roundtrip(filename, None, ("file", b"text\n"))
                self.roundtrip(filename, ("file", b"text\n"), None)
                self.roundtrip(filename, ("file", b"old\n"), ("file", b"new\n"))

    def test_binary_new_files_remain_manifest_only(self):
        changes, diff = compare_inventories({}, {"bin.dat": ("file", b"\x00\x01")})
        self.assertEqual("added", changes[0]["change"])
        self.assertIn("binary", diff)
        self.assertNotIn("new file mode", diff)
