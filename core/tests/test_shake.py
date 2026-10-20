import math
import random
import unittest

from core.shake import (HomeHold, ShakeDetector, STROKE_MAC, STROKE_WINDOWS, STROKE_X11,
                        STROKE_WAYLAND, stroke_at_sensitivity)


def trace(strokes, rate=125, axis="x", start=0.0, jitter=0.0, noise=0.0, seed=17):
    """Make constant-speed strokes, preserving each stroke's requested duration."""
    rng = random.Random(seed)
    result = []
    t = start
    last_event_t = start - 0.000001
    for direction, distance, duration in strokes:
        count = max(2, round(duration * rate) + 1)
        for i in range(1, count + 1):
            ideal = duration * (i - 1) / (count - 1)
            dt = ideal + (rng.uniform(-jitter, jitter) if jitter else 0.0)
            along = direction * distance / count
            cross_step = rng.uniform(-noise, noise) if noise else 0.0
            if axis == "x":
                dx, dy = along, cross_step
            else:
                dx, dy = cross_step, along
            event_t = max(last_event_t + 0.000001, t + dt)
            result.append((event_t, dx, dy))
            last_event_t = event_t
        t += duration
        if jitter:
            t += rng.uniform(-jitter, jitter)
    return result


def qualifying_strokes(length=64.0, duration=0.1, direction=1):
    return [(direction if i % 2 == 0 else -direction, length, duration) for i in range(4)]


def qualifying_trace(rate=125, axis="x", direction=1, start=0.31, **kwargs):
    strokes = qualifying_strokes(direction=direction)
    strokes.append((direction, 12.001, 0.02))
    return trace(strokes, rate, axis, start=start, **kwargs)


def candidate_trace(lengths, durations, rate=1000, **kwargs):
    strokes = [(1 if i % 2 == 0 else -1, length, duration)
               for i, (length, duration) in enumerate(zip(lengths, durations))]
    strokes.append((1, 12.001, 0.02))
    return trace(strokes, rate, start=0.31, **kwargs)


def run(detector, events):
    fired = []
    for t, dx, dy in events:
        if detector.motion(t, dx, dy):
            fired.append(t)
    return fired


class ShakeDetectorTests(unittest.TestCase):
    def test_changing_sensitivity_discards_partial_gesture_and_preserves_cooldown(self):
        detector = self.detector()
        events = qualifying_trace()
        run(detector, events[:30])
        detector.set_stroke(24)
        self.assertEqual(run(detector, events[30:]), [])
        self.assertEqual(len(run(detector, qualifying_trace(start=1.1))), 1)
        detector.set_stroke(48)
        self.assertEqual(run(detector, qualifying_trace(start=1.6)), [])

    def test_equal_normalised_motion_fires_at_the_same_time_on_every_backend(self):
        for stroke in (STROKE_MAC, STROKE_WINDOWS, STROKE_X11, STROKE_WAYLAND):
            for sensitivity in (50, 100, 150, 200):
                detector = self.detector(stroke_at_sensitivity(stroke, sensitivity))
                scale = stroke / 48 * 100 / sensitivity
                events = [(t, dx * scale, dy * scale) for t, dx, dy in qualifying_trace()]
                self.assertEqual(run(detector, events), [events[-1][0]])

    def test_sensitivity_scales_the_platform_stroke(self):
        self.assertEqual(stroke_at_sensitivity(STROKE_MAC, 50), 96)
        self.assertEqual(stroke_at_sensitivity(STROKE_WINDOWS, 100), STROKE_WINDOWS)
        self.assertEqual(stroke_at_sensitivity(48, 200), 24)

    def detector(self, stroke=48.0):
        detector = ShakeDetector(stroke)
        detector.arm(0.0)
        return detector

    def test_qualifying_shake_fires_once_at_fourth_turn_across_rates_axes_and_directions(self):
        for rate in (60, 125, 500, 1000):
            for axis in ("x", "y"):
                for direction in (-1, 1):
                    with self.subTest(rate=rate, axis=axis, direction=direction):
                        events = qualifying_trace(rate, axis, direction, jitter=0.001, noise=0.1)
                        fired = run(self.detector(), events)
                        self.assertEqual(len(fired), 1)
                        self.assertEqual(fired[0], events[-1][0])

    def test_three_turns_do_not_fire(self):
        events = trace(qualifying_strokes()[:3], start=0.31)
        self.assertEqual(run(self.detector(), events), [])

    def test_turn_needs_net_reverse_travel_of_a_quarter_stroke(self):
        events = trace([(1, 64, .1)], start=.31)
        t = events[-1][0]
        for _ in range(8):
            t += .01
            events.append((t, -8, 0))
            t += .01
            events.append((t, 8, 0))
        self.assertEqual(run(self.detector(), events), [])

    def test_each_stroke_needs_at_least_two_motion_events(self):
        events = [(.31, 60, 0)]
        for t, dx in ((.33, -7.5), (.35, -7.5), (.37, -15), (.39, -15), (.41, -15),
                      (.43, 7.5), (.45, 7.5), (.47, 15), (.49, 15), (.51, 15),
                      (.53, -7.5), (.55, -7.5), (.57, -15), (.59, -15), (.61, -15),
                      (.63, 7.5), (.65, 7.5)):
            events.append((t, dx, 0))
        self.assertEqual(run(self.detector(), events), [])

    def test_sweep_circle_and_single_flick_do_not_fire(self):
        sweep = trace([(1, 300.0, 0.1)], start=0.31)
        circle = []
        for i in range(81):
            angle0 = 4 * 3.141592653589793 * (i - 1) / 80
            angle1 = 4 * 3.141592653589793 * i / 80
            circle.append((.31 + i * .005,
                           10 * (math.cos(angle1) - math.cos(angle0)),
                           10 * (math.sin(angle1) - math.sin(angle0))))
        flick = trace([(1, 200, .03), (-1, 8, .03)], start=0.31)
        for events in (sweep, circle, flick):
            with self.subTest(events=len(events)):
                self.assertEqual(run(self.detector(), events), [])

    def test_slow_back_and_forth_and_fidget_below_stroke_length_do_not_fire(self):
        slow = trace([(1 if i % 2 == 0 else -1, 64, .25) for i in range(4)] + [(1, 13, .02)],
                     start=0.31)
        fidget = trace([(1 if i % 2 == 0 else -1, 40, .05) for i in range(4)] + [(1, 13, .02)],
                       start=0.31)
        self.assertEqual(run(self.detector(), slow), [])
        self.assertEqual(run(self.detector(), fidget), [])

    def test_stroke_length_threshold(self):
        lengths = [64.0] * 4
        lengths[0] = 48.001
        self.assertEqual(len(run(self.detector(), candidate_trace(lengths, [.1] * 4))), 1)
        lengths[0] = 47.999
        self.assertEqual(run(self.detector(), candidate_trace(lengths, [.1] * 4)), [])

    def test_stroke_duration_thresholds(self):
        durations = [.1] * 4
        durations[0] = .030001
        self.assertEqual(len(run(self.detector(), candidate_trace([64.0] * 4, durations))), 1)
        durations[0] = .029999
        self.assertEqual(run(self.detector(), candidate_trace([64.0] * 4, durations)), [])
        durations[0] = .200001
        self.assertEqual(run(self.detector(), candidate_trace([64.0] * 4, durations)), [])
        durations[0] = .199999
        self.assertEqual(len(run(self.detector(), candidate_trace([64.0] * 4, durations))), 1)

    def test_average_speed_threshold(self):
        lengths = [57.599, 64.0, 64.0, 64.0]
        durations = [.2, .1, .1, .1]
        self.assertEqual(run(self.detector(), candidate_trace(lengths, durations)), [])
        lengths[0] = 57.601
        self.assertEqual(len(run(self.detector(), candidate_trace(lengths, durations))), 1)

    def test_total_travel_threshold(self):
        self.assertEqual(run(self.detector(), candidate_trace([59.999] * 4, [.1] * 4)), [])
        self.assertEqual(len(run(self.detector(), candidate_trace([60.0] * 4, [.1] * 4))), 1)

    def test_endpoint_must_be_within_two_strokes_of_start(self):
        lengths = [64.0, 64.0, 64.0, 160.0]
        self.assertEqual(len(run(self.detector(), candidate_trace(lengths, [.1] * 4))), 1)
        lengths[-1] = 160.001
        self.assertEqual(run(self.detector(), candidate_trace(lengths, [.1] * 4)), [])

    def test_cross_axis_travel_must_not_exceed_half_along_travel(self):
        at_limit = trace([(1 if i % 2 == 0 else -1, 60.0, .1) for i in range(4)] + [(1, 12.001, .02)],
                         start=.31, noise=0.0)
        beyond = trace([(1 if i % 2 == 0 else -1, 60.0, .1) for i in range(4)] + [(1, 12.001, .02)],
                       start=.31, noise=0.0)
        count = len(at_limit) - 3
        at_limit = [(t, dx, (120.0 / count) * (1 if i % 2 else -1)) for i, (t, dx, _) in enumerate(at_limit)]
        beyond = [(t, dx, (120.1 / count) * (1 if i % 2 else -1)) for i, (t, dx, _) in enumerate(beyond)]
        self.assertEqual(len(run(self.detector(), at_limit)), 1)
        self.assertEqual(run(self.detector(), beyond), [])

    def test_pause_longer_than_120_ms_resets_the_gesture(self):
        first = trace(qualifying_strokes()[:2], start=.31)
        second = trace(qualifying_strokes()[2:] + [(1, 13, .02)], start=.8)
        self.assertEqual(run(self.detector(), first + second), [])

    def test_pause_threshold(self):
        for pause, expected in ((.119, 1), (.120, 0), (.121, 0)):
            first = trace([(1, 60, .03), (-1, 60, .03)], start=.31)
            second = trace([(1, 60, .03), (-1, 60, .03), (1, 12.001, .02)],
                           start=.37 + pause)
            with self.subTest(pause=pause):
                self.assertEqual(len(run(self.detector(), first + second)), expected)

    def test_650_ms_turn_window(self):
        inside = candidate_trace([60.0] * 4, [.157475] * 4)
        outside = candidate_trace([60.0] * 4, [.157525] * 4)
        self.assertEqual(len(run(self.detector(), inside)), 1)
        self.assertEqual(run(self.detector(), outside), [])

    def test_home_hold_releases_after_two_hundred_ms_quiet(self):
        hold = HomeHold()
        hold.motion(1.0)
        self.assertTrue(hold.blocks(1.199))
        self.assertFalse(hold.blocks(1.2))

    def test_home_hold_motion_refreshes_quiet_deadline(self):
        hold = HomeHold()
        hold.motion(1.0)
        hold.motion(1.15)
        self.assertTrue(hold.blocks(1.34))
        self.assertFalse(hold.blocks(1.35))

    def test_disarmed_motion_never_fires(self):
        detector = self.detector()
        detector.disarm()
        self.assertEqual(run(detector, qualifying_trace()), [])

    def test_motion_before_arm_delay_is_ignored(self):
        events = qualifying_trace(start=.1)
        self.assertEqual(run(self.detector(), events), [])
        self.assertEqual(len(run(self.detector(), qualifying_trace(start=.3))), 1)

    def test_scroll_suppresses_motion_for_250_ms(self):
        detector = self.detector()
        detector.scroll(0.31)
        self.assertEqual(run(detector, trace(qualifying_strokes(), start=0.32)), [])

    def test_scroll_quiet_boundary(self):
        detector = self.detector()
        detector.scroll(0.31)
        self.assertFalse(detector.motion(.5599, 30, 0))
        self.assertEqual(len(run(detector, qualifying_trace(start=.5601))), 1)
        detector = self.detector()
        detector.scroll(0.31)
        self.assertEqual(len(run(detector, qualifying_trace(start=.56))), 1)

    def test_held_button_or_key_resets_and_ignores_motion_until_released(self):
        detector = self.detector()
        detector.held(0.31, True)
        self.assertEqual(run(detector, qualifying_trace(start=.32)), [])
        detector.held(1.0, False)
        self.assertEqual(len(run(detector, qualifying_trace(start=1.01))), 1)

    def test_fires_no_more_than_once_until_rearmed(self):
        detector = self.detector()
        first = qualifying_trace()
        self.assertEqual(len(run(detector, first)), 1)
        second = qualifying_trace(start=0.8)
        self.assertEqual(run(detector, second), [])
        third = qualifying_trace(start=2.23)
        self.assertEqual(len(run(detector, third)), 1)

    def test_crossing_straight_back_out_keeps_the_one_and_a_half_seconds(self):
        detector = self.detector()
        fired = run(detector, qualifying_trace())
        self.assertEqual(len(fired), 1)
        detector.disarm()
        detector.arm(fired[0] + 0.05)
        self.assertEqual(run(detector, qualifying_trace(start=fired[0] + 0.4)), [])
        self.assertEqual(len(run(detector, qualifying_trace(start=fired[0] + 1.6))), 1)


if __name__ == "__main__":
    unittest.main()
