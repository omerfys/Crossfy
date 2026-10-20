import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "win_app"))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

import effect_previews
import theme
from core import effects


class EffectPreviewTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _frame_at(self, picture, now, playing_since=None, reduced=False):
        picture.resize(180, effect_previews.STILL_HEIGHT)
        picture.playing_since = playing_since
        picture._image = None
        frames = []
        picture._paint_still = lambda _painter, t, still=False: frames.append((t, still))
        with patch.object(effect_previews.time, "monotonic", return_value=now), \
                patch.object(effect_previews, "system_reduced_motion", return_value=reduced), \
                patch.object(effect_previews, "QPainter"):
            picture.paintEvent(None)
        return frames[-1]

    def test_crossing_preview_stays_on_its_canonical_still_until_hover_intent_expires(self):
        picture = effect_previews.EffectStill("rupture", ("#ff0000",))
        with patch.object(effects, "still_time", return_value=1.9):
            idle = self._frame_at(picture, 100.0)
            intent = self._frame_at(picture, 100.05, playing_since=100.1)
        self.assertEqual(idle, (1.9, True))
        self.assertEqual(intent, (1.9, True))

    def test_crossing_preview_starts_at_approach_zero_then_uses_live_elapsed_time(self):
        picture = effect_previews.EffectStill("rupture", ("#ff0000",))
        with patch.object(effects, "still_time", return_value=1.9):
            approach = self._frame_at(picture, 100.15, playing_since=100.1)
            live = self._frame_at(picture, 100.8, playing_since=100.1)
        self.assertAlmostEqual(approach[0], 0.05)
        self.assertFalse(approach[1])
        self.assertAlmostEqual(live[0], 0.7)
        self.assertFalse(live[1])

    def test_reduced_motion_returns_to_the_canonical_still_during_playback(self):
        picture = effect_previews.EffectStill("rupture", ("#ff0000",))
        with patch.object(effects, "still_time", return_value=1.9):
            frame = self._frame_at(picture, 100.8, playing_since=100.1, reduced=True)
        self.assertEqual(frame, (1.9, True))

    def test_switch_preview_continues_from_its_existing_still(self):
        picture = effect_previews.SwitchStill("match", "rupture", ("#ff0000",))
        with patch.object(effects, "still_time", return_value=0.8):
            frame = self._frame_at(picture, 100.3, playing_since=100.1)
        self.assertAlmostEqual(frame[0], 1.0)
        self.assertFalse(frame[1])

    def test_reduced_motion_keeps_a_switch_on_its_canonical_still(self):
        picture = effect_previews.SwitchStill("match", "rupture", ("#ff0000",))
        with patch.object(effects, "still_time", return_value=0.8):
            frame = self._frame_at(picture, 100.3, playing_since=100.1, reduced=True)
        self.assertEqual(frame, (0.8, True))

    def test_specimen_screens_use_the_card_ground_while_live_scenes_keep_the_dark_ground(self):
        original_appearance = theme.is_dark()
        theme.set_dark(False)
        ground = theme.colour("ground")
        view = QRectF(0, 0, 200, 100)

        def render(scene):
            image = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            effect_previews.paint_scene(painter, QRectF(0, 0, 200, 100), view, scene, 11, False)
            painter.end()
            return image

        scene = {"screens": [(0, 0, 200, 100, "mac")], "pens": [], "pointer": None, "notch": None}
        try:
            specimen = render(dict(scene, seam=(100, 0, 100, 100)))
            self.assertEqual(specimen.pixelColor(50, 50), ground)
            self.assertEqual(specimen.pixelColor(100, 50), QColor(theme.colour("rule")))
            self.assertEqual(render(scene).pixelColor(50, 50), QColor(effects.PREVIEW_TILE_GROUND))
        finally:
            theme.set_dark(original_appearance)


if __name__ == "__main__":
    unittest.main()
