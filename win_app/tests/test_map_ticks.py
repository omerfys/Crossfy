"""The Crossing map's thirds breaks, shortcut-cycle badge, status dot, fit and seam on a standalone Qt
canvas with synthetic tiles (rc14: ticks hung inside the lower tile, the badge sat on the status dot)."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PARTS = ["start", "middle", "end"]
OWN, LAPTOP, FEDORA, DESK = "0a" * 16, "1b" * 16, "2c" * 16, "3d" * 16
LABELS = {OWN: "This PC", LAPTOP: "Loan laptop with a long name", FEDORA: "fedora", DESK: "Desk-PC-Workstation"}
DISPLAYS = {"0": {"x": 0, "y": 0, "w": 2560, "h": 1440}, "1": {"x": 2560, "y": 0, "w": 1512, "h": 982}}
# An external display with the shorter built-in to its right, top edges level, and a machine below
# reaching under both: only the external's bottom edge touches it.
WITH_DISPLAYS = {OWN: {"x": 0, "y": 0, "w": 226, "h": 80, "displays": DISPLAYS},
                 DESK: {"x": 60, "y": 80, "w": 113, "h": 70}}
TWO_WIDE = {"a": {"x": 0, "y": 0, "w": 1920, "h": 1080}, "b": {"x": 1920, "y": 0, "w": 1920, "h": 1080}}
# Two displays meeting at a corner beside a side contact: under this PC and off its bottom-right
# corner, then this PC's right-hand display off the bottom-right corner of a machine under its left one.
DISPLAY_CORNERS = ({OWN: {"x": 0, "y": 0, "w": 160, "h": 90}, DESK: {"x": 0, "y": 90, "w": 320, "h": 90, "displays": TWO_WIDE}},
                   {OWN: {"x": 0, "y": 0, "w": 160, "h": 90, "displays": TWO_WIDE}, DESK: {"x": 0, "y": 90, "w": 80, "h": 90}})
ROW = {OWN: {"x": 0, "y": 0, "w": 160, "h": 100},
       LAPTOP: {"x": -160, "y": 0, "w": 160, "h": 100},
       FEDORA: {"x": -320, "y": 0, "w": 160, "h": 100},
       DESK: {"x": 0, "y": 100, "w": 160, "h": 100}}


def peer_state(**changes):
    return {"state": "edge", "crosses": True, "linked": True, "thirds": PARTS, "lit": PARTS,
            "detail": "Windows · Linked", **changes}


class MapTicks(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])

    def canvas(self, tiles=ROW, width=850, desk=None, cycle=None):
        from diagram import AtlasCanvas

        canvas = AtlasCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(width, 268)
        states = {key: peer_state() for key in tiles if key != OWN}
        states[OWN] = {"state": "this", "detail": "Desk PC"}
        states[DESK] = peer_state(**(desk or {}))
        canvas.set_tiles(tiles, LABELS, states, DESK, cycle_mode="ticked",
                         cycle=cycle or {key: True for key in tiles if key != OWN}, own_id=OWN)
        self.paint(canvas)
        return canvas

    def paint(self, canvas, ratio=1):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        image = QImage(canvas.width() * ratio, canvas.height() * ratio, QImage.Format.Format_ARGB32)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        canvas.render(image)
        return image

    def bottom_pieces(self, canvas):
        return sorted((path for path in canvas.seam_paths if path[0] == "bottom"), key=lambda path: path[1].x())

    def assert_breaks(self, canvas, wanted):
        import diagram

        pieces = self.bottom_pieces(canvas)
        self.assertEqual(len(pieces), len(wanted) + 1)
        for before, after, point in zip(pieces, pieces[1:], wanted):
            seen_end = before[2].x() + before[4] / 2
            seen_start = after[1].x() - after[4] / 2
            self.assertAlmostEqual((seen_end + seen_start) / 2, point, delta=0.01)
            self.assertAlmostEqual(seen_start - seen_end, diagram.THIRD_GAP, delta=0.01)

    def test_all_lit_thirds_share_one_continuous_seam(self):
        canvas = self.canvas()
        own = canvas.tile_rect(OWN)
        pieces = self.bottom_pieces(canvas)
        self.assertEqual([path[4] for path in pieces], [4.0])
        self.assertAlmostEqual(pieces[0][1].x(), own.left() + 2)
        self.assertAlmostEqual(pieces[0][2].x(), own.right() - 2)

    def test_an_unlit_third_breaks_the_same_way_as_a_lit_one(self):
        canvas = self.canvas(desk={"thirds": ["start", "end"], "lit": ["start", "end"]})
        own = canvas.tile_rect(OWN)
        self.assertEqual([path[4] for path in self.bottom_pieces(canvas)], [4.0, 2.0, 4.0])
        self.assert_breaks(canvas, [own.left() + own.width() / 3, own.left() + 2 * own.width() / 3])

    def test_partial_contact_keeps_one_continuous_seam_across_lit_thirds(self):
        canvas = self.canvas({OWN: ROW[OWN], DESK: {"x": 40, "y": 100, "w": 80, "h": 100}})
        own = canvas.tile_rect(OWN)
        pieces = self.bottom_pieces(canvas)
        self.assertEqual([path[4] for path in pieces], [4.0])
        self.assertAlmostEqual(pieces[0][1].x(), own.left() + 40 * canvas._scale + 2)
        self.assertAlmostEqual(pieces[0][2].x(), own.left() + 120 * canvas._scale - 2)

    def test_adjacent_lit_thirds_join_and_keep_the_lit_unlit_divider(self):
        from PySide6.QtCore import QPointF

        contacts = (ROW, {**ROW, DESK: {"x": 40, "y": 100, "w": 80, "h": 100}})
        for tiles in contacts:
            with self.subTest(contact=tiles[DESK]["x"]):
                canvas = self.canvas(tiles, desk={"thirds": ["start", "middle"], "lit": ["start", "middle"]})
                own = canvas.tile_rect(OWN)
                lit, track = [path for path in self.bottom_pieces(canvas) if path[4] == 4.0], \
                             [path for path in self.bottom_pieces(canvas) if path[4] == 2.0]
                self.assertEqual(len(lit), 1)
                self.assertEqual(len(track), 1)
                first_boundary = own.left() + own.width() / 3
                lit_unlit_boundary = own.left() + 2 * own.width() / 3
                self.assertLess(lit[0][1].x(), first_boundary)
                self.assertGreater(lit[0][2].x(), first_boundary)
                self.assertAlmostEqual(lit[0][2].x(), lit_unlit_boundary - 3)
                self.assertAlmostEqual(track[0][1].x(), lit_unlit_boundary + 2)
                painted_gap = (track[0][1].x() - track[0][4] / 2) - (lit[0][2].x() + lit[0][4] / 2)
                self.assertAlmostEqual(painted_gap, 2.0)

                for x, third in ((46, "start"), (80, "middle"), (113, "end")):
                    point = QPointF(own.left() + (x - ROW[OWN]["x"]) * canvas._scale, own.bottom())
                    self.assertEqual(canvas._third_at(point), (DESK, third))

    def test_nothing_for_the_thirds_is_drawn_outside_the_seam_band(self):
        from PySide6.QtCore import QPointF
        from unittest.mock import patch
        import diagram

        for desk in ({}, {"thirds": ["middle"], "lit": ["middle"]}):
            with self.subTest(desk=desk):
                canvas = self.canvas(desk=desk)
                line = canvas.tile_rect(OWN).bottom()
                own = canvas.tile_rect(OWN)
                lines = []
                original = diagram.QPainter

                class RecordingPainter(original):
                    def drawLine(self, *args):
                        if len(args) == 2:
                            lines.append((QPointF(args[0]), QPointF(args[1]), self.pen().widthF()))
                        return super().drawLine(*args)

                with patch.object(diagram, "QPainter", RecordingPainter):
                    self.paint(canvas)
                near = [entry for entry in lines if own.left() - 1 <= entry[0].x() <= own.right() + 1
                        and abs(entry[0].y() - line) < 10]
                self.assertTrue(near)
                for one, two, width in near:
                    for point in (one, two):
                        self.assertLessEqual(abs(point.y() - line) + width / 2, 2.0)

    def test_unselected_peer_seam_is_one_unbroken_line(self):
        canvas = self.canvas()
        left = [path for path in canvas.seam_paths if path[0] == "left"]
        own = canvas.tile_rect(OWN)
        self.assertEqual(len(left), 1)
        self.assertAlmostEqual(left[0][1].y(), own.top() + 2)
        self.assertAlmostEqual(left[0][2].y(), own.bottom() - 2)

    def test_edge_off_draws_nothing_for_the_thirds(self):
        canvas = self.canvas(desk={"crosses": False, "edge_off": True, "thirds": [], "lit": []})
        self.assertEqual(self.bottom_pieces(canvas), [])

    def test_lit_seam_lies_on_the_shared_edge_and_spans_the_shared_stretch(self):
        canvas = self.canvas()
        own, desk = canvas.tile_rect(OWN), canvas.tile_rect(DESK)
        self.assertAlmostEqual(own.bottom(), desk.top(), delta=0.5)
        pieces = self.bottom_pieces(canvas)
        for _side, one, two, _alpha, _width in pieces:
            self.assertAlmostEqual(one.y(), desk.top(), delta=0.5)
            self.assertAlmostEqual(two.y(), own.bottom(), delta=0.5)
        self.assertAlmostEqual(pieces[0][1].x(), own.left() + 2)
        self.assertAlmostEqual(pieces[-1][2].x(), own.right() - 2)

    def test_badge_never_meets_the_name_at_any_tile_height(self):
        for width, band in ((850, "row"), (260, "small"), (200, "tiny")):
            canvas = self.canvas(width=width)
            for key in canvas.tiles:
                rect = canvas.tile_rect(key)
                with self.subTest(band=band, peer=LABELS[key]):
                    {"row": lambda: self.assertGreaterEqual(rect.height(), 56),
                     "small": lambda: self.assertTrue(44 <= rect.height() < 56),
                     "tiny": lambda: self.assertLess(rect.height(), 44)}[band]()
                    title = canvas._title_rect(key, rect)
                    if key == OWN:
                        self.assertFalse(canvas._shows_cycle(key))
                        self.assertAlmostEqual(title.left(), rect.left() + 8)
                        continue
                    box = canvas._cycle_box(rect)
                    self.assertEqual((box.width(), box.height()), (16, 16))
                    self.assertAlmostEqual(box.left(), rect.right() - (36 if rect.height() < 56 else 24))
                    self.assertFalse(box.intersects(title))
                    if band == "small":
                        self.assertGreaterEqual(title.width(), rect.width() - 16 - 1e-9)
                        self.assertAlmostEqual(title.top(), rect.top() + 4)
                        self.assertAlmostEqual(box.top(), rect.bottom() - 20)
                    else:
                        self.assertAlmostEqual(box.center().y(), title.center().y())
                    if band == "tiny":
                        self.assertAlmostEqual(title.right(), box.left() - 6)

    def test_a_name_that_fits_stays_centred_and_a_long_one_takes_the_room_left_of_the_badge(self):
        canvas = self.canvas()
        fedora, laptop = canvas.tile_rect(FEDORA), canvas.tile_rect(LAPTOP)
        short, long = canvas._title_rect(FEDORA, fedora), canvas._title_rect(LAPTOP, laptop)
        self.assertAlmostEqual(short.left(), fedora.left() + 30)
        self.assertAlmostEqual(short.left() - fedora.left(), fedora.right() - short.right())
        self.assertAlmostEqual(long.left(), laptop.left() + 8)
        self.assertAlmostEqual(long.right(), canvas._cycle_box(laptop).left() - 6)

    def test_cycle_hit_follows_the_badge_under_the_name(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        toggled = []
        canvas = self.canvas(width=260)
        canvas.on_cycle = lambda peer, enabled: toggled.append((peer, enabled))
        rect = canvas.tile_rect(DESK)
        box = canvas._cycle_box(rect)
        self.assertAlmostEqual(box.top(), rect.bottom() - 20)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=box.center().toPoint())
        self.assertEqual(toggled, [(DESK, False)])

    def test_cycle_hit_area_is_the_box_grown_to_24(self):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtTest import QTest

        toggled = []
        canvas = self.canvas()
        canvas.on_cycle = lambda peer, enabled: toggled.append((peer, enabled))
        rect = canvas.tile_rect(DESK)
        box = canvas._cycle_box(rect)
        hit = canvas._cycle_hit_rect(rect)
        self.assertEqual((hit.left(), hit.top(), hit.width(), hit.height()),
                         (box.left() - 4, box.top() - 4, 24, 24))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=box.center().toPoint())
        self.assertEqual(toggled, [(DESK, False)])
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPointF(hit.left() + 1, hit.top() + 1).toPoint())
        self.assertEqual(toggled, [(DESK, False), (DESK, True)])
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPointF(rect.right() - 2, rect.top() + 2).toPoint())
        self.assertEqual(len(toggled), 2)

    def test_check_glyph_is_a_tick_and_off_is_an_outlined_well(self):
        from PySide6.QtGui import QColor
        import theme

        def ink_points(canvas):
            image = self.paint(canvas, 2)
            box = canvas._cycle_box(canvas.tile_rect(DESK))
            ground, fill = QColor(theme.colour("ground")), QColor(theme.colour("ink_2"))
            found = []
            for py in range(round((box.top() + 2) * 2), round((box.bottom() - 2) * 2)):
                for px in range(round((box.left() + 2) * 2), round((box.right() - 2) * 2)):
                    colour = image.pixelColor(px, py)
                    near = lambda other: sum((a - b) ** 2 for a, b in zip(
                        (colour.red(), colour.green(), colour.blue()), (other.red(), other.green(), other.blue())))
                    if near(ground) < near(fill):
                        found.append((px / 2, py / 2))
            return box, found

        box, ink = ink_points(self.canvas())
        self.assertGreater(len(ink), 10)
        lowest = max(point[1] for point in ink)
        highest = min(point[1] for point in ink)
        bottom = [point[0] for point in ink if point[1] == lowest]
        top = [point[0] for point in ink if point[1] == highest]
        self.assertLess(sum(bottom) / len(bottom), box.center().x())
        self.assertGreater(sum(top) / len(top), box.center().x())
        canvas = self.canvas(cycle={DESK: False})
        image = self.paint(canvas)
        box = canvas._cycle_box(canvas.tile_rect(DESK))
        self.assertEqual(image.pixelColor(box.center().toPoint()), QColor(theme.colour("well")))

    def test_status_dot_sits_at_the_left_of_the_detail_line(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QColor
        import theme

        canvas = self.canvas()
        image = self.paint(canvas)
        signal = QColor(theme.colour("signal"))
        for key in canvas.tiles:
            rect = canvas.tile_rect(key)
            with self.subTest(peer=LABELS[key]):
                self.assertEqual(image.pixelColor(QPoint(round(rect.left() + 15), round(rect.top() + 39))), signal)
                self.assertNotEqual(image.pixelColor(QPoint(round(rect.right() - 13), round(rect.top() + 13))), signal)

    def test_map_fits_and_centres_the_whole_arrangement(self):
        for width in (850, 240, 480):
            with self.subTest(width=width):
                canvas = self.canvas(width=width)
                rects = [canvas.tile_rect(key) for key in canvas.tiles]
                left, right = min(r.left() for r in rects), max(r.right() for r in rects)
                top, bottom = min(r.top() for r in rects), max(r.bottom() for r in rects)
                self.assertAlmostEqual((left + right) / 2, canvas.width() / 2, delta=1)
                self.assertAlmostEqual((top + bottom) / 2, canvas.height() / 2, delta=1)
                room_w, room_h = canvas.width() - 24, canvas.height() - 24
                self.assertTrue(abs(canvas._scale - 1.0) < 1e-9 or abs(right - left - room_w) <= 1
                                or abs(bottom - top - room_h) <= 1, (canvas._scale, right - left, bottom - top))
                self.assertLessEqual(right - left, room_w + 1e-6)
                self.assertLessEqual(bottom - top, room_h + 1e-6)

    def external(self):
        from core import ways

        return next(screen for screen in ways._display_frames(WITH_DISPLAYS[OWN]) if screen["display"] == "0")

    def test_with_displays_the_seam_runs_only_where_a_display_edge_touches_the_machine(self):
        for desk in ({}, {"thirds": ["start", "middle"], "lit": ["start", "middle"]}):
            with self.subTest(desk=desk):
                canvas = self.canvas(WITH_DISPLAYS, desk=desk)
                own, external = canvas.tile_rect(OWN), self.external()
                bottom = own.top() + (external["y"] + external["h"]) * canvas._scale
                pieces = self.bottom_pieces(canvas)
                self.assertTrue(pieces)
                for _side, one, two, _alpha, width in pieces:
                    self.assertAlmostEqual(one.y(), bottom)
                    self.assertAlmostEqual(two.y(), bottom)
                    self.assertGreaterEqual(one.x() - width / 2, own.left() + 60 * canvas._scale - 1e-9)
                    self.assertLessEqual(two.x() + width / 2,
                                         own.left() + (external["x"] + external["w"]) * canvas._scale + 1e-9)

    def test_with_displays_adjacent_lit_thirds_stay_continuous_inside_the_contact(self):
        from PySide6.QtCore import QPointF

        canvas = self.canvas(WITH_DISPLAYS)
        own, external = canvas.tile_rect(OWN), self.external()
        pieces = self.bottom_pieces(canvas)
        self.assertEqual(len(pieces), 1)
        contact = canvas._side_contacts(DESK)[0][1]
        self.assertAlmostEqual(pieces[0][1].x(),
                               own.left() + (contact[1] - WITH_DISPLAYS[OWN]["x"]) * canvas._scale + 2)
        self.assertAlmostEqual(pieces[0][2].x(),
                               own.left() + (contact[2] - WITH_DISPLAYS[OWN]["x"]) * canvas._scale - 2)
        y = own.top() + 80 * canvas._scale + 4
        end = own.left() + (external["x"] + 0.9 * external["w"]) * canvas._scale
        self.assertEqual(canvas._third_at(QPointF(end, y)), (DESK, "end"))
        self.assertEqual(canvas._third_at(QPointF(own.left() + 70 * canvas._scale, y)), (DESK, "middle"))
        self.assertIsNone(canvas._third_at(QPointF(own.left() + 160 * canvas._scale, y)))
        self.assertEqual(canvas._third_tooltip(*canvas._third_segment_at(QPointF(end, y))),
                         "Right third: click to leave it out")

    def corner_dots(self, canvas):
        from unittest.mock import patch
        import diagram

        dots = []
        original = diagram.QPainter

        class RecordingPainter(original):
            def drawEllipse(self, *args):
                if len(args) == 3 and args[1] == 3.5:
                    dots.append(args[0])
                return super().drawEllipse(*args)

        with patch.object(diagram, "QPainter", RecordingPainter):
            self.paint(canvas)
        return dots

    def test_a_corner_where_two_displays_meet_beside_a_side_contact_is_not_drawn(self):
        for tiles in DISPLAY_CORNERS:
            for selected in (DESK, OWN):
                with self.subTest(tiles=sorted(tiles[DESK]), selected=selected == DESK):
                    canvas = self.canvas(tiles)
                    canvas.selected = selected
                    self.assertEqual(self.corner_dots(canvas), [])
                    self.assertEqual({path[0] for path in canvas.seam_paths}, {"bottom"})

    def test_a_machine_reached_at_a_corner_alone_keeps_its_dot(self):
        canvas = self.canvas({OWN: ROW[OWN], DESK: {"x": 160, "y": 100, "w": 160, "h": 100}})
        canvas.selected = OWN
        own = canvas.tile_rect(OWN)
        dots = self.corner_dots(canvas)
        self.assertEqual(len(dots), 1)
        self.assertAlmostEqual(dots[0].x(), own.right())
        self.assertAlmostEqual(dots[0].y(), own.bottom())

    def test_the_join_between_a_machines_displays_is_not_a_break(self):
        tiles = {OWN: {"x": 0, "y": 0, "w": 160, "h": 90},
                 DESK: {"x": 0, "y": 90, "w": 160, "h": 90, "displays": TWO_WIDE}}
        for lit in (["start"], PARTS):
            with self.subTest(lit=lit):
                canvas = self.canvas(tiles, desk={"thirds": lit, "lit": lit})
                own = canvas.tile_rect(OWN)
                if lit == PARTS:
                    pieces = self.bottom_pieces(canvas)
                    self.assertTrue(pieces)
                    self.assertTrue(all(path[4] == 4.0 for path in pieces))
                    for before, after in zip(pieces, pieces[1:]):
                        painted_gap = (after[1].x() - after[4] / 2) - (before[2].x() + before[4] / 2)
                        self.assertAlmostEqual(painted_gap, 0.0)
                else:
                    self.assert_breaks(canvas, [own.left() + own.width() / 3,
                                                 own.left() + 2 * own.width() / 3])


if __name__ == "__main__":
    unittest.main()
