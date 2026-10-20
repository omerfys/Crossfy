"""Crossing end to end (crossing_harness.py): desks paired on loopback, their maps and Crossing pages
driven as the apps drive them, and every way across pushed through, asserting where input lands.

Every case asserts twice where a change travels: at once, on the machine where it was made, and once
the desks have exchanged what they send, on both. `SETTLE_LIMIT` bounds how long that may take.

On release/1.5.3 40a0f29 (rc12) 19 of these fail, among them an rc12 report from both machines'
logs (switch_v6 raising "display and side go together" on the first push back, which disarms the
way home), display metadata lost from the shared picture, and an endless `arrangement` exchange
between two PCs diagonal to each other. docs/crossing-model-1.5.2.md has the list."""

import copy
import itertools
import time
import unittest
from unittest import mock

from core import return_edge, ways
from core.return_edge import Rect
from core.tests.crossing_harness import THIRD_AT, Net, per_screen_layout
from core.tests.crossing_shells import SHELLS

MAC_DISPLAYS = {"0": Rect(0, 0, 1728, 1117)}
PC_DISPLAYS = {"0": Rect(0, 0, 3840, 2160)}
SIDES = ("left", "right", "top", "bottom")
OPPOSITE = return_edge.OPPOSITE
SETTLE_LIMIT = 1.0
THIRD_SETS = [list(combo) for size in (1, 2, 3) for combo in itertools.combinations(return_edge.PARTS, size)]


class Desks(unittest.TestCase):
    DESKS = ()  # (name, platform, displays, seed)

    def setUp(self):
        grace = mock.patch.object(return_edge, "ARRIVAL_GRACE_SECONDS", 0.0)
        grace.start()
        self.addCleanup(grace.stop)
        self.net = Net(self, SHELLS)
        self.desk = {}
        for name, platform, displays, seed in self.DESKS:
            self.desk[name] = self.net.add(name, platform, displays, seed)
        self.net.pair_all()
        self.net.start()

    def place(self, on, moved, side, shift=0):
        """`on`'s map: `moved`'s tile dropped centred on `side` of `on`'s own tile, `shift` along it."""
        own = on.settings["layout"][on.id]
        tile = on.settings["layout"].get(moved.id) or {"w": moved.tile_size[0], "h": moved.tile_size[1]}
        w, h = tile["w"], tile["h"]
        x, y = {"left": (own["x"] - w, own["y"] + (own["h"] - h) // 2 + shift),
                "right": (own["x"] + own["w"], own["y"] + (own["h"] - h) // 2 + shift),
                "top": (own["x"] + (own["w"] - w) // 2 + shift, own["y"] - h),
                "bottom": (own["x"] + (own["w"] - w) // 2 + shift, own["y"] + own["h"])}[side]
        return on.shell.drop(moved, x, y)

    def settled(self):
        started = time.monotonic()
        self.assertTrue(self.net.settle(SETTLE_LIMIT), "the desks did not settle")
        return time.monotonic() - started

    def assert_agree(self):
        self.assertEqual(self.net.views_agree(), [])
        self.assertEqual(self.net.bad_zones(), [])

    def assert_cross(self, holder, side, to, label="", along=0.5, display=None):
        here = self.net.at(holder)
        landed = self.net.push(holder, side, along, display)
        self.assertIs(landed, to, f"{label}: {holder.name}'s pointer on {here.name} through {side} at {along:.2f} "
                                  f"went to {landed.name}, not {to.name}")
        return landed

    def assert_round_trip(self, holder, other, side, label="", along=0.5, back=None):
        """`holder`'s pointer at home goes through `side` to `other`, lands on the facing side, and comes
        back through it at `back` of the way along (`along` when the two tiles' contact is the same
        stretch of both)."""
        facing = OPPOSITE[side]
        self.assertIs(self.net.at(holder), holder, label)
        self.assert_cross(holder, side, other, label, along)
        self.assertEqual(self.net.landed(other)[1], facing, f"{label}: landed on {other.name}")
        self.assert_cross(holder, facing, holder, f"{label}, back", along if back is None else back)


class Pair(Desks):
    """A Mac and a PC on one desk: This Mac and DESK-WIN11. The Mac's id is the larger."""

    DESKS = (("This Mac", "mac", MAC_DISPLAYS, 90), ("DESK-WIN11", "pc", PC_DISPLAYS, 60))

    def setUp(self):
        super().setUp()
        self.mac, self.pc = self.desk["This Mac"], self.desk["DESK-WIN11"]


class SameSideArrival(Pair):
    def test_left_departure_lands_right_even_when_the_way_back_is_left(self):
        self.assertTrue(self.place(self.mac, self.pc, "left"))
        self.settled()
        self.assertTrue(self.pc.shell.edit(self.mac, ["edge"], edges=["left"]))
        self.settled()
        self.assertTrue(any(zone.get("peer") == self.mac.id and zone.get("side") == "left"
                            for zone in self.pc.settings["zones"]))
        self.assert_cross(self.mac, "left", self.pc, along=0.3)
        self.assertEqual(self.net.landed(self.pc), ("0", "right"))
        self.assertAlmostEqual(self.pc.screen.placed[-1][1] / 2160, 0.3, delta=0.002)
        start = len(self.pc.machine.injector.calls)
        self.mac.hand.move(-40, 0)
        self.assertTrue(self.mac.hand.until(
            lambda: ("move", -40, 0) in self.pc.machine.injector.calls[start:], SETTLE_LIMIT))
        self.assertIs(self.net.at(self.mac), self.pc)
        self.assert_cross(self.mac, "left", self.mac, along=0.3)
        self.assertEqual(self.net.landed(self.mac), ("0", "right"))

    def test_ordinary_left_departure_still_lands_at_the_right_way_back(self):
        self.assertTrue(self.place(self.mac, self.pc, "left"))
        self.settled()
        self.assert_round_trip(self.mac, self.pc, "left", along=0.3)


    def test_left_corner_departure_lands_right_with_clearance_from_the_ends(self):
        self.assertTrue(self.place(self.mac, self.pc, "left"))
        self.settled()
        self.assertTrue(self.mac.shell.edit(self.pc, [], corners=["top_left"]))
        self.assertTrue(self.pc.shell.edit(self.mac, ["edge"], edges=["left"]))
        self.settled()
        self.assertIs(self.net.push_corner(self.mac, "top_left"), self.pc)
        self.assertEqual(self.net.landed(self.pc), ("0", "right"))
        self.assertEqual(self.pc.screen.placed[-1][1], return_edge.LANDING_CLEAR_PX)


class PerScreenPair(Pair):
    """The literal A0–B0–A1 / B1-below desk, with both pictures exchanged over the link."""

    LAYOUT_OPTIONS = {}

    DESKS = (("This Mac", "mac", {"0": Rect(0, 0, 100, 100), "1": Rect(100, 0, 100, 100)}, 90),
             ("DESK-WIN11", "pc", {"0": Rect(0, 0, 100, 100), "1": Rect(0, 100, 100, 100)}, 60))

    def setUp(self):
        super().setUp()
        self.picture = per_screen_layout(self.mac.id, self.pc.id, **self.LAYOUT_OPTIONS)
        settings = copy.deepcopy(self.mac.settings)
        settings["layout"] = copy.deepcopy(self.picture)
        self.mac.save(settings)
        self.assertTrue(self.mac.shell.drop(self.pc, self.picture[self.pc.id]["x"],
                                            self.picture[self.pc.id]["y"], snap=False))
        self.settled()
        self.assert_agree()
        self.assertEqual(self.net.bad_zones(), [])

    def test_pc_b0_crosses_to_mac_a0_and_returns(self):
        self.assertIs(self.net.push(self.pc, "left", display="0"), self.mac)
        self.assertEqual(self.net.landed(self.mac), ("0", "right"))
        self.assertIs(self.net.push(self.pc, "right", display="0"), self.pc)
        self.assertEqual(self.net.landed(self.pc), ("0", "left"))

    def test_a0_crosses_to_b0_and_reciprocally_lands_on_a0(self):
        self.assertIs(self.net.push(self.mac, "right", display="0"), self.pc)
        self.assertEqual(self.net.landed(self.pc), ("0", "left"))
        self.assertIs(self.net.push(self.mac, "left", display="0"), self.mac)
        self.assertEqual(self.net.landed(self.mac), ("0", "right"))

    def test_a1_crosses_to_b0_and_reciprocally_lands_on_a1(self):
        self.assertIs(self.net.push(self.mac, "left", display="1"), self.pc)
        self.assertEqual(self.net.landed(self.pc), ("0", "right"))
        self.assertIs(self.net.push(self.mac, "right", display="0"), self.mac)
        self.assertEqual(self.net.landed(self.mac), ("1", "left"))

    def test_b1_corner_routes_to_the_two_adjacent_a_displays(self):
        for corner, target_display in (("top_left", "0"), ("top_right", "1")):
            with self.subTest(corner=corner):
                self.assertIs(self.net.push_corner(self.pc, corner, display="1"), self.mac)
                self.assertEqual(self.net.landed(self.mac)[0], target_display)
                self.net.shortcut(self.pc)


class UnevenContactABA(Pair):
    DESKS = (("This Mac", "mac", {"0": Rect(0, 0, 100, 80), "1": Rect(100, 0, 100, 120)}, 90),
             ("DESK-WIN11", "pc", {"0": Rect(0, 0, 100, 100), "1": Rect(0, 100, 100, 100)}, 60))
    LAYOUT_OPTIONS = {"a_sizes": ((100, 80), (100, 120)), "b_sizes": ((100, 100), (100, 100))}

    def setUp(self):
        super().setUp()
        self.picture = per_screen_layout(self.mac.id, self.pc.id, **self.LAYOUT_OPTIONS)
        settings = copy.deepcopy(self.mac.settings)
        settings["layout"] = copy.deepcopy(self.picture)
        self.mac.save(settings)
        self.assertTrue(self.mac.shell.drop(self.pc, self.picture[self.pc.id]["x"],
                                            self.picture[self.pc.id]["y"], snap=False))
        self.settled()
        self.assert_agree()
        self.assertEqual(self.net.bad_zones(), [])

    def test_a0_lands_proportionally_inside_b0_contact_with_b1_below(self):
        self.assertIs(self.net.push(self.pc, "left", 0.9, display="0"), self.pc)
        self.assertIs(self.net.push(self.mac, "right", 0.5, display="0"), self.pc)

        self.assertEqual(self.net.landed(self.pc), ("0", "left"))
        self.assertEqual(self.pc.screen.placed[-1][1], 40)
        self.assertIs(self.net.push(self.pc, "left", 0.4, display="0"), self.mac)
        self.assertEqual(self.net.landed(self.mac), ("0", "right"))
        self.assertEqual(self.mac.screen.placed[-1][1], 40)


class Rc12Report(Pair):
    """10-10, rc12, from both machines' logs: the Mac crossed up to the rig and the rig's first push back
    raised in switch_v6 ("display and side go together"), leaving its zones disarmed; the user then moved
    This Mac to the rig's right and back below on the rig's map, and neither crossed until a shortcut
    re-armed it."""

    def test_the_first_crossing_back_after_pairing_lands_home(self):
        self.assert_round_trip(self.mac, self.pc, "right", "default side")

    def test_moved_on_the_driven_rigs_map_and_back_every_way_still_crosses(self):
        self.assertTrue(self.place(self.mac, self.pc, "top"))
        self.settled()
        self.assert_cross(self.mac, "top", self.pc, "Mac up to the rig")
        self.assert_cross(self.mac, "bottom", self.mac, "rig's first push back")
        self.assert_cross(self.mac, "top", self.pc, "Mac up again")
        self.assertTrue(self.place(self.pc, self.mac, "right"), "rig's map: Mac to its right")
        self.assert_cross(self.mac, "right", self.mac, "rig: pushed right at once")
        self.assert_cross(self.mac, "left", self.pc, "Mac: rig now on its left")
        self.assertTrue(self.place(self.pc, self.mac, "bottom"), "rig's map: Mac back below")
        self.assert_cross(self.mac, "bottom", self.mac, "rig: pushed down at once")
        self.settled()
        self.assert_agree()
        self.assert_round_trip(self.mac, self.pc, "top", "after settling")
        self.assert_round_trip(self.pc, self.mac, "bottom", "the rig's own pointer")


class Sides(Pair):
    """The peer on each side, set on either machine's map; both pointers both ways, at once and after
    the exchange."""

    def test_each_side_from_the_macs_map(self):
        for side in SIDES:
            with self.subTest(side=side):
                self.assertTrue(self.place(self.mac, self.pc, side))
                self.assert_round_trip(self.mac, self.pc, side, f"Mac's map, {side}, at once")
                took = self.settled()
                self.assert_agree()
                self.assert_round_trip(self.mac, self.pc, side, f"Mac's map, {side}, settled in {took:.2f}s")
                self.assert_round_trip(self.pc, self.mac, OPPOSITE[side], f"Mac's map, {side}, the PC's pointer")

    def test_each_side_from_the_pcs_map(self):
        for side in SIDES:
            with self.subTest(side=side):
                self.assertTrue(self.place(self.pc, self.mac, side))
                self.assert_round_trip(self.pc, self.mac, side, f"PC's map, {side}, at once")
                took = self.settled()
                self.assert_agree()
                self.assert_round_trip(self.pc, self.mac, side, f"PC's map, {side}, settled in {took:.2f}s")
                self.assert_round_trip(self.mac, self.pc, OPPOSITE[side], f"PC's map, {side}, the Mac's pointer")


class Moves(Pair):
    """A peer moved from side to side and back, on the driving machine's map and on the driven one's
    while it is driven, each push made at once after the drop."""

    ROUTE = ("top", "left", "top", "bottom", "right", "bottom", "top")

    def test_moved_on_the_drivers_map(self):
        for index, side in enumerate(self.ROUTE):
            with self.subTest(step=index, side=side):
                self.assertTrue(self.place(self.mac, self.pc, side))
                self.assert_round_trip(self.mac, self.pc, side, f"step {index}, at once")
        self.settled()
        self.assert_agree()

    def test_moved_on_the_driven_machines_map_while_driven(self):
        self.assertTrue(self.place(self.mac, self.pc, "top"))
        self.settled()
        for index, side in enumerate(self.ROUTE):
            with self.subTest(step=index, side=side):
                facing = OPPOSITE[side]
                # Drive the PC through the side it is on now, then move the Mac on the PC's map.
                held = ways.ways(self.mac.settings, self.pc.id)["side"]
                self.assert_cross(self.mac, held, self.pc, f"step {index}: onto the PC by {held}")
                self.assertTrue(self.place(self.pc, self.mac, facing), f"step {index}: PC's map, Mac to its {facing}")
                self.assert_cross(self.mac, facing, self.mac, f"step {index}: back home at once by the PC's {facing}")
                self.assert_cross(self.mac, side, self.pc, f"step {index}: Mac to the PC by {side}")
                self.assert_cross(self.mac, facing, self.mac, f"step {index}: and home")
        self.settled()
        self.assert_agree()


class Thirds(Pair):
    """Whole edge and every combination of thirds, picked on the page; a third crosses only when
    picked, and the pick survives drops on either machine's map (rc12: thirds lost on drop)."""

    def test_every_combination_of_thirds(self):
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.settled()
        for picked in THIRD_SETS:
            with self.subTest(picked=picked):
                methods = ["edge"] if len(picked) == 3 else ["part"]
                self.assertTrue(self.mac.shell.edit(self.pc, methods, picked))
                for third, along in THIRD_AT.items():
                    if third in picked:
                        self.assert_round_trip(self.mac, self.pc, "right", f"{picked}, {third}", along)
                    else:
                        self.assertIs(self.net.push(self.mac, "right", along), self.mac, f"{picked}: {third} is a wall")

    def test_a_pick_survives_drops_on_both_maps(self):
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.settled()
        self.assertTrue(self.mac.shell.edit(self.pc, ["part"], ["start", "end"]))
        for label, drop in (("Mac's map, same place", lambda: self.place(self.mac, self.pc, "right")),
                            ("Mac's map, away and back", lambda: self.place(self.mac, self.pc, "bottom")
                             and self.place(self.mac, self.pc, "right")),
                            ("PC's map", lambda: self.place(self.pc, self.mac, "left"))):
            with self.subTest(label=label):
                self.assertTrue(drop())
                self.settled()
                self.assertEqual(ways.ways(self.mac.settings, self.pc.id)["parts"], ["start", "end"], label)
                self.assertIs(self.net.push(self.mac, "right", THIRD_AT["middle"]), self.mac, f"{label}: middle")
                self.assert_round_trip(self.mac, self.pc, "right", f"{label}: start", THIRD_AT["start"])


class Corners(Pair):
    """A corner beside the edge and on its own; brackets are the page's business, crossing is ours."""

    def test_corner_with_the_edge_and_alone(self):
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.settled()
        for corner in ("top_right", "bottom_right"):
            with self.subTest(corner=corner, edge=True):
                self.assertTrue(self.mac.shell.edit(self.pc, ["edge", "corner"], corner=corner))
                self.assertIs(self.net.push_corner(self.mac, corner), self.pc, f"{corner} with the edge")
                self.assertIs(self.net.push(self.mac, "left"), self.mac)
                self.assert_round_trip(self.mac, self.pc, "right", f"edge beside {corner}")
            with self.subTest(corner=corner, edge=False):
                self.assertTrue(self.mac.shell.edit(self.pc, ["corner"], corner=corner))
                self.assertIs(self.net.push(self.mac, "right"), self.mac, f"{corner} alone: the edge is a wall")
                self.assertIs(self.net.push_corner(self.mac, corner), self.pc, f"{corner} alone")
                self.assertIs(self.net.push(self.mac, "left"), self.mac)


class Ledger(Pair):
    """Ledger clicks update both the local engine and a visiting pointer's responder."""

    def assert_ledger_thirds(self, on, other, side, picked, label):
        for third, along in THIRD_AT.items():
            with self.subTest(third=third, pointer="own", label=label):
                self.assertIs(self.net.at(on), on)
                if third in picked:
                    self.assert_round_trip(on, other, side, label, along)
                else:
                    self.assertIs(self.net.push(on, side, along), on, f"{label}: {third} is a wall")
            with self.subTest(third=third, pointer="visiting", label=label):
                self.assertIs(self.net.shortcut(other, on), on)
                self.assertIs(self.net.push(other, side, along), other if third in picked else on,
                              f"{label}: visiting pointer, {third}")
                self.assertIs(self.net.shortcut(other), other)

    def test_every_thirds_combination_by_clicks_on_both_platforms_and_every_side(self):
        for on, other in ((self.mac, self.pc), (self.pc, self.mac)):
            for side in SIDES:
                for phase in ("at once", "settled"):
                    for picked in THIRD_SETS:
                        with self.subTest(platform=on.platform, side=side, phase=phase, picked=picked):
                            self.assertTrue(self.place(on, other, side))
                            if phase == "settled":
                                self.settled()
                            for third in ("start", "middle", "end"):
                                if third not in picked:
                                    self.assertTrue(on.shell.click_third(other, third))
                            self.assert_ledger_thirds(on, other, side, picked, phase)
                            self.settled()
                            self.assert_agree()
                            self.assertTrue(on.shell.click_edge_text(other))
                            self.assertTrue(on.shell.click_edge_text(other))

    def test_last_lit_third_off_and_any_third_on_alone_keep_the_shortcut(self):
        for on, other in ((self.mac, self.pc), (self.pc, self.mac)):
            for phase, side in (("at once", "right"), ("settled", "top")):
                with self.subTest(platform=on.platform, phase=phase):
                    self.assertTrue(self.place(on, other, side))
                    if phase == "settled":
                        self.settled()
                    self.assertTrue(on.shell.click_third(other, "start"))
                    self.assertTrue(on.shell.click_third(other, "end"))
                    self.assertTrue(on.shell.click_third(other, "middle"))
                    self.assert_ledger_thirds(on, other, side, [], "last lit third off")
                    self.assertEqual(ways.ways(on.settings, other.id)["parts"], ["middle"])
                    self.assertIs(self.net.shortcut(on, other), other)
                    self.assertIs(self.net.shortcut(on), on)
                    for third in ("start", "middle", "end"):
                        self.assertTrue(on.shell.click_third(other, third))
                        self.assert_ledger_thirds(on, other, side, [third], "one third from off")
                        self.assertTrue(on.shell.click_third(other, third))
                    self.assertTrue(on.shell.click_edge_text(other))

    def test_edge_text_turns_any_on_form_off_and_restores_the_whole_edge(self):
        for on, other in ((self.mac, self.pc), (self.pc, self.mac)):
            for phase, side in (("at once", "right"), ("settled", "top")):
                for picked in THIRD_SETS:
                    with self.subTest(platform=on.platform, phase=phase, picked=picked):
                        self.assertTrue(self.place(on, other, side))
                        if phase == "settled":
                            self.settled()
                        for third in ("start", "middle", "end"):
                            if third not in picked:
                                self.assertTrue(on.shell.click_third(other, third))
                        self.assertTrue(on.shell.click_edge_text(other))
                        self.assert_ledger_thirds(on, other, side, [], "Edge text off")
                        self.assertTrue(on.shell.click_edge_text(other))
                        self.assert_ledger_thirds(on, other, side, ["start", "middle", "end"],
                                                  "Edge text restores whole edge")

    def test_corner_click_moves_only_the_corner_and_lit_dot_turns_it_off(self):
        for on, other in ((self.mac, self.pc), (self.pc, self.mac)):
            self.assertTrue(on.shell.click_third(other, "start"))
            self.assertTrue(on.shell.click_third(other, "end"))
            for phase, side in (("at once", "right"), ("settled", "top")):
                for corner in ("top_left", "top_right", "bottom_left", "bottom_right"):
                    with self.subTest(platform=on.platform, phase=phase, corner=corner):
                        self.assertTrue(self.place(on, other, side))
                        if phase == "settled":
                            self.settled()
                        self.assertTrue(on.shell.click_corner(other, corner))
                        for pushed in ("top_left", "top_right", "bottom_left", "bottom_right"):
                            with self.subTest(pointer="own", pushed=pushed):
                                landed = self.net.push_corner(on, pushed)
                                self.assertIs(landed, other if pushed == corner else on,
                                              f"{corner}: own diagonal push at {pushed} went to {landed.name}")
                            self.assertIs(self.net.shortcut(on), on)
                            self.assertIs(self.net.shortcut(other, on), on)
                            with self.subTest(pointer="visiting", pushed=pushed):
                                landed = self.net.push_corner(other, pushed)
                                self.assertIs(landed, other if pushed == corner else on,
                                              f"{corner}: visiting diagonal push at {pushed} went to {landed.name}")
                            self.assertIs(self.net.shortcut(other), other)
                        self.assert_ledger_thirds(on, other, side, ["middle"], "edge beside the corner")
                        self.assertTrue(on.shell.click_edge_text(other))
                        with self.subTest(edit="Edge text", corner=corner):
                            self.assertIs(self.net.push_corner(on, corner), other, "Edge off keeps Corner")
                        self.assertIs(self.net.shortcut(on), on)
                        self.assertTrue(on.shell.click_third(other, "middle"))
                        with self.subTest(edit="third", corner=corner):
                            self.assertIs(self.net.push_corner(on, corner), other, "third click keeps Corner")
                        self.assertIs(self.net.shortcut(on), on)
                self.assertTrue(on.shell.click_corner(other, "bottom_right"))
                for corner in ("top_left", "top_right", "bottom_left", "bottom_right"):
                    self.assertIs(self.net.push_corner(on, corner), on, "lit dot off leaves no corner")
                self.assert_ledger_thirds(on, other, side, ["middle"], "Corner off keeps Edge")

    def test_left_out_controls_are_inert_and_put_back_keeps_the_choices(self):
        for on, other in ((self.mac, self.pc), (self.pc, self.mac)):
            with self.subTest(platform=on.platform):
                self.assertTrue(self.place(on, other, "right"))
                self.assertTrue(on.shell.click_third(other, "start"))
                self.assertTrue(on.shell.click_corner(other, "top_left"))
                on.shell.leave_out(other)
                self.settled()
                with on.shell.lock:
                    before = copy.deepcopy(on.settings)
                    sent = on.shell.sent_count
                    saves = on.machine.settings.saves
                    self.assertFalse(on.shell.click_third(other, "middle"))
                    self.assertFalse(on.shell.click_edge_text(other))
                    self.assertFalse(on.shell.click_corner(other, "bottom_right"))
                    self.assertEqual(on.settings, before)
                    self.assertEqual(on.shell.sent_count, sent)
                    self.assertEqual(on.machine.settings.saves, saves)
                self.assert_ledger_thirds(on, other, "right", [], "left out")
                on.shell.put_back(other)
                self.assert_ledger_thirds(on, other, "right", ["middle", "end"], "put back")
                self.assertIs(self.net.push_corner(on, "top_left"), other, "put back keeps Corner")
                self.assertIs(self.net.shortcut(on), on)

    def test_clicks_rearm_the_responder_while_a_visiting_pointer_is_already_there(self):
        for on, other in ((self.mac, self.pc), (self.pc, self.mac)):
            for phase in ("at once", "settled"):
                with self.subTest(platform=on.platform, phase=phase):
                    self.assertTrue(self.place(on, other, "right"))
                    self.assertIs(self.net.shortcut(other, on), on)
                    self.assertTrue(self.place(on, other, "right"))
                    if phase == "settled":
                        self.settled()
                    for third in ("start", "end", "middle"):
                        self.assertTrue(on.shell.click_third(other, third))
                        self.assertIs(self.net.push(other, "right", THIRD_AT[third]), on,
                                      f"{phase}: clicked third must become a wall while driven")
                    self.assertTrue(on.shell.click_edge_text(other))
                    self.assertIs(self.net.push(other, "right"), other, "Edge text re-arms while driven")
                    self.assertIs(self.net.shortcut(other, on), on)
                    self.assertTrue(on.shell.click_corner(other, "top_right"))
                    self.assertTrue(on.shell.click_edge_text(other))
                    self.assertIs(self.net.push(other, "right"), on, "Edge off applies while driven")
                    self.assertIs(self.net.push_corner(other, "top_right"), other,
                                  "Corner on applies while driven and survives Edge off")
                    self.assertIs(self.net.shortcut(other, on), on)
                    self.assertTrue(on.shell.click_corner(other, "top_right"))
                    self.assertIs(self.net.push_corner(other, "top_right"), on,
                                  "lit dot off applies while driven")
                    self.assertTrue(on.shell.click_edge_text(other))
                    self.assertIs(self.net.shortcut(other), other)


class EdgeOff(Pair):
    """Edge off and on again, with a drop in place between (rc11: Edge off did not reach the map)."""

    def test_off_holds_through_a_drop_and_on_again_crosses(self):
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.settled()
        self.assertTrue(self.mac.shell.edit(self.pc, []))
        self.assertFalse(ways.crosses_on_map(self.mac.settings, self.pc.id))
        self.assertIs(self.net.push(self.mac, "right"), self.mac, "off")
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.settled()
        self.assertIs(self.net.push(self.mac, "right"), self.mac, "off, after a drop in place")
        self.assertIs(self.net.shortcut(self.mac, self.pc), self.pc, "the shortcut still reaches it")
        self.assertIs(self.net.shortcut(self.mac), self.mac)
        self.assertTrue(self.mac.shell.edit(self.pc, ["edge"]))
        self.assertTrue(ways.crosses_on_map(self.mac.settings, self.pc.id))
        self.assert_round_trip(self.mac, self.pc, "right", "on again")


class Wrap(Pair):
    def test_two_wrap_edges_and_corners_cross_and_can_be_removed(self):
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.settled()
        self.assertTrue(self.mac.shell.edit(self.pc, ["edge"], edges=["left", "top"],
                                            corners=["top_left", "bottom_left"]))
        self.assert_cross(self.mac, "left", self.pc, "left wrap")
        self.assertEqual(self.net.landed(self.pc)[1], "right")
        self.assert_cross(self.mac, "right", self.mac, "way back through arrival side")
        self.assertEqual(self.net.landed(self.mac)[1], "left")
        for corner in ("top_left", "bottom_left"):
            self.assertIs(self.net.push_corner(self.mac, corner), self.pc, corner)
            self.assertEqual(self.net.landed(self.pc)[1], "right")
            self.assert_cross(self.mac, "right", self.mac, f"{corner} way back")
        self.assert_cross(self.mac, "top", self.pc, "top wrap")
        self.assertEqual(self.net.landed(self.pc)[1], "bottom")
        self.assert_cross(self.mac, "bottom", self.mac, "top wrap way back")
        self.settled()
        self.assert_agree()

        self.assertTrue(self.mac.shell.edit(self.pc, ["edge"], edges=["left"], corners=["top_left"]))
        self.assertIs(self.net.push(self.mac, "top"), self.mac, "removed top wrap")
        self.assertIs(self.net.push(self.mac, "left"), self.pc, "left wrap retained")
        self.assert_cross(self.mac, "right", self.mac, "return after removing a way")
        self.assertTrue(self.mac.shell.edit(self.pc, [], edges=["left"], corners=["top_left"]))
        self.assertIs(self.net.push_corner(self.mac, "bottom_left"), self.mac, "removed corner")
        self.assertIs(self.net.push_corner(self.mac, "top_left"), self.pc, "retained corner")
        self.assert_cross(self.mac, "right", self.mac, "corner return")
        self.settled()
        self.assert_agree()

    def test_edge_off_remembers_wrap_edges_until_restored(self):
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.settled()
        self.assertTrue(self.mac.shell.edit(self.pc, [], edges=["left"]))
        self.assertEqual(ways.ways(self.mac.settings, self.pc.id)["edges"], ["left"])
        self.assertIs(self.net.push(self.mac, "left"), self.mac)
        self.assertTrue(self.mac.shell.edit(self.pc, ["edge"], edges=["left"]))
        self.assertIs(self.net.push(self.mac, "left"), self.pc)
        self.assert_cross(self.mac, "right", self.mac, "restored wrap way back")
        self.settled()
        self.assert_agree()

    def test_wrap_works_from_the_other_maps_intent_too(self):
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.settled()
        self.assertTrue(self.pc.shell.edit(self.mac, ["edge"], edges=["right"]))
        self.assert_cross(self.pc, "right", self.mac, "PC wrap")
        self.assertEqual(self.net.landed(self.mac)[1], "left")
        self.assert_cross(self.pc, "left", self.pc, "PC wrap way back")
        self.assertEqual(self.net.landed(self.pc)[1], "right")
        self.settled()
        self.assert_agree()


class Shortcut(Pair):
    def test_the_shortcut_goes_and_comes_back_whatever_the_edges(self):
        self.assertIs(self.net.shortcut(self.mac, self.pc), self.pc)
        self.assertIs(self.net.shortcut(self.mac), self.mac)
        self.assertIs(self.net.shortcut(self.pc, self.mac), self.mac)
        self.assertIs(self.net.shortcut(self.pc), self.pc)


class TwoDisplays(Desks):
    """A Mac with an external display to the right of its own; the PC placed above the external one
    only: only that display's top edge crosses, and the way back lands on it."""

    DESKS = (("This Mac", "mac", {"0": Rect(0, 0, 1728, 1117), "1": Rect(1728, 0, 2560, 1440)}, 90),
             ("DESK-WIN11", "pc", PC_DISPLAYS, 60))

    def test_per_display_edges(self):
        mac, pc = self.desk["This Mac"], self.desk["DESK-WIN11"]
        self.settled()
        own = mac.settings["layout"][mac.id]
        tile = mac.settings["layout"][pc.id]
        # Over the external display only: its frame is the right 60% of the Mac's tile, so the PC's
        # tile starts 90 units in from the Mac's right edge and overhangs it.
        x = own["x"] + own["w"] - 90
        self.assertTrue(mac.shell.drop(pc, x, own["y"] - tile["h"]))
        self.settled()
        self.assertIs(self.net.push(mac, "top", display="1"), pc, "the external display's top")
        self.assertEqual(self.net.landed(pc)[1], "bottom")
        self.assertIs(self.net.push(mac, "bottom"), mac, "back")
        self.assertEqual(self.net.landed(mac), ("1", "top"), "lands on the display it left")
        self.assertIs(self.net.push(mac, "top", display="0"), mac, "the built-in display's top is a wall")


class Three(Desks):
    """This Mac, the rig and a Linux PC: two peers sharing one side by thirds, chains, and a third
    machine dropped and moved (rc12: the split undone by a compile)."""

    DESKS = (("This Mac", "mac", MAC_DISPLAYS, 90), ("DESK-WIN11", "pc", PC_DISPLAYS, 60),
             ("Fedora", "pc", {"0": Rect(0, 0, 2560, 1600)}, 120))

    def setUp(self):
        super().setUp()
        self.mac, self.pc, self.linux = (self.desk[name] for name in ("This Mac", "DESK-WIN11", "Fedora"))

    def test_one_above_one_left_every_way_and_the_chain(self):
        self.assertTrue(self.place(self.mac, self.pc, "top"))
        self.assertTrue(self.place(self.mac, self.linux, "left"))
        self.settled()
        self.assert_agree()
        self.assert_round_trip(self.mac, self.pc, "top", "rig above", along=0.25, back=0.75)
        self.assert_round_trip(self.mac, self.linux, "left", "Fedora left")
        self.assert_round_trip(self.pc, self.mac, "bottom", "the rig's own pointer")
        self.assert_round_trip(self.linux, self.mac, "right", "Fedora's own pointer")

    def test_two_on_one_side_split_by_the_map_and_kept_through_a_drop(self):
        # Pairing leaves the default tiles wherever the winning picture put them; clear the right side
        # first, so neither drop below lands on a tile and is snapped elsewhere.
        self.assertTrue(self.place(self.mac, self.pc, "top"))
        self.assertTrue(self.place(self.mac, self.linux, "left"))
        self.settled()
        own = self.mac.settings["layout"][self.mac.id]
        half = own["h"] // 2
        self.assertTrue(self.mac.shell.drop(self.pc, own["x"] + own["w"], own["y"] - half))
        self.assertTrue(self.mac.shell.drop(self.linux, own["x"] + own["w"], own["y"] + half + 1))
        self.settled()
        self.assert_round_trip(self.mac, self.pc, "right", "upper", THIRD_AT["start"], back=THIRD_AT["end"])
        self.assert_round_trip(self.mac, self.linux, "right", "lower", THIRD_AT["end"], back=THIRD_AT["start"])
        self.assertTrue(self.place(self.mac, self.pc, "top"))
        self.assertTrue(self.mac.shell.drop(self.pc, own["x"] + own["w"], own["y"] - half))
        self.settled()
        self.assert_round_trip(self.mac, self.pc, "right", "upper again", THIRD_AT["start"], back=THIRD_AT["end"])
        self.assert_round_trip(self.mac, self.linux, "right", "lower kept", THIRD_AT["end"], back=THIRD_AT["start"])

    def test_moving_one_peer_leaves_the_other_alone(self):
        self.assertTrue(self.place(self.mac, self.pc, "top"))
        self.assertTrue(self.place(self.mac, self.linux, "left"))
        self.settled()
        for side in ("right", "bottom", "top"):
            with self.subTest(side=side):
                self.assertTrue(self.place(self.mac, self.pc, side))
                self.settled()
                self.assert_round_trip(self.mac, self.pc, side, f"rig {side}")
                self.assert_round_trip(self.mac, self.linux, "left", f"Fedora still left, rig {side}")

    def test_a_wrap_edge_takes_only_the_thirds_not_held_by_a_peer_contact(self):
        self.assertTrue(self.place(self.mac, self.pc, "right"))
        self.assertTrue(self.place(self.mac, self.linux, "left", shift=25))
        self.settled()
        self.assertTrue(self.mac.shell.edit(self.pc, ["edge"], edges=["left"]))
        map_entry = ways.compile_layout(self.mac.settings, self.mac.settings["layout"],
                                        capable=self.mac.shell.capable())["tiles"][self.pc.id]
        self.assertEqual(map_entry["wraps"], [{"display": "0", "side": "left", "parts": ["start"]}])
        self.assert_cross(self.mac, "left", self.pc, "free wrap third", THIRD_AT["start"])
        self.assert_cross(self.mac, "right", self.mac, "way back from the free wrap third")
        self.assert_cross(self.mac, "left", self.linux, "contact-owned thirds", THIRD_AT["middle"])
        self.settled()
        self.assert_agree()


class Rc14Corner(Three):
    """10-10, rc14, from the Mac's and the rig's logs: the rig's corner for the Mac (top left, edges
    off) sent input home onto the very end of the Mac's bottom edge, which is also its left edge, and
    the hand still moving left crossed the Mac's left zone to the machine there 14 ms later."""

    def test_a_corner_crossing_home_lands_clear_of_the_edge_beside_it(self):
        # The rig half a tile left of centre, so Fedora shares part of its top edge. Placed before the
        # tiles were exchanged, the rig sometimes went exactly below the Mac instead; Fedora then
        # touched the rig's top left corner and, since 1.5.3, holds it, so the Mac's corner was refused.
        self.settled()
        self.assertTrue(self.place(self.mac, self.pc, "bottom", shift=-self.mac.settings["layout"][self.mac.id]["w"] // 2))
        self.assertTrue(self.place(self.mac, self.linux, "left"))
        self.settled()
        for corner in ("top_left", "top_right"):
            with self.subTest(corner=corner):
                self.assertTrue(self.pc.shell.edit(self.mac, ["corner"], corner=corner))
                self.assert_cross(self.mac, "bottom", self.pc, "Mac down to the rig", along=0.25)
                self.assertIs(self.net.push_corner(self.mac, corner), self.mac, f"the rig's {corner} corner home")
                display, side = self.net.landed(self.mac)
                self.assertEqual(side, "bottom", "landed on the Mac's bottom edge")
                x, y = self.mac.screen.placed[-1]
                rect = self.mac.screen.displays[display]
                clear = return_edge.LANDING_CLEAR_PX
                self.assertTrue(rect.x + clear <= x <= rect.right - clear,
                                f"landed at x {x}, inside {clear} px of an end of {rect}")
                self.assertTrue(rect.x + return_edge.CORNER_PX < x < rect.right - return_edge.CORNER_PX,
                                "landed inside a corner box")
                self.assert_round_trip(self.mac, self.linux, "left", "Fedora on the left still crosses")


class LedgerThree(Three):
    def test_another_machines_held_corner_is_refused_without_a_write(self):
        for on, holder, refused in ((self.mac, self.pc, self.linux),
                                   (self.pc, self.mac, self.linux)):
            self.assertTrue(self.place(on, holder, "top"))
            self.assertTrue(self.place(on, refused, "left"))
            self.settled()
            self.assertTrue(on.shell.click_corner(holder, "top_left"))
            self.assertTrue(on.shell.click_corner(refused, "bottom_left"))
            for phase, side in (("at once", "right"), ("settled", "top")):
                with self.subTest(platform=on.platform, phase=phase):
                    self.assertTrue(self.place(on, holder, side))
                    if phase == "settled":
                        self.settled()
                    with on.shell.lock:
                        before = copy.deepcopy(on.settings)
                        sent = on.shell.sent_count
                        saves = on.machine.settings.saves
                        self.assertFalse(on.shell.click_corner(refused, "top_left"))
                        self.assertEqual(on.settings, before, "a held dot must write nothing")
                        self.assertEqual(on.shell.sent_count, sent, "a refused click must send nothing")
                        self.assertEqual(on.machine.settings.saves, saves, "a refused click must save nothing")
                    with self.subTest(pointer="own"):
                        self.assertIs(self.net.push_corner(on, "top_left"), holder, "B keeps its corner")
                    self.assertIs(self.net.shortcut(on), on)
                    self.assertIs(self.net.shortcut(refused, on), on)
                    with self.subTest(pointer="visiting"):
                        self.assertIs(self.net.push_corner(refused, "top_left"), holder,
                                      "B keeps its corner for a visiting pointer")
                    self.assertIs(self.net.shortcut(refused), refused)
                    self.settled()
                    self.assert_agree()
            self.assertTrue(on.shell.click_corner(holder, "top_left"))
            self.assertTrue(on.shell.click_corner(refused, "bottom_left"))


if __name__ == "__main__":
    unittest.main()
