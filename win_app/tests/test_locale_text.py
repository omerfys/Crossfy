import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import widgets
from core import i18n, locale


class VisibleTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_authored_us_spelling_reaches_widgets_menus_tooltips_and_notices(self):
        notices = []

        def capture(_tray, title, body, *_args):
            notices.append((title, body))

        with mock.patch.object(locale, "is_us_region", return_value=True):
            with mock.patch.object(QSystemTrayIcon, "showMessage", capture):
                label = widgets.label(i18n.tr("Colourful behaviour"), "note")
                self.assertEqual(label.text(), "Colorful behavior")
                label.setText(i18n.tr("Favourite centre"))
                label.setToolTip(i18n.tr("Organising a colourful favourite"))
                menu = QMenu()
                action = menu.addAction(i18n.tr("Minimise"))
                self.assertEqual(action.text(), "Minimize")
                action.setText(i18n.tr("Initialising cancelled"))
                QSystemTrayIcon().showMessage(i18n.tr("Initialising"), i18n.tr("Cancelled colourful behaviour"))

        self.assertEqual(label.text(), "Favorite center")
        self.assertEqual(label.toolTip(), "Organizing a colorful favorite")
        self.assertEqual(action.text(), "Initializing canceled")
        self.assertEqual(notices, [("Initializing", "Canceled colorful behavior")])
