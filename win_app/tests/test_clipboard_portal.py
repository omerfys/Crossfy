"""set_contents on the link's reader thread: it never waits for the RemoteDesktop session. The
desktop's consent dialog can hold the session up for longer than the sender waits for an
acknowledgement, so a clipboard arriving before the session is up is dropped at once, not waited on
(Fedora, 10-10-2026: a 2 s wait stalled input and the Mac ended the link)."""

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import clipboard_portal
import inject_portal

# Well under core.link.ACK_STALL_SECONDS (1.5), which core.link needs PyNaCl to import.
QUICK_SECONDS = 0.2
STUB_WAIT_SECONDS = 0.6


class StubRemote:
    """Stands in for inject_portal.Remote. `ask`, like the real one, starts the session and waits
    for it (here STUB_WAIT_SECONDS) unless it is ready, then runs the work on a stub session."""

    def __init__(self, ready):
        self.ready = threading.Event()
        if ready:
            self.ready.set()
        self.asked = 0
        self.session = mock.Mock(changes=5)
        self.session.set_selection.return_value = True

    def ask(self, work, default=None, **_kwargs):
        self.asked += 1
        if not self.ready.is_set():
            time.sleep(STUB_WAIT_SECONDS)
            return default
        return work(self.session)


class SetContentsTest(unittest.TestCase):
    def setUp(self):
        clipboard_portal.forget_sync()
        self.saved = inject_portal._remote

    def tearDown(self):
        inject_portal._remote = self.saved

    def timed(self):
        started = time.monotonic()
        result = clipboard_portal.set_contents("hello", None)
        return result, time.monotonic() - started

    def test_a_session_not_started_is_not_waited_on_and_not_started(self):
        stub = StubRemote(ready=False)
        inject_portal._remote = None
        with mock.patch.object(inject_portal, "remote", return_value=stub):
            result, elapsed = self.timed()
        self.assertFalse(result)
        self.assertLess(elapsed, QUICK_SECONDS)
        self.assertEqual(stub.asked, 0)

    def test_a_session_started_but_not_ready_is_not_waited_on(self):
        stub = StubRemote(ready=False)
        inject_portal._remote = stub
        with mock.patch.object(inject_portal, "remote", return_value=stub):
            result, elapsed = self.timed()
        self.assertFalse(result)
        self.assertLess(elapsed, QUICK_SECONDS)
        self.assertEqual(stub.asked, 0)

    def test_a_ready_session_still_takes_the_clipboard(self):
        stub = StubRemote(ready=True)
        inject_portal._remote = stub
        with mock.patch.object(inject_portal, "remote", return_value=stub):
            self.assertTrue(clipboard_portal.set_contents("hello\r\nthere", None))
        stub.session.set_selection.assert_called_once()
        offer = stub.session.set_selection.call_args[0][0]
        self.assertEqual(offer["text/plain"], b"hello\nthere")
        self.assertEqual(clipboard_portal._synced, 5)


if __name__ == "__main__":
    unittest.main()
