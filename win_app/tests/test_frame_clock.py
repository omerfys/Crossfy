import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import frame_clock


class FrameClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_interval_uses_the_screen_refresh_rate_floor(self):
        for rate, expected in ((120.0, 8), (60.0, 16), (0.0, 16)):
            screen_rate = rate
            with self.subTest(rate=rate), mock.patch.object(
                    frame_clock.QGuiApplication, "screens",
                    return_value=[] if rate == 0.0 else [SimpleNamespace(refreshRate=lambda: screen_rate)]):
                self.assertEqual(frame_clock.frame_interval_ms(), expected)

    def test_interval_applies_the_selected_divisor(self):
        self.addCleanup(frame_clock.set_divisor, 1)
        with mock.patch.object(frame_clock, "refresh_rate", return_value=120.0):
            for divisor, expected in ((1, 8), (2, 16), (4, 33)):
                with self.subTest(divisor=divisor):
                    frame_clock.set_divisor(divisor)
                    self.assertEqual(frame_clock.frame_interval_ms(), expected)

    def test_with_no_widget_the_fastest_screen_paces_the_clock(self):
        screens = [SimpleNamespace(refreshRate=lambda: 60.0), SimpleNamespace(refreshRate=lambda: 120.0)]
        with mock.patch.object(frame_clock.QGuiApplication, "screens", return_value=screens):
            self.assertEqual(frame_clock.frame_interval_ms(), 8)

    def test_frame_timer_is_precise_and_uses_the_widget_rate(self):
        widget = object()
        with mock.patch.object(frame_clock, "refresh_rate", return_value=120.0):
            timer = frame_clock.frame_timer(None, lambda: None, widget)
        self.assertEqual(timer.interval(), 8)
        self.assertEqual(timer.timerType(), Qt.TimerType.PreciseTimer)

    def test_design_previews_play_at_sixty_at_most(self):
        with mock.patch.object(frame_clock, "refresh_rate", return_value=120.0):
            self.assertEqual(frame_clock.frame_interval_ms(max_rate=frame_clock.PREVIEW_MAX_RATE), 16)
        with mock.patch.object(frame_clock, "refresh_rate", return_value=50.0):
            self.assertEqual(frame_clock.frame_interval_ms(max_rate=frame_clock.PREVIEW_MAX_RATE), 20)


if __name__ == "__main__":
    unittest.main()
