import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

import crossing_ledger
import widgets
from core import i18n, locale, peerlist


class UserNameLocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_crossing_name_preserves_typed_spelling_in_us_english(self):
        peers = [{"id": "synthetic-peer", "token": "synthetic-token",
                  "name": "Colourful", "port": 24800}]
        source = peerlist.label_for(peers, peer_id="synthetic-peer")
        with mock.patch.object(i18n, "is_source", return_value=True), \
                mock.patch.object(locale, "is_us_region", return_value=True):
            name = crossing_ledger._Name()
            name.resize(600, 40)
            name.set_name(source)
            self.assertEqual(name.full_text, "Colourful")
            self.assertEqual(name.accessibleName(), "Colourful")
            self.assertEqual(name.text(), "Colourful")
            self.assertEqual(name.toolTip(), "Colourful")

    def test_direct_and_interpolated_typed_fields_keep_their_spelling(self):
        with mock.patch.object(i18n, "_language", "en"), \
                mock.patch.object(i18n, "_translations", i18n.load("en")), \
                mock.patch.object(locale, "is_us_region", return_value=True):
            for value in ("Colourful", "Favourite centre", "colour.example", "Organising"):
                with self.subTest(value=value):
                    label = widgets.label(value, "note")
                    label.setToolTip(value)
                    self.assertEqual(label.text(), value)
                    self.assertEqual(label.toolTip(), value)
                    label.setText(i18n.tr("Favourite: {name}").format(name=value))
                    self.assertEqual(label.text(), "Favorite: " + value)


if __name__ == "__main__":
    unittest.main()
