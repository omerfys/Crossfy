"""The detector's first stroke length for each PC capture back end."""

from core.shake import STROKE_WINDOWS, STROKE_WAYLAND, STROKE_X11, stroke_at_sensitivity


def shake_stroke(backend, sensitivity=100):
    name = getattr(backend, "__name__", backend)
    lengths = {
        "capture_win": STROKE_WINDOWS,
        "capture_x11": STROKE_X11,
        "capture_portal": STROKE_WAYLAND,
    }
    try:
        return stroke_at_sensitivity(lengths[name], sensitivity)
    except KeyError as exc:
        raise ValueError(f"unknown capture back end: {name}") from exc
