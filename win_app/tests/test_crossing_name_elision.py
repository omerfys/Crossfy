"""Long peer names fit in the wrapped Crossing summary."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QLabel, QWidget

import kvm_bridge_win


LONG_NAME = "M" * 48


class CrossingNameElisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_summary_label(self):
        page = QWidget()
        page.resize(640, 400)
        label = QLabel(page)
        label.setWordWrap(True)
        label.setGeometry(0, 0, 360, 100)
        self.addCleanup(page.deleteLater)
        return label

    def summary_text(self, label, name):
        return kvm_bridge_win.ways_summary_for_label(
            label, ["edge"], "", [], "top_left", "Right Ctrl", "double_tap", name
        )

    def test_long_name_is_elided_and_wrapped_lines_fit_the_640_pixel_page(self):
        label = self.make_summary_label()
        label.setText(self.summary_text(label, LONG_NAME))
        self.assertIn("…", label.text())

        option = QTextOption(Qt.AlignmentFlag.AlignLeft)
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        layout = QTextLayout(label.text(), label.font(), label)
        layout.setTextOption(option)
        layout.beginLayout()
        widths = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(label.contentsRect().width())
            widths.append(line.naturalTextWidth())
        layout.endLayout()
        self.assertTrue(widths)
        self.assertLessEqual(max(widths), label.contentsRect().width())

    def test_short_name_stays_in_full(self):
        label = self.make_summary_label()
        label.setText(self.summary_text(label, "Studio PC"))
        self.assertIn("Studio PC", label.text())
        self.assertNotIn("…", label.text())

    def test_a_label_laid_out_after_its_text_is_set_elides_on_its_resize(self):
        # The Crossing page is hidden at start, so the sentence is set before the label has a width.
        page = QWidget()
        self.addCleanup(page.deleteLater)
        label = QLabel(page)
        label.setWordWrap(True)
        refresh = lambda: label.setText(self.summary_text(label, LONG_NAME))
        label.resize(0, 0)
        hook = kvm_bridge_win._OnResize(label, refresh)
        refresh()
        self.assertIn(LONG_NAME, label.text())
        label.resize(360, 100)
        page.show()
        self.app.processEvents()
        self.assertIn("…", label.text())
        self.assertIsNotNone(hook)


if __name__ == "__main__":
    unittest.main()
