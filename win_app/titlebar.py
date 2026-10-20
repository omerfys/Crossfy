"""Beamer's native title-bar colouring on Windows 11.

Windows paints the ACTIVE window's native caption in the user's accent colour when "Show accent
colour on title bars and window borders" is on (HKCU\\Software\\Microsoft\\Windows\\DWM
ColorPrevalence). DWMWA_USE_IMMERSIVE_DARK_MODE only toggles which of the two system caption themes
is used — it does not opt out of that accent paint, so a window can look right unfocused and turn
accent-coloured the moment it gains focus. DWMWA_CAPTION_COLOR and its neighbours (Windows 11
22H2+) are the documented opt-out.
"""

from __future__ import annotations

import sys

DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_COLOR_NONE = 0xFFFFFFFE


def _colorref(hex_colour: str) -> int:
    """"#RRGGBB" -> COLORREF (0x00BBGGRR), the byte order DWM's colour attributes expect."""
    value = hex_colour.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return (b << 16) | (g << 8) | r


def apply_caption(hwnd: int, palette: dict, dark: bool = True) -> None:
    """Paints hwnd's native title bar with Vernier's ground, ink and rule from `palette`
    (theme.P), replacing the Windows accent colour, and toggles the native caption theme so the
    caption buttons' glyphs follow. Cosmetic only: any failure (older Windows, missing dwmapi, a
    bad hwnd) is swallowed so the caller's window still opens."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        dwmapi = ctypes.windll.dwmapi
        dark_mode = ctypes.c_int(1 if dark else 0)
        for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, 19):  # 19 is the pre-20H1 alias
            if dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)) == 0:
                break
        caption = ctypes.c_int(_colorref(palette["ground"]))
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(caption), ctypes.sizeof(caption))
        text = ctypes.c_int(_colorref(palette["ink_2"]))
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ctypes.byref(text), ctypes.sizeof(text))
        border = ctypes.c_int(_colorref(palette["rule"]))
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border), ctypes.sizeof(border))
    except Exception:
        pass
