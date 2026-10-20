"""A selected Vernier choice is filled with the current palette's ink: black in Light, as in Dark it
is the light ink. It took the dark palette's in both, so Light showed no fill (Linux, 06-10)."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

import theme
import tokens
import widgets


class ChoiceFillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setFont(theme.font(theme.TYPE["body"]))

    def setUp(self):
        self.previous_stylesheet = self.app.styleSheet()
        theme.set_dark(True)
        theme.apply_stylesheet(self.app)
        self.host = QWidget()

    def tearDown(self):
        self.host.close()
        self.host.deleteLater()
        self.app.setStyleSheet(self.previous_stylesheet)
        theme.set_dark(True)

    def assert_selected_fill(self, button, expected):
        self.app.processEvents()
        image = button.grab().toImage()
        dpr = image.devicePixelRatio()
        self.assertEqual(image.pixelColor(round(8 * dpr), round(8 * dpr)), QColor(expected))

    def assert_label_ink(self, button, expected):
        # The label is painted by ActionButton.paintEvent, not the stylesheet: it must follow the
        # palette too, or Light shows black text on the black fill.
        image = button.grab().toImage()
        want = QColor(expected)
        near = sum(1 for x in range(image.width()) for y in range(image.height())
                   if max(abs(image.pixelColor(x, y).red() - want.red()),
                          abs(image.pixelColor(x, y).green() - want.green()),
                          abs(image.pixelColor(x, y).blue() - want.blue())) < 24)
        self.assertGreater(near, 10)

    def test_settings_choice_fill_matches_selected_colour_in_both_themes(self):
        choice = widgets.Choice((("one", "First option"), ("two", "Second option")), 2, "one", parent=self.host)
        choice.view.resize(choice.view.sizeHint())
        self.host.resize(choice.view.sizeHint())
        self.host.show()
        for dark in (True, False):
            with self.subTest(dark=dark):
                theme.set_dark(dark)
                theme.apply_stylesheet(self.app)
                self.app.processEvents()
                palette = tokens.PALETTE if dark else tokens.PALETTE_LIGHT
                self.assert_selected_fill(choice._buttons["one"], palette["ink"])
                self.assert_label_ink(choice._buttons["one"], palette["ground"])

if __name__ == "__main__":
    unittest.main()
