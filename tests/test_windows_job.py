from __future__ import annotations

import ctypes
import subprocess
import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from patchtransit._windows_job import WindowsJob, _ExtendedLimits


class WindowsJobTests(unittest.TestCase):
    def setUp(self):
        self.kernel = SimpleNamespace(
            CreateJobObjectW=Mock(return_value=42),
            SetInformationJobObject=Mock(side_effect=self.configure),
            AssignProcessToJobObject=Mock(return_value=True),
            CloseHandle=Mock(return_value=True),
        )
        self.windows = patch.dict(
            vars(ctypes),
            {
                "WinDLL": lambda *_args, **_kwargs: self.kernel,
                "get_last_error": lambda: 5,
            },
        )
        self.windows.start()
        self.addCleanup(self.windows.stop)

    def configure(self, _handle, code, pointer, length):
        self.assertEqual(9, code)
        self.assertEqual(ctypes.sizeof(_ExtendedLimits), length)
        limits = ctypes.cast(pointer, ctypes.POINTER(_ExtendedLimits)).contents
        self.assertEqual(0x2000, limits.basic.flags)
        return True

    def test_job_closes_once(self):
        job = WindowsJob()
        proc = cast(subprocess.Popen[bytes], SimpleNamespace(_handle=55))
        job.attach(proc)
        self.kernel.AssignProcessToJobObject.assert_called_once_with(42, 55)
        job.close()
        job.close()
        self.kernel.CloseHandle.assert_called_once_with(42)

    def test_create_failure(self):
        self.kernel.CreateJobObjectW.return_value = None
        with self.assertRaises(OSError):
            WindowsJob()
        self.kernel.CloseHandle.assert_not_called()

    def test_configure_failure(self):
        self.kernel.SetInformationJobObject.side_effect = None
        self.kernel.SetInformationJobObject.return_value = False
        with self.assertRaises(OSError):
            WindowsJob()
        self.kernel.CloseHandle.assert_called_once_with(42)

    def test_attach_failure(self):
        job = WindowsJob()
        self.kernel.AssignProcessToJobObject.return_value = False
        proc = cast(subprocess.Popen[bytes], SimpleNamespace(_handle=55))
        with self.assertRaises(OSError):
            job.attach(proc)
        job.close()
        self.kernel.CloseHandle.assert_called_once_with(42)
