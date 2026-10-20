"""Section 9: ledger controls round trip through saved intent and the map."""

import copy
import unittest
from itertools import combinations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QAccessible, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import app_config
import diagram
from core import ways
import test_crossing_page_parity as parity


def row_of(window, peer):
    return window.crossing_ledger.rows[peer]


def contact_chip(window, peer):
    return next(chip for chip in row_of(window, peer).edge_chips.chips.values() if chip.kind == "contact")


def chip_kinds(window, peer):
    return {side: chip.kind for side, chip in row_of(window, peer).edge_chips.chips.items() if not chip.isHidden()}


def picked(window, peer):
    return [third for third, segment in contact_chip(window, peer).segments.items() if segment.isChecked()]


def band_point(canvas, third, side="right"):
    rect = canvas.tile_rect(canvas._own_id())
    fraction = {"start": 1 / 6, "middle": 1 / 2, "end": 5 / 6}[third]
    if side in ("left", "right"):
        return QPoint(round(rect.left() if side == "left" else rect.right()), round(rect.top() + rect.height() * fraction))
    return QPoint(round(rect.left() + rect.width() * fraction), round(rect.top() if side == "top" else rect.bottom()))


def stroke_insets(image, left, top, right, bottom, reference):
    """Device-pixel insets of every pixel that differs from the colour at `reference`, measured inside
    the box (left, top, right, bottom), inclusive."""
    base = image.pixelColor(*reference)
    xs, ys = [], []
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            pixel = image.pixelColor(x, y)
            if abs(pixel.red() - base.red()) + abs(pixel.green() - base.green()) + abs(pixel.blue() - base.blue()) > 60:
                xs.append(x)
                ys.append(y)
    return min(xs) - left, min(ys) - top, right - max(xs), bottom - max(ys)


def paint(canvas):
    image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    canvas.render(image)
    return image


class CrossingLedgerTests(unittest.TestCase):
    setUp = parity.CrossingPageParityTests.setUp
    tearDown = parity.CrossingPageParityTests.tearDown
    _open_window = parity.CrossingPageParityTests._open_window
    _close_window = parity.CrossingPageParityTests._close_window
    _stop_patches = parity.CrossingPageParityTests._stop_patches

    def test_seven_thirds_combinations_round_trip_and_match_map(self):
        peer = self.peers[0]["id"]
        for size in (1, 2, 3):
            for subset in combinations(ways.PARTS, size):
                with self.subTest(subset=subset):
                    window = self.window
                    if picked(window, peer):
                        contact_chip(window, peer).click()
                    contact_chip(window, peer).click()
                    for third in ways.PARTS:
                        if third not in subset:
                            contact_chip(window, peer).segments[third].click()
                    held = ways.ways(app_config.load_settings(self.path), peer)
                    self.assertEqual(ways.picked_thirds(held["methods"], held["parts"]), list(subset))
                    self.assertEqual(picked(window, peer), list(subset))
                    self.assertEqual(window.atlas_canvas.states[peer]["thirds"], list(subset))
                    self._close_window()
                    self._open_window()
                    self.assertEqual(picked(self.window, peer), list(subset))

    def test_last_third_off_and_click_while_off_on_ledger_and_map(self):
        peer = self.peers[0]["id"]
        for surface in ("ledger", "map"):
            with self.subTest(surface=surface):
                window = self.window
                if not picked(window, peer):
                    contact_chip(window, peer).click()
                def click(third):
                    if surface == "ledger":
                        contact_chip(window, peer).segments[third].click()
                    else:
                        QTest.mouseClick(window.atlas_canvas, Qt.MouseButton.LeftButton, pos=band_point(window.atlas_canvas, third))
                for third in ways.PARTS:
                    click(third)
                self.assertEqual(picked(window, peer), [])
                self.assertFalse(contact_chip(window, peer).isChecked())
                self.assertFalse(window.atlas_canvas.states[peer]["crosses"])
                click("middle")
                self.assertEqual(picked(window, peer), ["middle"])
                self.assertTrue(contact_chip(window, peer).isChecked())
                contact_chip(window, peer).click()
                contact_chip(window, peer).click()
                self.assertEqual(picked(window, peer), list(ways.PARTS))

    def test_each_corner_on_and_off_round_trips(self):
        peer = self.peers[0]["id"]
        for corner in ways.CORNERS:
            for on in (True, False):
                with self.subTest(corner=corner, on=on):
                    row_of(self.window, peer).corner_grid.buttons[corner].click()
                    held = ways.ways(app_config.load_settings(self.path), peer)
                    self.assertEqual(corner in held["corners"], on)
                    self.assertEqual(self.window.atlas_canvas.states[peer]["corners"], [corner] if on else [])
                    self._close_window()
                    self._open_window()
                    self.assertEqual(row_of(self.window, peer).corner_grid.buttons[corner].isChecked(), on)

    def test_corner_brackets_sit_centred_in_whole_squares(self):
        # A style sheet's min-height replaced the minimum setFixedSize set, so the grid squashed
        # each square to 28 x 19 and the bracket drawn for 28 x 28 was clipped off-centre.
        self.window.resize(1280, 1392)
        self.window.show()
        QApplication.processEvents()
        row = row_of(self.window, self.peers[0]["id"])
        for kind, enabled in (("free", True), ("on", True), ("held", False), ("unavailable", False)):
            for corner, button in row.corner_grid.buttons.items():
                with self.subTest(kind=kind, corner=corner):
                    button.set_state(kind, "", "", enabled)
                    self.assertEqual(button.size().toTuple(), (28, 28))
                    image = button.grab().toImage()
                    w, h = image.width(), image.height()
                    insets = stroke_insets(image, 3, 3, w - 4, h - 4, (w // 2, h // 2))
                    self.assertLessEqual(max(insets) - min(insets), 1, insets)
                    self.assertGreaterEqual(min(insets), 3, insets)

    def test_map_corner_pad_bracket_sits_centred_in_its_pad(self):
        # Drawn at 4x so a half-pixel offset shows as two device pixels.
        scale = 4
        for corner in ways.CORNERS:
            with self.subTest(corner=corner):
                image = QImage(80 * scale, 80 * scale, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.black)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.scale(scale, scale)
                diagram.AtlasCanvas._paint_corner_pad(painter, QRectF(30, 30, 20, 20), corner, 1.0)
                painter.end()
                x = 30 if corner.endswith("left") else 50
                y = 30 if corner.startswith("top") else 50
                insets = stroke_insets(image, (x - 6) * scale, (y - 6) * scale, (x + 6) * scale - 1, (y + 6) * scale - 1,
                                       ((x + 5) * scale + 2, (y + 5) * scale + 2))
                self.assertLessEqual(max(insets) - min(insets), 1, insets)

    def test_two_corners_at_once_a_held_one_and_an_unavailable_one_refuse_without_a_write(self):
        first, second = [entry["id"] for entry in self.peers]
        rows = self.window.crossing_ledger.rows
        rows[first].corner_grid.buttons["top_left"].click()
        rows[first].corner_grid.buttons["bottom_right"].click()
        self.assertTrue(rows[first].corner_grid.buttons["top_left"].isChecked())
        self.assertTrue(rows[first].corner_grid.buttons["bottom_right"].isChecked())
        self.assertEqual(ways.ways(app_config.load_settings(self.path), first)["corners"], ["top_left", "bottom_right"])
        before = app_config.load_settings(self.path)
        held = rows[second].corner_grid.buttons["bottom_right"]
        self.assertFalse(held.isEnabled())
        self.assertEqual(held.toolTip(), "MacBook Pro's corner")
        held.click()
        self.window._ledger_corner(second, "bottom_right")
        self.assertEqual(app_config.load_settings(self.path), before)
        rows[second].corner_grid.buttons["bottom_left"].click()
        self.window._choose_machine(second)
        paint(self.window.atlas_canvas)
        self.assertEqual(set(self.window.atlas_canvas.corner_marks),
                         {(first, "top_left", .55), (first, "bottom_right", .55), (second, "bottom_left", 1.0)})
        layout = copy.deepcopy(app_config.load_settings(self.path)["layout"])
        layout[second] = {"x": 0, "y": 400, "w": 160, "h": 100}
        self.window._config.layout = layout
        self.window._reflect_ways()
        paint(self.window.atlas_canvas)
        self.assertNotIn(second, {peer for peer, _corner, _opacity in self.window.atlas_canvas.corner_marks},
                         "a corner that no longer crosses draws no pad")
        apart = rows[second].corner_grid.buttons["top_right"]
        self.assertFalse(apart.isEnabled())
        self.assertEqual(apart.toolTip(), "Place Desktop PC beside this PC first")
        before = app_config.load_settings(self.path)
        self.window._ledger_corner(second, "top_right")
        self.assertEqual(app_config.load_settings(self.path), before)
        # A corner already on stays removable after its machine loses the side contact.
        rows[second].corner_grid.buttons["bottom_left"].click()
        self.assertEqual(ways.ways(app_config.load_settings(self.path), second)["corners"], [])

    def test_every_chip_state_round_trips_through_the_saved_ways_and_the_map(self):
        peer, other = [entry["id"] for entry in self.peers]
        window = self.window
        def saved():
            return ways.ways(app_config.load_settings(self.path), peer)
        def edge_on():
            return bool(ways.picked_thirds(saved()["methods"], saved()["parts"]))
        def chip(side):
            return row_of(window, peer).edge_chips.chips[side]
        def agree():
            held = saved()
            for side, mine in row_of(window, peer).edge_chips.chips.items():
                if mine.kind in ("on", "kept"):
                    self.assertIn(side, held["edges"])
            wraps = {item["side"] if isinstance(item, dict) else item
                     for item in window.atlas_canvas.states[peer].get("wraps", ())}
            self.assertEqual(wraps, {side for side, mine in row_of(window, peer).edge_chips.chips.items() if mine.kind == "on"})
            self.assertEqual(set(window.atlas_canvas.states[peer]["kept_wraps"]),
                             {side for side, mine in row_of(window, peer).edge_chips.chips.items() if mine.kind == "kept"})
        self.assertEqual(chip_kinds(window, peer), {"left": "held", "right": "contact", "top": "free", "bottom": "free"})
        self.assertFalse(edge_on())
        chip("top").click()
        self.assertEqual((saved()["edges"], edge_on(), chip("top").kind), (["top"], True, "on"))
        self.assertTrue(contact_chip(window, peer).isChecked())
        agree()
        chip("bottom").click()
        self.assertEqual(saved()["edges"], ["top", "bottom"])
        agree()
        chip("top").click()
        self.assertEqual((saved()["edges"], chip("top").kind), (["bottom"], "free"))
        agree()
        contact_chip(window, peer).click()
        self.assertFalse(edge_on())
        self.assertEqual((saved()["edges"], chip("bottom").kind), (["bottom"], "kept"))
        self.assertFalse(contact_chip(window, peer).isChecked())
        agree()
        chip("bottom").click()
        self.assertEqual((saved()["edges"], edge_on(), chip("bottom").kind), (["bottom"], True, "on"))
        agree()
        contact_chip(window, peer).click()
        contact_chip(window, peer).click()
        self.assertEqual((saved()["edges"], edge_on()), (["bottom"], True))
        before = app_config.load_settings(self.path)
        self.assertFalse(chip("left").isEnabled())
        self.window._ledger_side(peer, "left")
        self.assertEqual(app_config.load_settings(self.path), before)
        self._close_window()
        self._open_window()
        self.assertEqual(chip_kinds(self.window, peer), {"left": "held", "right": "contact", "top": "free", "bottom": "on"})
        agree()
        self.assertEqual(saved()["edges"], ["bottom"])
        self.assertEqual(chip_kinds(self.window, other)["right"], "held")

    def test_chips_are_ordered_contact_first_and_labelled_by_state(self):
        peer, other = [entry["id"] for entry in self.peers]
        edges = row_of(self.window, peer).edge_chips
        chips = edges.chips
        shown = lambda: [side for side in (chip.side for chip in
                         sorted((c for c in chips.values() if not c.isHidden()), key=lambda c: c.geometry().top() * 10000 + c.geometry().left()))]
        self.assertEqual(shown()[0], "right")
        self.window._ledger_side(peer, "top")
        chip_texts = {side: chip.text_ for side, chip in chips.items()}
        self.assertEqual(chip_texts, {"left": "Left, Desktop PC", "right": "Right", "top": "Top, wraps", "bottom": "Bottom"})
        self.assertEqual(chips["right"].toolTip(), "Right edge: touches MacBook Pro; click to turn it off")
        self.assertEqual(chips["top"].toolTip(), "Top edge wraps round to MacBook Pro; click to remove")
        self.assertEqual(chips["bottom"].toolTip(), "Bottom edge: click to wrap round to MacBook Pro")
        self.assertEqual(chips["left"].toolTip(), "Left edge: Desktop PC's")
        self.window._ledger_edge(peer)
        self.assertEqual(chips["right"].toolTip(), "Right edge: touches MacBook Pro; click to turn it on")
        self.assertEqual(chips["top"].toolTip(), "Top edge wraps round to MacBook Pro once Edge is on; click to turn Edge on")
        self.assertEqual(chips["top"].kind, "kept")

    def test_map_draws_a_seam_and_label_for_each_wrap_and_stops_short_of_a_pad(self):
        peer = self.peers[0]["id"]
        window = self.window
        window._ledger_side(peer, "top")
        window._ledger_side(peer, "bottom")
        window._ledger_corner(peer, "top_left")
        window._ledger_corner(peer, "bottom_right")
        canvas = window.atlas_canvas
        paint(canvas)
        rect = canvas.tile_rect(canvas._own_id())
        wrapped = {side: (one, two, alpha) for side, one, two, alpha, _width in canvas.seam_paths
                   if side in ("top", "bottom") and alpha == 1.0}
        self.assertEqual(set(wrapped), {"top", "bottom"})
        one, two, _alpha = wrapped["top"]
        self.assertAlmostEqual(one.x(), rect.left() + 13)
        self.assertAlmostEqual(two.x(), rect.right() - 2)
        one, two, _alpha = wrapped["bottom"]
        self.assertAlmostEqual(one.x(), rect.left() + 2)
        self.assertAlmostEqual(two.x(), rect.right() - 13)
        self.assertEqual({(side, text) for _peer, side, text, kept, _alpha in canvas.wrap_marks if not kept},
                         {("top", "wraps to MacBook Pro"), ("bottom", "wraps to MacBook Pro")})
        self.assertEqual({(corner) for _peer, corner, _opacity in canvas.corner_marks}, {"top_left", "bottom_right"})
        window._ledger_edge(peer)
        paint(canvas)
        self.assertEqual({(side, kept) for _peer, side, _text, kept, _alpha in canvas.wrap_marks}, {("top", True), ("bottom", True)})
        self.assertEqual([text for *_head, text, _kept, _alpha in canvas.wrap_marks][0], "wrap kept, Edge off")
        self.assertEqual(canvas.states[peer]["crosses"], True)

    def test_shortcut_cycle_and_jump_chord_round_trip(self):
        peer = self.peers[0]["id"]
        row = self.window.crossing_ledger.rows[peer]
        row.cycle.click()
        row.jump.click()
        QTest.keyClick(row.jump, Qt.Key.Key_F18, Qt.KeyboardModifier.AltModifier)
        saved = next(entry for entry in app_config.load_settings(self.path)["peers"] if entry["id"] == peer)
        self.assertFalse(saved["shortcut_cycle"])
        self.assertEqual(saved["jump_key"], "alt+f18")
        self._close_window()
        self._open_window()
        row = self.window.crossing_ledger.rows[peer]
        self.assertFalse(row.cycle.isChecked())
        self.assertEqual(row.jump.key.text(), "Alt F18")
        self.assertTrue(row.clear.isVisible())
        row.clear.click()
        self.assertEqual(row.jump.key.text(), "Set a key")

    def test_offline_and_left_out_rows_keep_intent_and_put_back_controls(self):
        peer = self.peers[0]["id"]
        self.window._ledger_edge(peer)
        self.window._ledger_side(peer, "top")
        row = self.window.crossing_ledger.rows[peer]
        self.window._live = lambda _peer: False
        self.window._reflect_ways()
        self.assertEqual(row.effect.opacity(), .5)
        self.assertEqual(row.status.text(), "macOS · Offline, ways kept")
        self.assertTrue(contact_chip(self.window, peer).isEnabled())
        self.window._canvas_left_out(peer, True)
        self.assertIs(row, self.window.crossing_ledger.rows[peer])
        self.assertEqual(row.status.text(), "macOS · Left out")
        self.assertEqual(row.leave.text(), "Put back")
        self.assertFalse(contact_chip(self.window, peer).isEnabled())
        self.assertEqual(chip_kinds(self.window, peer), {"right": "contact", "top": "on"})
        self.assertEqual(row.edge_chips.chips["top"].toolTip(), "Left out: Put back to change its ways")
        self.assertFalse(row.corner_grid.buttons["top_left"].isEnabled())
        self.assertEqual(picked(self.window, peer), list(ways.PARTS))
        row.leave.click()
        self.assertTrue(contact_chip(self.window, peer).isEnabled())
        self.assertEqual(chip_kinds(self.window, peer)["top"], "on")

    def test_narrow_has_no_horizontal_scroll_and_all_controls_fit(self):
        for peer in [entry["id"] for entry in self.peers]:
            self.window._ledger_side(peer, "top")
            self.window._ledger_side(peer, "bottom")
        self.window.resize(640, 700)
        parity.settle(self.window)
        ledger = self.window.crossing_ledger
        self.assertTrue(ledger.narrow)
        self.assertTrue(ledger.header.isHidden())
        scroll = self.window.stack.currentWidget()
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        for row in ledger.rows.values():
            self.assertGreater(row.edge.width(), row.machine.width() * .9)
            self.assertLess(row.corner_cell.mapTo(ledger, QPoint()).y() + 1, row.keys.mapTo(ledger, QPoint()).y() + row.keys.height())
            self.assertEqual(row.corner_cell.mapTo(ledger, QPoint()).y(), row.keys.mapTo(ledger, QPoint()).y())
            shown = [chip for chip in row.edge_chips.chips.values() if not chip.isHidden()]
            self.assertEqual(len(shown), 4)
            for control in (*row.cells, row.rename, row.leave, row.cycle, row.jump, *shown,
                            *row.corner_grid.buttons.values()):
                rect = control.mapTo(ledger, QPoint())
                self.assertGreaterEqual(rect.x(), 0)
                self.assertLessEqual(rect.x() + control.width(), ledger.width())
                self.assertGreater(control.width(), 0)
                self.assertGreater(control.height(), 0)
            for chip in shown:
                self.assertGreaterEqual(chip.mapTo(row.edge, QPoint()).y() + chip.height(), 1)
                self.assertLessEqual(chip.mapTo(row, QPoint()).y() + chip.height(), row.height())

    def test_accessibility_table_headers_and_named_stateful_controls(self):
        ledger = self.window.crossing_ledger
        self.assertEqual(QAccessible.queryAccessibleInterface(ledger).role(), QAccessible.Role.Table)
        row = ledger.rows[self.peers[0]["id"]]
        self.assertEqual(QAccessible.queryAccessibleInterface(row).role(), QAccessible.Role.Row)
        self.assertEqual(QAccessible.queryAccessibleInterface(row.machine).role(), QAccessible.Role.RowHeader)
        headers = ledger.header.findChildren(QWidget)
        self.assertEqual([w.accessibleName() for w in headers if w.property("ledger_role") == "columnheader"], ["Machine", "Edges", "Corners", "Keys"])
        names = {side: chip.accessibleName() for side, chip in row.edge_chips.chips.items() if not chip.isHidden()}
        self.assertEqual(names, {"left": "Left edge, held by Desktop PC", "right": "Right edge, touches MacBook Pro, off",
                                 "top": "Top edge, wraps round, off", "bottom": "Bottom edge, wraps round, off"})
        self.window._ledger_side(self.peers[0]["id"], "top")
        self.assertEqual(row.edge_chips.chips["top"].accessibleName(), "Top edge, wraps round, on")
        self.assertEqual(row.edge_chips.chips["right"].accessibleName(), "Right edge, touches MacBook Pro, on")
        self.assertEqual([button.accessibleName() for button in row.corner_grid.buttons.values()],
                         [f"{corner} corner, off" for corner in ("Top left", "Top right", "Bottom left", "Bottom right")])
        for button in (*row.edge_chips.chips.values(), *row.corner_grid.buttons.values()):
            self.assertEqual(QAccessible.queryAccessibleInterface(button).role(), QAccessible.Role.CheckBox)
        row.corner_grid.buttons["top_left"].click()
        self.assertEqual(row.corner_grid.buttons["top_left"].accessibleName(), "Top left corner, on")
        titles = ways.part_names("right")
        self.assertEqual([segment.accessibleName() for segment in contact_chip(self.window, self.peers[0]["id"]).segments.values()],
                         [f"Right edge, {titles[third].lower()} third, on" for third in ways.PARTS])

    def test_selection_and_cell_updates_keep_all_rows_in_place(self):
        ledger = self.window.crossing_ledger
        rows = dict(ledger.rows)
        before = parity.descendants(ledger)
        for peer in rows:
            QTest.mouseClick(rows[peer].name, Qt.MouseButton.LeftButton)
            self.assertEqual(self.window.atlas_canvas.selected, peer)
            self.assertTrue(rows[peer].selected)
            rows[peer].corner_grid.buttons["top_left"].click()
            self.assertEqual(ledger.rows, rows)
            self.assertEqual(parity.descendants(ledger).keys(), before.keys())


if __name__ == "__main__":
    unittest.main()
