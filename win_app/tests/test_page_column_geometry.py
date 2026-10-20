"""Centred scroll columns must follow the document after page and width changes."""

import os
import sys
import unittest
from unittest import mock
from pathlib import Path
from types import MethodType, SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QStackedWidget, QWidget

import kvm_bridge_win as kvm
import theme


class PageColumnGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        theme.init_fonts()
        cls.app.setFont(theme.font(theme.TYPE["body"]))

    def settle(self):
        for _ in range(5):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            self.app.processEvents()

    def test_fit_does_not_reset_an_unchanged_width(self):
        scroll = QWidget()
        column = QWidget()
        scroll.resize(900, 600)
        target = round(kvm.page_column_width(scroll.width() - 16))
        column.setFixedWidth(target)
        fit = kvm.ColumnFit(scroll, column)
        with mock.patch.object(column, "setFixedWidth", wraps=column.setFixedWidth) as set_width:
            fit.fit()
        set_width.assert_not_called()
        scroll.resize(1000, 600)
        with mock.patch.object(column, "setFixedWidth", wraps=column.setFixedWidth) as set_width:
            fit.fit()
        set_width.assert_called_once_with(round(kvm.page_column_width(scroll.width() - 16)))

    def test_centred_column_stays_in_document_after_hidden_page_resize(self):
        window = QWidget()
        window.setMinimumSize(640, 600)
        stack = QStackedWidget()
        row = QHBoxLayout(window)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        sidebar = QWidget()
        sidebar.setFixedWidth(177)
        row.addWidget(sidebar)
        row.addWidget(stack)
        for index in range(5):
            owner = SimpleNamespace(
                scope_labels={}, _host="localhost-live.example.lan",
                _hide_addresses=lambda: False, _set_hide_addresses=lambda *_: None,
                _shown=lambda text: text, save=lambda: None, _firewall_action=lambda: None,
                _set_language=lambda *_: None, relaunch=lambda *_: None,
            )
            owner._firewall_module = MethodType(kvm.WindowsApplication._firewall_module, owner)
            scroll, layout = kvm.WindowsApplication._page_shell(
                owner, "Connection", "Reach this machine")
            kvm.WindowsApplication._connection_page(owner, layout, kvm.default_config())
            owner.firewall_note.setText(
                "Windows Firewall lets your other machines reach Beamer on port 24820 on this "
                "private network, and lets a new machine discover this PC.")
            layout.addStretch(1)
            stack.addWidget(scroll)
        self.addCleanup(window.deleteLater)
        window.resize(1000, 800)
        window.show()
        self.settle()
        for width in (640, 1600, 640, 1000, 640):
            window.resize(width, 600)
            self.settle()
            for index in range(stack.count()):
                stack.setCurrentIndex(index)
                self.settle()
                page = stack.currentWidget().widget()
                column = page.findChild(QWidget, "page_column")
                bounds = column.geometry()
                with self.subTest(width=width, page=index):
                    self.assertLessEqual(bounds.right(), page.width() - 1,
                                         f"column {bounds.getRect()}, document {page.size().toTuple()}, "
                                         f"layout {page.layout().geometry().getRect()}")
                    self.assertAlmostEqual(bounds.x(), (page.width() - column.width()) / 2, delta=1,
                                           msg=f"column {bounds.getRect()}, document {page.size().toTuple()}, "
                                           f"layout {page.layout().geometry().getRect()}")


if __name__ == "__main__":
    unittest.main()
