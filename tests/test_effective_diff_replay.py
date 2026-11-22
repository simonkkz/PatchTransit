"""Complete effective diffs must reproduce the new candidate from the old one."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import evaluate, inventory


class EffectiveDiffReplay(unittest.TestCase):
    def test_multiple_changes_replay_with_crlf_and_missing_final_newline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ("git", *args), cwd=repo, check=True, capture_output=True
                ).stdout

            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "core.autocrlf", "false")
            (repo / "keep.txt").write_bytes(b"base\n")
            (repo / "remove.txt").write_bytes(b"removed later\n")
            (repo / "unchanged.txt").write_bytes(b"stay\n")
            git("add", ".")
            git("commit", "-qm", "base")

            (repo / "keep.txt").write_bytes(b"old\n")
            old_patch = root / "old.patch"
            old_patch.write_bytes(git("diff", "--binary"))
            git("restore", "keep.txt")

            (repo / "keep.txt").write_bytes(b"new\r\nno final newline")
            (repo / "remove.txt").unlink()
            (repo / "added.txt").write_bytes(b"")
            git("add", "-A")
            new_patch = root / "new.patch"
            new_patch.write_bytes(git("diff", "--cached", "--binary"))
            git("reset", "--hard", "-q", "HEAD")

            report = evaluate(repo, "HEAD", old_patch, new_patch)
            self.assertTrue(report["diff_preview_complete"])
            self.assertEqual(
                ["added.txt", "keep.txt", "remove.txt"],
                [change["path"] for change in report["changes"]],
            )

            replay = root / "replay"
            expected = root / "expected"
            for destination in (replay, expected):
                destination.mkdir()
                for name in ("keep.txt", "remove.txt", "unchanged.txt"):
                    shutil.copyfile(repo / name, destination / name)

            def apply(destination: Path, patch: Path) -> None:
                subprocess.run(
                    (
                        "git",
                        "-c",
                        "core.autocrlf=false",
                        "apply",
                        "--whitespace=nowarn",
                        str(patch),
                    ),
                    cwd=destination,
                    check=True,
                    capture_output=True,
                )

            apply(replay, old_patch)
            apply(expected, new_patch)
            effective = root / "effective.patch"
            effective.write_text(
                report["effective_diff"], encoding="utf-8", newline="\n"
            )
            apply(replay, effective)
            self.assertEqual(inventory(expected), inventory(replay))
