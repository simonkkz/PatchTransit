"""A complete effective diff must remain applicable after empty file entries."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import _preview_complete, compare_inventories


class EmptyFileDiffRoundtrip(unittest.TestCase):
    def test_empty_add_or_delete_followed_by_modified_content(self):
        cases: tuple[
            tuple[
                str,
                dict[str, tuple[str, bytes | str]],
                dict[str, tuple[str, bytes | str]],
            ],
            ...,
        ] = (
            (
                "add-empty",
                {"a.txt": ("file", b"old\n")},
                {"0empty": ("file", b""), "a.txt": ("file", b"new\n")},
            ),
            (
                "delete-empty",
                {"0empty": ("file", b""), "a.txt": ("file", b"old\n")},
                {"a.txt": ("file", b"new\n")},
            ),
            (
                "add-executable-empty",
                {"b.txt": ("file", b"original\n")},
                {"0empty": ("file+x", b""), "b.txt": ("file+x", b"new\n")},
            ),
            (
                "multiple-edits",
                {"a.txt": ("file", b"a\n"), "b.txt": ("file", b"b\n")},
                {"a.txt": ("file", b"new a\n"), "b.txt": ("file", b"new b\n")},
            ),
        )
        for label, old, new in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                for name, (kind, data) in old.items():
                    self.assertIsInstance(data, bytes)
                    file = base / name
                    file.write_bytes(data)
                    file.chmod(0o755 if kind.endswith("+x") else 0o644)
                changes, diff = compare_inventories(old, new)
                self.assertEqual(
                    len(changes),
                    len(old.keys() ^ new.keys())
                    + sum(
                        key in old and key in new and old[key] != new[key]
                        for key in old.keys() & new.keys()
                    ),
                )
                self.assertTrue(_preview_complete(changes, old, new, diff))
                patchfile = base.parent / f"{base.name}.patch"
                try:
                    patchfile.write_text(diff, encoding="utf-8")
                    result = subprocess.run(
                        ("git", "apply", "--", str(patchfile)),
                        cwd=base,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(
                        0, result.returncode, result.stderr.decode(errors="replace")
                    )
                    self.assertEqual(set(new), {file.name for file in base.iterdir()})
                    for name, (kind, data) in new.items():
                        file = base / name
                        self.assertEqual(data, file.read_bytes())
                        if os.name != "nt":
                            self.assertEqual(
                                kind.endswith("+x"), bool(file.stat().st_mode & 0o111)
                            )
                finally:
                    patchfile.unlink(missing_ok=True)
