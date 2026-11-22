"""Command invocation must preserve Windows backslashes, quotes and spaces."""

from __future__ import annotations

import random
import subprocess
import unittest
from unittest.mock import patch

from patchtransit.cli import _split_command, _split_windows_command


class WindowsCommandArguments(unittest.TestCase):
    def test_absolute_windows_executable_paths(self):
        self.assertEqual(
            [r"C:\Program Files\Python314\python.exe", "-m", "unittest"],
            _split_windows_command(
                r'"C:\Program Files\Python314\python.exe" -m unittest'
            ),
        )
        self.assertEqual(
            [r"C:\Python314\python.exe", "-V"],
            _split_windows_command(r"C:\Python314\python.exe -V"),
        )

    def test_nested_quotes_and_empty_arguments(self):
        self.assertEqual(
            ["python", "-c", 'print("hello")', ""],
            _split_windows_command(r'python -c "print(\"hello\")" ""'),
        )
        self.assertEqual(["a", "b c", "d"], _split_windows_command('a "b c" d'))

    def test_trailing_backslashes_and_argument_boundaries(self):
        for argv in (
            ["C:\\path\\", "two words", "\\\\server\\share\\"],
            ["", "", ""],
            ["\\", "a", "b"],
            ['quote"inside', "left", "right"],
            ["unicode é ☃", "tabs\tand spaces", "literal\\backslash"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(
                    argv, _split_windows_command(subprocess.list2cmdline(argv))
                )

    def test_deterministic_windows_c_runtime_roundtrip(self):
        rng = random.Random(0xC0DE)
        alphabet = 'abCD  \t\\"\né'
        for _ in range(1000):
            argv = [
                "".join(rng.choices(alphabet, k=rng.randrange(0, 20)))
                for _ in range(rng.randrange(1, 8))
            ]
            self.assertEqual(
                argv, _split_windows_command(subprocess.list2cmdline(argv))
            )

    def test_platform_selection_uses_windows_parser_without_shell(self):
        command = r'C:\Python314\python.exe -c "print(1)"'
        with patch("patchtransit.cli.os.name", "nt"):
            self.assertEqual(
                [r"C:\Python314\python.exe", "-c", "print(1)"],
                _split_command(command),
            )
