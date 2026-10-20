"""Hide a driven machine's pointer once its driver lets go, until that pointer moves again.

Without it the pointer stays wherever the driver last put it, and on a desk of two screens the one
not in use still shows a pointer, so which machine has the input is a guess (rufusmp on Instagram,
12-10-2026). Any movement shows it again, whoever makes it: this machine's own mouse or trackpad, or
a driver coming back, whose first injected move is the end of the hide.

Movement is read by polling the pointer's position, the one reading every platform has, and only
while hidden. The baseline is taken SETTLE_SECONDS after the hide, not at it: the driver's last
moves are still being injected as it lets go, and reading one of those as this machine's own hand
would show the pointer the moment it was hidden.
"""

import logging
import threading
from typing import Callable, Optional, Tuple

POLL_SECONDS = 0.1
SETTLE_SECONDS = 0.3


class IdlePointer:
    def __init__(
        self,
        hide: Callable[[], None],
        show: Callable[[], None],
        position: Callable[[], Tuple[int, int]],
        poll_seconds: float = POLL_SECONDS,
        settle_seconds: float = SETTLE_SECONDS,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._hide = hide
        self._show = show
        self._position = position
        self._poll = poll_seconds
        self._settle = settle_seconds
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._stop: Optional[threading.Event] = None

    @property
    def hidden(self) -> bool:
        return self._stop is not None

    def driver_left(self) -> None:
        with self._lock:
            if self._stop is not None:
                return
            try:
                self._hide()
            except Exception:
                self._logger.exception("could not hide the pointer after the driver left")
                return
            stop = self._stop = threading.Event()
        threading.Thread(target=self._watch, args=(stop,), name="Beamer-idle-pointer", daemon=True).start()

    def cancel(self) -> None:
        """Show the pointer now: a driver arrived, or the app is stopping."""
        with self._lock:
            stop, self._stop = self._stop, None
            if stop is None:
                return
            stop.set()
            self._show_quietly()

    def _watch(self, stop: threading.Event) -> None:
        if stop.wait(self._settle):
            return
        try:
            start = self._position()
            while not stop.wait(self._poll):
                if self._position() != start:
                    break
        except Exception:
            # A pointer that cannot be read cannot be watched, and a hidden one nobody can bring
            # back is worse than one left showing.
            self._logger.exception("could not read the pointer while it was hidden; showing it")
        with self._lock:
            if self._stop is not stop:
                return
            self._stop = None
            self._show_quietly()

    def _show_quietly(self) -> None:
        try:
            self._show()
        except Exception:
            self._logger.exception("could not show the pointer again")
