"""The tray icon: the Mac menu bar's two-screen glyph (mac_app/kvm_bridge_app.py menu_bar_glyph) in
Qt, so the taskbar and a KDE or GNOME tray show where input is the way the menu bar does.

The drive state is the glyph. The receiver's state is a badge over its lower right corner, as the
old colour mark carried: signal connected, amber waiting, fault needs attention, off stopped. A
receiver that is not running, stopped or in error, cannot be driven, so it dims the glyph.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

import theme

# The Mac's local, windows and held. "elsewhere" is its "windows": on this PC the other end is
# whichever machine has input, or is driven from here.
LOCAL, ELSEWHERE, HELD = "local", "elsewhere", "held"
DRIVE_STATES = (LOCAL, ELSEWHERE, HELD)
DESCRIPTIONS = {
    LOCAL: "Input on this PC",
    ELSEWHERE: "Input on another machine",
    HELD: "Input held on this PC; crossing is paused",
}
# What a tray asks for: Windows takes 16 at 100%, 20 at 125%, 24 at 150% and 32 at 200%.
SIZES = (16, 20, 24, 32, 48, 64)
DIMMED_STATES = ("stopped", "error")
GLYPH_WIDTH, GLYPH_HEIGHT = 22.0, 16.0


def drive_state(redirecting: bool, driven: bool, held: bool) -> str:
    """Which glyph: input is away from this PC, held, or here. Away wins, as on the Mac."""
    if redirecting or driven:
        return ELSEWHERE
    return HELD if held else LOCAL


def _ink(dark: bool) -> QColor:
    return QColor("#ffffff" if dark else "#000000")


def _draw_glyph(painter: QPainter, drive: str) -> None:
    for x, filled in ((1.0, drive == LOCAL), (13.0, drive == ELSEWHERE)):
        if filled:
            painter.drawRoundedRect(QRectF(x, 2, 8, 12), 1.5, 1.5)
        else:
            pen = QPen(painter.brush().color(), 1.5)
            outline = QPainterPath()
            outline.addRoundedRect(QRectF(x + 0.75, 2.75, 6.5, 10.5), 1, 1)
            painter.save()
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(outline)
            painter.restore()
    if drive == HELD:
        painter.drawRoundedRect(QRectF(10, 0, 2, 16), 1, 1)
        return
    tip, tail = (10.0, 12.0) if drive == LOCAL else (12.0, 10.0)
    chevron = QPainterPath()
    chevron.moveTo(tail, 5.5)
    chevron.lineTo(tip, 8.0)
    chevron.lineTo(tail, 10.5)
    pen = QPen(painter.brush().color(), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.save()
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(chevron)
    painter.restore()


def pixmap(drive: str, status: str, size: int, dark: bool) -> QPixmap:
    """One square tray image: the glyph in the taskbar's ink along the top, with the receiver badge
    in the strip below its lower right corner, a hair of gap cut where they touch. `status` is a ServerState value in lower case; `dark` is the taskbar's."""
    image = QPixmap(size, size)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_ink(dark))
    scale = size / GLYPH_WIDTH
    painter.save()
    painter.scale(scale, scale)
    painter.setOpacity(0.4 if status in DIMMED_STATES else 1.0)
    _draw_glyph(painter, drive)
    painter.restore()
    dot = size * 0.30
    gap = size / 32
    corner = size - dot
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.setOpacity(1.0)
    painter.drawEllipse(QRectF(corner - gap, corner - gap, dot + 2 * gap, dot + 2 * gap))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.setBrush(QColor(theme.state_colour(status)))
    painter.drawEllipse(QRectF(corner, corner, dot, dot))
    painter.end()
    return image


def icon(drive: str, status: str, dark: bool) -> QIcon:
    """Every size drawn natively, so the shell picks one rather than scaling a large image down."""
    result = QIcon()
    for size in SIZES:
        result.addPixmap(pixmap(drive, status, size, dark))
    return result


def taskbar_is_dark(system_dark: bool) -> bool:
    """Windows has a taskbar theme of its own, apart from the apps': SystemUsesLightTheme. Anywhere
    else the panel follows the desktop's scheme, which `system_dark` is."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "SystemUsesLightTheme")[0] == 0
    except (ImportError, OSError):
        return system_dark
