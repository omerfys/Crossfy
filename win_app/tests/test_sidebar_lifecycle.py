"""Application-wide sidebar hooks stay cheap and end with their owning window."""

import statistics
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent, QPaintEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from shiboken6 import getCppPointer, isValid

import theme
import widgets


def window_with_sidebar(sidebar_type=widgets.Sidebar):
    window = QWidget()
    layout = QVBoxLayout(window)
    sidebar = sidebar_type([("overview", "Overview", ""), ("crossing", "Crossing", "")],
                           lambda _key: None, parent=window)
    layout.addWidget(sidebar)
    sidebar.select("overview")
    return window, sidebar


class SidebarLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        theme.init_fonts()
        widgets.keyboard_navigation()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_destroyed_sidebars_leave_no_application_hooks(self):
        app = self.app
        removed = []
        original_remove = app.removeEventFilter

        def remove(filter_object):
            removed.append(getCppPointer(filter_object)[0])
            original_remove(filter_object)

        errors = []

        class TrackedSidebar(widgets.Sidebar):
            def __init__(self, *args, **kwargs):
                self.presses = 0
                self.focus_changes = 0
                super().__init__(*args, **kwargs)

            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.MouseButtonPress:
                    self.presses += 1
                return super().eventFilter(watched, event)

            def _focus_changed(self, old, new):
                self.focus_changes += 1
                super()._focus_changed(old, new)

        with patch.object(app, "removeEventFilter", remove), patch.object(sys, "excepthook", lambda *_error: errors.append(_error)):
            destroyed = []
            for _ in range(2):
                window, sidebar = window_with_sidebar(TrackedSidebar)
                pointer = getCppPointer(sidebar)[0]
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.assertFalse(isValid(window))
                self.assertFalse(isValid(sidebar))
                self.assertIn(pointer, removed)
                destroyed.append((sidebar, sidebar.presses, sidebar.focus_changes))

            window, sidebar = window_with_sidebar(TrackedSidebar)
            try:
                mouse = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(1, 1), QPointF(1, 1),
                                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                    Qt.KeyboardModifier.NoModifier)
                QCoreApplication.postEvent(window, mouse)
                QCoreApplication.sendPostedEvents(window, QEvent.Type.MouseButtonPress)
                app.focusChanged.emit(None, sidebar._buttons["overview"])
                self.assertEqual(sidebar.presses, 1)
                self.assertGreaterEqual(sidebar.focus_changes, 1)
                self.assertEqual([(old.presses, old.focus_changes) for old, _, _ in destroyed],
                                 [(presses, changes) for _, presses, changes in destroyed])
                self.assertEqual(errors, [])
            finally:
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_ring_update_skips_a_deleted_page_button(self):
        window, sidebar = window_with_sidebar()
        try:
            button = sidebar._buttons["crossing"]
            button.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.assertFalse(isValid(button))
            sidebar._update_rings()
        finally:
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_unchanged_pointer_selection_does_not_walk_every_design_tile(self):
        window, sidebar = window_with_sidebar()
        sidebar._last_keyboard_mode = sidebar.keyboard_mode
        try:
            with patch.object(window, "findChildren", side_effect=AssertionError("tile scan on unchanged mode")):
                sidebar.select("overview")
        finally:
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_keyboard_mode_change_refreshes_design_tile_focus_rings(self):
        window, sidebar = window_with_sidebar()
        sidebar._last_keyboard_mode = not sidebar.keyboard_mode
        try:
            with patch.object(window, "findChildren", wraps=window.findChildren) as find_children:
                sidebar._update_rings()
            find_children.assert_called_once_with(widgets._Tile)
        finally:
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_pointer_selection_does_not_select_the_sidebar_twice(self):
        window, sidebar = window_with_sidebar()
        sidebar._on_select = lambda key: sidebar.select(key)
        original_select = sidebar.select
        try:
            with patch.object(sidebar, "select", wraps=original_select) as select:
                sidebar._pointer_select("crossing")
            self.assertEqual(select.call_count, 1)
        finally:
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_irrelevant_events_never_inspect_the_watched_window(self):
        class Watched:
            def window(self):
                raise AssertionError("An irrelevant event must not inspect its widget")

        window, sidebar = window_with_sidebar()
        recorder = widgets.InputRecorder("Right Ctrl", lambda *_args: None, lambda *_args: 0)
        jump = widgets.JumpKeyRecorder(lambda *_args: None)
        recorder.armed = jump.armed = True
        try:
            for kind in (QEvent.Type.Paint, QEvent.Type.Polish, QEvent.Type.StyleChange,
                         QEvent.Type.LayoutRequest):
                for filter_object in (sidebar, widgets.keyboard_navigation(), recorder, jump):
                    self.assertIs(filter_object.eventFilter(Watched(), QEvent(kind)), False)
        finally:
            recorder.armed = jump.armed = False
            recorder.deleteLater()
            jump.deleteLater()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_sidebar_paint_filter_cost_stays_within_three_times_baseline(self):
        plain = QWidget()
        event = QPaintEvent(QRect(0, 0, 1, 1))

        def duration():
            start = time.perf_counter()
            for _ in range(2000):
                QApplication.sendEvent(plain, event)
            return time.perf_counter() - start

        try:
            duration()
            baseline = statistics.median(duration() for _ in range(5))
            window, sidebar = window_with_sidebar()
            try:
                duration()
                with_sidebar = statistics.median(duration() for _ in range(5))
                self.assertLess(with_sidebar, baseline * 3, (baseline, with_sidebar))
            finally:
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            plain.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
