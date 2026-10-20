"""Internal X11 seam geometry and pressure without requiring an X server."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import x11_seams  # noqa: E402
from core.return_edge import CornerPush, PartEdge, Rect, ReturnEdge  # noqa: E402


class FakeBackend:
    def __init__(self):
        self.created = []
        self.destroyed = []

    def create_barrier(self, seam):
        self.created.append(seam)
        return len(self.created) + 100

    def destroy_barrier(self, barrier):
        self.destroyed.append(barrier)

class SeamGeometryTest(unittest.TestCase):
    def test_only_shared_monitor_edge_segments_are_returned(self):
        found = x11_seams.seams([
            Rect(-1280, 100, 1280, 1024),
            Rect(0, 0, 1920, 1080),
            Rect(1920, 400, 1280, 800),
        ])
        self.assertEqual([seam.key for seam in found], [
            (0, 100, 0, 1079),
            (1920, 400, 1920, 1079),
        ])

    def test_diagonal_and_gapped_displays_have_no_seam(self):
        self.assertEqual(x11_seams.seams([Rect(0, 0, 100, 100), Rect(100, 101, 100, 100)]), [])
        self.assertEqual(x11_seams.seams([Rect(0, 0, 100, 100), Rect(101, 0, 100, 100)]), [])

    def test_only_armed_display_side_creates_an_internal_seam(self):
        monitors = [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)]
        display_map = {"0": monitors[0], "1": monitors[1]}
        model = ReturnEdge("right", display="0")

        found = x11_seams.armed_seams(monitors, display_map, [model])

        self.assertEqual([seam.key for seam in found], [(100, 0, 100, 99)])
        self.assertEqual(found[0].directions, x11_seams.BARRIER_NEGATIVE_X)

    def test_reverse_zone_uses_the_opposite_barrier_direction(self):
        monitors = [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)]
        display_map = {"0": monitors[0], "1": monitors[1]}

        found = x11_seams.armed_seams(monitors, display_map,
                                      [ReturnEdge("left", display="1")])

        self.assertEqual(found[0].directions, x11_seams.BARRIER_POSITIVE_X)

    def test_opposing_armed_zones_block_both_directions_on_shared_stretch(self):
        monitors = [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)]
        display_map = {"0": monitors[0], "1": monitors[1]}
        models = [ReturnEdge("right", display="0"), ReturnEdge("left", display="1")]

        found = x11_seams.armed_seams(monitors, display_map, models)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].directions, 0)

    def test_part_edge_creates_only_its_selected_third(self):
        monitors = [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)]
        display_map = {"0": monitors[0], "1": monitors[1]}
        model = PartEdge("right", {"middle"}, display="0")

        found = x11_seams.armed_seams(monitors, display_map, [model])

        self.assertEqual([seam.key for seam in found], [(100, 34, 100, 66)])

    def test_disjoint_selected_thirds_leave_the_middle_open(self):
        monitors = [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)]
        display_map = {"0": monitors[0], "1": monitors[1]}
        model = PartEdge("right", {"start", "end"}, display="0")

        found = x11_seams.armed_seams(monitors, display_map, [model])

        self.assertEqual([seam.key for seam in found], [(100, 0, 100, 33), (100, 67, 100, 99)])

    def test_corner_push_creates_only_its_corner_stretch(self):
        monitors = [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)]
        display_map = {"0": monitors[0], "1": monitors[1]}
        model = CornerPush("top_right", "right", display="0")

        found = x11_seams.armed_seams(monitors, display_map, [model])

        self.assertEqual([seam.key for seam in found], [(100, 0, 100, 8)])

    def test_unarmed_or_unmapped_zones_do_not_block_local_monitor_movement(self):
        monitors = [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)]
        self.assertEqual(x11_seams.armed_seams(monitors, {"0": monitors[0]}, []), [])
        self.assertEqual(x11_seams.armed_seams(monitors, {}, [ReturnEdge("right", display="0")]), [])

        disarmed = ReturnEdge("right", display="0")
        disarmed.armed = False
        self.assertEqual(x11_seams.armed_seams(monitors, {"0": monitors[0], "1": monitors[1]},
                                                [disarmed]), [])


class SeamControllerTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.controller = x11_seams.Controller(self.backend)
        self.monitors = [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)]
        self.display_map = {"0": self.monitors[0], "1": self.monitors[1]}
        self.model = ReturnEdge("right", display="0")

    def configure_active(self, resistance=30, enabled=True):
        self.controller.configure(self.monitors, resistance, enabled,
                                  display_map=self.display_map, models=[self.model])

    def test_unselected_internal_seam_has_no_barrier(self):
        self.controller.configure(self.monitors, 30, enabled=True)

        self.assertEqual(self.backend.created, [],
                         "X11 seam holds gap: barriers must follow an armed per-display zone")


    def test_disabled_state_removes_all_barriers_and_zero_resistance_creates_none(self):
        self.configure_active()
        self.controller.configure(self.monitors, 30, enabled=False,
                                  display_map=self.display_map, models=[self.model])
        self.assertEqual(self.backend.destroyed, [101])
        self.controller.configure(self.monitors, 0, display_map=self.display_map, models=[self.model])
        self.assertEqual(len(self.backend.created), 1)

    def test_zone_change_rebuilds_only_armed_barriers_and_empty_zones_release_them(self):
        self.controller.configure(self.monitors, 30, display_map=self.display_map,
                                  models=[PartEdge("right", {"middle"}, display="0")])
        self.assertEqual([seam.key for seam in self.backend.created], [(100, 34, 100, 66)])

        self.controller.configure(self.monitors, 30, display_map=self.display_map, models=[])

        self.assertEqual(self.backend.destroyed, [101])
        self.assertFalse(self.controller.active)

    def test_direction_change_rebuilds_barrier(self):
        self.configure_active()
        self.model = ReturnEdge("left", display="1")

        self.configure_active()

        self.assertEqual(self.backend.destroyed, [101])
        self.assertEqual(self.backend.created[-1].directions, x11_seams.BARRIER_POSITIVE_X)


class XlibBackendProtocolTest(unittest.TestCase):
    def test_create_pointer_barrier_wire_format_has_pad(self):
        try:
            import Xlib  # noqa: F401
        except ImportError:
            self.skipTest("python-xlib not installed")

        create_cls, _ = x11_seams._request_classes()
        field_types = [type(f).__name__ for f in create_cls._request.fields]
        field_names = [f.name for f in create_cls._request.fields]
        dirs_idx = field_names.index("directions")
        self.assertIn("Pad", field_types[dirs_idx:],
                      "CreatePointerBarrier wire format must include Pad(2) between directions and num_devices")

    def test_create_barrier_applies_to_all_devices(self):
        try:
            from Xlib import display
        except ImportError:
            self.skipTest("python-xlib not installed")

        recorded = []
        class MockProtocol:
            def allocate_resource_id(self):
                return 42
            def get_extension_major(self, name):
                return 138

        class MockDisplay:
            display = MockProtocol()

        class MockRoot:
            id = 999

        backend = x11_seams.XlibBackend(MockDisplay(), MockRoot())
        def mock_create(**kwargs):
            recorded.append(kwargs)
        backend._create = mock_create

        seam = x11_seams.Seam(100, 0, 100, 100, "x", directions=0)
        barrier = backend.create_barrier(seam)
        self.assertEqual(barrier, 42)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["devices"], [],
                         "Global pointer barrier must specify empty devices list (num_devices=0)")


if __name__ == "__main__":
    unittest.main()
