"""Candidate trees must match committed blobs, regardless of Git archive attributes."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import (
    PatchTransitError,
    _nul_records,
    evaluate,
    export_tree,
    repository,
)


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

    @unittest.skipIf(sys.platform == "win32", "Git file URL paths differ on Windows")
    def test_partial_clone_missing_blobs_do_not_trigger_lazy_fetch(self):
        (self.repo / "data.txt").write_bytes(b"partial clone content" * 1024)
        self.git("config", "uploadpack.allowFilter", "true")
        self.commit()
        clone = self.root / "partial"
        result = subprocess.run(
            (
                "git",
                "clone",
                "-q",
                "--filter=blob:none",
                "--no-checkout",
                self.repo.as_uri(),
                str(clone),
            ),
            capture_output=True,
            check=False,
        )
        if result.returncode:
            self.skipTest("Local Git partial cloning is unavailable")
        oid = (
            subprocess.run(
                ("git", "rev-parse", "HEAD:data.txt"),
                cwd=clone,
                capture_output=True,
                check=True,
            )
            .stdout.decode()
            .strip()
        )
        exists = subprocess.run(
            ("git", "cat-file", "-e", oid),
            cwd=clone,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
            capture_output=True,
            check=False,
        )
        if exists.returncode == 0:
            self.skipTest("Clone server returned blobs despite the filter")
        repo, tree = repository(clone, "HEAD")
        exported = self.root / "partial-export"
        exported.mkdir()
        with self.assertRaisesRegex(PatchTransitError, "Cannot read Git blob"):
            export_tree(repo, tree, exported)
        self.assertFalse((exported / "data.txt").exists())

    def test_sha256_object_format_repository(self):
        sha256_repo = self.root / "sha256-repo"
        sha256_repo.mkdir()
        init = subprocess.run(
            ("git", "init", "-q", "--object-format=sha256"),
            cwd=sha256_repo,
            capture_output=True,
            check=False,
        )
        if init.returncode:
            self.skipTest("Git SHA-256 repository format is unavailable")
        for args in (
            ("git", "config", "user.name", "Fixture"),
            ("git", "config", "user.email", "fixture@example.invalid"),
        ):
            subprocess.run(args, cwd=sha256_repo, capture_output=True, check=True)
        (sha256_repo / "data.txt").write_bytes(b"sha256 repository\n")
        subprocess.run(("git", "add", "."), cwd=sha256_repo, check=True)
        subprocess.run(("git", "commit", "-qm", "base"), cwd=sha256_repo, check=True)
        resolved, tree = repository(sha256_repo, "HEAD")
        self.assertEqual(64, len(tree))
        destination = self.root / "sha256-export"
        destination.mkdir()
        export_tree(resolved, tree, destination)
        self.assertEqual(
            b"sha256 repository\n", (destination / "data.txt").read_bytes()
        )

    def test_git_tree_listing_frames_and_entry_limit(self):
        data = io.BytesIO(b"first\0second\0")
        self.assertEqual([b"first", b"second"], list(_nul_records(data)))
        with (
            patch("patchtransit.core.MAX_TREE_ENTRY_BYTES", 5),
            self.assertRaisesRegex(PatchTransitError, "oversized"),
        ):
            list(_nul_records(io.BytesIO(b"123456\0")))
        with self.assertRaisesRegex(PatchTransitError, "Truncated Git tree"):
            list(_nul_records(io.BytesIO(b"missing terminator")))

    def test_export_rejects_overlarge_file(self):
        (self.repo / "file.txt").write_bytes(b"x" * 128)
        self.commit()
        with (
            patch("patchtransit.core.MAX_FILE_BYTES", 64),
            self.assertRaisesRegex(PatchTransitError, "safety size limit"),
        ):
            self.exported()
