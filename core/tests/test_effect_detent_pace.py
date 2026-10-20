import math
import unittest
from unittest import mock

from core import effects
from core.fx_instrument import detent


class InstrumentDetentPaceTests(unittest.TestCase):
    def test_pace_one_keeps_the_original_detent_values(self):
        for n, slide in ((3, 0.4), (4, 0.25), (4, 0.4), (5, 0.4)):
            for step in range(1001):
                u = step / 1000
                if u <= 0:
                    expected = 0.0
                elif u >= 1:
                    expected = 1.0
                else:
                    k = math.floor(u * n)
                    f = u * n - k
                    expected = min(1.0, (k + min(1.0, max(0.0, f / slide))) / n)
                for pace in (0.5, 1.0):
                    self.assertEqual(detent(u, n, slide, pace=pace), expected)

    def test_longer_pace_keeps_each_move_end_and_rises_monotonically(self):
        # Gauge and Rangefinder lock against the end of their last move; it must not move later.
        for n, slide in ((3, 0.4), (4, 0.25), (4, 0.4), (5, 0.4)):
            for pace in (1.5, 2.0, 2.5):
                with self.subTest(n=n, slide=slide, pace=pace):
                    for move in range(n):
                        self.assertAlmostEqual(detent((move + slide) / n, n, slide, pace=pace), (move + 1) / n)
                    values = [detent(step / 2000, n, slide, pace=pace) for step in range(2001)]
                    self.assertEqual(values, sorted(values))
                    self.assertEqual((values[0], values[-1]), (0.0, 1.0))

    def test_crossing_and_switch_previews_forward_pace_to_timed_states(self):
        fx = effects.effect("rule")
        with mock.patch.object(effects, "state", wraps=effects.state) as make_state:
            effects.preview_scene(fx, 2.4, "edge", ("#58c8f0", "#a673ec", "#f05e8a"), pace=2.5)
            effects.preview_switch_scene(fx, 0.5, ("#58c8f0", "#a673ec", "#f05e8a"), pace=2.5)
        self.assertEqual([call.kwargs["pace"] for call in make_state.call_args_list], [2.5, 2.5, 2.5])

    def test_player_instrument_frames_do_not_hold_for_more_than_fifty_ms_at_pace_2_5(self):
        for effect_id in ("rule", "gauge", "rangefinder"):
            with self.subTest(effect=effect_id):
                player = effects.Player(pace=2.5)
                player.effect_size_fraction = 0.02
                region = {"kind": "edge", "edge": "right", "x": 1199.0,
                          "y": 0.0, "w": 1.0, "h": 800.0}
                player.push(0.0, "edge", region, (1199.0, 360.0), 1.0)
                player.cross(0.0)
                player.arrive(0.0, "edge", (1.0, 360.0), "left")
                fx = effects.effect(effect_id)
                palette = effects.legible(("#58c8f0", "#a673ec", "#f05e8a"), True, fx)
                previous = None
                repeated_for = 0.0
                for frame_index in range(91):
                    now = frame_index / 60.0
                    pens = player.frames(now, fx, (1200.0, 800.0, "windows"), palette, False, True)
                    current = tuple(tuple(pen.ops) for pen in pens)
                    if current == previous:
                        repeated_for += 1.0 / 60.0
                    else:
                        repeated_for = 0.0
                    # Rangefinder's locked rest before its fade is 20ms at pace 1 and stretches with
                    # the pace by design; every detent hold stays at its pace 1 length.
                    self.assertLessEqual(repeated_for, 0.07, f"identical frame held {repeated_for:.3f}s")
                    previous = current


if __name__ == "__main__":
    unittest.main()
