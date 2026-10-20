import unittest

from core.return_edge import CROSS, PASS, CornerPush, Rect


class ScopedCornerTests(unittest.TestCase):
    def setUp(self):
        self.displays = {
            "a0": Rect(0, 0, 100, 100),
            "b0": Rect(100, 0, 100, 100),
            "a1": Rect(200, 0, 100, 100),
            "b1": Rect(100, 100, 100, 100),
        }
        self.monitors = list(self.displays.values())

    def test_scoped_corner_crosses_when_both_nominated_walls_are_internal(self):
        edge = CornerPush("bottom_right", "right", resistance_px=10, display="b0")
        outcome = edge.feed(self.monitors, (199, 99), 10, 10, display_map=self.displays)
        self.assertEqual((outcome.action, outcome.edge), (CROSS, "left"))

    def test_scoped_corner_box_without_wall_contact_does_not_hold(self):
        edge = CornerPush("bottom_right", "right", display="b0")
        self.assertFalse(edge._at_edge(self.monitors, (194, 94), self.displays))

    def test_unknown_nominated_display_does_not_fall_back_to_an_outer_corner(self):
        edge = CornerPush("bottom_right", "right", resistance_px=10, display="missing")
        outcome = edge.feed(self.monitors, (299, 99), 10, 10, display_map=self.displays)
        self.assertEqual(outcome.action, PASS)


if __name__ == "__main__":
    unittest.main()
