"""Git subprocess wrappers must bound captured output even on failure."""

from __future__ import annotations

import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from patchtransit.core import PatchTransitError, run


class BoundedSubprocessCapture(unittest.TestCase):
    def test_small_stdout_and_stderr_preserved(self):
        code = (
            "import sys;sys.stdout.buffer.write(b'out');sys.stderr.buffer.write(b'err')"
        )
        result = run([sys.executable, "-c", code])
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertEqual(
            (b"out", b"err", 0), (result.stdout, result.stderr, result.returncode)
        )

    def test_nonzero_exit_remains_result(self):
        code = "import sys;sys.stderr.write('bad');sys.exit(7)"
        result = run([sys.executable, "-c", code])
        self.assertEqual(7, result.returncode)
        self.assertEqual(b"bad", result.stderr)

    def test_binary_input_is_forwarded_exactly(self):
        payload = b"binary\\x00data\\xff"
        code = "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())"
        self.assertEqual(
            payload, run([sys.executable, "-c", code], input_data=payload).stdout
        )

    def test_stdout_limit_is_checked_while_process_still_running(self):
        code = (
            "import sys,time;sys.stdout.buffer.write(b'X'*8192);"
            "sys.stdout.buffer.flush();time.sleep(4)"
        )
        started = time.monotonic()
        with (
            patch("patchtransit.core.MAX_GIT_CAPTURE_BYTES", 1024),
            self.assertRaisesRegex(PatchTransitError, "output exceeds safety limit"),
        ):
            run([sys.executable, "-c", code], timeout=2)
        self.assertLess(time.monotonic() - started, 3.0)

    def test_stderr_limit_is_enforced(self):
        code = "import sys;sys.stderr.buffer.write(b'E'*8192)"
        with (
            patch("patchtransit.core.MAX_GIT_CAPTURE_BYTES", 1024),
            self.assertRaisesRegex(PatchTransitError, "output exceeds safety limit"),
        ):
            run([sys.executable, "-c", code], timeout=5)

    def test_timeout_kills_command_and_reports_explicit_error(self):
        with self.assertRaisesRegex(PatchTransitError, "Command timed out"):
            run([sys.executable, "-c", "import time;time.sleep(5)"], timeout=1)

    def test_missing_executable_uses_project_error(self):
        with self.assertRaisesRegex(PatchTransitError, "Required executable not found"):
            run(["this-executable-definitely-does-not-exist-123"])
