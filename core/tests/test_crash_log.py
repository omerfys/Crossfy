"""core/crash_log.py: a worker thread's uncaught exception reaches the log, and a fatal signal leaves
every thread's Python stack in crash.log."""

import logging
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from core import crash_log

REPO = Path(__file__).resolve().parent.parent.parent


class Catch(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class AThreadThatRaises(unittest.TestCase):
    def setUp(self):
        before = threading.excepthook
        self.addCleanup(setattr, threading, "excepthook", before)
        self.logger = logging.getLogger("crash-log-test")
        self.logger.propagate = False
        self.catch = Catch()
        self.logger.addHandler(self.catch)
        self.addCleanup(self.logger.removeHandler, self.catch)

    def test_its_exception_and_the_thread_are_in_the_log(self):
        with tempfile.TemporaryDirectory() as directory:
            crash_log.install(directory, self.logger, fatal_signals=False)

            def fails():
                raise ValueError("lost on a worker thread")

            worker = threading.Thread(target=fails, name="Beamer-link")
            worker.start()
            worker.join()
        [record] = self.catch.records
        self.assertEqual(record.levelno, logging.CRITICAL)
        self.assertIn("Beamer-link", record.getMessage())
        self.assertIs(record.exc_info[0], ValueError)


def _run_child(directory, ending):
    script = (
        "import os, signal, threading, time\n"
        "from core import crash_log\n"
        f"crash_log.install({directory!r}, fatal_signals=True)\n"
        "def waits_on_the_link():\n"
        "    time.sleep(30)\n"
        "threading.Thread(target=waits_on_the_link, daemon=True).start()\n"
        "time.sleep(0.2)\n"
        + ending
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True, timeout=30)
    return result, (Path(directory) / "crash.log").read_text(encoding="utf-8")


# Not on macOS: a real fatal signal there makes ReportCrash put a crash report and its dialog on
# the desktop of whoever is at the Mac, every run (14-10-2026). The Mac test below proves the same
# wiring without dying.
@unittest.skipUnless(sys.platform.startswith("linux"), "a real fatal signal runs on Linux only")
class AFatalSignal(unittest.TestCase):
    def test_leaves_the_python_stack_of_every_thread_in_crash_log(self):
        with tempfile.TemporaryDirectory() as directory:
            result, text = _run_child(directory, "os.kill(os.getpid(), signal.SIGSEGV)\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Segmentation fault", text)
        self.assertIn("waits_on_the_link", text)


@unittest.skipUnless(sys.platform == "darwin", "the Mac's quiet stand-in for the fatal signal")
class TheFatalSignalHandlerOnTheMac(unittest.TestCase):
    def test_is_armed_and_writes_every_threads_stack_to_crash_log(self):
        # faulthandler's own dump into the very descriptor the fatal handler writes to: the stack
        # the signal would leave, with no process dying and nothing for ReportCrash to see.
        ending = (
            "import faulthandler, sys\n"
            "assert faulthandler.is_enabled()\n"
            "faulthandler.dump_traceback(file=crash_log._fault_file, all_threads=True)\n"
            "crash_log._fault_file.flush()\n"
            "sys.exit(3)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            result, text = _run_child(directory, ending)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("waits_on_the_link", text)
        self.assertIn("Current thread", text)


if __name__ == "__main__":
    unittest.main()
