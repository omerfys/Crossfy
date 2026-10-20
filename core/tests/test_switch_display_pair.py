"""A zone that knows the display it leads to but not which of its sides (or the reverse) still
crosses, and a driven machine whose switch cannot be built keeps its zones (rc12, 10-10-2026: the rig's
first push back raised "display and side go together" after disarming, and nothing crossed after)."""

import unittest
from unittest import mock

from core import protocol, receiver, return_edge
from core.return_edge import Rect
from core.tests.responder_harness import Initiator, Machine, entry, wait_for, B, HERE

MONITORS = [Rect(0, 0, 1920, 1080)]


class Outcomes(unittest.TestCase):
    def push(self, model):
        outcome = None
        for _ in range(10):
            outcome = model.feed(MONITORS, (0, 540), -40, 0, display_map={"0": MONITORS[0]})
            if outcome.action == return_edge.CROSS:
                return outcome
        self.fail(f"never crossed: {outcome}")

    def test_a_target_side_with_no_target_display_names_neither(self):
        outcome = self.push(return_edge.ReturnEdge("left", 120, display="0", target_side="right"))
        self.assertIsNone(outcome.display)
        self.assertIsNone(outcome.side)
        protocol.switch_v6(1, HERE, outcome.edge, outcome.offset, display=outcome.display, side=outcome.side)

    def test_a_target_display_brings_its_side(self):
        outcome = self.push(return_edge.ReturnEdge("left", 120, display="0", target_display="2", target_side="top"))
        self.assertEqual((outcome.display, outcome.side), ("2", "top"))
        outcome = self.push(return_edge.ReturnEdge("left", 120, display="0", target_display="2"))
        self.assertEqual((outcome.display, outcome.side), ("2", "right"))


class DrivenSwitch(unittest.TestCase):
    def setUp(self):
        grace = mock.patch.object(return_edge, "ARRIVAL_GRACE_SECONDS", 0.0)
        grace.start()
        self.addCleanup(grace.stop)

    def test_a_switch_that_cannot_name_its_display_still_goes_and_never_strands_the_zones(self):
        # A PC's report: a scoped zone with target_side and no target_display.
        machine = Machine([entry(B, "Mac", side="left")],
                          [{"peer": protocol.id_text(B), "kind": "edge", "display": "0", "side": "left",
                            "target_side": "right"}]).start()
        self.addCleanup(machine.stop)
        link = Initiator(machine)
        self.addCleanup(link.close)
        link.handshake()
        route = link.take(reach=[], resistance_px=120)
        self.assertEqual(link.answer(route)[0], protocol.MSG_ACCEPT)
        machine.desktop.cursor = (0, 540)
        for _ in range(8):
            link.move(-40, 0)
            machine.desktop.cursor = (0, 540)
        switch = link.expect(protocol.MSG_SWITCH, timeout=2.0)
        self.assertIsNotNone(switch, "the push through the edge sent no switch")
        self.assertEqual(switch["next"], protocol.id_text(B))
        self.assertNotIn("display", switch)

    def test_a_switch_that_cannot_be_built_leaves_the_zones_armed(self):
        machine = Machine([entry(B, "Mac", side="left")], [{"peer": protocol.id_text(B), "kind": "edge"}]).start()
        self.addCleanup(machine.stop)
        link = Initiator(machine)
        self.addCleanup(link.close)
        link.handshake()
        route = link.take(reach=[], resistance_px=120)
        self.assertEqual(link.answer(route)[0], protocol.MSG_ACCEPT)
        real = protocol.switch_v6
        with mock.patch.object(protocol, "switch_v6", side_effect=ValueError("broken")) as broken:
            machine.desktop.cursor = (0, 540)
            for _ in range(8):
                link.move(-40, 0)
                machine.desktop.cursor = (0, 540)
            self.assertTrue(wait_for(lambda: broken.call_count >= 1, 2.0), "the push never reached the edge")
            self.assertTrue(link.acked(link.seq), "the moves were not all taken")
        self.assertTrue(machine.responder._zones_live, "a failed switch disarmed the way out")
        with mock.patch.object(protocol, "switch_v6", real):
            for _ in range(8):
                link.move(-40, 0)
                machine.desktop.cursor = (0, 540)
            self.assertIsNotNone(link.expect(protocol.MSG_SWITCH, timeout=2.0), "the next push did not cross")


if __name__ == "__main__":
    unittest.main()
