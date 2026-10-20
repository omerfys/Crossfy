"""Crossing profiles end to end (spec 1.5.5 sections 5, 7, 8 and 12): two to four desktops on
loopback, each a real responder and owner, syncing the desk (`settings.data.desk`) over the real
encrypted links through the shells in crossing_shells.py, which do what the apps do.

Every case settles the desks and then asserts the same things: they settled within SETTLE_LIMIT, no
message is still travelling a quarter of a second later (the frame count stops), no `settings` frame
reaches 64 KiB, the profile-aware desks hold equal `crossing_desk` registers, the pictures and sides
agree and no zone is malformed."""

import copy
import sys
import time
import unittest
from unittest import mock

from core import crossing_state, profiles, return_edge, ways
from core.return_edge import Rect
from core.tests.crossing_harness import Net, text
from core.tests.crossing_shells import SHELLS
from core.tests.responder_harness import entry

SETTLE_LIMIT = 1.0
QUIET = 0.25
FRAME_LIMIT = 64 * 1024
MAC = {"0": Rect(0, 0, 1728, 1117)}
PC = {"0": Rect(0, 0, 3840, 2160)}
SPECS = {"A": ("mac", MAC, 90), "B": ("pc", PC, 60), "C": ("pc", {"0": Rect(0, 0, 2560, 1600)}, 120),
         "D": ("mac", {"0": Rect(0, 0, 1512, 982)}, 150)}
DESK = profiles.DESK_ID
MEASURED = {}


def tearDownModule():
    for name, (settle, frames) in sorted(MEASURED.items()):
        print(f"{name}: slowest settle {settle:.3f}s, {frames} frames", file=sys.stderr)


def desk_state(desk):
    state = copy.deepcopy(desk.settings["crossing_desk"])
    state.pop("format", None)
    for profile in state["profiles"].values():
        if profile.get("removed") is None:
            profile.pop("removed", None)
    return state


def rows(desk, pid=DESK):
    return {machine: reg["value"] for machine, reg in
            desk.settings["crossing_desk"]["profiles"][pid]["rows"].items()}


def spot(tile):
    return tuple(tile[key] for key in ("x", "y", "w", "h"))


def own_row(desk):
    return copy.deepcopy(desk.settings["crossing_own"]["row"])


def live(desk):
    return profiles.live_row(desk.settings)


def zones(desks):
    return {desk.name: copy.deepcopy(desk.settings["zones"]) for desk in desks}


def archived(desk, row):
    return any(item["row"] == profiles.canonical_row(row) for item in desk.settings["crossing_own"]["saved"])


class Mesh(unittest.TestCase):
    def setUp(self):
        grace = mock.patch.object(return_edge, "ARRIVAL_GRACE_SECONDS", 0.0)
        grace.start()
        self.addCleanup(grace.stop)
        self.net = Net(self, SHELLS)
        self.worst = 0.0
        self.sent_before = 0
        self.addCleanup(self.record)

    def record(self):
        MEASURED[self.id().rsplit(".", 2)[-2] + "." + self.id().rsplit(".", 1)[-1]] = (self.worst, self.frames())

    def build(self, names, pairs=None, plain=()):
        """Desks `names`, paired as `pairs` (strings like "AB"; every pair by default). Those in
        `plain` are 1.5.3-style: no `profiles` capability and no crossing_own."""
        partial = pairs is not None
        pairs = pairs or [one + two for i, one in enumerate(names) for two in names[i + 1:]]
        self.d = {}
        for name in names:
            platform, displays, seed = SPECS[name]
            self.d[name] = self.net.add(name, platform, displays, seed, profiles=name not in plain)
        self.pairs = [(self.d[p[0]], self.d[p[1]]) for p in pairs]
        for desk in self.d.values():
            partners = [other for one, two in self.pairs for other in (one, two)
                        if desk in (one, two) and other is not desk]
            with desk.lock:
                settings = copy.deepcopy(desk.settings)
                settings["peers"] = [entry(other.own, other.name, token=self.key(desk, other),
                                           platform=other.platform_name, linked=False,
                                           paired_with=[third.id for third in partners if third is not other]
                                           + [desk.id])
                                     for other in partners]
                for item in settings["peers"]:
                    item["side"] = ""
                settings["zones"] = []
                if partial:
                    settings.update(self.whole_picture(names))
                desk.shell.paired(settings)
                desk.save(settings)
        for desk in self.d.values():
            desk.machine.start()
            self.addCleanup(desk.machine.stop)
            desk.started = True
        for one, two in self.pairs:
            self.link(one, two)
        for one, two in self.pairs:
            one.shell.link_up(two)
            two.shell.link_up(one)
        self.settle("built")
        return [self.d[name] for name in names]

    def whole_picture(self, names):
        """Every desk of a chain holds the same complete picture from the start: two machines that
        are not paired never learn each other's tile through the middle one, and the cases here are
        about the desk rows, not about how a chain's pictures merge."""
        tiles = {}
        for number, name in enumerate(names):
            desk = self.d[name]
            tiles[desk.id] = {"x": number * 160, "y": 0, "w": 160, "h": 100,
                              "displays": {key: {"x": rect.x, "y": rect.y, "w": rect.width, "h": rect.height}
                                           for key, rect in desk.screen.displays.items()}}
        return {"layout": tiles, "layout_set_at": 5, "layout_by": self.d[names[0]].id}

    @staticmethod
    def key(one, two):
        from core.tests.crossing_harness import key
        return key(one.own, two.own)

    def link(self, one, two):
        one.hand.connect(two)
        two.hand.connect(one)

    def unlink(self, gone):
        """`gone` drops off the network: every link to and from it closes."""
        for one, two in self.pairs:
            if gone in (one, two):
                one.hand.drop(two)
                two.hand.drop(one)

    def relink(self, back):
        mine = [(one, two) for one, two in self.pairs if back in (one, two)]
        for one, two in mine:
            self.link(one, two)
        for one, two in mine:
            one.shell.link_up(two)
            two.shell.link_up(one)

    def frames(self):
        return sum(len(desk.shell.frames) for desk in self.d.values())

    def desk_frames(self):
        return [frame for desk in self.d.values() for frame in desk.shell.frames if frame["desk"]]

    def settle(self, label=""):
        started = time.monotonic()
        self.assertTrue(self.net.settle(SETTLE_LIMIT), f"{label}: the desks did not settle")
        took = time.monotonic() - started
        self.worst = max(self.worst, took)
        sent = self.frames()
        time.sleep(QUIET)
        self.assertTrue(self.net.settle(SETTLE_LIMIT), f"{label}: the desks did not settle again")
        self.assertEqual(self.frames(), sent, f"{label}: messages were still being sent after settling")
        for desk in self.d.values():
            self.assertEqual(desk.shell.errors, [], f"{label}: {desk.name} raised")
        biggest = max((frame["size"] for desk in self.d.values() for frame in desk.shell.frames), default=0)
        self.assertLess(biggest, FRAME_LIMIT, f"{label}: a frame of {biggest} bytes")
        self.assertLess(max((f["size"] for f in self.desk_frames()), default=0), profiles.MAX_DESK_BYTES)
        self.assertEqual(self.net.bad_zones(), [], label)
        return took

    def aware(self, *names):
        return [desk for desk in self.d.values() if desk.profiles and (not names or desk.name in names)]

    def assert_converged(self, label="", names=()):
        desks = self.aware(*names)
        first = desk_state(desks[0])
        for desk in desks[1:]:
            self.assertEqual(desk_state(desk), first, f"{label}: {desk.name} differs from {desks[0].name}")

    def assert_agree(self, label=""):
        self.assertEqual(self.net.views_agree(), [], label)
        self.assertEqual(self.net.bad_zones(), [], label)

    def place(self, on, moved, side, shift=0):
        own = on.settings["layout"][on.id]
        tile = on.settings["layout"].get(moved.id) or {"w": moved.tile_size[0], "h": moved.tile_size[1]}
        w, h = tile["w"], tile["h"]
        x, y = {"left": (own["x"] - w, own["y"] + (own["h"] - h) // 2 + shift),
                "right": (own["x"] + own["w"], own["y"] + (own["h"] - h) // 2 + shift),
                "top": (own["x"] + (own["w"] - w) // 2 + shift, own["y"] - h),
                "bottom": (own["x"] + (own["w"] - w) // 2 + shift, own["y"] + own["h"])}[side]
        self.assertTrue(on.shell.drop(moved, x, y))

    def arrange(self, first, others):
        """`others` round `first` on its map, then every desk given its own odd ways so that
        no row is the default."""
        for other, side in zip(others, ("right", "left", "top")):
            self.place(first, other, side)
        self.settle("arranged")
        for number, desk in enumerate(self.d.values()):
            for peer in self.d.values():
                if peer is not desk and desk.peer(peer) is not None:
                    parts = [["start"], ["middle"], ["end"], ["start", "end"]][(number + len(peer.name)) % 4]
                    desk.shell.edit(peer, ["part"], parts=parts)
        self.settle("odd ways")

    def turn_on(self, desk):
        self.assertTrue(desk.shell.same_ways(True)["accepted"])
        self.settle("same ways on")

    def make_profile(self, desk, name):
        known = set(desk.settings["crossing_desk"]["profiles"])
        self.assertTrue(desk.shell.new_profile(name)["accepted"])
        (pid,) = set(desk.settings["crossing_desk"]["profiles"]) - known
        self.settle(f"{name} made")
        return pid


class SameWaysChangesNothing(Mesh):
    def check(self, names):
        desks = self.build(names)
        self.arrange(desks[0], desks[1:])
        self.assert_agree("before")
        before_zones, before_live = zones(desks), {d.name: live(d) for d in desks}
        before_own = {d.name: own_row(d) for d in desks}
        self.turn_on(desks[-1])
        self.assert_agree("after")
        self.assert_converged("on")
        self.assertEqual(zones(desks), before_zones, "a zone moved when Same ways went on")
        for desk in desks:
            self.assertEqual(live(desk), before_live[desk.name], desk.name)
            self.assertEqual(own_row(desk), before_own[desk.name], f"{desk.name}'s own row")
            self.assertEqual(profiles.in_force(desk.settings), (before_own[desk.name], True), desk.name)
            for other in desks:
                self.assertEqual(rows(desk)[other.id], before_own[other.name],
                                 f"{desk.name} holds {other.name}'s row as its previous own row")
        return desks

    def test_two_machines(self):
        for desk in self.check("AB"):
            self.assertFalse(desk.shell.refused_desks)

    def test_three_machines(self):
        self.check("ABC")

    def test_four_machines(self):
        self.check("ABCD")

    def test_each_machine_turns_it_on_from_its_own_page(self):
        desks = self.build("ABC")
        self.arrange(desks[0], desks[1:])
        before = zones(desks)
        self.turn_on(desks[2])
        self.assert_converged()
        self.assertEqual(zones(desks), before)
        self.assertEqual(desk_state(desks[0])["on"]["by"], desks[2].id)

    def test_a_stale_machine_turning_it_on_again_seeds_nobody(self):
        a, b, c = self.build("ABC")
        self.arrange(a, [b, c])
        self.turn_on(a)
        self.assertTrue(b.shell.edit_other(a, c, thirds=["end"])["accepted"])
        self.settle("edit")
        held = desk_state(a)
        c.shell.skew = -60
        c.shell.same_ways(True)
        self.settle("again")
        self.assertEqual(desk_state(a)["on"], held["on"])
        self.assertEqual(rows(a)[a.id], rows(c)[a.id])
        self.assertEqual(rows(a)[a.id][c.id]["ways"]["thirds"], ["end"])


class Edits(Mesh):
    def test_an_edit_arrives_is_in_force_and_the_old_row_is_archived(self):
        a, b = self.build("AB")
        self.place(a, b, "right")
        self.settle("placed")
        self.assertTrue(a.shell.edit(b, ["edge"], edges=["right"]))
        self.assertTrue(b.shell.edit(a, ["edge"], edges=["left"]))
        self.settle("ways")
        self.turn_on(a)
        previous = own_row(b)
        self.assertTrue(self.net.push(b, "left", 0.1) is a, "the whole edge crosses before the edit")
        self.net.shortcut(b)
        out = a.shell.edit_other(b, a, thirds=["end"])
        self.assertTrue(out["accepted"])
        self.settle("edit")
        self.assert_converged()
        self.assertEqual(ways.ways(b.settings, a.id)["parts"], ["end"])
        row, desk_in_force = profiles.in_force(b.settings)
        self.assertTrue(desk_in_force)
        self.assertEqual(row[a.id]["ways"]["thirds"], ["end"])
        self.assertEqual(own_row(b), previous, "the edit never reaches B's own row")
        self.assertTrue(archived(b, previous), "B's previous row is in its archive")
        self.assertEqual(rows(b)[b.id][a.id]["ways"]["thirds"], ["end"])
        self.assertIs(self.net.push(b, "left", 0.1), b, "the start third is now a wall")
        self.assertIs(self.net.push(b, "left", 0.9), a, "the end third crosses")
        self.net.shortcut(b)
        self.assert_agree()

    def edits_reach_everyone(self, names):
        desks = self.build(names)
        self.arrange(desks[0], desks[1:])
        self.turn_on(desks[0])
        for number, editor in enumerate(desks):
            target = desks[(number + 1) % len(desks)]
            peer = desks[(number + 2) % len(desks)]
            previous = copy.deepcopy(rows(target)[target.id])
            self.assertTrue(editor.shell.edit_other(target, peer, thirds=["middle"], edge=True)["accepted"])
            self.settle(f"{editor.name} edits {target.name}")
            self.assert_converged(f"{editor.name} edits {target.name}")
            self.assertEqual(ways.ways(target.settings, peer.id)["parts"], ["middle"])
            self.assertEqual(profiles.in_force(target.settings)[1], True)
            self.assertTrue(archived(target, previous), f"{target.name}'s row before {editor.name}'s edit")
        self.assert_agree()

    def test_edits_from_any_machine_reach_the_others_in_three(self):
        self.edits_reach_everyone("ABC")

    def test_edits_from_any_machine_reach_the_others_in_four(self):
        self.edits_reach_everyone("ABCD")

    def test_concurrent_edits_to_one_row_converge_to_the_newer(self):
        a, b, c = self.build("ABC")
        self.arrange(a, [b, c])
        self.turn_on(a)
        b.shell.skew = 10
        a.shell.edit_other(c, b, thirds=["start"])
        b.shell.edit_other(c, a, thirds=["end"])
        self.settle("concurrent")
        self.assert_converged()
        held = self.d["C"].settings["crossing_desk"]["profiles"][DESK]["rows"][c.id]
        self.assertEqual(held["by"], b.id, "the later clock's whole row won")
        self.assertEqual(held["value"][a.id]["ways"]["thirds"], ["end"])
        self.assertEqual(ways.ways(c.settings, a.id)["parts"], ["end"])

    def test_concurrent_edits_to_different_rows_both_land(self):
        a, b, c = self.build("ABC")
        self.arrange(a, [b, c])
        self.turn_on(a)
        a.shell.edit_other(c, b, thirds=["start"])
        b.shell.edit_other(a, c, thirds=["end"])
        c.shell.edit_other(b, a, thirds=["middle"])
        self.settle("concurrent")
        self.assert_converged()
        self.assertEqual(rows(a)[c.id][b.id]["ways"]["thirds"], ["start"])
        self.assertEqual(rows(a)[a.id][c.id]["ways"]["thirds"], ["end"])
        self.assertEqual(rows(a)[b.id][a.id]["ways"]["thirds"], ["middle"])
        self.assertEqual(ways.ways(c.settings, b.id)["parts"], ["start"])
        self.assertEqual(ways.ways(a.settings, c.id)["parts"], ["end"])
        self.assertEqual(ways.ways(b.settings, a.id)["parts"], ["middle"])

    def test_a_burst_of_edits_from_four_machines_settles(self):
        desks = self.build("ABCD")
        self.arrange(desks[0], desks[1:])
        self.turn_on(desks[0])
        for round_ in range(3):
            for number, editor in enumerate(desks):
                target = desks[(number + 1 + round_) % 4]
                peer = desks[(number + 2 + round_) % 4]
                if target is peer or target is editor:
                    continue
                editor.shell.edit_other(target, peer, thirds=[["start"], ["middle"], ["end"]][round_])
        self.settle("burst")
        self.assert_converged()
        self.assert_agree()


class Chains(Mesh):
    def test_b_edits_a_towards_c_while_b_is_not_paired_with_c(self):
        a, b, c = self.build("ABC", pairs=["AB", "AC"])
        self.place(a, b, "right")
        self.place(a, c, "left")
        self.settle("placed")
        self.turn_on(b)
        self.assertEqual(rows(c)[b.id], own_row(b), "B's seed reached C through A")
        self.assertTrue(b.shell.edit_other(a, c, thirds=["end"], edge=True)["accepted"])
        self.settle("edit")
        self.assert_converged()
        self.assertEqual(ways.ways(a.settings, c.id)["parts"], ["end"], "A applies it: it is paired with C")
        self.assertEqual(rows(c)[a.id][c.id]["ways"]["thirds"], ["end"])
        self.assertEqual(desk_state(a)["status"][a.id]["value"]["waiting"], [])
        self.assertEqual(profiles.machine_line(b.settings, a.id, linked=True, caps={"profiles"},
                                               last_heard=None), "Uses the desk's ways")
        self.assertIsNone(b.peer(c))

    def test_a_waits_for_a_machine_it_is_not_paired_with(self):
        a, b, c = self.build("ABC", pairs=["AB", "BC"])
        self.place(b, a, "left")
        self.place(b, c, "right")
        self.settle("placed")
        self.turn_on(b)
        live_before = live(a)
        self.assertTrue(b.shell.edit_other(a, c, thirds=["end"], edge=True)["accepted"])
        self.settle("edit")
        self.assert_converged()
        self.assertEqual(live(a), live_before, "nothing to apply to a machine it does not have")
        self.assertEqual(rows(c)[a.id][c.id]["ways"]["thirds"], ["end"])
        self.assertEqual(desk_state(b)["status"][a.id]["value"]["waiting"], [c.id])
        line = profiles.machine_line(b.settings, a.id, linked=True, caps={"profiles"}, last_heard=None)
        self.assertTrue(line.startswith("Needs pairing with"), line)
        self.assertEqual(desk_state(b)["status"][b.id]["value"]["waiting"], [])
        self.assertIsNone(a.peer(c))

    def test_a_chain_of_four_syncs_end_to_end(self):
        a, b, c, d = self.build("ABCD", pairs=["AB", "BC", "CD"])
        self.turn_on(a)
        self.assert_converged("on")
        self.assertTrue(d.shell.edit_other(a, b, thirds=["middle"])["accepted"])
        self.settle("edit")
        self.assert_converged()
        self.assertEqual(ways.ways(a.settings, b.id)["parts"], ["middle"])


class Offline(Mesh):
    def test_a_machine_offline_takes_the_edit_when_it_comes_back(self):
        a, b, c = self.build("ABC")
        self.arrange(a, [b, c])
        self.turn_on(a)
        previous = own_row(c)
        held = live(c)
        self.unlink(c)
        self.assertTrue(a.shell.edit_other(c, b, thirds=["end"], edge=True)["accepted"])
        self.settle("a edits")
        self.assertTrue(b.shell.edit_other(c, a, thirds=["start"], edge=True)["accepted"])
        self.settle("offline")
        self.assertEqual(live(c), held, "C has heard nothing")
        self.assertEqual(rows(a)[c.id], rows(b)[c.id])
        self.assertNotEqual(rows(a)[c.id], rows(c)[c.id])
        self.relink(c)
        self.settle("back")
        self.assert_converged()
        self.assertEqual(ways.ways(c.settings, a.id)["parts"], ["start"])
        self.assertEqual(ways.ways(c.settings, b.id)["parts"], ["end"])
        self.assertEqual(own_row(c), previous, "its own row never moved")
        self.assertTrue(archived(c, previous))
        self.assert_agree()

    def test_edits_made_on_both_sides_of_the_gap_converge_to_the_newer(self):
        a, b, c = self.build("ABC")
        self.arrange(a, [b, c])
        self.turn_on(a)
        self.unlink(c)
        a.shell.edit_other(c, b, thirds=["end"])
        self.settle("away")
        time.sleep(1.1)
        c.shell.edit(b, ["part"], parts=["start"])
        self.settle("c edits itself")
        self.relink(c)
        self.settle("back")
        self.assert_converged()
        self.assertEqual(rows(a)[c.id][b.id]["ways"]["thirds"], ["start"], "the later edit wins whoever made it")
        self.assertEqual(ways.ways(c.settings, b.id)["parts"], ["start"])

    def test_the_offline_machine_catches_up_on_a_new_profile_too(self):
        a, b, c = self.build("ABC")
        self.turn_on(a)
        self.unlink(c)
        pid = self.make_profile(a, "Sofa")
        a.shell.switch_profile(pid)
        self.settle("switched")
        self.relink(c)
        self.settle("back")
        self.assert_converged()
        self.assertEqual(c.settings["crossing_desk"]["active"]["value"], pid)
        self.assert_agree()


class ClockSkew(Mesh):
    def test_a_minute_either_way_changes_nothing_that_matters(self):
        a, b, c = self.build("ABC")
        a.shell.skew, b.shell.skew, c.shell.skew = 60, 0, -60
        self.arrange(a, [b, c])
        before = zones([a, b, c])
        self.turn_on(a)
        self.assertEqual(zones([a, b, c]), before)
        # The machine 120 s behind the one that switched on: its edit still beats every seed.
        self.assertTrue(c.shell.edit_other(b, a, thirds=["end"], edge=True)["accepted"])
        self.settle("behind edits")
        self.assert_converged()
        self.assertEqual(ways.ways(b.settings, a.id)["parts"], ["end"])
        for first, second in ((a, c), (c, a)):
            second_choice = ["start"] if first is a else ["middle"]
            first.shell.edit_other(b, a, thirds=["start"])
            self.settle(f"{first.name} then {second.name}")
            second.shell.edit_other(b, a, thirds=second_choice)
            self.settle(f"{second.name} after {first.name}")
            self.assert_converged()
            self.assertEqual(ways.ways(b.settings, a.id)["parts"], second_choice,
                             f"{second.name}'s edit came after {first.name}'s and wins whatever the clocks say")
        self.assert_agree()

    def test_concurrent_edits_a_minute_apart_go_to_the_later_clock_everywhere(self):
        a, b, c = self.build("ABC")
        a.shell.skew, c.shell.skew = -60, 60
        self.arrange(a, [b, c])
        self.turn_on(b)
        a.shell.edit_other(b, c, thirds=["start"])
        c.shell.edit_other(b, a, thirds=["end"])
        self.settle("concurrent")
        self.assert_converged()
        self.assertEqual(rows(a)[b.id][a.id]["ways"]["thirds"], ["end"])
        self.assertEqual(desk_state(a)["profiles"][DESK]["rows"][b.id]["by"], c.id)


class PlainMiddle(Mesh):
    def test_a_machine_without_profiles_relays_nothing_and_is_unaffected(self):
        a, m, c = self.build("ABC", pairs=["AB", "BC"], plain=("B",))
        self.place(m, a, "left")
        self.place(m, c, "right")
        self.settle("placed")
        self.assert_agree()
        picture = copy.deepcopy(m.settings["layout"])
        m_before = copy.deepcopy(m.settings)
        a.shell.same_ways(True)
        self.settle("on")
        a.shell.edit_other(c, a, thirds=["end"])
        self.settle("edit")
        self.assertEqual(desk_state(c)["on"]["value"], False, "the desk did not cross a machine without profiles")
        self.assertNotIn("crossing_desk", m.settings)
        self.assertNotIn("crossing_own", m.settings)
        self.assertEqual(m.settings, m_before)
        self.assertFalse([f for f in a.shell.frames if f["desk"] and f["peer"] == m.id])
        self.assertFalse([f for f in m.shell.frames if f["desk"]])
        self.assertEqual(m.settings["layout"], picture)
        self.assertIs(self.net.push(a, "right"), m, "layout and crossing carry on across it")
        self.net.shortcut(a)
        self.assert_agree()

    def test_with_a_direct_link_the_desk_still_syncs_and_the_plain_machine_is_untouched(self):
        a, m, c = self.build("ABC", plain=("B",))
        self.place(a, m, "right")
        self.place(a, c, "left")
        self.settle("placed")
        m_before = copy.deepcopy(m.settings)
        a.shell.same_ways(True)
        a.shell.edit_other(c, a, thirds=["end"])
        self.settle("edit")
        self.assert_converged()
        self.assertEqual(ways.ways(c.settings, a.id)["parts"], ["end"])
        self.assertEqual(m.settings, m_before)
        self.assertEqual(m.shell.refused_desks, [])
        self.assert_agree()


class Override(Mesh):
    def test_override_holds_b_until_it_turns_it_off(self):
        a, b, c = self.build("ABC")
        self.arrange(a, [b, c])
        self.turn_on(a)
        own = own_row(b)
        held, held_zones = live(b), copy.deepcopy(b.settings["zones"])
        self.assertTrue(b.shell.own_ways(True)["accepted"])
        self.settle("override")
        self.assertEqual(b.settings["zones"], held_zones)
        self.assertTrue(a.shell.edit_other(b, a, thirds=["end"], edge=True)["accepted"])
        self.assertTrue(c.shell.edit_other(b, c, thirds=["middle"], edge=True)["accepted"])
        self.settle("edits")
        self.assert_converged()
        self.assertEqual(live(b), held, "B's crossing did not move")
        self.assertEqual(b.settings["zones"], held_zones)
        self.assertEqual(own_row(b), own)
        self.assertEqual(rows(b)[b.id][a.id]["ways"]["thirds"], ["end"], "the desk row took the edit")
        self.assertEqual(profiles.in_force(b.settings)[1], False)
        a.shell.own_ways(False)
        self.settle("a's own page")
        self.assertTrue(b.settings["crossing_own"]["use_own"], "no message turns B's override off")
        self.assertTrue(b.shell.own_ways(False)["accepted"])
        self.settle("override off")
        self.assertEqual(ways.ways(b.settings, a.id)["parts"], ["end"])
        self.assertEqual(ways.ways(b.settings, c.id)["parts"], ["middle"])
        self.assertEqual(own_row(b), own, "its own row is still what it was")
        self.assert_agree()

    def test_sharing_mine_sends_the_own_row_to_the_desk(self):
        a, b = self.build("AB")
        self.place(a, b, "right")
        self.settle("placed")
        self.turn_on(a)
        b.shell.own_ways(True)
        b.shell.edit(a, ["part"], parts=["start"])
        self.settle("own edit")
        self.assertNotEqual(rows(a)[b.id], own_row(b))
        out = crossing_state.share_mine(b.shell.current(), platform=b.shell.platform, now=b.shell.now())
        b.shell.carry_out(out)
        self.settle("shared")
        self.assert_converged()
        self.assertEqual(rows(a)[b.id], own_row(b))
        self.assertEqual(rows(a)[b.id][a.id]["ways"]["thirds"], ["start"])


class OffAndOn(Mesh):
    def test_off_then_on_moves_nobodys_zones(self):
        a, b, c = self.build("ABC")
        self.arrange(a, [b, c])
        self.turn_on(a)
        a.shell.edit_other(c, a, thirds=["end"], edge=True)
        b.shell.edit_other(a, b, thirds=["middle"], edge=True)
        self.settle("edits")
        desks = [a, b, c]
        before = zones(desks)
        before_live = {d.name: live(d) for d in desks}
        rows_before = copy.deepcopy(rows(a))
        self.assertTrue(b.shell.same_ways(False)["accepted"])
        self.settle("off")
        self.assertEqual(zones(desks), before)
        for desk in desks:
            self.assertFalse(profiles.same_ways_on(desk.settings))
            self.assertEqual(live(desk), before_live[desk.name])
            self.assertEqual(own_row(desk), rows_before[desk.id], f"{desk.name} keeps what it crossed by as its own")
        self.assertTrue(a.shell.same_ways(True)["accepted"])
        self.settle("on again")
        self.assert_converged()
        self.assertEqual(zones(desks), before)
        for desk in desks:
            self.assertEqual(live(desk), before_live[desk.name])
            self.assertEqual(rows(desk)[desk.id], rows_before[desk.id])
        self.assert_agree()


class Switching(Mesh):
    def test_a_switch_carries_the_picture_and_a_switch_back_restores_it(self):
        a, b, c = self.build("ABC")
        self.place(a, b, "right")
        self.place(a, c, "left")
        self.settle("placed")
        self.turn_on(a)
        desk_picture = {d.name: copy.deepcopy(d.settings["layout"]) for d in (a, b, c)}
        sofa = self.make_profile(a, "Sofa")
        self.assert_converged()
        self.assertEqual(rows(b, sofa), rows(b), "a new profile starts from the active one's rows")
        a.shell.switch_profile(sofa)
        self.settle("to Sofa")
        self.assertTrue(all(d.settings["crossing_desk"]["active"]["value"] == sofa for d in (a, b, c)))
        self.place(a, c, "bottom")
        self.settle("moved in Sofa")
        sofa_picture = copy.deepcopy(a.settings["layout"])
        self.assertNotEqual(spot(sofa_picture[c.id]), spot(desk_picture["A"][c.id]))
        self.assert_agree("sofa")
        b.shell.switch_profile(DESK)
        self.settle("back to Desk")
        self.assert_converged()
        self.assert_agree("desk")
        for d in (a, b, c):
            self.assertEqual(spot(d.settings["layout"][c.id]), spot(desk_picture["A"][c.id]), d.name)
        a.shell.switch_profile(sofa)
        self.settle("to Sofa again")
        self.assert_agree("sofa again")
        self.assertEqual(spot(c.settings["layout"][c.id]), spot(sofa_picture[c.id]))

    def test_a_drop_in_flight_during_a_switch_converges(self):
        a, b, c = self.build("ABC")
        self.place(a, b, "right")
        self.place(a, c, "left")
        self.settle("placed")
        self.turn_on(a)
        sofa = self.make_profile(a, "Sofa")
        own = b.settings["layout"][b.id]
        a.shell.switch_profile(sofa)
        b.shell.drop(c, own["x"], own["y"] + own["h"])
        c.shell.edit_other(a, b, thirds=["end"])
        self.settle("racing")
        self.assert_converged()
        self.assert_agree()
        self.assertEqual({d.settings["crossing_desk"]["active"]["value"] for d in (a, b, c)}, {sofa})
        self.assertEqual(len({tuple(sorted((k, v["x"], v["y"]) for k, v in d.settings["layout"].items()))
                              for d in (a, b, c)}), 1, "one picture everywhere")
        a.shell.switch_profile(DESK)
        self.settle("home")
        self.assert_converged()
        self.assert_agree()

    def test_a_removed_profile_stays_removed_for_the_machine_that_was_away(self):
        a, b, c = self.build("ABC")
        self.turn_on(a)
        sofa = self.make_profile(a, "Sofa")
        self.unlink(c)
        a.shell.switch_profile(sofa)
        a.shell.switch_profile(DESK)
        out = crossing_state.remove_profile(a.shell.current(), sofa, platform="mac", now=a.shell.now())
        self.assertTrue(out["accepted"])
        a.shell.carry_out(out)
        self.settle("removed")
        self.relink(c)
        self.settle("back")
        self.assert_converged()
        self.assertIsNotNone(c.settings["crossing_desk"]["profiles"][sofa]["removed"])

class Refusal(Mesh):
    def test_a_desk_from_a_peer_that_may_not_drive_is_refused(self):
        a, b = self.build("AB")
        self.place(a, b, "right")
        self.settle("placed")
        settings = copy.deepcopy(b.settings)
        settings["peers"][0]["allow_drive"] = False
        b.save(settings)
        held = copy.deepcopy(b.settings)
        a.shell.same_ways(True)
        a.shell.edit_other(b, a, thirds=["end"])
        self.settle("sent")
        self.assertTrue(b.shell.refused_desks)
        self.assertEqual({reason for _, reason in b.shell.refused_desks}, {"untrusted"})
        self.assertEqual(b.settings["crossing_desk"], held["crossing_desk"])
        self.assertEqual(b.settings["zones"], held["zones"])
        self.assertEqual(b.settings["peers"], held["peers"])
        self.assertTrue(profiles.same_ways_on(a.settings))

    def test_what_a_trusted_peer_relays_is_taken_whoever_made_it(self):
        a, b, c = self.build("ABC")
        self.arrange(a, [b, c])
        settings = copy.deepcopy(b.settings)
        for item in settings["peers"]:
            if item["id"] == a.id:
                item["allow_drive"] = False
        b.save(settings)
        a.shell.same_ways(True)
        self.settle("on")
        self.assertTrue(profiles.same_ways_on(b.settings), "C relayed it")
        self.assertIn((a.id, "untrusted"), b.shell.refused_desks)
        a.shell.edit_other(b, c, thirds=["end"])
        self.settle("edit")
        self.assertEqual(ways.ways(b.settings, c.id)["parts"], ["end"])


class TileResizeConvergence(Mesh):
    def test_resizing_one_tile_converges_and_crosses_into_its_matching_span(self):
        a, b, c = self.build("ABC")
        self.place(a, b, "top")
        self.place(a, c, "left")
        self.settle("clear resize area")
        own = a.settings["layout"][a.id]
        tiles = copy.deepcopy(a.settings["layout"])
        resized = ways.resize_tile(tiles[b.id], 320)
        resized.update(x=own["x"] + own["w"], y=own["y"] + own["h"] - resized["h"])
        tiles[b.id] = resized
        with a.shell.lock:
            outcome = crossing_state.drop(a.shell.current(), tiles, b.id,
                capable=a.shell.capable(), snap_radius=0, **a.shell._args())
            self.assertTrue(outcome["accepted"])
            a.shell.carry_out(outcome)
        self.settle("resized")
        self.assert_agree("resized")
        for desk in (a, b, c):
            self.assertEqual((desk.settings["layout"][b.id]["w"],
                              desk.settings["layout"][b.id]["h"]), (320, 200), desk.name)
        edge = next(zone for zone in a.settings["zones"]
                    if zone["peer"] == b.id and zone["kind"] == "edge")
        self.assertEqual(edge["target_span"], [0.5, 1.0])
        self.assertIs(self.net.push(a, "right", 0.75), b)
        landed = b.screen.placed[-1]
        self.assertGreater(landed[1], b.screen.displays["0"].y + b.screen.displays["0"].height / 2)


if __name__ == "__main__":
    unittest.main()
