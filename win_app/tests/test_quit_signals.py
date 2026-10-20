"""SIGTERM and SIGINT reach the app's quit() through the Qt event loop, once, and closing puts the
previous handlers back."""
import os
import signal
import unittest

try:
    from PySide6.QtCore import QCoreApplication, QTimer
    import quit_signals
except ImportError:  # PySide6 is only in the Windows venv and the Flatpak
    quit_signals = None


@unittest.skipIf(quit_signals is None, "needs PySide6")
class QuitSignalsTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.calls = []
        self.handler = quit_signals.QuitSignals(lambda: (self.calls.append("quit"), self.app.quit()))
        self.addCleanup(self.handler.close)

    def run_loop_after(self, raise_it):
        # raise_signal runs the handler in this process on every OS; os.kill on Windows would end it.
        QTimer.singleShot(0, raise_it)
        QTimer.singleShot(2000, self.app.quit)
        self.app.exec()

    def test_sigterm_quits_through_the_event_loop(self):
        self.run_loop_after(lambda: signal.raise_signal(signal.SIGTERM))
        self.assertEqual(self.calls, ["quit"])

    def test_sigint_quits_and_a_second_signal_does_not_quit_twice(self):
        def twice():
            signal.raise_signal(signal.SIGINT)
            signal.raise_signal(signal.SIGINT)
        self.run_loop_after(twice)
        self.assertEqual(self.calls, ["quit"])

    def test_close_restores_the_previous_handlers(self):
        self.handler.close()
        self.handler.close()
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)


if __name__ == "__main__":
    unittest.main()
