"""The Crossing ledger: kept intent, edited directly in each machine's row."""

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAccessibleWidget, QCheckBox, QFrame, QGraphicsOpacityEffect,
                               QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton,
                               QSizePolicy, QStyle, QStyleOptionButton, QVBoxLayout, QWidget)

from core.i18n import N_, tr
from core import profiles, ways
import theme
import widgets


def _accessible_factory(_name, obj):
    role = obj.property("ledger_role") if isinstance(obj, QWidget) else None
    roles = {"table": QAccessible.Role.Table, "row": QAccessible.Role.Row,
             "columnheader": QAccessible.Role.ColumnHeader, "rowheader": QAccessible.Role.RowHeader,
             "cell": QAccessible.Role.Cell}
    if role in roles:
        return QAccessibleWidget(obj, roles[role])


QAccessible.installFactory(_accessible_factory)


def _quiet(text, callback=None):
    button = QPushButton(text)
    button.setProperty("vernier", "plain")
    button.setProperty("ledger_quiet", True)
    button.setFont(theme.font(theme.TYPE["note"]))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setMinimumWidth(0)
    button.setFixedHeight(24)
    _quiet_style(button)
    if callback:
        button.clicked.connect(callback)
    return button


def _quiet_style(button):
    button.setStyleSheet(f"QPushButton {{ color: {theme.colour('ink_2')}; background: transparent; border: 0; padding: 0; font-size: {round(theme.TYPE['note'])}px; font-weight: 400; text-align: left; }} QPushButton:focus {{ border: 1px solid {theme.colour('signal')}; }}")


SIDE_NAMES = {"left": N_("Left"), "right": N_("Right"), "top": N_("Top"), "bottom": N_("Bottom")}
CORNER_TITLES = {"top_left": N_("Top left"), "top_right": N_("Top right"),
                 "bottom_left": N_("Bottom left"), "bottom_right": N_("Bottom right")}
CHIP_HEIGHT = 26


def _tone(name, alpha=1.0):
    tone = QColor(theme.colour(name))
    tone.setAlphaF(alpha)
    return tone


def _mix(one, two, amount):
    one, two = QColor(theme.colour(one)), QColor(theme.colour(two))
    return QColor(*(round(a + (b - a) * amount) for a, b in zip(one.getRgb()[:3], two.getRgb()[:3])))


class _Flow(QLayout):
    """Chips that wrap onto further lines at the cell's width, 6 px apart."""

    def __init__(self, parent=None, gap=6):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def order(self, widgets):
        by_widget = {item.widget(): item for item in self._items}
        self._items = [by_widget[widget] for widget in widgets if widget in by_widget]
        self.invalidate()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), False)

    def minimumHeightForWidth(self, width):
        return self.heightForWidth(width)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, True)

    def sizeHint(self):
        shown = [item for item in self._items if not item.isEmpty()]
        width = sum(item.sizeHint().width() for item in shown) + self._gap * max(0, len(shown) - 1)
        return QSize(width, CHIP_HEIGHT)

    def minimumSize(self):
        shown = [item for item in self._items if not item.isEmpty()]
        return QSize(max((item.minimumSize().width() for item in shown), default=0), CHIP_HEIGHT if shown else 0)

    def _place(self, rect, apply):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            width = min(hint.width(), max(1, rect.width()))
            if x > rect.x() and x + width > rect.x() + rect.width():
                x, y = rect.x(), y + line + self._gap
                line = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, hint.height())))
            x += width + self._gap
            line = max(line, hint.height())
        return y + line - rect.y() if line else 0


class _Segment(QPushButton):
    """One third of a contact chip's bar: a 9 px wide button laid over the drawn bar."""

    def __init__(self, parent, callback):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.restyle()
        self.clicked.connect(lambda _checked=False: callback())

    def restyle(self):
        self.setStyleSheet("QPushButton { background: transparent; border: 0; padding: 0; min-width: 0; min-height: 0; }"
                           " QPushButton[keyboard_ring=\"true\"]:focus { border: 1px solid " + theme.colour("signal") + "; }")

    def nextCheckState(self):
        pass


class _Chip(QPushButton):
    """One side of This PC as a chip: a drawn icon, the label, and for the contact side a thirds bar."""

    def __init__(self, side, on_click, on_third):
        super().__init__()
        self.side, self.kind, self.text_, self.picked = side, "free", "", ()
        self.edge_on = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(CHIP_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("QPushButton { padding: 0; min-width: 0; min-height: 0; }")
        self.setFont(theme.font(12))
        self.clicked.connect(lambda _checked=False: on_click(self.side))
        self.segments = {}
        for third in ways.PARTS:
            segment = _Segment(self, lambda third=third: on_third(third))
            segment.hide()
            self.segments[third] = segment

    def nextCheckState(self):
        pass

    def set_state(self, kind, text, on, tooltip, name, edge_on=False, picked=(), enabled=True, segments_enabled=True):
        self.kind, self.text_, self.edge_on, self.picked = kind, text, edge_on, tuple(picked)
        self.setFont(theme.font(12))
        self.setToolTip(tooltip)
        self.setAccessibleName(name)
        self.setEnabled(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        for third, segment in self.segments.items():
            segment.restyle()
            segment.setVisible(kind == "contact")
            segment.setEnabled(segments_enabled)
            title = ways.part_names(self.side)[third]
            lit = edge_on and third in picked
            segment.setAccessibleName(tr("{side} edge, {third} third, {state}").format(
                side=tr(SIDE_NAMES[self.side]),
                third=tr(ways.PART_NAMES_LOWER[title.lower()]), state=tr("on" if lit else "off")))
            segment.setToolTip(tr("{third} third: click to {action}").format(
                third=tr(title), action=tr("leave it out" if lit else "turn it on")))
            segment.blockSignals(True)
            segment.setChecked(lit)
            segment.blockSignals(False)
        self.updateGeometry()
        self.update()

    def _natural(self):
        advance = QFontMetrics(self.font()).horizontalAdvance(self.text_)
        return 8 + 14 + 6 + advance + 10 + (28 if self.kind == "contact" else 0) + 2

    def sizeHint(self):
        return QSize(self._natural(), CHIP_HEIGHT)

    def minimumSizeHint(self):
        return QSize(min(self._natural(), 84), CHIP_HEIGHT)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        bar_x = self.width() - 10 - 22
        for index, segment in enumerate(self.segments.values()):
            centre = bar_x + 1 + index * 7.3 + 2.5
            segment.setGeometry(round(centre - 4.5), 2, 9, CHIP_HEIGHT - 4)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def _icon(self, painter, colour):
        pen = QPen(colour, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.save()
        painter.translate(8, (CHIP_HEIGHT - 14) / 2)
        path = QPainterPath()
        if self.kind == "free":
            path.moveTo(7, 3)
            path.lineTo(7, 11)
            path.moveTo(3, 7)
            path.lineTo(11, 7)
        elif self.kind in ("on", "kept"):
            path.moveTo(10.5, 4.5)
            path.lineTo(5, 4.5)
            path.arcTo(QRectF(2.5, 4.5, 5, 5), 90, 180)
            path.lineTo(11, 9.5)
            path.moveTo(9, 7.5)
            path.lineTo(11, 9.5)
            path.lineTo(9, 11.5)
        else:
            path.moveTo(2, 2.5)
            path.lineTo(2, 11.5)
            path.moveTo(5, 7)
            path.lineTo(12, 7)
            path.moveTo(9.5, 4.5)
            path.lineTo(12, 7)
            path.lineTo(9.5, 9.5)
        painter.drawPath(path)
        painter.restore()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        kind, live = self.kind, self.isEnabled()
        lit = kind == "on" or (kind == "contact" and self.edge_on)
        hover = self.underMouse() and live
        pressed = self.isDown() and live
        border, fill, ink, icon = _tone("edge"), None, _tone("ink_2"), _tone("ink_2")
        dashed = False
        if lit:
            border, fill, ink, icon = _tone("signal"), _tone("signal_dim"), _tone("ink"), _tone("signal")
        elif kind == "contact":
            ink = icon = _tone("ink_3")
        elif kind == "kept":
            border, ink, icon, dashed = _tone("signal", .45), _tone("ink_3"), _tone("ink_3"), True
        elif kind == "free":
            dashed = True
        elif kind == "held":
            border, ink, icon = _tone("rule"), _tone("ink_3"), _tone("ink_3")
            painter.setOpacity(.45)
        if not live:
            border, fill, ink, icon, dashed = _tone("rule"), None, _tone("ink_3"), _tone("ink_3"), False
        if pressed:
            border, fill, ink, dashed = _tone("signal"), _mix("signal_dim", "signal", .12), _tone("ink"), False
        elif hover:
            border, fill, ink, dashed = _tone("ink_2"), _mix("panel", "well", .5), _tone("ink"), False
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        pen = QPen(border, 1)
        if dashed:
            pen.setDashPattern([3.0, 3.0])
        painter.setPen(pen)
        painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 5, 5)
        if pressed:
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
        self._icon(painter, icon)
        bar = 28 if kind == "contact" else 0
        painter.setFont(self.font())
        painter.setPen(ink)
        room = max(1, self.width() - 28 - 10 - bar)
        painter.drawText(QRectF(28, 0, room, CHIP_HEIGHT), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         QFontMetrics(self.font()).elidedText(self.text_, Qt.TextElideMode.ElideRight, round(room)))
        if kind == "contact":
            bar_x = self.width() - 10 - 22
            for index, third in enumerate(ways.PARTS):
                on = self.edge_on and third in self.picked
                stroke = QPen(_tone("ink_3" if not live else "signal" if on else "edge"), 3 if on else 1.5)
                stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(stroke)
                start = bar_x + 1 + index * 7.3
                painter.drawLine(QPointF(start, CHIP_HEIGHT / 2), QPointF(start + 5, CHIP_HEIGHT / 2))
        if widgets.focus_ring_visible(self):
            painter.setOpacity(1)
            painter.setPen(QPen(_tone("signal"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 5, 5)
        painter.end()


class EdgeChips(QWidget):
    """The Edges cell: the contact side first, then left, right, top and bottom, as chips."""

    def __init__(self, peer, owner, parent=None):
        super().__init__(parent)
        self.setProperty("vernier", "plain")
        self.setMinimumWidth(0)
        self.flow = _Flow(self)
        self.chips = {side: _Chip(side, lambda side, peer=peer: self._clicked(peer, owner, side),
                                  lambda third, peer=peer: owner._ledger_third(peer, third)) for side in ways.EDGES}
        for chip in self.chips.values():
            self.flow.addWidget(chip)
            chip.hide()
        self.kinds = {}

    def _clicked(self, peer, owner, side):
        if self.kinds.get(side) == "contact":
            owner._ledger_edge(peer)
        else:
            owner._ledger_side(peer, side)

    def reflect(self, sides, name, labels, edge_on, picked, contact, left_out):
        order = ([contact] if contact else []) + [side for side in ways.EDGES if side != contact]
        self.flow.order([self.chips[side] for side in order])
        self.kinds = {side: sides.get(side, {}).get("state", "unavailable") for side in ways.EDGES}
        lock = "Left out: Put back to change its ways"
        for side in ways.EDGES:
            chip, kind = self.chips[side], self.kinds[side]
            title = tr(SIDE_NAMES[side])
            if kind == "unavailable" or left_out and kind in ("free", "held"):
                # A left-out row shows only the ways it keeps.
                chip.hide()
                continue
            held_by = labels.get(sides[side].get("by"), tr("Another machine")) if kind == "held" else ""
            if kind == "contact":
                answer = tr("turn it off" if edge_on else "turn it on")
                chip.set_state("contact", title, edge_on,
                               tr("Left out: Put back to change its ways") if left_out else tr("{side} edge: touches {name}; click to {action}").format(side=title, name=name, action=answer),
                               tr("{side} edge, touches {name}, {state}").format(side=title, name=name, state=tr("on" if edge_on else "off")), edge_on, picked,
                               enabled=not left_out, segments_enabled=not left_out)
            elif kind == "on":
                chip.set_state("on", tr("{side}, wraps").format(side=title), True, tr("Left out: Put back to change its ways") if left_out else tr("{side} edge wraps round to {name}; click to remove").format(side=title, name=name),
                               tr("{side} edge, wraps round, on").format(side=title), enabled=not left_out)
            elif kind == "kept":
                tip = tr("Left out: Put back to change its ways") if left_out else (
                    tr("{side} edge wraps round to {name} once Edge is on; click to turn Edge on").format(side=title, name=name) if not edge_on
                    else tr("{side} edge: none of it is free just now; click to remove").format(side=title))
                chip.set_state("kept", tr("{side}, wraps").format(side=title), False, tip,
                               tr("{side} edge, wraps round, kept").format(side=title), enabled=not left_out)
            elif kind == "held":
                chip.set_state("held", tr("{side}, {name}").format(side=title, name=held_by), False,
                               tr("{side} edge: {name}'s").format(side=title, name=held_by),
                               tr("{side} edge, held by {name}").format(side=title, name=held_by), enabled=False)
            else:
                chip.set_state("free", title, False, tr("Left out: Put back to change its ways") if left_out else tr("{side} edge: click to wrap round to {name}").format(side=title, name=name),
                               tr("{side} edge, wraps round, off").format(side=title), enabled=not left_out)
            chip.show()
        self.updateGeometry()

    def any_shown(self):
        return any(kind != "unavailable" for kind in self.kinds.values())


class _CornerButton(QPushButton):
    """One corner of This PC: a 28 px square with an L bracket drawn at that corner."""

    def __init__(self, corner, callback):
        super().__init__()
        self.corner, self.kind = corner, "unavailable"
        self.setCheckable(True)
        # No min-width or min-height in the sheet: a style sheet's minimum replaces the one
        # setFixedSize sets, and the grid then squashed the square to 28 x 19 and clipped the bracket.
        self.setFixedSize(28, 28)
        self.setStyleSheet("QPushButton { padding: 0; }")
        self.clicked.connect(lambda _checked=False: callback(self.corner))

    def nextCheckState(self):
        pass

    def set_state(self, kind, tooltip, name, enabled):
        self.kind = kind
        self.setToolTip(tooltip)
        self.setAccessibleName(name)
        self.setEnabled(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.blockSignals(True)
        self.setChecked(kind == "on")
        self.blockSignals(False)
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        kind = self.kind
        hover = self.underMouse() and self.isEnabled()
        pressed = self.isDown() and self.isEnabled()
        border, fill, bracket, dashed, opacity = _tone("edge"), None, _tone("ink_2"), True, 1.0
        if kind == "on":
            border, fill, bracket, dashed = _tone("signal"), _tone("signal"), _tone("ground"), False
        elif kind == "held":
            border, bracket, dashed = _tone("signal", .35), _tone("signal", .5), False
        elif kind == "unavailable":
            opacity = .4
        if not self.isEnabled():
            border, fill, bracket, dashed, opacity = _tone("rule"), None, _tone("ink_3"), False, 1.0
        if pressed:
            border, fill, dashed = _tone("signal"), _mix("signal_dim", "signal", .12), False
            bracket = _tone("ink")
        elif hover:
            border, dashed = _tone("ink_2"), False
            fill = fill if fill is not None else _mix("panel", "well", .5)
        painter.setOpacity(opacity)
        pen = QPen(border, 1)
        if dashed:
            pen.setDashPattern([3.0, 3.0])
        painter.setPen(pen)
        painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 5, 5)
        vertical, horizontal = self.corner.split("_")
        dx, dy = (1 if horizontal == "left" else -1), (1 if vertical == "top" else -1)
        # The 7 px bracket sits centred in the square, its corner towards the square's corner.
        inset_x, inset_y = (self.width() - 7) / 2, (self.height() - 7) / 2
        x = inset_x if horizontal == "left" else self.width() - inset_x
        y = inset_y if vertical == "top" else self.height() - inset_y
        stroke = QPen(bracket, 1.8)
        stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(stroke)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(x, y + dy * 7))
        path.lineTo(x, y)
        path.lineTo(x + dx * 7, y)
        painter.drawPath(path)
        if widgets.focus_ring_visible(self):
            painter.setOpacity(1)
            painter.setPen(QPen(_tone("signal"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 5, 5)
        painter.end()


class CornerGrid(QWidget):
    """The Corners cell: a 2 x 2 grid of corner buttons in screen order."""

    def __init__(self, peer, owner, parent=None):
        super().__init__(parent)
        self.setProperty("vernier", "plain")
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.buttons = {}
        for index, corner in enumerate(("top_left", "top_right", "bottom_left", "bottom_right")):
            button = _CornerButton(corner, lambda corner, peer=peer: owner._ledger_corner(peer, corner))
            self.buttons[corner] = button
            grid.addWidget(button, index // 2, index % 2)
        self.setFixedWidth(60)

    def reflect(self, corners, name, labels, platform_word, left_out):
        lock = "Left out: Put back to change its ways"
        for corner, button in self.buttons.items():
            kind = corners.get(corner, {}).get("state", "unavailable")
            title = tr(CORNER_TITLES[corner])
            if kind == "held":
                holder = labels.get(corners[corner].get("by"), tr("Another machine"))
                button.set_state("held", tr("Left out: Put back to change its ways") if left_out else tr("{name}'s corner").format(name=holder), tr("{corner} corner, held by {name}").format(corner=title, name=holder), False)
            elif kind == "unavailable":
                button.set_state("unavailable", tr("Left out: Put back to change its ways") if left_out else tr("Place {name} beside this {platform} first").format(name=name, platform=platform_word),
                                 tr("{corner} corner, unavailable").format(corner=title), False)
            else:
                on = kind == "on"
                button.set_state(kind, tr("Left out: Put back to change its ways") if left_out else tr("{corner} corner: click to turn it {state}").format(corner=title, state=tr("off" if on else "on")),
                                 tr("{corner} corner, {state}").format(corner=title, state=tr("on" if on else "off")), not left_out)


class _Name(QLabel):
    def __init__(self):
        super().__init__()
        self.full_text = ""
        self.setMinimumWidth(0)
        self.setFont(theme.font(theme.TYPE["body"], 600))

    def set_name(self, text):
        self.full_text = text
        self.setAccessibleName(text)
        self.setToolTip(text)
        self._fit()

    def sizeHint(self):
        return QSize(132, self.fontMetrics().height())

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height())

    def _fit(self):
        self.setText(QFontMetrics(self.font()).elidedText(self.full_text, Qt.TextElideMode.ElideRight, max(1, self.width())))

    def resizeEvent(self, event):
        self._fit()
        super().resizeEvent(event)


class _Jump(widgets.JumpKeyRecorder):
    def __init__(self, callback, on_arm):
        super().__init__(callback, on_arm)
        self.setMinimumHeight(24)
        self.layout().setContentsMargins(5, 2, 5, 2)
        self.key.setFont(theme.mono_font(theme.TYPE["small"]))
        self.hint.hide()

    def sizeHint(self):
        return QSize(self.key.fontMetrics().horizontalAdvance(self.key.text()) + 10,
                     24 if not self.armed else 56)

    def heightForWidth(self, width):
        return 24 if not self.armed else 56

    def set_value(self, value):
        super().set_value(value)
        if not value and not self.armed:
            self.key.setText(tr("Set a key"))
        self._reflect_style()

    def _reflect_style(self):
        chip = bool(self.value) or self.armed
        widgets.set_role(self, "keycap-live" if self.armed else "keycap" if chip else "plain")
        self.key.setFont(theme.mono_font(theme.TYPE["small"]) if chip else theme.font(theme.TYPE["note"]))
        if chip:
            self.setStyleSheet("")
        else:
            _quiet_style(self)

    def _toggle(self):
        super()._toggle()
        self._reflect_style()
        self.hint.setVisible(self.armed)
        self.updateGeometry()

    def cancel(self):
        super().cancel()
        self._reflect_style()
        self.hint.hide()
        self.updateGeometry()

    def eventFilter(self, watched, event):
        if self.armed and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.cancel()
            return True
        return super().eventFilter(watched, event)


class _Cycle(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.colour("ground")), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        points = [QPointF(rect.x() + rect.width() * x, rect.y() + rect.height() * y)
                  for x, y in ((.25, .52), (.43, .7), (.78, .28))]
        painter.drawLine(points[0], points[1])
        painter.drawLine(points[1], points[2])
        painter.end()


# Machine, Edges, Corners, Keys: minimum width and stretch, the spec's minmax(132, 1.3fr), minmax(220, 2fr), 70, minmax(128, 1fr).
COLUMNS = ((N_("Machine"), 132, 13), (N_("Edges"), 220, 20), (N_("Corners"), 70, 0), (N_("Keys"), 128, 10))


class LedgerRow(QFrame):
    def minimumSizeHint(self):
        return QSize(0, self.grid.minimumSize().height())

    def __init__(self, peer, owner):
        super().__init__()
        self.peer, self.owner, self.selected, self.narrow = peer, owner, False, None
        self.remote = self.remote_mac = self.read_only = False
        self.setProperty("ledger_role", "row")
        self.setProperty("vernier", "plain")
        self.setMinimumWidth(0)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(12, 12, 0, 12)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        self.cells = []
        for _ in range(4):
            cell = QWidget(self)
            cell.setProperty("vernier", "plain")
            cell.setProperty("ledger_role", "cell")
            cell.setMinimumWidth(0)
            self.cells.append(cell)
        self.machine, self.edge, self.corner_cell, self.keys = self.cells
        self.machine.setProperty("ledger_role", "rowheader")
        machine = QVBoxLayout(self.machine)
        machine.setContentsMargins(0, 0, 0, 0)
        machine.setSpacing(2)
        machine.setSizeConstraint(machine.SizeConstraint.SetMinimumSize)
        self.name = _Name()
        self.name.installEventFilter(self)
        self.machine.installEventFilter(self)
        self.status = widgets.label("", "small", wrap=True)
        self.status.installEventFilter(self)
        status_line = QHBoxLayout()
        status_line.setSpacing(6)
        self.dot = QLabel()
        self.dot.setFixedSize(6, 6)
        status_line.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        status_line.addWidget(self.status, 1)
        self.edit = QLineEdit()
        self.edit.setMinimumWidth(0)
        self.edit.hide()
        self.edit.returnPressed.connect(self.save_name)
        self.edit.installEventFilter(self)
        self.rename_hint = widgets.label(tr("Return saves, Escape cancels · Only on this PC"), "small", wrap=True)
        self.rename_hint.hide()
        machine.addWidget(self.name)
        machine.addWidget(self.edit)
        machine.addWidget(self.rename_hint)
        machine.addLayout(status_line)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.rename = _quiet(tr("Rename"), self.begin_rename)
        self.leave = _quiet(tr("Leave out"), lambda: owner._canvas_left_out(peer, not self.left_out))
        actions.addWidget(self.rename)
        actions.addWidget(self.leave)
        actions.addStretch()
        machine.addLayout(actions)
        machine.addStretch()
        self.edge_chips = EdgeChips(peer, owner)
        edges = QVBoxLayout(self.edge)
        edges.setContentsMargins(0, 0, 0, 0)
        edges.setSpacing(2)
        edges.addWidget(self.edge_chips, 0, Qt.AlignmentFlag.AlignTop)
        self.edge_note = widgets.label(tr("Place it on the map"), "small", wrap=True)
        edges.addWidget(self.edge_note, 0, Qt.AlignmentFlag.AlignTop)
        edges.addStretch()
        self.corner_grid = CornerGrid(peer, owner)
        corners = QVBoxLayout(self.corner_cell)
        corners.setContentsMargins(0, 0, 0, 0)
        corners.addWidget(self.corner_grid, 0, Qt.AlignmentFlag.AlignTop)
        corners.addStretch()
        keys = QVBoxLayout(self.keys)
        keys.setContentsMargins(0, 0, 0, 0)
        keys.setSpacing(4)
        self.cycle = _Cycle()
        self.cycle.setFont(theme.font(theme.TYPE["body"]))
        self.cycle.setToolTip(tr("In the shortcut's cycle"))
        self.cycle.toggled.connect(lambda on: owner._set_shortcut_cycle(peer, on))
        keys.addWidget(self.cycle)
        jump = QHBoxLayout()
        jump.setSpacing(5)
        jump.addWidget(widgets.label(tr("Jump"), "small"))
        self.jump = _Jump(lambda value: owner._ledger_jump(peer, value), owner._jump_arming)
        jump.addWidget(self.jump, 0, Qt.AlignmentFlag.AlignLeft)
        self.clear = _quiet(tr("Clear"), lambda: owner._ledger_jump(peer, ""))
        self.clear.setAccessibleName(tr("Clear jump key"))
        jump.addWidget(self.clear)
        jump.addStretch()
        keys.addLayout(jump)
        keys.addStretch()
        self.notch_cell = QWidget(self)
        self.notch_cell.setProperty("vernier", "plain")
        self.notch_cell.setProperty("ledger_role", "cell")
        notch_layout = QVBoxLayout(self.notch_cell)
        notch_layout.setContentsMargins(0, 0, 0, 0)
        notch_layout.setSpacing(4)
        self.notch = QCheckBox(tr("Notch"))
        self.notch.toggled.connect(lambda on: owner._write_ways(peer=peer, notch=on))
        notch_layout.addWidget(self.notch)
        self.notch_return = QCheckBox(tr("Return here"))
        self.notch_return.toggled.connect(lambda on: owner._write_ways(peer=peer, notch_return=on))
        notch_layout.addWidget(self.notch_return)
        notch_layout.addStretch()
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.reflow(False)

    def reflow(self, narrow, remote=None, remote_mac=None):
        remote = self.remote if remote is None else remote
        remote_mac = self.remote_mac if remote_mac is None else remote_mac
        if (self.narrow, self.remote, self.remote_mac) == (narrow, remote, remote_mac):
            return
        self.narrow, self.remote, self.remote_mac = narrow, remote, remote_mac
        for cell in (*self.cells, self.notch_cell):
            self.grid.removeWidget(cell)
        self.keys.setVisible(not remote)
        self.notch_cell.setVisible(remote_mac)
        self.rename.setVisible(not remote)
        self.leave.setVisible(not remote)
        if remote:
            self.jump.cancel()
            self.cancel_name()
        cells = self.cells[:3] + ([self.notch_cell] if remote_mac else [] if remote else [self.keys])
        for col in range(4):
            self.grid.setColumnMinimumWidth(col, 0)
            self.grid.setColumnStretch(col, 0)
        if narrow:
            self.grid.addWidget(self.machine, 0, 0, 1, 2)
            self.grid.addWidget(self.edge, 1, 0, 1, 2)
            self.grid.addWidget(self.corner_cell, 2, 0)
            if len(cells) == 4:
                self.grid.addWidget(cells[3], 2, 1)
            self.grid.setColumnMinimumWidth(0, COLUMNS[2][1])
            self.grid.setColumnStretch(1, 1)
        else:
            for index, (cell, (_title, minimum, stretch)) in enumerate(zip(cells, COLUMNS)):
                self.grid.addWidget(cell, 0, index)
                self.grid.setColumnMinimumWidth(index, minimum)
                self.grid.setColumnStretch(index, stretch)

    def reflect(self, settings, entry, name, side, linked, selected, trigger, labels, legacy="", reach=None):
        self.read_only = bool(getattr(self.owner, "_profile_read_only", lambda: False)())
        seen = (theme.is_dark(), id(settings), repr(entry), name, side, linked, selected, trigger,
                repr(labels), legacy, repr(reach), self.remote, self.remote_mac, self.read_only)
        if seen == getattr(self, "_reflection_seen", None):
            return
        self._reflection_seen = seen
        self._reflection = (settings, entry, name, side, linked, selected, trigger, labels, legacy, reach)
        for button in (self.rename, self.leave, self.clear):
            _quiet_style(button)
        self.entry, self.left_out, self.selected = entry, bool(entry.get("left_out")), selected
        self.setAccessibleName(name)
        self.machine.setAccessibleName(name)
        self.name.set_name(name)
        self.name.setStyleSheet(f"color: {theme.colour('ink' if linked and not self.left_out else 'ink_2')}")
        platform = {"windows": N_("Windows"), "macos": N_("macOS"), "linux": N_("Linux")}.get(
            entry.get("platform"), N_("Computer"))
        status = tr("Left out") if self.left_out else tr("Linked") if linked else tr("Offline, ways kept")
        self.status.setText(legacy if legacy else tr("{platform} · {status}").format(platform=tr(platform), status=status))
        self.status.setStyleSheet(f"color: {theme.colour('amber' if legacy else 'ink_3')}")
        self.dot.setStyleSheet(f"background: {theme.colour('amber' if legacy else 'signal' if linked and not self.left_out else 'ink_3')}; border-radius: 3px;")
        self.status.setAccessibleDescription(tr("Linked") if linked else status)
        self.leave.setText(tr("Put back" if self.left_out else "Leave out"))
        self.leave.setToolTip(tr("Left out machines stay paired and linked. The shortcut, menu and clipboard still reach them." if self.left_out else "Leave this machine out of crossings"))
        held = ways.ways(settings, self.peer)
        picked = ways.picked_thirds(held["methods"], held["parts"])
        edge_on = bool(picked)
        reach = reach or {}
        # A left-out row's reach is answered as if put back; `self.left_out` makes it inert below.
        sides, corners = reach.get("sides", {}), reach.get("corners", {})
        corners ={corner: ({"state": "on"} if corner in held["corners"] and value.get("state") == "unavailable" else value)
                   for corner, value in corners.items()}
        contact = next((edge for edge, value in sides.items() if value.get("state") == "contact"), "")
        self.edge_chips.reflect(sides, name, labels, edge_on, picked if edge_on else (), contact, self.left_out)
        self.edge_note.setVisible(not self.edge_chips.any_shown())
        self.corner_grid.reflect(corners, name, labels, tr("Mac") if self.remote_mac else tr("PC"), self.left_out)
        self.edge_chips.setEnabled(not self.read_only)
        self.corner_grid.setEnabled(not self.read_only)
        self.notch_cell.setEnabled(not self.read_only and not self.left_out)
        notch_on = "notch" in held["methods"]
        for check, value in ((self.notch, notch_on),
                             (self.notch_return, entry.get("notch_return", False))):
            check.blockSignals(True)
            check.setChecked(bool(value))
            check.blockSignals(False)
        self.notch.setAccessibleName(tr("Notch, on") if notch_on else tr("Notch, off"))
        self.notch.setToolTip(tr("Push into the notch to reach {name}").format(name=name))
        self.notch_return.setVisible(notch_on)
        self.notch_return.setAccessibleName(tr("Return through the notch, on") if self.notch_return.isChecked()
                                           else tr("Return through the notch, off"))
        self.notch_return.setToolTip(tr("Coming back from {name}, arrive just below the notch").format(name=name))
        self.cycle.blockSignals(True)
        self.cycle.setText(trigger)
        self.cycle.setChecked(entry.get("shortcut_cycle", True))
        self.cycle.blockSignals(False)
        self.jump.set_value(entry.get("jump_key", ""))
        self.jump.setToolTip(tr("Press {key} to send input to {name}; press again to bring it home.").format(key=self.jump.key.text(), name=name) if self.jump.value else tr("Choose a key combination to jump to {name} and back.").format(name=name))
        self.clear.setVisible(bool(self.jump.value))
        self.effect.setOpacity(.5 if self.left_out or not linked else 1)
        self.update()

    def refresh_colours(self):
        if hasattr(self, "_reflection"):
            self.reflect(*self._reflection)

    def begin_rename(self):
        if self.remote or self.read_only:
            return
        self.edit.setText(self.entry.get("label") or self.entry.get("name") or "")
        self.name.hide()
        self.edit.show()
        self.rename_hint.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def save_name(self):
        if not self.remote and not self.read_only:
            self.owner._rename_canvas_peer(self.peer, self.edit.text().strip()[:64])
        self.cancel_name()

    def cancel_name(self):
        self.edit.hide()
        self.rename_hint.hide()
        self.name.show()

    def eventFilter(self, watched, event):
        if watched is self.edit and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.cancel_name()
            return True
        if watched in (self.machine, self.name, self.status) and event.type() == QEvent.Type.MouseButtonPress:
            self.owner._choose_machine(self.peer)
            return True
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor(theme.colour("rule")), 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        if self.selected:
            painter.fillRect(0, 12, 3, max(1, self.height() - 24), QColor(theme.colour("signal")))
        painter.end()


class CrossingLedger(QWidget):
    def minimumSizeHint(self):
        return QSize(0, self.column.minimumSize().height())

    def __init__(self, owner):
        super().__init__()
        self.owner, self.rows, self.narrow = owner, {}, False
        self.setProperty("ledger_role", "table")
        self.setProperty("vernier", "plain")
        self.setAccessibleName(tr("How each machine is reached"))
        self.setMinimumWidth(0)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(0)
        self.header = QWidget()
        self.header.setProperty("vernier", "plain")
        head = QGridLayout(self.header)
        head.setContentsMargins(12, 0, 0, 8)
        head.setHorizontalSpacing(16)
        for index, (title, minimum, stretch) in enumerate(COLUMNS):
            label = widgets.Eyebrow(tr(title))
            label.setProperty("ledger_role", "columnheader")
            label.setAccessibleName(tr(title))
            head.addWidget(label, 0, index)
            head.setColumnMinimumWidth(index, minimum)
            head.setColumnStretch(index, stretch)
        self.header.setStyleSheet(f"border-bottom: 1px solid {theme.colour('rule')};")
        self.column.addWidget(self.header)

    def cancel_recording(self):
        for row in self.rows.values():
            row.jump.cancel()

    def refresh_colours(self):
        self.header.setStyleSheet(f"border-bottom: 1px solid {theme.colour('rule')};")

    def reflect(self, settings, layout, labels, chosen, live, trigger, legacy=None, reach=None):
        self.header.setStyleSheet(f"border-bottom: 1px solid {theme.colour('rule')};")
        remote = bool(getattr(self.owner, "_profile_remote", lambda: False)())
        if remote and hasattr(self.owner, "_crossing_view_settings"):
            settings = self.owner._crossing_view_settings()
        remote_mac = (remote and hasattr(self.owner, "_profile_settings")
                      and hasattr(self.owner, "_profile_machine")
                      and profiles.view_platform(self.owner._profile_settings(), self.owner._profile_machine()) == "mac")
        head = self.header.layout()
        last_header = head.itemAtPosition(0, 3).widget()
        last_header.setVisible(not remote or remote_mac)
        last_header.setText(tr("Notch") if remote_mac else tr("Keys"))
        last_header.setAccessibleName(tr("Notch") if remote_mac else tr("Keys"))
        head.setColumnMinimumWidth(3, COLUMNS[3][1] if not remote or remote_mac else 0)
        head.setColumnStretch(3, COLUMNS[3][2] if not remote or remote_mac else 0)
        entries = {p["id"]: p for p in settings.get("peers", [])}
        order = sorted(entries, key=lambda p: (0, layout[p]["x"], layout[p]["y"]) if p in layout else (1, 0, 0))
        for peer in self.rows.keys() - entries.keys():
            row = self.rows.pop(peer)
            row.jump.cancel()
            self.column.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        for index, peer in enumerate(order):
            row = self.rows.get(peer)
            if row is None:
                row = LedgerRow(peer, self.owner)
                self.rows[peer] = row
            row.reflow(self.narrow, remote, remote_mac)
            if self.column.indexOf(row) != index + 1:
                self.column.insertWidget(index + 1, row)
            own = layout.get(settings.get("machine_id"))
            tile = layout.get(peer)
            contact = ways._rect_contact(own, tile) if own and tile else None
            side = contact[0] if contact and contact[0] != "corner" else ""
            row.reflect(settings, entries[peer], labels.get(peer, tr("Other machine")), side, live(peer), chosen == peer, trigger, labels, (legacy or {}).get(peer, ""), (reach or {}).get(peer))
        self.setVisible(bool(entries))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < 620
        if narrow != self.narrow:
            self.narrow = narrow
            self.header.setVisible(not narrow)
            for row in self.rows.values():
                row.reflow(narrow)
