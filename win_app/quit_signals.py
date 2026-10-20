"""SIGTERM and SIGINT quit the Qt app through its own quit(), so a restart from outside (a session
over ssh, the desktop's logout, `kill`) still restores the pointer and stops the portals and the
injector, instead of dying mid-capture (14-10-2026, Fedora 1.5.3 to 1.5.4).

Python runs a signal handler only between bytecodes on the main thread, and that thread sits in
Qt's event loop, in C, until something wakes it. So the signal's byte goes to a socket that
Python's set_wakeup_fd writes, a QSocketNotifier on its other end wakes the loop, and the handler
then runs and asks for quit() on the next turn of the loop."""

import logging
import signal
import socket
from typing import Callable, Optional

from PySide6.QtCore import QObject, QSocketNotifier, QTimer

LOGGER = logging.getLogger(__name__)

SIGNALS = tuple(getattr(signal, name) for name in ("SIGTERM", "SIGINT") if hasattr(signal, name))


class QuitSignals(QObject):
    def __init__(self, on_quit: Callable[[], None], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._on_quit = on_quit
        self._quitting = False
        self._reader, self._writer = socket.socketpair()
        for end in (self._reader, self._writer):
            end.setblocking(False)
        self._previous_fd = signal.set_wakeup_fd(self._writer.fileno())
        self._previous = {number: signal.signal(number, self._handle) for number in SIGNALS}
        self._notifier = QSocketNotifier(self._reader.fileno(), QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._drain)

    def _drain(self, *_args) -> None:
        try:
            while self._reader.recv(64):
                pass
        except (BlockingIOError, InterruptedError):
            pass

    def _handle(self, number, _frame) -> None:
        if self._quitting:
            return
        self._quitting = True
        LOGGER.info("%s received; quitting", signal.Signals(number).name)
        QTimer.singleShot(0, self._on_quit)

    def close(self) -> None:
        if self._reader.fileno() == -1:
            return
        self._notifier.setEnabled(False)
        for number, previous in self._previous.items():
            signal.signal(number, previous)
        signal.set_wakeup_fd(self._previous_fd)
        self._reader.close()
        self._writer.close()
