"""1.5.2 rc10: the Crossing page's selected-machine header went side by side at a fixed 120 DIP for its
text, under the "Selected machine" eyebrow's own 124 on Windows, and side by side it asked for its
side-by-side minimum. Shown first at a narrow width, before ColumnFit pins the column, that minimum held
the page wider than the scroll area's viewport, which kept the header side by side, while stacked was
stable too; QScrollArea's cached minimum lagged each switch, so it resized the page between the two with
no Python frame in between until the native stack overflowed (0xC00000FD on the rig). On the Mac the
loop never starts, so this fails only on Windows if the bug returns, and fails rather than crashes."""

import unittest

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QBoxLayout

import test_settings_layout_acceptance as acceptance


class ResizeCounter(QObject):
    """Counts a widget's resizes. Past the cap it swallows them, which ends a runaway loop as a test
    failure on any stack size instead of a crash; installed after QScrollArea's own filter, so it runs
    first."""

    CAP = 200

    def __init__(self, widget) -> None:
        super().__init__(widget)
        self.count = 0
        widget.installEventFilter(self)

    def eventFilter(self, _watched, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.count += 1
            return self.count > self.CAP
        return False


class CrossingHeaderResizeTests(unittest.TestCase):
    setUpClass = acceptance.SettingsLayoutAcceptance.__dict__["setUpClass"]
    setUp = acceptance.SettingsLayoutAcceptance.setUp
    tearDown = acceptance.SettingsLayoutAcceptance.tearDown
    settle = acceptance.SettingsLayoutAcceptance.settle
    set_size = acceptance.SettingsLayoutAcceptance.set_size
    page_scroll = acceptance.SettingsLayoutAcceptance.page_scroll

    def test_header_direction_never_holds_the_page_open(self):
        scroll = self.window.stack.widget(self.window._page_indexes["crossing"])
        header = self.window.crossing_ledger
        counter = ResizeCounter(scroll.widget())
        # rc10's path: the page is first shown narrow, before ColumnFit has pinned its column, with
        # the header built side by side.
        self.set_size(320)
        for width in (320, *range(326, 720, 6), *range(714, 320, -6)):
            counter.count = 0
            self.set_size(width)
            if width == 320:
                self.page_scroll("crossing")
            with self.subTest(width=width):
                self.assertTrue(header.isVisible())
                self.assertLess(counter.count, ResizeCounter.CAP, "the page resized without end")
                self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())
                self.assertLessEqual(header.minimumSizeHint().width(), header.width())

    def test_long_unbroken_machine_name_elides_at_320_dip_without_widening_header(self):
        full_name = "M" * 60
        self.window._peer_entries[0]["name"] = full_name
        self.window._reflect_ways()
        self.set_size(320)
        self.page_scroll("crossing")

        header = self.window.crossing_ledger
        name = header.rows[self.window._peer_entries[0]["id"]].name
        with self.subTest("visible text is elided"):
            self.assertTrue(name.text().endswith("…"))
            self.assertLess(name.fontMetrics().horizontalAdvance(name.text()), name.width() + 1)
        with self.subTest("full name remains available"):
            self.assertEqual(name.toolTip(), full_name)
            self.assertEqual(name.accessibleName(), full_name)
        with self.subTest("header still asks only for its stacked minimum"):
            self.assertLessEqual(header.minimumSizeHint().width(), header.width())
            self.assertLessEqual(header.width(), self.window.stack.widget(
                self.window._page_indexes["crossing"]
            ).width())

if __name__ == "__main__":
    unittest.main()
