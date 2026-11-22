"""Candidate tree evidence must fail closed on unsupported filesystem entries."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patchtransit.core import PatchTransitError, inventory


class UnsupportedCandidateEntries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO support required")
    def test_fifo_is_rejected_without_opening_or_blocking(self):
        fifo = self.candidate / "special.fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(
            PatchTransitError, "Unsupported candidate entry.*special.fifo"
        ):
            inventory(self.candidate)

    @unittest.skipIf(
        sys.platform == "win32", "Unix-domain socket file support varies on Windows"
    )
    def test_unix_socket_is_rejected(self):
        path = self.candidate / "unix.sock"
        with socket.socket(socket.AF_UNIX) as endpoint:
            endpoint.bind(str(path))
            with self.assertRaisesRegex(
                PatchTransitError, "Unsupported candidate entry.*unix.sock"
            ):
                inventory(self.candidate)

    def test_files_disappearing_during_walk_are_not_silently_ignored(self):
        filename = self.candidate / "vanished.txt"
        filename.write_bytes(b"existing")
        original_is_file = Path.is_file

        def missing_only_for_target(path: Path) -> bool:
            if path == filename:
                return False
            return original_is_file(path)

        with (
            patch(
                "patchtransit.core.pathlib.Path.is_file",
                autospec=True,
                side_effect=missing_only_for_target,
            ),
            self.assertRaisesRegex(
                PatchTransitError, "Unsupported candidate entry.*vanished.txt"
            ),
        ):
            inventory(self.candidate)

    def test_normal_files_and_safe_symlinks_remain_supported(self):
        source = self.candidate / "regular.txt"
        source.write_bytes(b"ordinary bytes\n")
        link = self.candidate / "alias"
        try:
            link.symlink_to("regular.txt")
        except OSError:
            expected = {"regular.txt"}
        else:
            expected = {"regular.txt", "alias"}
        self.assertEqual(expected, set(inventory(self.candidate)))
