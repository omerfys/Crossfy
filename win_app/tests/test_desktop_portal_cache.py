"""Wayland input readers consume Qt geometry captured by the GUI thread."""

import threading
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication
from core.return_edge import Rect
import desktop_portal


class DesktopPortalCache(unittest.TestCase):
    def test_display_mapping_tolerates_a_zero_size_geometry_during_refresh(self):
        screens = [Rect(0, 0, 0, 10), Rect(0, 10, 10, 10)]
        rectangles = [Rect(0, 0, 10, 10), Rect(0, 10, 10, 10)]

        self.assertEqual(desktop_portal._match_rectangles(screens, rectangles), rectangles)

    def test_worker_readers_never_enumerate_qt_screens(self):
        app = QApplication.instance() or QApplication([])
        desktop_portal.set_zones([])
        desktop_portal.set_regions([])
        desktop_portal.refresh_qt_screens()
        expected = desktop_portal.display_map()
        results = []
        with mock.patch("PySide6.QtGui.QGuiApplication.screens", side_effect=AssertionError("worker Qt read")) as screens:
            thread = threading.Thread(target=lambda: results.append((desktop_portal.display_map(), desktop_portal.monitors())))
            thread.start()
            thread.join(2)
        screens.assert_not_called()
        self.assertEqual(results[0][0], expected)

    def test_gui_refresh_updates_geometry_and_keeps_portal_zone_precedence(self):
        app = QApplication.instance() or QApplication([])
        desktop_portal.refresh_qt_screens()
        self.assertTrue(desktop_portal.display_map())
        zone = Rect(10, 20, 300, 200)
        desktop_portal.set_zones([zone])
        self.addCleanup(desktop_portal.set_zones, [])
        self.assertEqual(desktop_portal.monitors(), [zone])

    def test_display_map_matches_reordered_mixed_scale_portal_zones(self):
        desktop_portal._screens = [Rect(-1920, 0, 1920, 1080), Rect(0, 0, 2560, 1440)]
        desktop_portal.set_zones([Rect(0, 0, 1280, 720), Rect(-960, 0, 960, 540)])
        self.addCleanup(desktop_portal.set_zones, [])
        self.addCleanup(setattr, desktop_portal, "_screens", [])

        self.assertEqual(desktop_portal.display_map(), {"0": Rect(-960, 0, 960, 540),
                                                        "1": Rect(0, 0, 1280, 720)})

    def test_display_map_skips_ambiguous_row_of_differently_scaled_zones(self):
        desktop_portal._screens = [Rect(x, 0, 1920, 1080) for x in (0, 1920, 3840, 5760)]
        desktop_portal.set_zones([Rect(0, 0, 3840, 2160),
                                  Rect(3840, 0, 960, 540),
                                  Rect(4800, 0, 960, 540),
                                  Rect(5760, 0, 960, 540)])
        self.addCleanup(desktop_portal.set_zones, [])
        self.addCleanup(setattr, desktop_portal, "_screens", [])

        self.assertEqual(desktop_portal.display_map(), {})
        self.assertIsNone(desktop_portal.absolute_position(1920, 270))

    def test_display_map_skips_ambiguous_stacked_mixed_scale_zones(self):
        desktop_portal._screens = [Rect(0, 0, 1920, 1080), Rect(1920, 0, 1920, 1080),
                                   Rect(0, 1080, 1920, 1080), Rect(1920, 1080, 1920, 1080)]
        desktop_portal.set_zones([Rect(0, 0, 960, 540), Rect(960, 0, 960, 540),
                                  Rect(0, 540, 1920, 1080), Rect(1920, 540, 3840, 2160)])
        self.addCleanup(desktop_portal.set_zones, [])
        self.addCleanup(setattr, desktop_portal, "_screens", [])

        self.assertEqual(desktop_portal.display_map(), {})

    def test_display_map_skips_equal_axis_positions_with_ambiguous_identity(self):
        desktop_portal._screens = [Rect(x, 0, 1920, 1080) for x in (0, 1920, 3840, 5760)]
        desktop_portal.set_zones([Rect(0, 0, 960, 540), Rect(1920, 0, 960, 540),
                                  Rect(960, 0, 960, 540), Rect(2880, 0, 3840, 2160)])
        self.addCleanup(desktop_portal.set_zones, [])
        self.addCleanup(setattr, desktop_portal, "_screens", [])

        self.assertEqual(desktop_portal.display_map(), {})

    def test_absolute_display_map_tracks_the_same_displays_as_input_zones(self):
        desktop_portal._screens = [Rect(0, 0, 1920, 1080), Rect(1920, 0, 1280, 720)]
        desktop_portal.set_zones([Rect(0, 0, 1920, 1080), Rect(1920, 0, 1280, 720)])
        desktop_portal.set_regions([Rect(0, 0, 960, 540), Rect(960, 0, 2560, 1440)])
        self.addCleanup(desktop_portal.set_zones, [])
        self.addCleanup(desktop_portal.set_regions, [])
        self.addCleanup(setattr, desktop_portal, "_screens", [])

        self.assertEqual(desktop_portal.absolute_display_map(), {"0": Rect(0, 0, 960, 540),
                                                                  "1": Rect(960, 0, 2560, 1440)})

    def test_landing_position_translates_between_zone_and_absolute_coordinates(self):
        desktop_portal._screens = [Rect(0, 0, 1920, 1080), Rect(1920, 0, 1280, 720)]
        desktop_portal.set_zones([Rect(0, 0, 1920, 1080), Rect(1920, 0, 1280, 720)])
        desktop_portal.set_regions([Rect(0, 0, 960, 540), Rect(960, 0, 2560, 1440)])
        self.addCleanup(desktop_portal.set_zones, [])
        self.addCleanup(desktop_portal.set_regions, [])
        self.addCleanup(setattr, desktop_portal, "_screens", [])

        self.assertEqual(desktop_portal.absolute_position(2560, 360), (2241, 721))

    def test_hotplug_rebuilds_the_display_map_from_the_current_portal_zones(self):
        desktop_portal._screens = [Rect(-1920, 0, 1920, 1080), Rect(0, 0, 2560, 1440)]
        desktop_portal.set_zones([Rect(-960, 0, 960, 540), Rect(0, 0, 1280, 720)])
        self.addCleanup(desktop_portal.set_zones, [])
        self.addCleanup(setattr, desktop_portal, "_screens", [])

        self.assertEqual(desktop_portal.display_map()["0"], Rect(-960, 0, 960, 540))
        desktop_portal._screens = [Rect(0, 0, 2560, 1440)]
        desktop_portal.set_zones([Rect(0, 0, 1280, 720)])

        self.assertEqual(desktop_portal.display_map(), {"0": Rect(0, 0, 1280, 720)})


if __name__ == "__main__":
    unittest.main()
