from __future__ import annotations

import os
import random
import subprocess
import tempfile
import unittest
from pathlib import Path

from patchtransit.core import _preview_complete, compare_inventories


class MultiFileReplay(unittest.TestCase):
    def test_randomized_changes(self):
        randomizer = random.Random(20261122)
        names = (
            "a.txt",
            "b.txt",
            "nested/source.txt",
            "équipe.md",
            "日本語.md",
            "file name.txt",
            "-option.txt",
            "space  double.txt",
        )
        contents = (
            b"",
            b"one",
            b"two\nthree\n",
            b"\r\n",
            b"\t\v\f\n",
            "a\u2028b\n".encode(),
            "caf\u00e9\u0085\n".encode(),
            "hi \U0001f389\n".encode(),
        )
        replayed = 0
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for case in range(90):
                old: dict[str, tuple[str, bytes]] = {}
                new: dict[str, tuple[str, bytes]] = {}
                for name in randomizer.sample(names, randomizer.randrange(2, 7)):
                    for state in (old, new):
                        if randomizer.random() < 0.7:
                            executable = os.name != "nt" and randomizer.random() < 0.2
                            mode = "file+x" if executable else "file"
                            state[name] = (mode, randomizer.choice(contents))
                if old == new:
                    continue
                for name in names:
                    (root / name).unlink(missing_ok=True)
                for name, (mode, data) in old.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    if os.name != "nt":
                        path.chmod(0o755 if mode.endswith("+x") else 0o644)

                changes, diff = compare_inventories(old, new)
                self.assertTrue(_preview_complete(changes, old, new, diff))
                applied = subprocess.run(
                    (
                        "git",
                        "-c",
                        "core.autocrlf=false",
                        "apply",
                        "--whitespace=nowarn",
                        "-",
                    ),
                    cwd=root,
                    input=diff.encode("utf-8", "surrogateescape"),
                    capture_output=True,
                    check=False,
                )
                with self.subTest(case=case):
                    self.assertEqual(
                        0, applied.returncode, applied.stderr.decode(errors="replace")
                    )
                    for name in names:
                        path = root / name
                        expected = new.get(name)
                        if expected is None:
                            self.assertFalse(path.exists(), name)
                            continue
                        mode, data = expected
                        self.assertEqual(data, path.read_bytes(), name)
                        if os.name != "nt":
                            self.assertEqual(
                                mode.endswith("+x"),
                                bool(path.stat().st_mode & 0o111),
                                name,
                            )
                replayed += 1
        self.assertGreaterEqual(replayed, 80)
