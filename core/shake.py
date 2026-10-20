"""Clock-free shake-to-come-home detection for relative mouse motion."""

from collections import deque


# Capture units differ by backend and device; these are hardware-tuned starting values, not inches.
STROKE_MAC = 48.0
STROKE_WINDOWS = 192.0
STROKE_X11 = 192.0
STROKE_WAYLAND = 48.0


def stroke_at_sensitivity(stroke, sensitivity):
    """Scale the capture backend's stroke length by the shared 50–200% preference."""
    return float(stroke) * 100 / int(sensitivity)

_WINDOW = 0.650
_PAUSE = 0.120
_ARM_DELAY = 0.300
_SCROLL_QUIET = 0.250
_REFRACTORY = 1.500
_TURN_FRACTION = 0.25
_EPSILON = 1e-9


class ShakeDetector:
    def __init__(self, stroke=48.0):
        self.stroke = float(stroke)
        self._armed_at = None
        self._cooldown_until = 0.0
        self._scroll_until = 0.0
        self._held = False
        self._events = deque()
        self.reset()

    def arm(self, t):
        # The 1.5 s after a shake still holds: crossing straight back out must not re-arm it early.
        self._armed_at = float(t) + _ARM_DELAY
        self._held = False
        self._scroll_until = 0.0
        self.reset()

    def set_stroke(self, stroke):
        stroke = float(stroke)
        if stroke != self.stroke:
            self.stroke = stroke
            self.reset()

    def disarm(self):
        self._armed_at = None
        self._held = False
        self.reset()

    def reset(self):
        self._events.clear()
        self._samples = []
        self._axis = None
        self._position = 0.0
        self._cross = 0.0
        self._event_count = 0
        self._direction = 0
        self._anchor = None
        self._extreme = None
        self._reverse = 0.0
        self._strokes = deque()
        self._last_t = None

    def scroll(self, t):
        self.reset()
        self._scroll_until = float(t) + _SCROLL_QUIET

    def held(self, t, anything_held):
        self.reset()
        self._held = bool(anything_held)

    def motion(self, t, dx, dy):
        t, dx, dy = float(t), float(dx), float(dy)
        if self._armed_at is None or self._held:
            return False
        if t < self._armed_at or t < self._cooldown_until or t < self._scroll_until:
            self.reset()
            return False
        if self._last_t is not None and t - self._last_t >= _PAUSE:
            self.reset()
        self._last_t = t
        if dx == 0 and dy == 0:
            return False

        self._events.append((t, dx, dy))
        while self._events and t - self._events[0][0] > _WINDOW:
            self._events.popleft()
        x_travel = sum(abs(event[1]) for event in self._events)
        y_travel = sum(abs(event[2]) for event in self._events)
        axis = 0 if x_travel >= y_travel else 1
        if self._axis is not None and axis != self._axis:
            self.reset()
            self._events.append((t, dx, dy))
            axis = 0 if abs(dx) >= abs(dy) else 1
        if self._axis is None:
            self._axis = axis

        along = dx if self._axis == 0 else dy
        across = dy if self._axis == 0 else dx
        if not self._samples:
            self._samples.append((t, self._position, self._cross, self._event_count))
        self._position += along
        self._cross += abs(across)
        self._event_count += 1
        self._samples.append((t, self._position, self._cross, self._event_count))

        if self._direction == 0:
            if along:
                self._direction = 1 if along > 0 else -1
                self._anchor = 0
                self._extreme = 1
            return False

        if self._direction * (self._position - self._samples[self._extreme][1]) > 0:
            self._extreme = len(self._samples) - 1
            self._reverse = 0.0
        else:
            self._reverse = max(
                0.0,
                -self._direction * (self._position - self._samples[self._extreme][1]),
            )

        if self._reverse < self.stroke * _TURN_FRACTION:
            return False

        extreme = self._samples[self._extreme]
        anchor = self._samples[self._anchor]
        stroke_events = max(0, extreme[3] - anchor[3])
        stroke = {
            "start": anchor[1],
            "start_t": anchor[0],
            "end": extreme[1],
            "distance": abs(extreme[1] - anchor[1]),
            "duration": max(0.0, extreme[0] - anchor[0]),
            "events": stroke_events,
            "cross": max(0.0, extreme[2] - anchor[2]),
            "turn_t": t,
        }
        self._strokes.append(stroke)
        while self._strokes and t - self._strokes[0]["start_t"] > _WINDOW:
            self._strokes.popleft()

        fired = self._qualifies()
        self._anchor = self._extreme
        self._direction *= -1
        self._reverse = 0.0
        self._extreme = self._anchor
        self._samples = self._samples[self._anchor:]
        self._anchor = 0
        self._extreme = 0
        if fired:
            self._cooldown_until = t + _REFRACTORY
            self.reset()
            self._last_t = t
            return True
        return False

    def _qualifies(self):
        if len(self._strokes) < 4:
            return False
        strokes = list(self._strokes)[-4:]
        if any(
            s["distance"] + _EPSILON < self.stroke
            or not 0.030 - _EPSILON <= s["duration"] <= 0.200 + _EPSILON
            or s["events"] < 2
            or s["distance"] / s["duration"] + _EPSILON < 6 * self.stroke
            for s in strokes
        ):
            return False
        total = sum(s["distance"] for s in strokes)
        if total + _EPSILON < 5 * self.stroke:
            return False
        if abs(strokes[-1]["end"] - strokes[0]["start"]) > 2 * self.stroke + _EPSILON:
            return False
        if sum(s["cross"] for s in strokes) > total / 2 + _EPSILON:
            return False
        return True


class HomeHold:
    def __init__(self):
        self._last_motion = None

    def motion(self, t):
        self._last_motion = float(t)

    def blocks(self, t):
        return self._last_motion is not None and float(t) < self._last_motion + 0.200
