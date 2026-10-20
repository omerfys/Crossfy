import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import kvm_bridge_win
import app_config
from core import effects


class LengthSizeSliderTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.length = kvm_bridge_win._DesignChoiceSlider(
            "Length", 25, 250, 5, 100, (0.5, 1.0, 2.0), effects.LENGTHS)
        self.size = kvm_bridge_win._DesignChoiceSlider(
            "Size", 20, 80, 1, 1000, (0.03, 0.045, 0.06), effects.SIZES)

    def tearDown(self):
        self.length.slider.close()
        self.size.slider.close()

    def test_slider_detent_and_keyboard_step(self):
        control = self.length
        control.set_numeric(0.53)
        control._snap(53)
        self.assertEqual(control.numeric_value(), 0.5)
        slider = control.slider
        slider.setValue(100)
        QTest.keyClick(slider, Qt.Key.Key_Right)
        self.assertEqual(slider.value(), 105)

    def test_slider_can_be_disabled_while_following_another_design(self):
        self.length.set_enabled(False)
        self.assertFalse(self.length.slider.isEnabled())
        self.length.set_enabled(True)
        self.assertTrue(self.length.slider.isEnabled())

    def test_design_sliders_keep_their_logical_width_cap(self):
        self.assertEqual(self.length.view.maximumWidth(), 240)
        self.assertEqual(self.size.view.maximumWidth(), 240)

    def test_playback_and_depth_readouts_keep_fixed_width(self):
        length, size = effects.design_slider_readouts("beam", 2.0, 0.06, 1920, 1080)
        length_readout, size_readout = kvm_bridge_win.design_readout(), kvm_bridge_win.design_readout()
        length_readout.setText(length)
        size_readout.setText(size)
        self.assertEqual(length_readout.text(), "1.2 s")
        self.assertTrue(size_readout.text().endswith(" pt"))
        self.assertEqual(length_readout.width(), 58)
        self.assertEqual(size_readout.width(), 58)
        self.assertEqual(effects.play_through_seconds("beam", 2.0), 1.2)
        self.assertIn("playback time", self.length.slider.accessibleDescription())

    def test_preset_only_windows_settings_migrate_and_round_trip_both_forms(self):
        config = app_config.config_from_dict({
            "host": "192.0.2.1", "port": 51820, "auth_token": "synthetic",
            "effect_length": "long", "effect_size": "small",
        })
        saved = app_config.config_to_dict(config)
        self.assertEqual((saved["effect_pace"], saved["effect_size_fraction"],
                          saved["effect_length"], saved["effect_size"]),
                         (2.0, 0.03, "long", "small"))


if __name__ == "__main__":
    unittest.main()
