import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

import machines_win
import theme


class LeftOutRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        theme.init_fonts()

    def test_button_can_be_pressed_before_the_first_refresh(self):
        calls = []
        row = machines_win.PeerRow("token", *([lambda *_: None] * 3),
                                   lambda token, enabled: calls.append((token, enabled)), lambda *_: None)

        row.left_out.click()

        self.assertEqual(calls, [("token", True)])

    def test_left_out_row_explains_the_shortcut_and_offers_put_back(self):
        calls = []
        row = machines_win.PeerRow("token", *([lambda *_: None] * 3),
                                   lambda token, enabled: calls.append((token, enabled)), lambda *_: None)
        entry = {"token": "token", "port": 24820, "in_use": True, "left_out": True,
                 "left_out_ways": ["edge"], "send": True, "allow_drive": True}
        state = SimpleNamespace(tone="amber", word="Linked", detail="Connected to Studio.")
        row.refresh(entry, "Studio", state, "Mac · 192.0.2.10 · port 24820", cycle_mode="last")

        self.assertEqual(row.left_out.text(), "Put back")
        self.assertFalse(row.left_out_note.isHidden())
        self.assertEqual(row.left_out_note.text(), "Left out of the layout. The shortcut and the menu still reach it.")
        row.left_out.click()
        self.assertEqual(calls, [("token", False)])

        row.refresh({**entry, "left_out": False}, "Studio", state, "Mac · 192.0.2.10 · port 24820", cycle_mode="last")
        self.assertEqual(row.left_out.text(), "Leave out")
        self.assertTrue(row.left_out_note.isHidden())


if __name__ == "__main__":
    unittest.main()
