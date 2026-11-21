"""Evidence collection must work without keeping unbounded child logs in RAM."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

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
        script = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)"
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

    def test_missing_executable_reports_error(self):
        result = execute(
            ["patchtransit-executable-does-not-exist"], self.root, timeout=1
        )
        self.assertIsNone(result["exit_code"])
        self.assertEqual("FileNotFoundError", result["error"])
