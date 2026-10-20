"""
Crossfy UI - Radial Menu Engine
Interactive circular / radial dial and palette selector drawn with QPainterPath.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

import app_config
import tokens

PALETTES_LIST = [
    ("colourful", "Colourful", ("#ff3264", "#ff7828", "#f032b4", "#6446ff", "#288cff", "#1eb9aa")),
    ("ocean", "Ocean", ("#288cff", "#6446ff", "#1eb9aa", "#3c6eff")),
    ("sunset", "Sunset", ("#ff7828", "#ff3264", "#ffb43c", "#f03278")),
    ("amethyst", "Amethyst", ("#8c46ff", "#b450ff", "#5a28c8", "#d278ff")),
    ("emerald", "Emerald", ("#00e676", "#1de9b6", "#00b0ff", "#00c853")),
    ("sapphire", "Sapphire", ("#00b0ff", "#2979ff", "#651fff", "#00e5ff")),
    ("sunstone", "Sunstone", ("#ff9100", "#ff3d00", "#ffea00", "#ff6d00")),
    ("signal", "Signal", ("#00f0ff", "#00e5ff", "#76ff03")),
    ("topaz", "Topaz", ("#ffd600", "#ffab00", "#ff6d00", "#ff9100")),
    ("amber", "Amber", ("#ffab00", "#ff6d00", "#ff3d00")),
]


class RadialPalettePicker(QWidget):
    """Futuristic Radial Color Dial drawn with QPainterPath arc segments."""

    paletteSelected = Signal(str)

    def __init__(
        self,
        current: str = "colourful",
        on_select: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.current = current
        self.on_select = on_select
        self.setFixedSize(260, 260)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._hover_idx = -1
        self._target_angle = 0.0
        self._current_angle = 0.0

        for i, (k, _, _) in enumerate(PALETTES_LIST):
            if k == current:
                self._current_angle = self._target_angle = (i * 360.0 / len(PALETTES_LIST))
                break

        self._anim = QPropertyAnimation(self, b"rotation_angle")
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_rotation_angle(self) -> float:
        return self._current_angle

    def set_rotation_angle(self, val: float):
        self._current_angle = val
        self.update()

    rotation_angle = Property(float, get_rotation_angle, set_rotation_angle)

    def select_palette(self, name: str):
        for i, (k, _, _) in enumerate(PALETTES_LIST):
            if k == name:
                self.current = name
                target = i * 360.0 / len(PALETTES_LIST)
                self._anim.stop()
                self._anim.setStartValue(self._current_angle)
                self._anim.setEndValue(target)
                self._anim.start()
                self.paletteSelected.emit(name)
                if self.on_select:
                    self.on_select(name)
                break

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._hit_test(event.position().x(), event.position().y())
            if idx is not None:
                val = PALETTES_LIST[idx][0]
                self.select_palette(val)
            event.accept()

    def mouseMoveEvent(self, event):
        idx = self._hit_test(event.position().x(), event.position().y())
        if idx != self._hover_idx:
            self._hover_idx = idx if idx is not None else -1
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_idx = -1
        self.update()
        super().leaveEvent(event)

    def _hit_test(self, x: float, y: float) -> Optional[int]:
        cx, cy = self.width() / 2.0, self.height() / 2.0
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        inner_r, outer_r = 65.0, 118.0

        if inner_r <= dist <= outer_r:
            angle = math.degrees(math.atan2(dy, dx))
            if angle < 0:
                angle += 360.0
            step = 360.0 / len(PALETTES_LIST)
            idx = int(angle // step) % len(PALETTES_LIST)
            return idx
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        count = len(PALETTES_LIST)
        step = 360.0 / count
        inner_r = 68.0
        outer_r = 116.0

        # 1. Background Halo
        painter.setPen(Qt.PenStyle.NoPen)
        halo = QColor(0, 240, 255, 10)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(cx, cy), outer_r + 6, outer_r + 6)

        # 2. Draw Arc Slices
        for i, (k, title, colors) in enumerate(PALETTES_LIST):
            start_angle = i * step + 1.5
            span_angle = step - 3.0
            is_active = (k == self.current)
            is_hover = (i == self._hover_idx)

            r_out = outer_r + (4.0 if (is_active or is_hover) else 0.0)
            r_in = inner_r - (2.0 if is_active else 0.0)

            # Arc Path
            path = QPainterPath()
            rad_start = math.radians(start_angle)
            rad_end = math.radians(start_angle + span_angle)

            # Outer arc
            path.arcMoveTo(cx - r_out, cy - r_out, r_out * 2, r_out * 2, -start_angle)
            path.arcTo(cx - r_out, cy - r_out, r_out * 2, r_out * 2, -start_angle, -span_angle)

            # Inner arc back
            path.arcTo(cx - r_in, cy - r_in, r_in * 2, r_in * 2, -(start_angle + span_angle), span_angle)
            path.closeSubpath()

            # Slice fill
            primary_c = QColor(colors[0])
            if is_active:
                painter.setBrush(primary_c)
                painter.setPen(QPen(QColor(255, 255, 255, 240), 1.5))
            elif is_hover:
                c = QColor(primary_c)
                c.setAlpha(190)
                painter.setBrush(c)
                painter.setPen(QPen(QColor(255, 255, 255, 110), 1.0))
            else:
                c = QColor(primary_c)
                c.setAlpha(110)
                painter.setBrush(c)
                painter.setPen(QPen(QColor(255, 255, 255, 28), 0.8))

            painter.drawPath(path)

        # 3. Inner Center Glass Disc
        disc_r = inner_r - 4.0
        disc_rect = QRectF(cx - disc_r, cy - disc_r, disc_r * 2, disc_r * 2)

        # Glass gradient
        disc_grad = QLinearGradient(disc_rect.topLeft(), disc_rect.bottomRight())
        disc_grad.setColorAt(0.0, QColor(25, 32, 46, 140))
        disc_grad.setColorAt(1.0, QColor(14, 18, 26, 160))

        painter.setBrush(disc_grad)
        painter.setPen(QPen(QColor(0, 240, 255, 90), 1.2))
        painter.drawEllipse(disc_rect)

        # Active Palette Title
        active_entry = next((item for item in PALETTES_LIST if item[0] == self.current), PALETTES_LIST[0])
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QRectF(cx - disc_r, cy - 18, disc_r * 2, 20), Qt.AlignmentFlag.AlignCenter, active_entry[1])

        # Color dots
        dot_colors = active_entry[2]
        dot_count = min(5, len(dot_colors))
        total_w = dot_count * 12.0
        start_x = cx - total_w / 2.0 + 6.0
        for di in range(dot_count):
            dc = QColor(dot_colors[di])
            painter.setBrush(dc)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(start_x + di * 12.0, cy + 8), 3.5, 3.5)
