"""Candidate trees must match committed blobs, regardless of Git archive attributes."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, evaluate, export_tree, repository


class ExactGitTree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for argv in (
            ("git", "init", "-q"),
            ("git", "config", "user.name", "Fixture"),
            ("git", "config", "user.email", "fixture@example.invalid"),
        ):
            subprocess.run(argv, cwd=self.repo, capture_output=True, check=True)

    def git(self, *args: str) -> bytes:
        return subprocess.run(
            ("git", *args), cwd=self.repo, capture_output=True, check=True
        ).stdout

    def commit(self, message: str = "base") -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def exported(self) -> Path:
        target = self.root / "export"
        target.mkdir()
        repo, tree = repository(self.repo, "HEAD")
        export_tree(repo, tree, target)
        return target

    def test_export_ignore_is_not_applied_to_committed_tree(self):
        (self.repo / ".gitattributes").write_text(
            "ignored.txt export-ignore\n", encoding="utf-8"
        )
        (self.repo / "ignored.txt").write_text("committed\n", encoding="utf-8")
        self.commit()
        self.assertEqual("committed\n", (self.exported() / "ignored.txt").read_text())
        (self.repo / "ignored.txt").write_text("changed\n", encoding="utf-8")
        update = self.root / "update.patch"
        update.write_bytes(self.git("diff", "--binary"))
        result = evaluate(self.repo, "HEAD", None, update)
        self.assertEqual("changed", result["verdict"])
        self.assertEqual(["ignored.txt"], [c["path"] for c in result["changes"]])

    def test_export_uses_blob_not_dirty_worktree(self):
        (self.repo / "file.txt").write_text("committed\n", encoding="utf-8")
        self.commit()
        (self.repo / "file.txt").write_text("dirty\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("local", encoding="utf-8")
        exported = self.exported()
        self.assertEqual("committed\n", (exported / "file.txt").read_text())
        self.assertFalse((exported / "untracked.txt").exists())

    def test_export_binary_blob_with_spaces_and_unicode(self):
        name = "café notes.txt"
        data = b"\x00\x01\xff\n\r\x00"
        (self.repo / name).write_bytes(data)
        self.commit()
        self.assertEqual(data, (self.exported() / name).read_bytes())

    def test_many_blobs_stream_across_multiple_output_chunks(self):
        for index in range(170):
            file = self.repo / f"segment-{index:04d}.txt"
            file.write_text(f"item {index}\n", encoding="utf-8")
        self.commit()
        exported = self.exported()
        self.assertEqual(170, len(list(exported.iterdir())))
        for index in (0, 17, 98, 169):
            self.assertEqual(
                f"item {index}\n",
                (exported / f"segment-{index:04d}.txt").read_text(),
            )

    @unittest.skipIf(sys.platform == "win32", "POSIX executable modes are not portable")
    def test_export_preserves_executable_bit(self):
        file = self.repo / "bin.sh"
        file.write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
        file.chmod(0o755)
        self.commit()
        self.assertTrue((self.exported() / "bin.sh").stat().st_mode & 0o111)

    @unittest.skipIf(
        sys.platform == "win32", "Symlink creation may require Windows privileges"
    )
    def test_export_symlink_after_regular_files(self):
        (self.repo / "file.txt").write_text("contents\n", encoding="utf-8")
        (self.repo / "alias.txt").symlink_to("file.txt")
        self.commit()
        exported = self.exported()
        self.assertTrue((exported / "alias.txt").is_symlink())
        self.assertEqual("file.txt", os.readlink(exported / "alias.txt"))
        self.assertEqual("contents\n", (exported / "alias.txt").read_text())

    def test_gitlink_is_rejected_instead_of_silently_ignored(self):
        (self.repo / "file.txt").write_text("base", encoding="utf-8")
        self.commit()
        oid = self.git("rev-parse", "HEAD").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{oid},vendor")
        self.git("commit", "-qm", "gitlink")
        with self.assertRaisesRegex(
            PatchTransitError, "Git submodules are unsupported"
        ):
            self.exported()

    def test_export_rejects_overlarge_file(self):
        (self.repo / "file.txt").write_bytes(b"x" * 128)
        self.commit()
        with (
            patch("patchtransit.core.MAX_FILE_BYTES", 64),
            self.assertRaisesRegex(PatchTransitError, "safety size limit"),
        ):
            self.exported()
