from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patchtransit.cli import main
from patchtransit.core import (
    PatchTransitError,
    compare_inventories,
    evaluate,
    export_tree,
    inventory,
    patch_metadata,
    repository,
)
from patchtransit.report import atomic_write, html_report


def cmd(*argv, cwd):
    return subprocess.run(argv, cwd=cwd, capture_output=True, check=True)


class Project(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        cmd("git", "init", "-q", cwd=self.repo)
        cmd("git", "config", "user.email", "example@example.invalid", cwd=self.repo)
        cmd("git", "config", "user.name", "Fixture", cwd=self.repo)
        (self.repo / "app.py").write_text("def value():\n    return 1\n")
        (self.repo / "README.md").write_text("# Demo\n")
        cmd("git", "add", ".", cwd=self.repo)
        cmd("git", "commit", "-qm", "base", cwd=self.repo)
        self.before_head = cmd("git", "rev-parse", "HEAD", cwd=self.repo).stdout
        self.old = self.dir / "old.patch"
        self.new = self.dir / "new.patch"
        self._patch(self.old, "def value():\n    return 2\n")
        self._patch(self.new, "def value():\n    return 3\n")

    def _patch(self, filename, content):
        p = self.repo / "app.py"
        original = p.read_text()
        p.write_text(content)
        filename.write_bytes(cmd("git", "diff", "--binary", cwd=self.repo).stdout)
        p.write_text(original)

    def report(self, **kwargs):
        return evaluate(self.repo, "HEAD", self.old, self.new, **kwargs)

    def test_patch_counts(self):
        self.assertEqual(1, len(patch_metadata(self.old)["files"]))
        self.assertEqual(1, patch_metadata(self.new)["hunks"])
        self.assertEqual(1, patch_metadata(self.new)["added_lines"])
        self.assertEqual(1, patch_metadata(self.new)["removed_lines"])

    def test_effective_delta(self):
        result = self.report()
        self.assertEqual("changed", result["verdict"])
        self.assertEqual(["app.py"], [c["path"] for c in result["changes"]])
        self.assertIn("+    return 3", result["effective_diff"])
        self.assertIn("-    return 2", result["effective_diff"])
        self.assertNotIn("-    return 1", result["effective_diff"])

    def test_same_result_identical_even_if_different_patch_bytes(self):
        self.new.write_bytes(self.old.read_bytes())
        result = self.report()
        self.assertEqual("identical", result["verdict"])
        self.assertEqual(result["old_state_sha256"], result["new_state_sha256"])

    def test_verify_compares_to_base(self):
        result = evaluate(self.repo, "HEAD", None, self.new)
        self.assertIn("-    return 1", result["effective_diff"])
        self.assertIn("+    return 3", result["effective_diff"])
        self.assertIsNone(result["old_patch"]["sha256"])

    def test_working_directory_untouched_even_if_dirty(self):
        (self.repo / "app.py").write_text("USER'S DIRTY WORK\n")
        (self.repo / "secret-untracked.txt").write_text("DO NOT TOUCH\n")
        result = self.report()
        self.assertEqual("changed", result["verdict"])
        self.assertEqual("USER'S DIRTY WORK\n", (self.repo / "app.py").read_text())
        self.assertEqual(
            "DO NOT TOUCH\n", (self.repo / "secret-untracked.txt").read_text()
        )
        self.assertEqual(
            self.before_head, cmd("git", "rev-parse", "HEAD", cwd=self.repo).stdout
        )
        self.assertEqual(b"", cmd("git", "diff", "--cached", cwd=self.repo).stdout)

    def test_multi_file_addition(self):
        self._patch(self.new, "def value():\n    return 3\n")
        new_file = self.repo / "new.txt"
        new_file.write_text("different\n")
        cmd("git", "add", "--intent-to-add", "new.txt", cwd=self.repo)
        self._patch(self.new, "def value():\n    return 3\n")
        cmd("git", "reset", "--", "new.txt", cwd=self.repo)
        new_file.unlink()
        result = self.report()
        self.assertEqual(["app.py", "new.txt"], [x["path"] for x in result["changes"]])

    def test_invalid_patch_fails_without_mutation(self):
        self.new.write_text("nonsense\n")
        with self.assertRaises(PatchTransitError):
            self.report()
        self.assertEqual(
            self.before_head, cmd("git", "rev-parse", "HEAD", cwd=self.repo).stdout
        )

    def test_wrong_base_ref_fails(self):
        with self.assertRaises(PatchTransitError):
            evaluate(self.repo, "missing-ref", self.old, self.new)

    def test_identical_patch_path_rejected(self):
        with self.assertRaises(PatchTransitError):
            evaluate(self.repo, "HEAD", self.old, self.old)

    def test_test_result_improves(self):
        self._patch(self.old, "def value():\n    return 1/0\n")
        outcome = self.report(
            command=[sys.executable, "-c", "import app; assert app.value() == 3"]
        )
        self.assertEqual("improvement", outcome["verdict"])
        self.assertNotEqual(0, outcome["checks"]["old"]["exit_code"])
        self.assertEqual(0, outcome["checks"]["new"]["exit_code"])
        self.assertNotIn("stderr", outcome["checks"]["old"])

    def test_test_output_does_not_contaminate_patch_fingerprint(self):
        baseline = self.report()
        outcome = self.report(
            command=[
                sys.executable,
                "-c",
                "from pathlib import Path; Path('generated.cache').write_text('side effect')",
            ]
        )
        self.assertEqual(baseline["old_state_sha256"], outcome["old_state_sha256"])
        self.assertEqual(baseline["new_state_sha256"], outcome["new_state_sha256"])
        self.assertNotIn("generated.cache", [c["path"] for c in outcome["changes"]])

    def test_test_result_regresses(self):
        outcome = self.report(
            command=[sys.executable, "-c", "import app; assert app.value() == 2"]
        )
        self.assertEqual("regression", outcome["verdict"])

    def test_test_timeout_not_a_success(self):
        outcome = self.report(
            command=[sys.executable, "-c", "import time;time.sleep(5)"], timeout=1
        )
        self.assertEqual(True, outcome["checks"]["new"]["timeout"])
        self.assertEqual(None, outcome["checks"]["old"]["exit_code"])

    def test_html_escapes_untrusted_patch_paths(self):
        outcome = self.report()
        outcome["changes"][0]["path"] = '<script>alert("X")</script>'
        text = html_report(outcome)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("Effective change report", text)

    def test_cli_writes_reports(self):
        result = main(
            [
                "compare",
                str(self.old),
                str(self.new),
                "--repo",
                str(self.repo),
                "--json",
                str(self.dir / "report.json"),
                "--html",
                str(self.dir / "report.html"),
                "--diff",
                str(self.dir / "diff.patch"),
            ]
        )
        self.assertEqual(0, result)
        self.assertIn(
            "changed_files", json.loads((self.dir / "report.json").read_text())
        )
        self.assertIn("<!doctype html>", (self.dir / "report.html").read_text())

    def test_cli_cannot_run_tests_without_consent(self):
        self.assertEqual(
            2,
            main(
                [
                    "verify",
                    str(self.new),
                    "--repo",
                    str(self.repo),
                    "--command",
                    "python -m unittest",
                ]
            ),
        )

    def test_scan_unsafe_patch_path(self):
        self.new.write_bytes(
            b"diff --git a/../../evil b/../../evil\n--- a/../../evil\n+++ b/../../evil\n@@ -0,0 +1 @@\n+BAD\n"
        )
        with self.assertRaises(PatchTransitError):
            patch_metadata(self.new)

    def test_git_tree_export_matches_base(self):
        root, tree = repository(self.repo, "HEAD")
        dest = self.dir / "export"
        dest.mkdir()
        export_tree(root, tree, dest)
        self.assertEqual("def value():\n    return 1\n", (dest / "app.py").read_text())

    def test_inventory_binary(self):
        a = self.dir / "left"
        b = self.dir / "right"
        a.mkdir()
        b.mkdir()
        (a / "data.bin").write_bytes(b"\0\x03")
        (b / "data.bin").write_bytes(b"\0\x04")
        changes, diff = compare_inventories(inventory(a), inventory(b))
        self.assertEqual(1, len(changes))
        self.assertIn("binary", diff)

    def test_atomic_write(self):
        p = self.dir / "out/report.json"
        atomic_write(p, "one")
        atomic_write(p, "two")
        self.assertEqual("two", p.read_text())


if __name__ == "__main__":
    unittest.main()


class MoreEdgeCases(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)

    def test_symlink_escape_validation(self):
        from patchtransit.core import _safe_target

        with self.assertRaises(PatchTransitError):
            _safe_target(Path("x"), "../../etc/passwd")
        with self.assertRaises(PatchTransitError):
            _safe_target(Path("x"), "/tmp/other")

    def test_allowed_symlink_validation(self):
        from patchtransit.core import _safe_target

        _safe_target(Path("foo/bar"), "../file.txt")

    def test_file_digest_is_raw_sha256(self):
        import hashlib

        from patchtransit.core import _digest

        expected = hashlib.sha256(b"hello\n").hexdigest()
        self.assertEqual(expected, _digest(("file", b"hello\n")))
        self.assertEqual(expected, _digest(("filehash", expected)))

    def test_large_file_inventory_is_bounded(self):
        from patchtransit.core import MAX_DIFF_TEXT_BYTES

        a = self.root / "a"
        a.mkdir()
        (a / "large.bin").write_bytes(b"x" * (MAX_DIFF_TEXT_BYTES + 1))
        v = inventory(a)
        self.assertEqual("filehash", v["large.bin"][0])
        self.assertEqual(64, len(v["large.bin"][1]))

    def test_simple_rename_metadata(self):
        p = self.root / "rename.patch"
        p.write_bytes(
            b"diff --git a/x b/y\nsimilarity index 100%\nrename from x\nrename to y\n"
        )
        self.assertEqual(["y"], patch_metadata(p)["files"])

    def test_effective_diff_escapes_html_code(self):
        data = {
            "verdict": "changed",
            "base_tree": "0" * 40,
            "old_patch": {"hunks": 0},
            "new_patch": {"hunks": 1},
            "old_state_sha256": "a" * 64,
            "new_state_sha256": "b" * 64,
            "changes": [],
            "effective_diff": "+<img src=x onerror=alert(1)>\n",
            "checks": None,
        }
        html = html_report(data)
        self.assertIn("&lt;img", html)
        self.assertNotIn("<img src=", html)

    def test_path_security(self):
        from patchtransit.core import _path_safe

        for p in ("../evil", "/etc/passwd", ".git/config", "foo/../../bar", "foo\\bar"):
            self.assertFalse(_path_safe(p))
        for p in ("src/example.py", "docs/my space.txt", "src/á.py"):
            self.assertTrue(_path_safe(p))
