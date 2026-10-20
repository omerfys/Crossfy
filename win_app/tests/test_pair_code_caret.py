import math
import os
import subprocess
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetricsF, QImage
from PySide6.QtWidgets import QApplication

import machines_win
import theme


class PairCodeCaretTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        previous_font = cls.app.font()
        previous_stylesheet = cls.app.styleSheet()
        previous_dark = theme.is_dark()
        cls.addClassCleanup(theme.set_dark, previous_dark)
        cls.addClassCleanup(cls.app.setStyleSheet, previous_stylesheet)
        cls.addClassCleanup(cls.app.setFont, previous_font)
        theme.set_dark(True)
        theme.init_fonts()
        cls.app.setFont(theme.font(theme.TYPE["body"]))
        cls.app.setStyleSheet(theme.stylesheet())

    def setUp(self):
        self.sheet = machines_win.PairingSheet(lambda: None, lambda: None, lambda *_: None, lambda *_: None)
        self.sheet.resize(432, 900)
        self.sheet.show()
        self.app.processEvents()
        self.sheet.code.setFocus()
        self.app.processEvents()
        self.addCleanup(self.sheet.deleteLater)

    def _signal_columns(self, image, rect):
        signal = QColor(theme.colour("signal"))
        scale = image.devicePixelRatio()
        top = math.ceil((rect.top() + 1) * scale)
        bottom = math.floor((rect.bottom() - 1) * scale)
        columns = []
        for x in range(image.width()):
            run = 0
            longest = 0
            for y in range(top, min(bottom + 1, image.height())):
                colour = image.pixelColor(x, y)
                if colour == signal:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
            if longest >= max(3, math.floor((bottom - top + 1) * 0.6)):
                columns.append(x)
        return columns

    def _digit_ink_columns(self, image, rect):
        scale = image.devicePixelRatio()
        columns = []
        for x in range(max(0, math.ceil(rect.left() * scale)),
                       min(image.width(), math.ceil(rect.right() * scale))):
            for y in range(max(0, math.ceil(rect.top() * scale)),
                           min(image.height(), math.ceil(rect.bottom() * scale))):
                colour = image.pixelColor(x, y)
                if colour.red() > 175 and colour.green() > 175 and colour.blue() > 165:
                    columns.append(x)
        return columns

    def test_qt_caret_rectangle_and_painted_caret_share_the_visible_cell(self):
        code = self.sheet.code
        original_font = code.font()
        try:
            child_scale = os.environ.get("PAIR_CODE_CARET_SCALE_CHILD") == "1"
            scale = 1.5 if child_scale else 1.0
            self.assertAlmostEqual(code.grab().devicePixelRatio(), scale)
            for scale in (scale,):
                code.setFont(theme.mono_font(20))
                self.app.processEvents()
                for length in range(7):
                    text = "123456"[:length]
                    for position in range(length + 1):
                        with self.subTest(scale=scale, text=text, position=position):
                            code.setText(text)
                            code.setCursorPosition(position)
                            self.app.processEvents()

                            actual = code.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)
                            self.assertTrue(hasattr(actual, "x"), actual)
                            cells = code._cell_rectangles()
                            metrics = QFontMetricsF(code.font())
                            if position < 6:
                                caret_cell = cells[position]
                                glyph = text[position] if position < length else "0"
                                expected_x = caret_cell.center().x() - metrics.horizontalAdvance(glyph) / 2
                            else:
                                caret_cell = cells[5]
                                expected_x = caret_cell.center().x() + metrics.horizontalAdvance(text[-1]) / 2
                            expected_y = caret_cell.top() + 8
                            expected_height = max(0, caret_cell.height() - 16)
                            self.assertLessEqual(abs(actual.x() - expected_x), 1, (actual, expected_x))
                            self.assertLessEqual(abs(actual.y() - expected_y), 1, (actual, expected_y))

                            painted = code.caret_rect(position)
                            self.assertLessEqual(abs(actual.x() - painted.x()), 1, (actual, painted))
                            self.assertLessEqual(abs(actual.y() - painted.y()), 1, (actual, painted))
                            self.assertGreaterEqual(actual.height(), painted.height() - 1)

                            self.assertLessEqual(abs(painted.x() - expected_x), 1, (painted, expected_x))
                            self.assertAlmostEqual(painted.height(), expected_height, delta=1)
                            self.assertGreaterEqual(actual.x(), caret_cell.left(), (actual, caret_cell))
                            self.assertLessEqual(actual.x(), caret_cell.right(), (actual, caret_cell))
                            # The caret is in the cell with the signal border, where the next digit goes.
                            self.assertIs(caret_cell, cells[min(5, position)])

                            if length == 6:
                                self.assertTrue(0 <= actual.x() <= cells[5].right() + machines_win.CODE_CELL_GAP,
                                                (actual, cells[5]))
                                if position == 6:
                                    sixth = cells[5]
                                    self.assertGreaterEqual(actual.x(), sixth.left() - machines_win.CODE_CELL_GAP)
                                    self.assertLessEqual(actual.x(), sixth.right() + machines_win.CODE_CELL_GAP)
                                    self.assertGreater(actual.x(), code.width() / 2)

                            image = code.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
                            dpr = image.devicePixelRatio()
                            if position == length == 6:
                                last_ink_cell = code.digit_cells()[length - 1]
                                ink_x = self._digit_ink_columns(image, last_ink_cell)
                                self.assertTrue(ink_x, (text, last_ink_cell))
                                trailing_distance = actual.x() - max(ink_x) / dpr
                                self.assertGreaterEqual(trailing_distance, -1, (actual, max(ink_x) / dpr))
                                self.assertLessEqual(trailing_distance,
                                                     cells[length - 1].width() / 2 + machines_win.CODE_CELL_GAP,
                                                     (actual, max(ink_x) / dpr))
                            expected_x = round(painted.x() * dpr)
                            signal_columns = self._signal_columns(image, painted)
                            focus_cell = cells[min(5, position)]
                            border_columns = (focus_cell.left() * dpr, focus_cell.right() * dpr)
                            border_tolerance = max(1.0, dpr)
                            signal_columns = [x for x in signal_columns
                                              if all(abs(x - border) > border_tolerance for border in border_columns)]
                            matching = [x for x in signal_columns if abs(x / dpr - painted.x()) <= 1]
                            self.assertGreaterEqual(len(matching), 1, (painted, signal_columns, border_columns))
                            self.assertEqual(signal_columns, matching,
                                             f"stray signal-coloured caret ink at {signal_columns}, expected {painted}")

                            native_cursor = code.cursorRect()
                            native_x = min(image.width() - 1, max(0, round(native_cursor.x() * dpr)))
                            code.clearFocus()
                            self.app.processEvents()
                            unfocused = code.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
                            native_changes = [
                                (native_x, y) for y in range(max(0, round(painted.top() * dpr)),
                                                             min(image.height(), round(painted.bottom() * dpr) + 1))
                                if image.pixelColor(native_x, y) != unfocused.pixelColor(native_x, y)
                            ]
                            self.assertEqual(native_changes, [],
                                             f"focus paints ink at Qt's native caret x {native_cursor.x()}")
                            code.setFocus()
                            self.app.processEvents()

                            anchor_position = position
                            if code.hasSelectedText():
                                start = code.selectionStart()
                                end = start + len(code.selectedText())
                                anchor_position = end if position == start else start
                            anchor = code.inputMethodQuery(Qt.InputMethodQuery.ImAnchorRectangle)
                            self.assertLessEqual(abs(anchor.x() - code.caret_rect(anchor_position).x()), 1,
                                                 (anchor, anchor_position))

                code.setText("123456")
                code.setSelection(1, 3)
                anchor = code.inputMethodQuery(Qt.InputMethodQuery.ImAnchorRectangle)
                self.assertLessEqual(abs(anchor.x() - code.caret_rect(1).x()), 1, anchor)

            if not child_scale:
                environment = os.environ.copy()
                environment["QT_SCALE_FACTOR"] = "1.5"
                environment["PAIR_CODE_CARET_SCALE_CHILD"] = "1"
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", "win_app.tests.test_pair_code_caret"],
                    cwd=Path(__file__).resolve().parents[2], env=environment,
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            code.setFont(original_font)

    def test_pasting_digits_with_separators_keeps_digits_and_places_caret_at_next_digit(self):
        code = self.sheet.code
        for raw, expected_text, expected_caret in (
            ("123-456", "123456", 6),
            ("123–456", "123456", 6),
            ("123 456", "123456", 6),
            ("12-3", "123", 3),
            ("123-456-789", "123456", 6),
        ):
            with self.subTest(raw=raw):
                code.clear()
                self.app.clipboard().setText(raw)
                code.paste()
                self.app.processEvents()
                self.assertEqual(code.text(), expected_text)
                self.assertEqual(code.cursorPosition(), expected_caret)

    def test_typing_space_or_hyphen_mid_code_does_not_move_caret_to_end(self):
        from PySide6.QtTest import QTest
        code = self.sheet.code
        for separator in (" ", "-"):
            with self.subTest(separator=separator):
                code.setText("1234")
                code.setCursorPosition(2)
                self.app.processEvents()
                QTest.keyClicks(code, separator)
                self.app.processEvents()
                self.assertEqual(code.text(), "1234")
                self.assertEqual(code.cursorPosition(), 2)


if __name__ == "__main__":
    unittest.main()
