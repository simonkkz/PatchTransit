"""Evidence collection must work without keeping unbounded child logs in RAM."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from patchtransit.core import execute


class CommandEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_concurrently_hashes_large_stdout_and_stderr(self):
        size = 2 * 1024 * 1024
        script = (
            "import sys; "
            f"sys.stdout.buffer.write(b'x' * {size}); "
            f"sys.stderr.buffer.write(b'y' * {size})"
        )
        result = execute([sys.executable, "-c", script], self.root, timeout=10)
        self.assertEqual(0, result["exit_code"])
        self.assertEqual(
            hashlib.sha256(b"x" * size).hexdigest(), result["stdout_sha256"]
        )
        self.assertEqual(
            hashlib.sha256(b"y" * size).hexdigest(), result["stderr_sha256"]
        )
        self.assertNotIn("stdout", result)
        self.assertNotIn("stderr", result)

    def test_nonzero_exit_still_hashes_both_streams(self):
        script = (
            "import sys; "
            "sys.stdout.buffer.write(b'out\\n'); "
            "sys.stderr.buffer.write(b'err\\n'); "
            "sys.exit(7)"
        )
        result = execute([sys.executable, "-c", script], self.root, timeout=10)
        self.assertEqual(7, result["exit_code"])
        self.assertEqual(hashlib.sha256(b"out\n").hexdigest(), result["stdout_sha256"])
        self.assertEqual(hashlib.sha256(b"err\n").hexdigest(), result["stderr_sha256"])

    def test_empty_outputs_still_have_hashes(self):
        result = execute([sys.executable, "-c", "pass"], self.root, timeout=10)
        self.assertEqual(0, result["exit_code"])
        self.assertEqual(hashlib.sha256(b"").hexdigest(), result["stdout_sha256"])
        self.assertEqual(hashlib.sha256(b"").hexdigest(), result["stderr_sha256"])

    def test_timeout_preserves_existing_result_schema(self):
        result = execute(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            self.root,
            timeout=1,
        )
        self.assertIsNone(result["exit_code"])
        self.assertTrue(result["timeout"])
        self.assertNotIn("stdout_sha256", result)

    def test_timeout_stops_child_processes(self):
        marker = self.root / "orphan.txt"
        child = (
            "import pathlib,time; "
            "time.sleep(2); "
            f"pathlib.Path({str(marker)!r}).write_text('still running')"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
            "time.sleep(8)"
        )
        result = execute([sys.executable, "-c", parent], self.root, timeout=1)
        self.assertTrue(result["timeout"])
        time.sleep(3)
        self.assertFalse(
            marker.exists(), "A timed-out verification left a child running"
        )

    def test_output_limit_stops_child_processes(self):
        marker = self.root / "orphan-output.txt"
        child = (
            "import pathlib,time; "
            "time.sleep(2); "
            f"pathlib.Path({str(marker)!r}).write_text('still running')"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
            "sys.stdout.write('x' * 8192); sys.stdout.flush(); "
            "time.sleep(8)"
        )
        with patch("patchtransit.core.MAX_COMMAND_OUTPUT_BYTES", 1024):
            result = execute([sys.executable, "-c", parent], self.root, timeout=3)
        self.assertEqual("OutputLimitExceeded", result["error"])
        time.sleep(3)
        self.assertFalse(
            marker.exists(), "An output-limited verification left a child running"
        )

    @unittest.skipIf(sys.platform == "win32", "POSIX process groups only")
    def test_missing_process_group_still_kills_command(self):
        with patch("patchtransit.core.os", wraps=os) as simulated_os:
            simulated_os.kill.side_effect = ProcessLookupError("group gone")
            result = execute(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                self.root,
                timeout=1,
            )
        self.assertTrue(result["timeout"])

    def test_windows_job_attached_and_closed(self):
        job = Mock()
        with (
            patch("patchtransit.core.os", wraps=os) as simulated_os,
            patch("patchtransit._windows_job.WindowsJob", return_value=job),
        ):
            simulated_os.name = "nt"
            result = execute([sys.executable, "-c", "pass"], self.root, timeout=3)
        self.assertEqual(0, result["exit_code"])
        job.attach.assert_called_once()
        job.close.assert_called_once()

    def test_windows_job_closed_on_timeout(self):
        job = Mock()
        with (
            patch("patchtransit.core.os", wraps=os) as simulated_os,
            patch("patchtransit._windows_job.WindowsJob", return_value=job),
        ):
            simulated_os.name = "nt"
            result = execute(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                self.root,
                timeout=1,
            )
        self.assertTrue(result["timeout"])
        job.attach.assert_called_once()
        self.assertGreaterEqual(job.close.call_count, 1)

    def test_windows_job_closed_on_output_limit(self):
        job = Mock()
        with (
            patch("patchtransit.core.os", wraps=os) as simulated_os,
            patch("patchtransit._windows_job.WindowsJob", return_value=job),
            patch("patchtransit.core.MAX_COMMAND_OUTPUT_BYTES", 1024),
        ):
            simulated_os.name = "nt"
            result = execute(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys,time; sys.stdout.write('x'*8192); "
                        "sys.stdout.flush(); time.sleep(10)"
                    ),
                ],
                self.root,
                timeout=3,
            )
        self.assertEqual("OutputLimitExceeded", result["error"])
        job.attach.assert_called_once()
        job.close.assert_called()

    def test_windows_job_attach_error_stops_command(self):
        job = Mock()
        job.attach.side_effect = OSError("job assignment failed")
        with (
            patch("patchtransit.core.os", wraps=os) as simulated_os,
            patch("patchtransit._windows_job.WindowsJob", return_value=job),
        ):
            simulated_os.name = "nt"
            result = execute(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                self.root,
                timeout=3,
            )
        self.assertEqual("OSError", result["error"])
        job.close.assert_called()

    def test_missing_executable_reports_error(self):
        result = execute(
            ["patchtransit-executable-does-not-exist"], self.root, timeout=1
        )
        self.assertIsNone(result["exit_code"])
        self.assertEqual("FileNotFoundError", result["error"])

    @unittest.skipIf(
        sys.platform == "win32", "Windows child handles are not guaranteed to inherit"
    )
    def test_inherited_output_handles_do_not_block_after_parent_exits(self):
        script = (
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(4)']); "
            "sys.stdout.buffer.write(b'parent\\n')"
        )
        started = time.monotonic()
        result = execute([sys.executable, "-c", script], self.root, timeout=2)
        elapsed = time.monotonic() - started
        self.assertEqual(0, result["exit_code"])
        self.assertLess(elapsed, 3)
        self.assertEqual(
            hashlib.sha256(b"parent\n").hexdigest(), result["stdout_sha256"]
        )

    def test_excessive_output_is_bounded(self):
        script = "import sys; sys.stdout.buffer.write(b'x' * 8192)"
        with patch("patchtransit.core.MAX_COMMAND_OUTPUT_BYTES", 1024):
            result = execute([sys.executable, "-c", script], self.root, timeout=10)
        self.assertIsNone(result["exit_code"])
        self.assertEqual("OutputLimitExceeded", result["error"])
        self.assertNotIn("stdout_sha256", result)

    def test_output_limit_interrupts_a_still_running_command(self):
        script = (
            "import sys,time; "
            "sys.stderr.buffer.write(b'x' * 8192); "
            "sys.stderr.buffer.flush(); "
            "time.sleep(4)"
        )
        with patch("patchtransit.core.MAX_COMMAND_OUTPUT_BYTES", 1024):
            result = execute([sys.executable, "-c", script], self.root, timeout=2)
        self.assertEqual("OutputLimitExceeded", result["error"])
        self.assertIsNone(result["exit_code"])
        self.assertNotIn("timeout", result)
