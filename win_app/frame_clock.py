"""Qt timer intervals matched to the screen displaying a widget."""

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication

_DIVISOR = 1


def set_divisor(n: int) -> None:
    global _DIVISOR
    _DIVISOR = n


def divisor() -> int:
    return _DIVISOR


def refresh_rate(widget=None) -> float:
    """`widget`'s screen's refresh rate, or with no widget the fastest screen's: an overlay is
    started before it moves to the display the crossing is at."""
    screen = widget.screen() if widget is not None else None
    screens = [screen] if screen is not None else QGuiApplication.screens()
    rate = max((float(each.refreshRate()) for each in screens), default=0.0)
    return rate if rate >= 1.0 else 60.0


# The Design page's tiles are thumbnails: at a 120Hz panel's rate their hover doubled the page's
# work for nothing anyone can see, so they play at 60 at most.
PREVIEW_MAX_RATE = 60


def frame_interval_ms(widget=None, max_rate=None) -> int:
    rate = refresh_rate(widget)
    return max(1, int(1000.0 * _DIVISOR / (min(rate, max_rate) if max_rate else rate)))


def frame_timer(parent: QObject, tick, widget=None, max_rate=None) -> QTimer:
    timer = QTimer(parent)
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(frame_interval_ms(widget, max_rate))
    timer.timeout.connect(tick)
    return timer


def start_paced(timer: QTimer, widget=None, max_rate=None) -> None:
    timer.setInterval(frame_interval_ms(widget, max_rate))
    timer.start()
