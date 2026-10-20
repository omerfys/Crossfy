"""
Crossfy UI - Liquid Glass Engine
Hardware-accelerated custom QPainter and QPainterPath glassmorphic rendering components.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Optional

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
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


def apply_windows_acrylic(hwnd: int) -> bool:
    """Enable native hardware-accelerated Windows 11 Acrylic blur."""
    if sys.platform != "win32":
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
        # 1. Extend Frame into client area (critical for client blur)
        margins = _MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

        # 2. Immersive Dark Mode (20)
        dark = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))

        # 3. SetWindowCompositionAttribute with AcrylicBlurBehind
        try:
            u32 = ctypes.windll.user32
            policy = _ACCENT_POLICY()
            policy.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
            policy.AccentFlags = 2  # Draw all borders
            policy.GradientColor = 0x55101522  # ~33% alpha dark navy/slate tint
            policy.AnimationId = 0

            data = _WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = 19  # WCA_ACCENT_POLICY
            data.Data = ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p)
            data.SizeOfData = ctypes.sizeof(policy)
            u32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        except Exception:
            pass

        # 4. Acrylic Backdrop (38 -> 3 = Acrylic)
        backdrop = ctypes.c_int(3)
        dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
        return True
    except Exception as exc:
        print("Acrylic notice:", exc)
        return False

class GlassPanel(QWidget):
    """Frosted Liquid Glass Panel drawn via QPainter and QPainterPath."""

    def __init__(
        self,
        radius: float = 16.0,
        border_color: QColor = QColor(255, 255, 255, 24),
        bg_color: QColor = QColor(12, 17, 28, 55),
        parent: Optional[QWidget] = None,
        active: bool = False,
    ):
        super().__init__(parent)
        self.radius = radius
        self.border_color = border_color
        self.bg_color = bg_color
        self.active = active
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_active(self, active: bool):
        self.active = active
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)

        # 1. Base Glass Fill
        if self.active:
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor(0, 240, 255, 28))
            grad.setColorAt(1.0, QColor(153, 51, 255, 20))
            painter.fillPath(path, grad)
        elif self._hover:
            painter.fillPath(path, QColor(255, 255, 255, 14))
        else:
            painter.fillPath(path, self.bg_color)

        # 2. Outer Border Pen
        if self.active:
            pen = QPen(QColor(0, 240, 255, 140), 1.2)
        elif self._hover:
            pen = QPen(QColor(255, 255, 255, 48), 1.0)
        else:
            pen = QPen(self.border_color, 1.0)
        painter.strokePath(path, pen)

        # 3. Specular Top Highlight (Refraction edge)
        specular = QLinearGradient(rect.topLeft(), rect.topRight())
        specular.setColorAt(0.0, QColor(255, 255, 255, 0))
        specular.setColorAt(0.2, QColor(255, 255, 255, 110))
        specular.setColorAt(0.8, QColor(255, 255, 255, 110))
        specular.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(QPen(specular, 1.0))
        painter.drawLine(
            QPointF(rect.left() + self.radius, rect.top() + 0.5),
            QPointF(rect.right() - self.radius, rect.top() + 0.5),
        )


class GlassButton(QWidget):
    """Custom-drawn Liquid Glass Button with smooth glow and refraction effects."""

    clicked = Signal()

    def __init__(
        self,
        text: str = "",
        height: int = 36,
        radius: float = 18.0,
        primary: bool = True,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.text = text
        self.radius = radius
        self.primary = primary
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._hover_val = 0.0
        self._press_val = 0.0

        self._anim = QPropertyAnimation(self, b"hover_val")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_hover_val(self) -> float:
        return self._hover_val

    def set_hover_val(self, val: float):
        self._hover_val = val
        self.update()

    hover_val = Property(float, get_hover_val, set_hover_val)

    def enterEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover_val)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover_val)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_val = 1.0
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_val = 0.0
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)

        # 1. Translucent Liquid Base
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if self.primary:
            alpha_cyan = int(30 + 40 * self._hover_val)
            alpha_purple = int(25 + 35 * self._hover_val)
            grad.setColorAt(0.0, QColor(0, 240, 255, alpha_cyan))
            grad.setColorAt(0.5, QColor(255, 255, 255, int(10 + 16 * self._hover_val)))
            grad.setColorAt(1.0, QColor(153, 51, 255, alpha_purple))
        else:
            alpha = int(12 + 25 * self._hover_val)
            grad.setColorAt(0.0, QColor(255, 255, 255, alpha))
            grad.setColorAt(1.0, QColor(255, 255, 255, alpha // 2))

        painter.fillPath(path, grad)

        # 2. Border Pen
        if self.primary:
            border_alpha = int(75 + 120 * self._hover_val)
            border_pen = QPen(QColor(0, 240, 255, border_alpha), 1.0)
        else:
            border_alpha = int(24 + 40 * self._hover_val)
            border_pen = QPen(QColor(255, 255, 255, border_alpha), 1.0)

        painter.strokePath(path, border_pen)

        # 3. Specular Highlight Edge
        specular = QLinearGradient(rect.topLeft(), rect.topRight())
        highlight_alpha = int(80 + 90 * self._hover_val)
        specular.setColorAt(0.0, QColor(255, 255, 255, 0))
        specular.setColorAt(0.2, QColor(255, 255, 255, highlight_alpha))
        specular.setColorAt(0.8, QColor(255, 255, 255, highlight_alpha))
        specular.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(QPen(specular, 1.1))
        painter.drawLine(
            QPointF(rect.left() + self.radius * 0.6, rect.top() + 0.8),
            QPointF(rect.right() - self.radius * 0.6, rect.top() + 0.8),
        )

        # 4. Text
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        text_color = QColor(0, 240, 255) if (self.primary and self._hover_val > 0.5) else QColor(255, 255, 255)
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)


class GlassPill(QWidget):
    """Minimalist Frosted Glass Status Badge drawn with QPainter, dynamically autoscaled to text."""

    def __init__(self, text: str, dot_color: QColor = QColor(0, 240, 255), parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.text = text
        self.dot_color = dot_color
        self.setFixedHeight(34)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._autoscale()

    def set_text(self, text: str):
        self.text = text
        self._autoscale()
        self.update()

    def _autoscale(self):
        from PySide6.QtGui import QFontMetrics
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        metrics = QFontMetrics(font)
        w = metrics.horizontalAdvance(self.text) + 48
        self.setFixedWidth(max(180, w))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        r = rect.height() / 2.0

        # Capsule fill
        painter.setPen(QPen(QColor(0, 240, 255, 60), 1))
        painter.setBrush(QColor(0, 240, 255, 12))
        painter.drawRoundedRect(rect, r, r)

        # Glowing Dot
        dot_x = rect.left() + 14.0
        dot_y = rect.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.dot_color.red(), self.dot_color.green(), self.dot_color.blue(), 45))
        painter.drawEllipse(QPointF(dot_x, dot_y), 5.5, 5.5)
        painter.setBrush(self.dot_color)
        painter.drawEllipse(QPointF(dot_x, dot_y), 3.5, 3.5)

        # Typography
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))

        text_rect = QRectF(rect.left() + 26.0, 0, rect.width() - 36.0, rect.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)
