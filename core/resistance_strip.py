"""Shared coordinate mapping for the Resistance strip's 0–500 pointer-delta scale."""

MAX_RESISTANCE = 500
TRACK_INSET = 18.0


def resistance_x(width: float, value: float, maximum: int = MAX_RESISTANCE,
                 inset: float = TRACK_INSET) -> float:
    """Map a raw resistance or pressure value onto the strip's shared track."""
    start = min(max(0.0, float(inset)), max(0.0, float(width)) / 2)
    end = max(start, float(width) - start)
    fraction = min(1.0, max(0.0, float(value) / maximum)) if maximum > 0 else 0.0
    return start + (end - start) * fraction
