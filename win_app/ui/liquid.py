"""
Crossfy UI - Liquid Animation Engine
Fluid morphing segmented controls, organic liquid toggles, and animated glass sliders.
"""

from __future__ import annotations

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


class LiquidSegmentedControl(QWidget):
    """Frosted Glass Segmented Control with a Fluid Liquid Animated Indicator."""

    valueChanged = Signal(str)

    def __init__(
        self,
        items: list[tuple[str, str]],
        current: str = "",
        on_change: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.items = items
        self.on_change = on_change
        self.current_value = current or (items[0][0] if items else "")
        self.current_idx = 0
        for i, (k, _) in enumerate(items):
            if k == self.current_value:
                self.current_idx = i
                break

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        self.setMinimumWidth(max(180, len(items) * 105))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._anim_pos = float(self.current_idx)
        self._anim = QPropertyAnimation(self, b"anim_pos")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_anim_pos(self) -> float:
        return self._anim_pos

    def set_anim_pos(self, val: float):
        self._anim_pos = val
        self.update()

    anim_pos = Property(float, get_anim_pos, set_anim_pos)

    def set_value(self, value: str):
        for i, (k, _) in enumerate(self.items):
            if k == value:
                self.current_value = value
                self.current_idx = i
                self._anim.stop()
                self._anim.setStartValue(self._anim_pos)
                self._anim.setEndValue(float(i))
                self._anim.start()
                break

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.items:
            w = self.width() / len(self.items)
            idx = max(0, min(len(self.items) - 1, int(event.position().x() / w)))
            val = self.items[idx][0]
            if val != self.current_value:
                self.set_value(val)
                self.valueChanged.emit(val)
                if self.on_change:
                    self.on_change(val)
            event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        r = 11.0

        # 1. Frosted Capsule Track
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.setBrush(QColor(255, 255, 255, 8))
        painter.drawRoundedRect(rect, r, r)

        if not self.items:
            return

        # 2. Liquid Animated Glowing Pill
        item_w = (rect.width() - 6.0) / len(self.items)
        pill_x = 3.0 + self._anim_pos * item_w
        pill_rect = QRectF(pill_x, 3.0, item_w, rect.height() - 6.0)

        # Gradient fill
        grad = QLinearGradient(pill_rect.topLeft(), pill_rect.bottomRight())
        grad.setColorAt(0.0, QColor(0, 240, 255, 55))
        grad.setColorAt(0.5, QColor(255, 255, 255, 18))
        grad.setColorAt(1.0, QColor(153, 51, 255, 45))

        painter.setBrush(grad)
        painter.setPen(QPen(QColor(0, 240, 255, 140), 1))
        painter.drawRoundedRect(pill_rect, r - 3.0, r - 3.0)

        # Specular top highlight line
        highlight = QLinearGradient(pill_rect.topLeft(), pill_rect.topRight())
        highlight.setColorAt(0.0, QColor(0, 240, 255, 0))
        highlight.setColorAt(0.25, QColor(255, 255, 255, 150))
        highlight.setColorAt(0.75, QColor(255, 255, 255, 150))
        highlight.setColorAt(1.0, QColor(153, 51, 255, 0))
        painter.setPen(QPen(highlight, 1.2))
        painter.drawLine(
            QPointF(pill_rect.left() + 5, pill_rect.top() + 1),
            QPointF(pill_rect.right() - 5, pill_rect.top() + 1),
        )

        # 3. Item Labels
        font_active = QFont(self.font())
        font_active.setBold(True)
        font_active.setPointSize(9)

        font_inactive = QFont(self.font())
        font_inactive.setBold(False)
        font_inactive.setPointSize(9)

        for i, (_, label) in enumerate(self.items):
            x = 3.0 + i * item_w
            target_rect = QRectF(x, 0, item_w, rect.height())
            is_active = (i == self.current_idx)

            if is_active:
                painter.setFont(font_active)
                painter.setPen(QColor(0, 240, 255))
            else:
                painter.setFont(font_inactive)
                painter.setPen(QColor(255, 255, 255, 180))

            painter.drawText(target_rect, Qt.AlignmentFlag.AlignCenter, label)


class LiquidToggle(QWidget):
    """Organic Liquid Toggle Switch with smooth fluid morphing animation."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, on_toggle: Optional[Callable[[bool], None]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._checked = checked
        self.on_toggle = on_toggle
        self.setFixedSize(52, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_pos(self) -> float:
        return self._pos

    def set_pos(self, val: float):
        self._pos = val
        self.update()

    pos = Property(float, get_pos, set_pos)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(1.0 if checked else 0.0)
            self._anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
            if self.on_toggle:
                self.on_toggle(self._checked)
            event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        r = rect.height() / 2.0

        # Track background
        if self._pos > 0.01:
            track_color = QColor(0, 240, 255, int(18 + 32 * self._pos))
            border_color = QColor(0, 240, 255, int(60 + 80 * self._pos))
        else:
            track_color = QColor(255, 255, 255, 10)
            border_color = QColor(255, 255, 255, 26)

        painter.setBrush(track_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(rect, r, r)

        # Sliding Liquid Knob
        knob_dia = rect.height() - 6.0
        travel = rect.width() - knob_dia - 6.0
        knob_x = 3.0 + travel * self._pos
        knob_y = 3.0
        knob_rect = QRectF(knob_x, knob_y, knob_dia, knob_dia)

        # Knob fill
        if self._pos > 0.5:
            painter.setBrush(QColor(0, 240, 255))
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
        else:
            painter.setBrush(QColor(255, 255, 255, 200))
            painter.setPen(QPen(QColor(255, 255, 255, 70), 1))

        painter.drawEllipse(knob_rect)


class LiquidSlider(QWidget):
    """Custom Frosted Glass Slider with Liquid Glow Fill."""

    valueChanged = Signal(int)

    def __init__(self, min_val: int = 0, max_val: int = 100, current: int = 50, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.min_val = min_val
        self.max_val = max_val
        self._val = current
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def value(self) -> int:
        return self._val

    def setValue(self, val: int):
        val = max(self.min_val, min(self.max_val, val))
        if self._val != val:
            self._val = val
            self.update()
            self.valueChanged.emit(val)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._update_from_mouse(event.position().x())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self._update_from_mouse(event.position().x())
            event.accept()

    def _update_from_mouse(self, x: float):
        track_w = self.width() - 20.0
        frac = max(0.0, min(1.0, (x - 10.0) / track_w))
        new_val = int(self.min_val + frac * (self.max_val - self.min_val))
        self.setValue(new_val)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        track_y = rect.center().y() - 3.0
        track_h = 6.0
        track_w = rect.width() - 20.0
        track_rect = QRectF(10.0, track_y, track_w, track_h)

        # Inactive track
        painter.setBrush(QColor(255, 255, 255, 12))
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.drawRoundedRect(track_rect, 3.0, 3.0)

        # Active filled liquid bar
        frac = (self._val - self.min_val) / max(1, (self.max_val - self.min_val))
        fill_w = track_w * frac
        fill_rect = QRectF(10.0, track_y, fill_w, track_h)

        grad = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
        grad.setColorAt(0.0, QColor(0, 240, 255, 110))
        grad.setColorAt(1.0, QColor(0, 240, 255, 230))

        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(fill_rect, 3.0, 3.0)

        # Glass Thumb
        thumb_x = 10.0 + fill_w
        thumb_y = rect.center().y()
        # Soft outer glow
        painter.setBrush(QColor(0, 240, 255, 55))
        painter.drawEllipse(QPointF(thumb_x, thumb_y), 9.0, 9.0)
        # Core thumb
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QPen(QColor(0, 240, 255), 2))
        painter.drawEllipse(QPointF(thumb_x, thumb_y), 6.5, 6.5)
