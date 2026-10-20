import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from core import effects
import theme
import widgets
from test_settings_layout_acceptance import SyntheticWindow, responder_harness, write_synthetic_settings
from tools.render_colour_choices import QtRenderer, relative_luminance, style_cases


def card_metrics(renderer, family, style):
    """(contrast, coverage) of a tile's picture against the card it is drawn on: the contrast the
    strongest tenth of its effect pixels reach, and the share of the picture changed by effect marks.
    The baseline uses the same scene, screens, seam and pointer, with only its pens removed."""
    import effect_previews

    preview_id = style if family == "crossing" else f"switch:{style}"
    image = renderer.preview(preview_id, "signal")
    draw_scene = effect_previews.paint_scene

    def without_effects(painter, rect, view, scene, pointer_size, labels):
        return draw_scene(painter, rect, view, dict(scene, pens=[]), pointer_size, labels)

    with mock.patch.object(effect_previews, "paint_scene", side_effect=without_effects):
        baseline = renderer.preview(preview_id, "signal")
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    baseline = baseline.convertToFormat(QImage.Format.Format_RGBA8888)
    ground = QColor(theme.colour("ground")).getRgb()[:3]
    ratios = []
    for y in range(image.height()):
        for x in range(image.width()):
            rgb = image.pixelColor(x, y).getRgb()[:3]
            base = baseline.pixelColor(x, y).getRgb()[:3]
            if max(abs(a - b) for a, b in zip(rgb, base)) > 3:
                lum = relative_luminance(rgb)
                ground_lum = relative_luminance(ground)
                ratios.append((max(lum, ground_lum) + .05) / (min(lum, ground_lum) + .05))
    ratios.sort()
    contrast = ratios[min(len(ratios) - 1, math.ceil(.9 * len(ratios)) - 1)] if ratios else 1.0
    return contrast, len(ratios) / max(1, image.width() * image.height())


class StyleTileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        theme.init_fonts()
        cls.app.setFont(theme.font(theme.TYPE["body"]))
        cls.folder = tempfile.TemporaryDirectory()
        with mock.patch.object(responder_harness, "free_port", return_value=24820):
            cls.window = SyntheticWindow(write_synthetic_settings(Path(cls.folder.name)))
        cls.window.full_screen_timer.stop()
        cls.window.refresh_timer.stop()
        cls.window._select_page("design")
        cls.window.show()
        cls.choice = cls.window.glow_style_choice
        cls.settle()

    @classmethod
    def tearDownClass(cls):
        cls.window.server.stop()
        cls.window.close()
        cls.window.deleteLater()
        cls.app.processEvents()
        cls.folder.cleanup()

    @classmethod
    def settle(cls):
        for _ in range(8):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            cls.app.processEvents()

    @classmethod
    def capture_tile(cls, tile):
        image = cls.window.grab().toImage()
        scale = image.devicePixelRatio()
        point = tile.mapTo(cls.window, QPoint())
        crop = image.copy(round(point.x() * scale), round(point.y() * scale),
                          round(tile.width() * scale), round(tile.height() * scale))
        crop.setDevicePixelRatio(scale)
        return crop

    def test_still_time_is_inside_the_loop_and_deterministic(self):
        first = effects.still_time("beam", "edge")
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, effects.PREVIEW_LOOP_S)
        self.assertEqual(first, effects.still_time("beam", "edge"))
        switch = effects.still_time("aperture", "switch")
        self.assertGreaterEqual(switch, 0)
        self.assertLess(switch, effects.SWITCH_LOOP_S)
        self.assertEqual(switch, effects.still_time("aperture", "switch"))

    def test_custom_pace_and_size_keep_the_still_inside_its_view(self):
        pace, size_fraction = 0.25, 0.08
        cases = ((effects.preview_effect("skin"), "edge"),
                 (effects.switch_effect("aperture", "beam"), "switch"))
        for fx, place in cases:
            with self.subTest(effect=fx.id, place=place):
                at = effects.still_time(fx, place, "large", pace, size_fraction)
                view = effects.still_view(fx, place, "large", pace, size_fraction)
                scene = effects.preview_still_scene(fx, at, place, ("#ffffff",), dark=True, pace=pace,
                                                    effect_size="large", effect_size_fraction=size_fraction,
                                                    live=True, view_width=view[2])
                self.assertTrue(any(
                    min(box[2], view[0] + view[2]) > max(box[0], view[0])
                    and min(box[3], view[1] + view[3]) > max(box[1], view[1])
                    for box, _alpha in effects._op_boxes(scene)))

    def test_real_tile_previews_reach_contrast_and_coverage_in_both_appearances_and_scales(self):
        previous = theme.is_dark()
        try:
            for dark in (True, False):
                theme.set_dark(dark)
                for scale in (1, 2):
                    renderer = QtRenderer(scale)
                    renderer.set_dark(dark)
                    for family, style in style_cases():
                        contrast, coverage = card_metrics(renderer, family, style)
                        with self.subTest(family=family, style=style, dark=dark, scale=scale):
                            self.assertGreaterEqual(contrast, 3.0)
                            # The baseline removes screen outlines and the pointer before coverage is measured.
                            # Flint is a few short sparks drawn at their real size, as on the Mac.
                            self.assertGreaterEqual(coverage, .004 if (family, style) == ("crossing", "flint") else .01)
        finally:
            theme.set_dark(previous)

    def test_selected_tile_has_a_badge_before_its_name_without_a_wash_or_picture_overlap(self):
        previous = theme.is_dark()
        tile = self.choice.tile("beam")
        try:
            for dark in (True, False):
                theme.set_dark(dark)
                self.app.setStyleSheet(theme.stylesheet())
                self.choice.set_value("glow")
                self.settle()
                # The tile itself, not the window: at the window's opening size the page scrolls
                # the caption row out of view.
                rest = tile.grab().toImage()
                self.choice.set_value("beam")
                self.settle()
                chosen = tile.grab().toImage()
                scale = chosen.devicePixelRatio()
                signal = QColor(theme.colour("signal")).getRgb()[:3]

                def distance(image, x, y):
                    return sum(abs(a - b) for a, b in zip(image.pixelColor(x, y).getRgb()[:3], signal))

                card = (chosen.width() // 2, round(5 * scale))
                name = tile.name_label.geometry()
                check = [(x, y) for x in range(round(name.x() * scale), round((name.x() + 14) * scale))
                         for y in range(round(name.y() * scale), round(name.bottom() * scale))]
                inked = [point for point in check if distance(chosen, *point) < 60]
                preview = tile.layout().itemAt(0).widget().geometry()
                match = self.window.switch_style_choice.tile("match")
                match_detail = match.detail_label.text()
                with self.subTest(dark=dark):
                    self.assertEqual(chosen.pixelColor(*card), rest.pixelColor(*card), "selection washes the card")
                    self.assertGreaterEqual(len(inked), 100 * scale * scale, "no filled badge before the name")
                    self.assertGreater(min(y for _x, y in inked) / scale, preview.bottom(),
                                       "the badge reaches into the picture")
                    self.assertEqual(tile.name_label.indent(), widgets._TileOutline.CHECK_ROOM)
                    self.assertTrue(match_detail.startswith("Plays "))
                    self.window.glow_style_choice.set_value("beam")
                    self.window._apply_look()
                    self.settle()
                    self.assertEqual(match.detail_label.text(), "Plays Beam")
                    self.window.glow_style_choice.set_value("glow")
                    self.window._apply_look()
                    self.settle()
        finally:
            theme.set_dark(previous)


if __name__ == "__main__":
    unittest.main()
