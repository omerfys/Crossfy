"""Replays a finger swipe through a synthetic Precision Touchpad so Windows'
own gesture engine recognises it and the user's Settings > Touchpad choices
decide what it does -- Task View for three fingers up, desktop switching for
four fingers sideways, with the same animation real fingers get.

Uses CreateSyntheticPointerDevice2 / InjectSyntheticPointerInput with
PT_TOUCHPAD (Windows 11; documented with a pre-release banner, present on
build 26200). Every entry point returns False rather than
raising when the API is missing or refuses, so the caller can fall back to
a keyboard shortcut. Importable on macOS for the tests: nothing touches
user32 until a swipe is asked for.
"""

import ctypes
import logging
import time

LOGGER = logging.getLogger("Beamer")

PT_TOUCHPAD = 5
POINTER_FEEDBACK_NONE = 3
SDCO_PHYSICAL_SIZE = 0x1
SDCO_TOUCHPAD_GESTURE_ONLY = 0x2
POINTER_FLAG_INRANGE = 0x2
POINTER_FLAG_INCONTACT = 0x4
POINTER_FLAG_CONFIDENCE = 0x4000
MAX_CONTACTS = 5

# A 100mm x 60mm pad in himetric (1/100 mm). Only the proportions matter:
# the gesture engine judges a swipe by distance across the pad.
PAD_WIDTH = 10000
PAD_HEIGHT = 6000
FINGER_SPACING = 1500
SWIPE_STEPS = 12
STEP_MS = 10

_DISTANCE = {
    "up": (0, -3000),
    "down": (0, 3000),
    "left": (-4000, 0),
    "right": (4000, 0),
}


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class POINTER_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerType", ctypes.c_uint32),
        ("pointerId", ctypes.c_uint32),
        ("frameId", ctypes.c_uint32),
        ("pointerFlags", ctypes.c_uint32),
        ("sourceDevice", ctypes.c_void_p),
        ("hwndTarget", ctypes.c_void_p),
        ("ptPixelLocation", _POINT),
        ("ptHimetricLocation", _POINT),
        ("ptPixelLocationRaw", _POINT),
        ("ptHimetricLocationRaw", _POINT),
        ("dwTime", ctypes.c_uint32),
        ("historyCount", ctypes.c_uint32),
        ("InputData", ctypes.c_int32),
        ("dwKeyStates", ctypes.c_uint32),
        ("PerformanceCount", ctypes.c_uint64),
        ("ButtonChangeType", ctypes.c_int32),
    ]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("touchFlags", ctypes.c_uint32),
        ("touchMask", ctypes.c_uint32),
        ("rcContact", _RECT),
        ("rcContactRaw", _RECT),
        ("orientation", ctypes.c_uint32),
        ("pressure", ctypes.c_uint32),
    ]


class POINTER_PEN_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("penFlags", ctypes.c_uint32),
        ("penMask", ctypes.c_uint32),
        ("pressure", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("tiltX", ctypes.c_int32),
        ("tiltY", ctypes.c_int32),
    ]


class _POINTER_TYPE_UNION(ctypes.Union):
    _fields_ = [("touchInfo", POINTER_TOUCH_INFO), ("penInfo", POINTER_PEN_INFO)]


class POINTER_TYPE_INFO(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_uint32), ("u", _POINTER_TYPE_UNION)]


class SYNTHETIC_DEVICE_CREATION_PARAMS(ctypes.Structure):
    _fields_ = [
        ("pointerType", ctypes.c_uint32),
        ("maxCount", ctypes.c_uint32),
        ("feedbackMode", ctypes.c_uint32),
        ("hMonitor", ctypes.c_void_p),
        ("deviceWidth", ctypes.c_uint32),
        ("deviceHeight", ctypes.c_uint32),
        ("options", ctypes.c_uint32),
    ]


_user32 = None
_device = None
_unavailable = False


def _load():
    global _user32
    if _user32 is not None:
        return _user32
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateSyntheticPointerDevice2.restype = ctypes.c_void_p
    user32.CreateSyntheticPointerDevice2.argtypes = [ctypes.POINTER(SYNTHETIC_DEVICE_CREATION_PARAMS)]
    user32.InjectSyntheticPointerInput.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(POINTER_TYPE_INFO),
        ctypes.c_uint32,
    ]
    user32.InjectSyntheticPointerInput.restype = ctypes.c_int
    _user32 = user32
    return user32


def _get_device():
    """The gesture-only device, created once. Gesture-only means its input
    can never be read as a click or a cursor move, only as a gesture."""
    global _device, _unavailable
    if _device is not None or _unavailable:
        return _device
    try:
        user32 = _load()
        params = SYNTHETIC_DEVICE_CREATION_PARAMS(
            PT_TOUCHPAD,
            MAX_CONTACTS,
            POINTER_FEEDBACK_NONE,
            None,
            PAD_WIDTH,
            PAD_HEIGHT,
            SDCO_PHYSICAL_SIZE | SDCO_TOUCHPAD_GESTURE_ONLY,
        )
        _device = user32.CreateSyntheticPointerDevice2(ctypes.byref(params))
        if not _device:
            raise OSError(ctypes.get_last_error(), "CreateSyntheticPointerDevice2 returned NULL")
    except (AttributeError, OSError) as exc:
        _unavailable = True
        LOGGER.warning("Synthetic touchpad unavailable; gestures fall back to shortcuts: %s", exc)
    return _device


def contact_frames(fingers, direction, steps=SWIPE_STEPS):
    """Pure planning: the himetric positions of each finger at each step,
    as a list of frames, each a list of (x, y). The fingers sit in a row
    across the middle of the pad and move together by the axis distance."""
    dx, dy = _DISTANCE[direction]
    row_width = FINGER_SPACING * (fingers - 1)
    start = [
        ((PAD_WIDTH - row_width) // 2 + i * FINGER_SPACING - dx // 2, PAD_HEIGHT // 2 - dy // 2)
        for i in range(fingers)
    ]
    return [
        [(x + dx * step // steps, y + dy * step // steps) for (x, y) in start]
        for step in range(steps + 1)
    ]


def swipe(fingers, direction):
    """Replay one swipe. Blocks for about SWIPE_STEPS * STEP_MS ms. Returns
    False when the device or an injection call is refused."""
    if fingers < 1 or fingers > MAX_CONTACTS or direction not in _DISTANCE:
        return False
    device = _get_device()
    if not device:
        return False
    user32 = _load()
    frames = contact_frames(fingers, direction)
    contacts = (POINTER_TYPE_INFO * fingers)()
    down_flags = POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT | POINTER_FLAG_CONFIDENCE

    def send(frame, elapsed_ms, flags):
        for index, (x, y) in enumerate(frame):
            contacts[index].type = PT_TOUCHPAD
            info = contacts[index].touchInfo.pointerInfo
            info.pointerType = PT_TOUCHPAD
            info.pointerId = index
            info.pointerFlags = flags
            info.ptHimetricLocation.x = x
            info.ptHimetricLocation.y = y
            # Every frame must carry a later time than the last, the lift included.
            info.dwTime = 1 + elapsed_ms
        if not user32.InjectSyntheticPointerInput(device, contacts, fingers):
            raise OSError(ctypes.get_last_error(), "InjectSyntheticPointerInput failed")

    try:
        for step, frame in enumerate(frames):
            if step:
                time.sleep(STEP_MS / 1000.0)
            send(frame, step * STEP_MS, down_flags)
        time.sleep(STEP_MS / 1000.0)
        send(frames[-1], (len(frames)) * STEP_MS, POINTER_FLAG_CONFIDENCE)
    except OSError as exc:
        LOGGER.warning("Touchpad swipe injection failed: %s", exc)
        return False
    return True
