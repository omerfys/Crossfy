"""The Crossing page's two pictures: the arrangement diagram at the top of Ways in, and the push
strip in Resistance. Geometry is pages_win's, pure and tested; this file only paints it."""

from __future__ import annotations

from core.i18n import N_, tr, trc
import sys

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import QLineEdit, QPushButton, QSlider, QSizePolicy, QToolTip, QWidget

import motion
import pages_win
import theme
import tokens
from core import ways
from core.resistance_strip import MAX_RESISTANCE, resistance_x

OTHER = N_("Other machine")
DASHBOARD_NAME = N_("This PC")
DIRECTION_NAMES = {"left": N_("left"), "right": N_("right"), "top": N_("top"), "bottom": N_("bottom")}
ATLAS_TILE = (160, 100)
SCREEN = (120.0, 75.0)
GAP = 14.0
PAD = 8.0
CAP_ROW = 34.0
NOTE_ROW = 22.0
LIT = 3.0
CORNER = 16.0
# The marks of the machines the page is not showing: there, but not the ones being edited.
QUIET = "ink_3"
QUIET_ALPHA = 0.55
# The clear space centred on each third boundary of the selected machine's seam and tracks.
THIRD_GAP = 2.0
CYCLE_BOX = 16.0
RESIZE_GRIP = 16.0
RESIZE_HELP = N_("Tile size can be changed by dragging a corner or pressing Alt+arrow.")


def _colour(name: str, alpha: float = 1.0) -> QColor:
    colour = QColor(theme.colour(name))
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


def _lit(lead: float, level: float) -> QColor:
    """A mark on this PC's screen: the signal colour for the machine shown, quieter for the rest."""
    lead = max(0.0, min(1.0, lead))
    return _blend(QUIET, "signal", lead, level * (QUIET_ALPHA + (1.0 - QUIET_ALPHA) * lead))


def _blend(quiet: str, strong: str, level: float, alpha: float = 1.0) -> QColor:
    """`quiet` at 0, `strong` at 1, so a machine chosen or left eases between the two."""
    one, two = QColor(theme.colour(quiet)), QColor(theme.colour(strong))
    level = max(0.0, min(1.0, level))
    mixed = QColor.fromRgbF(*(a + (b - a) * level for a, b in zip(one.getRgbF()[:3], two.getRgbF()[:3])))
    mixed.setAlphaF(max(0.0, min(1.0, alpha)))
    return mixed


def _drawn_side(machine: dict, alone: bool) -> str:
    # One machine with no side is drawn on the right, as the one-machine page always drew it.
    return machine.get("side") or ("right" if alone else "")


def _marks(machines, shortcut) -> dict:
    """Each mark the diagram can draw, keyed (kind, machine, detail), at 1 when the settings light it;
    ("lead", machine) at 1 lights its marks in the signal colour, ("named", machine) its name in ink."""
    alone = len(machines) == 1
    marks = {("cap",): 1.0 if shortcut else 0.0}
    for machine in machines:
        key, methods = machine["key"], set(machine["methods"])
        edge = _drawn_side(machine, alone) if machine.get("side") else ""
        for side in pages_win.SIDE_ANGLE:
            marks[("edge", key, side)] = 1.0 if "edge" in methods and side == edge else 0.0
            marks[("track", key, side)] = 1.0 if "part" in methods and side == edge else 0.0
            for part in pages_win.PART_SPANS:
                lit = "part" in methods and side == edge and part in machine["parts"]
                marks[("part", key, side, part)] = 1.0 if lit else 0.0
        for name in pages_win.CORNER_NAMES:
            marks[("corner", key, name)] = 1.0 if "corner" in methods and name == machine["corner"] else 0.0
        marks[("lead", key)] = 1.0 if machine["chosen"] or alone else 0.0
        marks[("named", key)] = 1.0 if machine["chosen"] and not alone else 0.0
    return marks


class ArrangementDiagram(QWidget):
    """This PC's screen in the middle and each paired machine's beside the side it is on, two on one
    side sharing it; on this PC's screen, lit, whatever crosses to each, the chosen machine's in the
    signal colour and the rest quieter; the machines with no side named underneath; the shortcut as a
    key cap below that."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Arrangement"))
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._state = None
        self._machines: list = []
        # Where each machine's screen is drawn now, by key: [angle, start, end, shown], moving between states.
        self._places: dict = {}
        self._labels: dict = {}
        self._marks = _marks([], False)
        self._unplaced = ""
        self._cap_text = ""

    def sizeHint(self) -> QSize:
        return QSize(2 * round(SCREEN[0]) + round(GAP) + 2 * round(PAD), self._height())

    def minimumSizeHint(self) -> QSize:
        return QSize(2 * round(SCREEN[0]) + round(GAP), self._height())

    def _drawing(self, width: float):
        keys = [key for key, place in self._places.items() if place[3] > 0.001]
        placed = [tuple(self._places[key][:3]) for key in keys]
        available = max(1.0, width - 2 * PAD)
        centre_pc = len(self._machines) > 1
        pc, rects, _height = pages_win.layout_rects(available, PAD, placed, SCREEN, GAP,
                                                    centre_pc=centre_pc)
        bounds_left = min([pc[0], *(rect[0] for rect in rects)])
        bounds_right = max([pc[0] + pc[2], *(rect[0] + rect[2] for rect in rects)])
        scale = available * 0.9 / max(1.0, bounds_right - bounds_left)
        screen = (SCREEN[0] * scale, SCREEN[1] * scale)
        gap = GAP * scale
        pc, rects, height = pages_win.layout_rects(available, PAD, placed, screen, gap,
                                                   centre_pc=centre_pc)
        metrics = QFontMetrics(theme.font(tokens.TYPE["small"], 600))
        needed = max((metrics.boundingRect(QRectF(0, 0, max(1, rect[2] - 8), 10000).toRect(),
                      int(Qt.TextFlag.TextWrapAnywhere), name).height() + 4
                      for rect, name in [(pc, tr(DASHBOARD_NAME)), *[(rect, self._labels.get(key, tr(OTHER)))
                                          for key, rect in zip(keys, rects)]]), default=screen[1])
        if needed > min([pc[3], *(rect[3] for rect in rects)]):
            screen = (screen[0], screen[1] * needed / max(1, min([pc[3], *(rect[3] for rect in rects)])))
            pc, rects, height = pages_win.layout_rects(available, PAD, placed, screen, gap,
                                                     centre_pc=centre_pc)
        return (pc[0] + PAD, pc[1], pc[2], pc[3]), {key: (rect[0] + PAD, *rect[1:]) for key, rect in zip(keys, rects)}, height

    def _height(self, width: int | None = None) -> int:
        _pc, _rects, height = self._drawing(float(width if width is not None else self.width() or 2 * SCREEN[0] + GAP + 2 * PAD))
        return round(PAD + height + PAD + (NOTE_ROW if self._unplaced else 0.0) + CAP_ROW * self._marks[("cap",)])

    def heightForWidth(self, width: int) -> int:
        return self._height(width)

    def set_machines(self, machines, key_name, style, shortcut) -> None:
        """Each machine a dict: `key`, `label` ("" for the placeholder of an unpaired PC), `side` (""
        when not placed), `methods`, `parts`, `corner` and `chosen`."""
        machines = [dict(machine, methods=list(machine["methods"]), parts=list(machine["parts"])) for machine in machines]
        state = (repr(machines), key_name, style, shortcut)
        if state == self._state:
            return
        first = self._state is None
        self._state = state
        self._machines = machines
        alone = len(machines) == 1
        self._labels = {machine["key"]: machine["label"] or tr(OTHER) for machine in machines}
        if shortcut:
            self._cap_text = pages_win.trigger_phrase(key_name, style)
        self._unplaced = "" if alone else pages_win.unplaced_line(
            [machine["label"] for machine in machines if not machine.get("side")])
        self.setAccessibleDescription(pages_win.diagram_description(
            [dict(machine, label=self._labels[machine["key"]]) for machine in machines],
            key_name, style, shortcut))
        targets = _marks(machines, shortcut)
        slots = pages_win.side_slots([dict(machine, side=_drawn_side(machine, alone)) for machine in machines])
        ends = {}
        for machine, slot in zip(machines, slots):
            held = self._places.get(machine["key"])
            if slot is None:
                ends[machine["key"]] = list(held[:3]) + [0.0] if held else [0.0, 0.0, 1.0, 0.0]
                continue
            side, start, end = slot
            # A machine already drawn goes round to its new side; one just placed fades in there.
            drawn = held is not None and held[3] > 0.0 and not first
            angle = pages_win.turn_to(held[0], side) if drawn else pages_win.SIDE_ANGLE[side]
            ends[machine["key"]] = [angle, start, end, 1.0]
        for key, held in self._places.items():
            # A machine removed or no longer placed fades where it was.
            ends.setdefault(key, list(held[:3]) + [0.0])
        starts = {}
        for key, end in ends.items():
            held = self._places.get(key)
            starts[key] = list(held) if held is not None and held[3] > 0.0 else end[:3] + [0.0]
        start_marks = dict(self._marks)

        def apply(t):
            self._places = {key: [a + (b - a) * t for a, b in zip(starts[key], end)] for key, end in ends.items()}
            self._marks = {key: start_marks.get(key, 0.0) + (targets.get(key, 0.0) - start_marks.get(key, 0.0)) * t
                           for key in set(targets) | set(start_marks)}
            self.updateGeometry()
            self.update()

        def settle():
            self._places = {key: [end[0] % 360.0, end[1], end[2], end[3]] for key, end in ends.items() if end[3] > 0.0
                            or key in self._labels}
            self._marks = {key: level for key, level in targets.items()}
            self.updateGeometry()
            self.update()

        if first:
            apply(1.0)
            settle()
            return
        motion.animate(self, "arrangement", 0.0, 1.0, apply, settle)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pc, rects, height = self._drawing(float(self.width()))
        radius = tokens.RADIUS["field"]
        for key, rect in rects.items():
            painter.setOpacity(self._places[key][3])
            named = self._marks.get(("named", key), 0.0)
            self._screen(painter, QRectF(*rect), self._labels.get(key, tr(OTHER)), "panel", _blend("edge", "ink_3", named),
                         _blend("ink_3", "ink", named), radius)
        painter.setOpacity(1.0)
        self._screen(painter, QRectF(*pc), tr(DASHBOARD_NAME), "well", _colour("edge"), _colour("ink_2"), radius)
        # The machines not shown first, so the chosen one's marks lie over theirs where they meet.
        for key, level in sorted(self._marks.items(), key=lambda item: self._marks.get(("lead", item[0][1]), 0.0)
                                 if len(item[0]) > 1 else 0.0):
            if level <= 0.001 or key[0] in ("cap", "lead", "named"):
                continue
            kind, lead = key[0], self._marks.get(("lead", key[1]), 0.0)
            if kind == "edge":
                self._segment(painter, pc, key[2], 0.0, 1.0, level, lead, LIT)
            elif kind == "track":
                self._track(painter, pc, key[2], level)
            elif kind == "part":
                start, end = pages_win.PART_SPANS[key[3]]
                self._segment(painter, pc, key[2], start, end, level, lead, LIT, gap=2.0)
            elif kind == "corner":
                self._corner(painter, pc, key[2], level, lead)
        top = PAD + height + PAD
        if self._unplaced:
            painter.setPen(_colour("ink_3"))
            painter.setFont(theme.font(tokens.TYPE["note"]))
            line = QRectF(PAD, top, self.width() - 2 * PAD, NOTE_ROW)
            painter.drawText(line, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             painter.fontMetrics().elidedText(self._unplaced, Qt.TextElideMode.ElideRight, int(line.width())))
            top += NOTE_ROW
        level = self._marks[("cap",)]
        if level > 0.001 and self._cap_text:
            self._cap(painter, top, level)
        painter.end()


    def _screen(self, painter, rect: QRectF, name, fill, line: QColor, ink: QColor, radius) -> None:
        painter.setPen(QPen(line, 1.0))
        painter.setBrush(_colour(fill))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.setPen(ink)
        painter.setFont(theme.font(tokens.TYPE["small"], 600))
        metrics = painter.fontMetrics()
        room = rect.adjusted(4, 2, -4, -2)
        wrapped = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWrapAnywhere
        painter.drawText(room, wrapped, name)

    @staticmethod
    def _segment(painter, rect, side, start, end, level, lead, width, gap=0.0) -> None:
        # Grows from its middle as it comes in.
        middle = (start + end) / 2.0
        half = (end - start) / 2.0 * level
        x1, y1, x2, y2 = pages_win.side_segment(rect, side, middle - half, middle + half, inset=width / 2.0 + 1.0)
        if gap and level > 0:
            if x1 == x2:
                y1, y2 = y1 + gap, y2 - gap
            else:
                x1, x2 = x1 + gap, x2 - gap
        pen = QPen(_lit(lead, level), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _track(self, painter, rect, side, level) -> None:
        """Part of the edge: the whole side as a dim track, with a divider between the thirds."""
        pen = QPen(_colour("off", level), LIT)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        x1, y1, x2, y2 = pages_win.side_segment(rect, side, 0.5 - 0.5 * level, 0.5 + 0.5 * level, inset=LIT / 2.0 + 1.0)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        pen = QPen(_colour("edge", level), 1.0)
        painter.setPen(pen)
        for fraction in (1.0 / 3.0, 2.0 / 3.0):
            x1, y1, _x2, _y2 = pages_win.side_segment(rect, side, fraction, fraction, inset=LIT / 2.0 + 1.0)
            if side in ("left", "right"):
                painter.drawLine(QPointF(x1 - 5, y1), QPointF(x1 + 5, y1))
            else:
                painter.drawLine(QPointF(x1, y1 - 5), QPointF(x1, y1 + 5))

    @staticmethod
    def _corner(painter, rect, corner, level, lead) -> None:
        size = CORNER * (0.4 + 0.6 * level)
        x, y, w, h = pages_win.corner_box(rect, corner, size)
        box = QRectF(x, y, w, h).adjusted(2, 2, -2, -2)
        painter.setPen(QPen(_lit(lead, level), 1.5))
        painter.setBrush(_lit(lead, 0.35 * level))
        painter.drawRoundedRect(box, 2, 2)

    def _cap(self, painter, top, level) -> None:
        key, _sep, how = self._cap_text.partition(", ")
        face = theme.mono_font(tokens.TYPE["small"], 700)
        painter.setFont(face)
        metrics = painter.fontMetrics()
        key_w = metrics.horizontalAdvance(key) + 18
        rest = f", {how}"
        body = theme.font(tokens.TYPE["note"])
        painter.setFont(body)
        rest_w = painter.fontMetrics().horizontalAdvance(rest)
        total = key_w + 2 + rest_w
        left = (self.width() - total) / 2.0
        cap = QRectF(left, top + 2 + (1.0 - level) * 6.0, key_w, 24)
        painter.setOpacity(level)
        painter.setPen(QPen(_colour("edge"), 1.0))
        painter.setBrush(_colour("ground"))
        painter.drawRoundedRect(cap.adjusted(0.5, 0.5, -0.5, -0.5), tokens.RADIUS["keycap"], tokens.RADIUS["keycap"])
        painter.setPen(QPen(_colour("edge"), 2.0))
        painter.drawLine(QPointF(cap.left() + 3, cap.bottom() - 1), QPointF(cap.right() - 3, cap.bottom() - 1))
        painter.setPen(_colour("signal"))
        painter.setFont(face)
        painter.drawText(cap.adjusted(0, 0, 0, -2), Qt.AlignmentFlag.AlignCenter, key)
        painter.setPen(_colour("ink_2"))
        painter.setFont(body)
        painter.drawText(QRectF(cap.right() + 2, cap.top(), rest_w + 4, cap.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, rest)
        painter.setOpacity(1.0)


def outcome_for_tile(state, crosses, is_own=False, other_name=""):
    if is_own:
        return ""
    if state in ("between", "set-elsewhere", "set_elsewhere") and other_name:
        return f"Crosses to {other_name}" if state == "between" else f"Set on {other_name}"
    if state in ("between", "set-elsewhere", "set_elsewhere"):
        return "Set elsewhere"
    if state == "gap" or not crosses:
        return "Drag to connect" if state == "gap" else "Edge off"
    return "Crosses"


class AtlasCanvas(QWidget):
    """One tile per paired machine, laid out around this screen with shared edge snaps."""

    def __init__(self, parent=None, on_drop=None, on_rename=None, on_leave_out=None, on_cycle=None,
                 on_select=None, on_third=None, on_edit_machine=None):
        super().__init__(parent)
        self.on_drop = on_drop or (lambda *_: None)
        self.on_rename = on_rename or (lambda *_: None)
        self.on_leave_out = on_leave_out or (lambda *_: None)
        self.on_cycle = on_cycle or (lambda *_: None)
        self.on_select = on_select or (lambda *_: None)
        self.on_third = on_third or (lambda *_: None)
        self.on_edit_machine = on_edit_machine or (lambda *_: None)
        self.profile_mode = False
        self.remote = False
        self.read_only = False
        self._profile_press = None
        self._profile_press_point = None
        self.on_announce = None
        self.on_hint = None
        self.on_rename_state = None
        self.setMinimumHeight(268)
        self.setMaximumHeight(268)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName(tr("Crossing layout"))
        self.setToolTip("")
        self.tiles = {}
        self.labels = {}
        self.states = {}
        self.selected = None
        self.own_id = None
        self.shelf_ids = set()
        self.left_out_ids = set()
        self.in_use = {}
        self.cycle = {}
        self.cycle_mode = "last"
        self.capable = set()
        self._drag = None
        self._resizing = False
        self._drag_display = None
        self._display_offset_start = None
        self._dragged_display = False
        self._split_on_release = False
        self._group_on_release = False
        self._keyboard_focus = False
        self._hover = None
        self._third_press = None
        self.corner_marks = []
        self.wrap_marks = []
        self.wrap_label_rects = []
        self.seam_paths = []
        self.ledger_height = False
        self._height_timer = QTimer(self)
        self._height_timer.setSingleShot(True)
        self._height_timer.timeout.connect(self._fit_ledger_height)
        self._origin = None
        self._scale = 1.0
        self._bounds = (0, 0, 1, 1)
        self._recentre_colours = None
        self.recentre_button = QPushButton(tr("Recentre"), self)
        self.recentre_button.setFont(theme.font(tokens.TYPE["note"]))
        self.recentre_button.setFixedSize(76, 26)
        self.recentre_button.clicked.connect(self.recentre)
        self.recentre_button.setVisible(False)
        self.recentre_button.installEventFilter(self)
        self.rename_edit = QLineEdit(self)
        self.rename_edit.setFont(theme.font(tokens.TYPE["body"]))
        self.rename_edit.setFixedHeight(28)
        self.rename_edit.setStyleSheet("QLineEdit { border-radius: 4px; padding: 3px 6px; }")
        self._rename_peer = None
        self.rename_edit.setVisible(False)
        self.rename_edit.returnPressed.connect(self._save_rename)
        self.rename_edit.installEventFilter(self)

    def set_tiles(self, tiles, labels, states, selected, cycle_mode="last", cycle=None, capable=(), own_id=None,
                  rename_values=None):
        seen = (tiles, labels, states, selected, cycle_mode, cycle, tuple(sorted(capable or ())), own_id,
                rename_values, self.profile_mode, self.remote, self.read_only)
        if seen == getattr(self, "_tiles_seen", None):
            return
        self._tiles_seen = seen
        self.tiles = {key: dict(tile) for key, tile in tiles.items()}
        self.labels = dict(labels)
        self.rename_values = dict(rename_values if rename_values is not None else labels)
        self.states = {key: dict(state) for key, state in states.items()}
        self.selected = selected if selected in tiles else next(iter(tiles), None)
        self.cycle_mode = cycle_mode
        self.cycle = dict(cycle or {})
        self.capable = set(capable)
        self.own_id = own_id
        if (self.remote or self.read_only) and self._rename_peer is not None:
            self._rename_peer = None
            self.rename_edit.hide()
            if self.on_rename_state:
                self.on_rename_state(False)
        if own_id in self.tiles and not self.remote:
            own_detail = self.states.get(own_id, {}).get("detail") or \
                ("Linux" if sys.platform.startswith("linux") else "Windows")
            self.states.setdefault(own_id, {}).update(
                detail=own_detail, linked=True
            )
        description = [self.labels.get(peer, OTHER) for peer in self.tiles]
        own_detail = self.states.get(own_id, {}).get("detail", "")
        if own_id in self.tiles and own_detail:
            description.append(own_detail)
        if not self.read_only and any(peer not in self.shelf_ids for peer in self.tiles):
            description.append(tr(RESIZE_HELP))
        self.setAccessibleDescription(trc("list", "; ").join(description))
        self._geometry()
        if self._drag is None:
            self.update()

    def set_left_out(self, peers, in_use=None, dormant=()):
        seen = (set(peers), in_use, set(dormant))
        if seen == getattr(self, "_left_out_seen", None):
            return
        self._left_out_seen = seen
        self.left_out_ids = set(peers)
        self.in_use = dict(in_use or {})
        self.shelf_ids = self.left_out_ids | set(dormant) | {peer for peer, enabled in self.in_use.items() if enabled is False}
        self._geometry()
        self.update()

    def set_cycle(self, peer, enabled):
        if self.remote or self.read_only:
            return
        self.cycle[peer] = bool(enabled)
        self.on_cycle(peer, bool(enabled))
        self.update()

    def put_back(self, peer):
        if not self.remote and not self.read_only:
            self.on_leave_out(peer, False)

    def leave_out(self, peer):
        if not self.remote and not self.read_only:
            self.on_leave_out(peer, True)

    def animate_tile(self, peer, target, done=None):
        current = self.tiles[peer]
        start = (current["x"], current["y"])
        end = (target["x"], target["y"])

        def apply(position):
            self.tiles[peer] = {**current, "x": round(position[0]), "y": round(position[1])}
            self._geometry()
            self.update()

        motion.animate(self, f"tile:{peer}", start, end, apply, done=done)

    def tile_rect(self, peer):
        tile = self.tiles[peer]
        x, y, w, h = (tile[k] for k in ("x", "y", "w", "h"))
        left, top, _width, _height = self._bounds
        return QRectF((x-left)*self._scale + self._origin.x(), (y-top)*self._scale + self._origin.y(),
                      w*self._scale, h*self._scale)

    def display_rect(self, peer, display):
        frame = next(frame for frame in ways._display_frames(self.tiles[peer]) if frame["display"] == display)
        left, top, _width, _height = self._bounds
        return QRectF((frame["x"]-left)*self._scale + self._origin.x(),
                      (frame["y"]-top)*self._scale + self._origin.y(),
                      frame["w"]*self._scale, frame["h"]*self._scale)

    def display_at(self, point):
        for peer in reversed(list(self.tiles)):
            if peer in self.shelf_ids or not self.tiles[peer].get("displays"):
                continue
            for frame in reversed(ways._display_frames(self.tiles[peer])):
                if self.display_rect(peer, frame["display"]).contains(point):
                    return peer, frame["display"]
        return None, None

    def _can_resize(self, peer):
        return not self.read_only and peer in self.tiles and peer not in self.shelf_ids

    def _resize_grip_rect(self, peer):
        if not self._can_resize(peer) or peer not in (self.selected, self._hover):
            return None
        rect = self.tile_rect(peer)
        size = min(RESIZE_GRIP, rect.width(), rect.height())
        grip = QRectF(rect.right()-size, rect.bottom()-size, size, size)
        for other, tile in self.tiles.items():
            if other == peer or other in self.shelf_ids:
                continue
            for display in tile.get("display_offsets", {}):
                if display in tile.get("displays", {}) and grip.intersects(self.display_rect(other, display)):
                    return None
        return grip

    def _resize_at(self, point):
        # An edge third's 5 px band wins over a grip it overlaps: the selected peer's and the
        # hovered tile's corners sit on the end third of a shared side.
        if self._third_segment_at(point) is not None:
            return None
        for peer in reversed(list(self.tiles)):
            grip = self._resize_grip_rect(peer)
            # A tile drawn smaller than the grip has its whole grip inside the band of the side it
            # shares; the hit area keeps the full grip size, reaching out past the corner.
            if grip is not None and QRectF(grip.left(), grip.top(), max(grip.width(), RESIZE_GRIP),
                                               max(grip.height(), RESIZE_GRIP)).contains(point):
                return peer
        return None

    def _geometry(self):
        self._sync_recentre()
        if self._drag:
            return
        visible = {key: tile for key, tile in self.tiles.items() if key not in self.shelf_ids}
        if not visible:
            self._bounds, self._scale = (0, 0, 1, 1), 1.0
            self._origin = QPointF(12, 12)
            return
        frames = [frame for tile in visible.values() for frame in ways._display_frames(tile)]
        left = min([tile["x"] for tile in visible.values()] + [frame["x"] for frame in frames])
        top = min([tile["y"] for tile in visible.values()] + [frame["y"] for frame in frames])
        right = max([tile["x"] + tile["w"] for tile in visible.values()] +
                    [frame["x"] + frame["w"] for frame in frames])
        bottom = max([tile["y"] + tile["h"] for tile in visible.values()] +
                     [frame["y"] + frame["h"] for frame in frames])
        cx, cy = (left+right)/2, (top+bottom)/2
        self._bounds = (cx, cy, right-left, bottom-top)
        room_w, room_h = max(1, self.width()-24), max(1, self.height()-24)
        self._scale = min(room_w/max(1, right-left), room_h/max(1, bottom-top), 1.0)
        self._origin = QPointF(self.width()/2, self.height()/2)

    def resizeEvent(self, event):
        self._geometry()
        if self.ledger_height:
            self._height_timer.start(0)
        super().resizeEvent(event)

    def _fit_ledger_height(self):
        target = 220 if self.width() < 620 else 260
        if self.minimumHeight() != target or self.maximumHeight() != target:
            self.setFixedHeight(target)
            self.updateGeometry()

    def _recentre_side(self):
        own_id = self._own_id()
        if (own_id not in self.tiles or self.selected not in self.tiles
                or self.selected == own_id or self.selected in self.shelf_ids):
            return None
        own, tile = self.tiles[own_id], self.tiles[self.selected]
        contact = ways._rect_contact(own, tile)
        if contact and contact[0] != "corner":
            return contact[0]
        targets = {side: ways.place_beside({own_id: own, self.selected: tile},
                                          own_id, self.selected, side) for side in ways.EDGES}
        return min(targets, key=lambda side: (targets[side]["x"]-tile["x"])**2
                   + (targets[side]["y"]-tile["y"])**2)

    def _can_recentre(self):
        if self.read_only:
            return False
        side = self._recentre_side()
        if side is None:
            return False
        own_id = self._own_id()
        tile = self.tiles[self.selected]
        centred = ways.place_beside({own_id: self.tiles[own_id], self.selected: tile},
                                    own_id, self.selected, side)
        return (tile["x"], tile["y"]) != (centred["x"], centred["y"])

    def _sync_recentre(self):
        button = self.recentre_button
        button.move(self.width()-button.width()-10, 10)
        button.setAccessibleName(tr("Recentre {name}").format(name=self.labels.get(self.selected, tr(OTHER))))
        colours = tuple(theme.colour(name) for name in ("panel", "ink_3", "ink", "edge", "ink_2"))
        if colours != self._recentre_colours:
            panel, ink_3, ink, edge, ink_2 = colours
            button.setStyleSheet(
                f"QPushButton {{ background: {panel}; color: {ink_3};"
                " border: 1px solid transparent; border-radius: 4px; padding: 3px 8px; }"
                f"QPushButton:hover {{ color: {ink}; border-color: {edge}; }}"
                f"QPushButton:focus {{ border-color: {ink_2}; }}")
            self._recentre_colours = colours
        button.setVisible(self._can_recentre())
        button.raise_()

    def _commit_tile(self, peer, resized=False):
        if self.read_only:
            return
        accepted = self.on_drop({key: dict(tile) for key, tile in self.tiles.items()}, peer) is not False
        if accepted:
            if resized:
                self.announce(tr("{name} resized.").format(name=self.labels.get(peer, tr(OTHER))))
            else:
                self._announce_move(peer)
        self._geometry()
        self.update()

    def recentre(self):
        if self._drag is not None or not self._can_recentre():
            return
        peer = self.selected
        active = {key: tile for key, tile in self.tiles.items() if key not in self.shelf_ids}
        target = ways.place_beside(active, self._own_id(), peer, self._recentre_side())
        self.animate_tile(peer, target, done=lambda: self._commit_tile(peer))

    def snap_preview(self):
        if not self._drag or self._resizing or self._drag == self._own_id() or self._drag_display is not None:
            return None
        tile = self.tiles[self._drag]
        others = {key: value for key, value in self.tiles.items()
                  if key != self._drag and key not in self.shelf_ids}
        radius = 12 / max(self._scale, 0.001)
        snapped = ways.snap_position(tile, self._own_id(), others, radius=radius)
        if ((snapped["x"], snapped["y"]) != (tile["x"], tile["y"])
                and ways.within_snap_radius(tile, snapped, self._own_id(), others, radius)):
            return {**tile, **snapped}
        return None

    def _paint_contact(self, painter, tile, rect, contact, colour="signal", alpha=1.0, breaks=(), screen=None):
        side, start, end = contact
        width = 4.0 if colour == "signal" else 2.0
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(_colour(colour, alpha), width,
                   Qt.PenStyle.SolidLine if colour == "signal" else Qt.PenStyle.DashLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if side == "corner":
            x = self._edge_px(tile, rect, screen or tile, "left" if start.endswith("left") else "right")
            y = self._edge_px(tile, rect, screen or tile, "top" if start.startswith("top") else "bottom")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_colour(colour, alpha))
            painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
        else:
            self._paint_seam(painter, tile, rect, contact, alpha, width, breaks, screen)

    def _paint_seam(self, painter, tile, rect, contact, alpha, width, breaks, screen=None):
        line = self.seam_line(tile, rect, contact, breaks, width, screen)
        if line is None:
            return
        one, two = line
        self.seam_paths.append((contact[0], one, two, alpha, width))
        painter.drawLine(one, two)

    def seam_line(self, tile, rect, contact, breaks=(), width=0.0, screen=None):
        """Pixel endpoints shared by the seam and its ghost track, including corner halos, on the edge
        of `screen` (one of the tile's display frames) or of the tile. An end at one of `breaks`, a third
        boundary in layout units, stops short enough that a round cap of `width` leaves half of THIRD_GAP
        clear; a piece with such an end and no length left is None."""
        side, start, end = contact
        vertical = side in ("left", "right")
        origin = tile["y"] if vertical else tile["x"]
        low = (rect.top() if vertical else rect.left()) + (start - origin) * self._scale
        high = (rect.top() if vertical else rect.left()) + (end - origin) * self._scale
        first, last = (rect.top(), rect.bottom()) if vertical else (rect.left(), rect.right())
        low_inset = high_inset = min(2.0, max(0.0, (high - low) / 2))
        broken = False
        if any(abs(start - point) < 1e-6 for point in breaks):
            low_inset, broken = THIRD_GAP / 2 + width / 2, True
        if any(abs(end - point) < 1e-6 for point in breaks):
            high_inset, broken = THIRD_GAP / 2 + width / 2, True
        if broken and high - high_inset <= low + low_inset:
            return None
        if tile is self.tiles.get(self._own_id()):
            corners = self._pad_corners()
            near, far = {"top": ("top_left", "top_right"), "bottom": ("bottom_left", "bottom_right"),
                         "left": ("top_left", "bottom_left"), "right": ("top_right", "bottom_right")}[side]
            if near in corners and abs(low - first) < 2.1:
                low_inset = 11
            if far in corners and abs(high - last) < 2.1:
                high_inset = 11
        fixed = self._edge_px(tile, rect, screen or tile, side)
        return ((QPointF(fixed, low + low_inset), QPointF(fixed, max(low + low_inset, high - high_inset)))
                if vertical else (QPointF(low + low_inset, fixed), QPointF(max(low + low_inset, high - high_inset), fixed)))

    def _edge_px(self, tile, rect, screen, side):
        """Where `screen`'s `side`, in layout units, falls in pixels across `tile`'s `rect`."""
        if side in ("left", "right"):
            return rect.left() + (screen["x"] + (screen["w"] if side == "right" else 0) - tile["x"]) * self._scale
        return rect.top() + (screen["y"] + (screen["h"] if side == "bottom" else 0) - tile["y"]) * self._scale

    def _side_contacts(self, peer):
        """[(screen, contact)]: this machine's display frames that meet `peer`'s along a side, as the
        engine finds them; thirds are measured along `screen`, the pointer's own display."""
        return ways.side_contacts(self.tiles[self._own_id()], self.tiles[peer])

    def _pad_corners(self):
        """Every corner of This PC that carries a pad, whichever machine holds it."""
        return {corner for peer, data in self.states.items()
                if peer in self.tiles and peer not in self.shelf_ids and peer != self._own_id()
                for corner in data.get("corners", ()) if corner in pages_win.CORNER_NAMES}

    @staticmethod
    def _wrap_sides(data):
        """The sides of This PC a machine's wrap-around crosses by now, each once, in map order."""
        sides = {item["side"] if isinstance(item, dict) else item for item in data.get("wraps", ())}
        return [side for side in ways.EDGES if side in sides]

    def wrap_seam(self, rect, side):
        """Pixel endpoints of a wrap-around seam along one of This PC's own sides: inset 2 px at each
        end, or 13 px where a corner pad sits on that vertex, so it stops at the pad's halo."""
        pads = self._pad_corners()
        vertical = side in ("left", "right")
        first, last = (rect.top(), rect.bottom()) if vertical else (rect.left(), rect.right())
        near, far = {"top": ("top_left", "top_right"), "bottom": ("bottom_left", "bottom_right"),
                     "left": ("top_left", "bottom_left"), "right": ("top_right", "bottom_right")}[side]
        low = first + (13 if near in pads else 2)
        high = max(low, last - (13 if far in pads else 2))
        fixed = rect.left() if side == "left" else rect.right() if side == "right" else rect.top() if side == "top" else rect.bottom()
        return (QPointF(fixed, low), QPointF(fixed, high)) if vertical else (QPointF(low, fixed), QPointF(high, fixed))

    @staticmethod
    def _paint_push_arrow(painter, tip, side, colour):
        dx, dy = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}[side]
        pen = QPen(colour, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(tip.x() - dx * 9, tip.y() - dy * 9), tip)
        path = QPainterPath(QPointF(tip.x() - dx * 4 - dy * 4, tip.y() - dy * 4 - dx * 4))
        path.lineTo(tip)
        path.lineTo(QPointF(tip.x() - dx * 4 + dy * 4, tip.y() - dy * 4 + dx * 4))
        painter.drawPath(path)

    def _paint_wrap(self, painter, rect, side, name, kept, alpha, peer=None):
        """A wrap-around side: the seam along This PC's own edge and, inside the tile, where it leads."""
        one, two = self.wrap_seam(rect, side)
        if kept:
            pen = QPen(_colour("signal", .35), 2.0)
            pen.setDashPattern([2.0, 2.5])
        else:
            pen = QPen(_colour("signal", alpha), 4.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(one, two)
        self.seam_paths.append((side, one, two, .35 if kept else alpha, pen.widthF()))
        text = "wrap kept, Edge off" if kept else f"wraps to {name}"
        self.wrap_marks.append((peer, side, text, kept, .35 if kept else alpha))

    def _paint_wrap_labels(self, painter, rect, marks):
        """Each wrap label gets its own row below This PC's name and detail line, so none ever lands on
        them or on another label: a top side's row nearest the name, a bottom side's nearest the
        bottom edge, left and right in between, sharing one row when both fit. Sides that say the
        same thing, as when one machine wraps on several, share one label naming them. Rows that do
        not fit the tile are left out; the seam still shows the side."""
        self.wrap_label_rects = []
        if rect.height() < 78:
            return
        painter.setFont(theme.font(tokens.TYPE["small"]))
        metrics = painter.fontMetrics()
        order = {"merged": 0, "top": 0, "left": 1, "right": 2, "bottom": 3}
        said = {}
        for side, text, kept, alpha in sorted(marks, key=lambda mark: order[mark[0]]):
            said.setdefault((text, kept), []).append((side, text, kept, alpha))
        labels = []
        for same in said.values():
            side, text, kept, alpha = same[0]
            if len(same) > 1:
                # The sides named, else counted, else the plain words: the seams still show which.
                text = next((option for option in (f"{text} · {', '.join(mark[0] for mark in same)}",
                                                   f"{text} · {len(same)} sides")
                             if metrics.horizontalAdvance(option) <= rect.width() - 24), text)
                side = "merged"
            room = rect.width() - (52 if side in ("left", "right") else 24)
            text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(1, round(room)))
            labels.append((side, text, kept, alpha, metrics.horizontalAdvance(text)))
        rows = []
        for label in sorted(labels, key=lambda label: order[label[0]]):
            if (label[0] == "right" and rows and len(rows[-1]) == 1 and rows[-1][0][0] == "left"
                    and 26 + rows[-1][0][4] + 8 + label[4] + 26 <= rect.width()):
                rows[-1].append(label)
            else:
                rows.append([label])
        first, last = rect.top() + 51, rect.bottom() - 22
        room = int((last - first) // 18) + 1 if last >= first else 0
        wanted = {"top": first, "merged": first, "left": rect.center().y() + 10,
                  "right": rect.center().y() + 10, "bottom": last}
        tops = []
        for row in rows[:room]:
            tops.append(max(min(last, wanted[row[0][0]]), tops[-1] + 18 if tops else first))
        for index in range(len(tops) - 1, -1, -1):
            tops[index] = min(tops[index], last if index == len(tops) - 1 else tops[index + 1] - 18)
        for top, row in zip(tops, rows):
            for side, text, kept, alpha, width in row:
                ink = _colour("ink_3", .8) if kept else _colour("signal", alpha)
                x = (rect.left() + 26 if side == "left" else rect.right() - 26 - width if side == "right"
                     else rect.right() - 12 - width)
                box = QRectF(x, top, width + 1, 16)
                if side in ("left", "right"):
                    self._paint_push_arrow(painter, QPointF(rect.left() + 16 if side == "left" else rect.right() - 16,
                                                            box.center().y()), side, ink)
                painter.setFont(theme.font(tokens.TYPE["small"]))
                painter.setPen(ink)
                painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
                self.wrap_label_rects.append((side, text, box))

    def _third_segment_at(self, point):
        if self.read_only:
            return None
        own_id, peer = self._own_id(), self.selected
        if (own_id not in self.tiles or peer not in self.tiles or peer == own_id
                or peer in self.shelf_ids):
            return None
        own_rect, own = self.tile_rect(own_id), self.tiles[own_id]
        for screen, contact in self._side_contacts(peer):
            side = contact[0]
            edge = self._edge_px(own, own_rect, screen, side)
            for third, _side, low, high in ways.third_stretches(contact, screen):
                if side in ("left", "right"):
                    y1 = own_rect.top() + (low - own["y"]) * self._scale
                    y2 = own_rect.top() + (high - own["y"]) * self._scale
                    hit = abs(point.x() - edge) <= 5 and y1 <= point.y() <= y2
                else:
                    x1 = own_rect.left() + (low - own["x"]) * self._scale
                    x2 = own_rect.left() + (high - own["x"]) * self._scale
                    hit = abs(point.y() - edge) <= 5 and x1 <= point.x() <= x2
                if hit:
                    return peer, third, side
        return None

    def _third_at(self, point):
        hit = self._third_segment_at(point)
        return hit[:2] if hit else None

    def _third_tooltip(self, peer, third, side):
        picked = self.states.get(peer, {}).get("thirds", [])
        name = ways.part_names(side)[third]
        return f"{name} third: click to {'leave it out' if third in picked else 'turn it on'}"

    @staticmethod
    def _paint_corner_pad(painter, rect, corner, opacity):
        x = rect.left() if corner.endswith("left") else rect.right()
        y = rect.top() if corner.startswith("top") else rect.bottom()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_colour("ground"))
        painter.drawRoundedRect(QRectF(x - 11, y - 11, 22, 22), 5, 5)
        painter.setBrush(_colour("signal", opacity))
        painter.drawRoundedRect(QRectF(x - 8, y - 8, 16, 16), 4, 4)
        dx = 1 if corner.endswith("left") else -1
        dy = 1 if corner.startswith("top") else -1
        pen = QPen(_colour("ground", opacity), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        # The 7 px bracket centred on the vertex, as in the 16 px pad around it.
        point = QPointF(x - 3.5 * dx, y - 3.5 * dy)
        painter.drawLine(point, QPointF(point.x() + 7 * dx, point.y()))
        painter.drawLine(point, QPointF(point.x(), point.y() + 7 * dy))

    def _paint_third_track(self, painter, own, rect, stretch, breaks=(), screen=None):
        _third, side, low, high = stretch
        pen = QPen(_colour("signal", 0.3), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        self._paint_seam(painter, own, rect, (side, low, high), .3, 2.0, breaks, screen)

    @staticmethod
    def _title_top(rect):
        return rect.top()+7 if rect.height() >= 56 else rect.center().y()-11

    def _shows_cycle(self, peer):
        return (not self.remote and not self.read_only and self.cycle_mode == "ticked"
                and peer != self._own_id() and peer not in self.shelf_ids)

    @staticmethod
    def _cycle_box(rect):
        """The shortcut-cycle tick: its own column at the right end of the name's line, or in the
        bottom row of a tile 44 to 56pt tall, leaving its corner free for the resize grip."""
        if 44 <= rect.height() < 56:
            return QRectF(rect.right() - RESIZE_GRIP - 4 - CYCLE_BOX,
                          rect.bottom() - 4 - CYCLE_BOX, CYCLE_BOX, CYCLE_BOX)
        margin = RESIZE_GRIP + 4 if rect.height() < 44 else 8
        return QRectF(rect.right() - margin - CYCLE_BOX, AtlasCanvas._title_top(rect) + 11 - CYCLE_BOX/2,
                      CYCLE_BOX, CYCLE_BOX)

    @staticmethod
    def _cycle_hit_rect(rect):
        return AtlasCanvas._cycle_box(rect).adjusted(-4, -4, 4, 4)

    def _title_rect(self, peer, rect):
        """The name's text rect. Beside the shortcut-cycle tick the name stays centred on the tile while
        it fits the room left symmetric by the tick, else takes the room left of the tick; a tile 44 to
        56pt tall puts the name on its own row above the tick, 20pt tall so a 44pt tile still fits both."""
        if not self._shows_cycle(peer):
            return QRectF(rect.left()+8, self._title_top(rect), max(1, rect.width()-16), 22)
        if 44 <= rect.height() < 56:
            return QRectF(rect.left()+8, rect.top()+4, max(1, rect.width()-16), 20)
        room = 8 + CYCLE_BOX + 6
        label = self.labels.get(peer, f"Machine · {peer[-6:]}")
        if (rect.height() >= 56 and QFontMetrics(theme.font(tokens.TYPE["body"], 650)).horizontalAdvance(label)
                <= rect.width() - 2*room):
            return QRectF(rect.left()+room, self._title_top(rect), rect.width()-2*room, 22)
        return QRectF(rect.left()+8, self._title_top(rect), max(1, self._cycle_box(rect).left()-6-rect.left()-8), 22)

    def paintEvent(self, _event):
        self._geometry()
        self.seam_paths = []
        self.wrap_marks = []
        self.wrap_label_rects = []
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(_colour("edge"), 1.0))
        painter.setBrush(_colour("ground"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width()-1, self.height()-1), 4, 4)
        own_id = self._own_id()
        if own_id in self.tiles:
            own_rect = self.tile_rect(own_id)
            painter.setPen(QPen(_colour("edge", 0.22), 1.0))
            for fraction in (1.0/3.0, 2.0/3.0):
                x = own_rect.left() + own_rect.width()*fraction
                y = own_rect.top() + own_rect.height()*fraction
                painter.drawLine(QPointF(x, 4), QPointF(x, self.height()-4))
                painter.drawLine(QPointF(4, y), QPointF(self.width()-4, y))
        for peer, tile in self.tiles.items():
            if peer in self.shelf_ids:
                continue
            rect = self.tile_rect(peer)
            state = self.states.get(peer, {}).get("state", "edge")
            chosen = peer == self.selected
            is_own = peer == own_id
            inactive = peer in self.shelf_ids or self.in_use.get(peer, True) is False
            fill = "well" if is_own else "panel"
            line = "edge" if is_own else "ink_2" if chosen else "amber" if state in ("gap", "between", "set-elsewhere", "overlap") else "edge"
            if self.profile_mode:
                line = "ink_2" if self.remote and is_own else "edge"
            if inactive:
                fill, line = "ground", "ink_2" if chosen and not is_own else "rule"
            painter.setOpacity(0.55 if inactive else 1.0)
            outlined = (self.remote and is_own) if self.profile_mode else (chosen and not is_own)
            painter.setPen(QPen(_colour(line), 2.0 if outlined else 1.0))
            painter.setBrush(_colour(fill))
            painter.drawRoundedRect(rect, tokens.RADIUS["button"], tokens.RADIUS["button"])
            displays = tile.get("displays") or {}
            if isinstance(displays, dict) and len(displays) > 1:
                for screen in ways._display_frames(tile):
                    screen_rect = self.display_rect(peer, screen["display"]).adjusted(2, 2, -2, -2)
                    painter.setPen(QPen(_colour("edge"), 1.0))
                    painter.setBrush(_colour("well"))
                    painter.drawRoundedRect(screen_rect, 2, 2)
            state_data = self.states.get(peer, {})
            dot_colour = "signal" if state_data.get("linked") else "amber" if state_data.get("legacy") else "ink_3"
            if self.profile_mode:
                dot_colour = "signal" if state_data.get("profile_word") in (tr("Desk"), tr("Own")) else "ink_3"
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_colour(dot_colour))
            if rect.height() >= 56:
                painter.drawEllipse(QPointF(rect.left()+15, rect.top()+39), 3, 3)
            if self._hover == peer and not chosen and not is_own:
                painter.setPen(QPen(_colour("ink_3"), 1.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect, 4, 4)
            sentence_keys = state_data.get("sentence_keys", [])
            legacy = state_data.get("legacy", False)
            painter.setPen(_colour("ink"))
            painter.setFont(theme.font(tokens.TYPE["body"], 650))
            title = self.labels.get(peer, f"Machine · {peer[-6:]}")
            title_room = self._title_rect(peer, rect)
            painter.drawText(title_room, Qt.AlignmentFlag.AlignCenter,
                             painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight,
                                                             max(1, round(title_room.width()))))
            detail = state_data.get("profile_word", "") if self.profile_mode else state_data.get("detail", "")
            if detail and rect.height() >= 56:
                painter.setPen(_colour("ink_2"))
                painter.setFont(theme.font(tokens.TYPE["note"]))
                painter.drawText(QRectF(rect.left()+24, rect.top()+31, max(1, rect.width()-32), 16),
                                 Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                                 painter.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight,
                                                                 max(1, round(rect.width()-32))))
            if legacy and rect.height() >= 78:
                painter.setPen(_colour("amber"))
                painter.setFont(theme.font(tokens.TYPE["note"]))
                painter.drawText(rect.adjusted(7, rect.height()-62, -7, -36),
                                 Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                                 state_data.get("legacy_label", ""))
            if inactive and rect.height() >= 78:
                label = "Left out" if peer in self.shelf_ids else "Not in use"
                painter.setPen(_colour("ink_3"))
                painter.setFont(theme.font(tokens.TYPE["note"]))
                painter.drawText(rect.adjusted(4, 0, -4, -6), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, label)
            foot = ("" if is_own else "Offline" if state_data.get("linked") is False else
                    "Crosses" if state_data.get("corners") or state_data.get("wraps") else
                    "Edge off" if state_data.get("edge_off") else
                    "Drag to connect" if state == "gap" else "Overlaps" if state == "overlap" else
                    outcome_for_tile(state, state_data.get("crosses", is_own), is_own,
                                     state_data.get("other_name", "")))
            if foot and (not legacy or self.profile_mode) and rect.height() >= 78:
                painter.setPen(_colour("signal" if foot == "Crosses" else "amber" if foot in
                                       ("Drag to connect", "Overlaps") else "ink_3"))
                painter.setFont(theme.font(tokens.TYPE["note"]))
                painter.drawText(QRectF(rect.left()+7, rect.bottom()-24, max(1, rect.width()-14), 16),
                                 Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, foot)
            if self._shows_cycle(peer):
                box = self._cycle_box(rect)
                ticked = bool(self.cycle.get(peer, True))
                painter.setPen(Qt.PenStyle.NoPen if ticked else QPen(_colour("edge"), 1.0))
                painter.setBrush(_colour("ink_2" if ticked else "well"))
                painter.drawRoundedRect(box, 3, 3)
                if ticked:
                    pen = QPen(_colour("ground"), 1.8)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    check = QPainterPath(QPointF(box.left()+4.5, box.top()+8.5))
                    check.lineTo(box.left()+7, box.top()+11)
                    check.lineTo(box.left()+11.5, box.top()+5)
                    painter.drawPath(check)
            painter.setOpacity(1.0)
        own_id = self._own_id()
        if own_id in self.tiles:
            own = self.tiles[own_id]
            own_rect = self.tile_rect(own_id)
            for peer, tile in self.tiles.items():
                if peer == own_id or peer in self.shelf_ids:
                    continue
                held = self.states.get(peer, {})
                seam_alpha = 1.0 if held.get("linked", True) else .55
                sides = self._side_contacts(peer)
                contact = ways._rect_contact(own, tile)
                # Only a machine reached at a corner alone keeps the corner dot; corners where two
                # displays meet beside a side contact are not marks.
                found = sides or ([(own, contact)] if contact and contact[0] == "corner" else [])
                if not found:
                    continue
                if peer == self.selected and sides and (
                        (held.get("state") in ("edge", "part") or held.get("unpicked"))
                        and held.get("thirds")):
                    lit_thirds = held.get("lit", held.get("thirds", []))
                    for screen, contact in sides:
                        stretches = ways.third_stretches(contact, screen)
                        breaks = [before[3] for before, after in zip(stretches, stretches[1:])
                                  if before[1] == after[1] and abs(before[3] - after[2]) < 1e-6]
                        lit_group = None
                        for stretch in stretches:
                            if stretch[0] in lit_thirds:
                                if (lit_group and lit_group[1] == stretch[1]
                                        and abs(lit_group[3] - stretch[2]) < 1e-6):
                                    lit_group = (lit_group[0], lit_group[1], lit_group[2], stretch[3])
                                else:
                                    if lit_group:
                                        self._paint_contact(painter, own, own_rect,
                                                            (lit_group[1], lit_group[2], lit_group[3]),
                                                            alpha=seam_alpha, breaks=breaks, screen=screen)
                                    lit_group = stretch
                            else:
                                if lit_group:
                                    self._paint_contact(painter, own, own_rect,
                                                        (lit_group[1], lit_group[2], lit_group[3]),
                                                        alpha=seam_alpha, breaks=breaks, screen=screen)
                                    lit_group = None
                                self._paint_third_track(painter, own, own_rect, stretch, breaks, screen)
                        if lit_group:
                            self._paint_contact(painter, own, own_rect,
                                                (lit_group[1], lit_group[2], lit_group[3]),
                                                alpha=seam_alpha, breaks=breaks, screen=screen)
                # The seam is the edge's own mark: a machine reached only by its corner shows the
                # corner bracket and no seam.
                elif (held.get("state") in ("edge", "part", "corner")
                      and held.get("crosses") is not False
                      and set(held.get("methods", ["edge"])) & {"edge", "part"}):
                    for screen, contact in found:
                        for stretch in ways.crossing_stretches(contact, screen, held.get("lit", held.get("thirds", []))):
                            self._paint_contact(painter, own, own_rect, stretch, alpha=seam_alpha, screen=screen)
            for peer, data in self.states.items():
                if peer == own_id or peer not in self.tiles or peer in self.shelf_ids:
                    continue
                alpha = (1.0 if data.get("linked", True) else .55) * (1.0 if peer == self.selected else .7)
                name = self.labels.get(peer, tr(OTHER))
                for side in self._wrap_sides(data):
                    self._paint_wrap(painter, own_rect, side, name, False, alpha, peer)
                crossing = set(self._wrap_sides(data))
                for side in data.get("kept_wraps", ()):
                    if side in ways.EDGES and side not in crossing:
                        self._paint_wrap(painter, own_rect, side, name, True, alpha, peer)
            self._paint_wrap_labels(painter, own_rect, [(side, text, kept, alpha)
                                                        for _peer, side, text, kept, alpha in self.wrap_marks])
            self.corner_marks = []
            for peer, data in self.states.items():
                if peer == own_id or peer not in self.tiles or peer in self.shelf_ids:
                    continue
                for corner in ways.CORNERS:
                    if corner not in data.get("corners", ()):
                        continue
                    opacity = 1.0 if peer == self.selected else 0.55
                    self.corner_marks.append((peer, corner, opacity))
                    self._paint_corner_pad(painter, own_rect, corner, opacity)
        else:
            self.corner_marks = []
        peers = [peer for peer in self.tiles if peer != own_id and peer not in self.shelf_ids]
        for index, one in enumerate(peers):
            for two in peers[index+1:]:
                if not any(self.states.get(peer, {}).get("state") in ("between", "set-elsewhere")
                           for peer in (one, two)):
                    continue
                contact = ways._rect_contact(self.tiles[one], self.tiles[two])
                if contact and not self.profile_mode:
                    self._paint_contact(painter, self.tiles[one], self.tile_rect(one), contact, "amber")
        snapped = self.snap_preview()
        if snapped is not None:
            left, top, _width, _height = self._bounds
            ghost = QRectF((snapped["x"]-left)*self._scale + self._origin.x(),
                           (snapped["y"]-top)*self._scale + self._origin.y(),
                           snapped["w"]*self._scale, snapped["h"]*self._scale)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_colour("signal", 0.4), 1.0, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(ghost, tokens.RADIUS["button"], tokens.RADIUS["button"])
            contact = ways._rect_contact(self.tiles[own_id], snapped)
            if contact:
                self._paint_contact(painter, self.tiles[own_id], self.tile_rect(own_id), contact, alpha=0.5)
        for peer in self.tiles:
            grip = self._resize_grip_rect(peer)
            if grip is not None:
                pen = QPen(_colour("ink_2"), 1.5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                for length in (4, 8):
                    length = min(length, max(1, grip.width()-4))
                    painter.drawLine(QPointF(grip.right()-3-length, grip.bottom()-3),
                                     QPointF(grip.right()-3, grip.bottom()-3-length))
        if self.hasFocus() and self.selected in self.tiles and self._keyboard_focus:
            painter.setPen(QPen(_colour("ink_2"), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.tile_rect(self.selected).adjusted(-3, -3, 3, 3), 3, 3)
        painter.end()

    def _own_id(self):
        return self.own_id or next((peer for peer, label in self.labels.items() if label == tr(DASHBOARD_NAME)), None)

    def mousePressEvent(self, event):
        point = event.position()
        peer = self._resize_at(point)
        if peer is not None and event.button() == Qt.MouseButton.LeftButton:
            motion.stop(self, f"tile:{peer}")
            self.selected = peer
            self._drag = peer
            self._resizing = True
            self._drag_start = QPointF(point)
            self._tile_start = dict(self.tiles[peer])
            self._profile_press = None
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._keyboard_focus = False
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            if not self.profile_mode and peer != self._own_id():
                self.on_select(peer)
            self.update()
            event.accept()
            return
        third = self._third_at(point)
        if third is not None:
            self._third_press = third
            event.accept()
            return
        if self.profile_mode:
            self._profile_press = next((peer for peer in reversed(list(self.tiles))
                                        if self.tile_rect(peer).contains(point)), None)
            self._profile_press_point = QPointF(point)
            if self._profile_press is not None and (self.read_only or self._profile_press == self._own_id()
                                                    or self._profile_press in self.shelf_ids):
                self.selected = self._profile_press
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self._keyboard_focus = False
                self.update()
                event.accept()
                return
        if self.read_only:
            event.accept()
            return
        display_peer, display = self.display_at(point)
        if display_peer is not None and display_peer != self._own_id():
            offsets = self.tiles[display_peer].get("display_offsets", {})
            split = display in offsets
            alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            if split or alt:
                motion.stop(self, f"tile:{display_peer}")
                self.selected = display_peer
                self._drag = display_peer
                self._drag_display = display
                self._dragged_display = False
                self._display_offset_start = dict(offsets.get(display, {"x": 0, "y": 0}))
                self._split_on_release = alt and not split
                self._group_on_release = alt and split
                self._drag_start = QPointF(point)
                self._tile_start = dict(self.tiles[display_peer])
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self._keyboard_focus = False
                if not self.profile_mode:
                    self.on_select(display_peer)
                self.update()
                event.accept()
                return
        for peer in reversed(list(self.tiles)):
            if peer in self.shelf_ids:
                continue
            rect = self.tile_rect(peer)
            if rect.contains(point):
                if peer == self._own_id():
                    event.accept()
                    return
                if self._shows_cycle(peer) and self._cycle_hit_rect(rect).contains(point):
                    self._profile_press = None
                    self.set_cycle(peer, not self.cycle.get(peer, True))
                    event.accept()
                    return
                self.selected = peer
                motion.stop(self, f"tile:{peer}")
                self._drag = peer
                self._drag_start = QPointF(point)
                self._tile_start = dict(self.tiles[peer])
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self._keyboard_focus = False
                if not self.profile_mode:
                    self.on_select(peer)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if self._resizing else Qt.CursorShape.ClosedHandCursor)
            delta = event.position() - self._drag_start
            if self._resizing:
                self.tiles[self._drag] = ways.resize_from_drag(
                    self._tile_start, delta.x()/self._scale, delta.y()/self._scale)
            elif self._drag_display is not None:
                tile = self.tiles[self._drag]
                offsets = dict(tile.get("display_offsets", {}))
                offsets[self._drag_display] = {
                    "x": round(self._display_offset_start["x"] + delta.x()/self._scale),
                    "y": round(self._display_offset_start["y"] + delta.y()/self._scale),
                }
                self.tiles[self._drag] = {**tile, "display_offsets": offsets}
                self._dragged_display = self._dragged_display or not delta.isNull()
            else:
                tile = self.tiles[self._drag]
                self.tiles[self._drag] = {**self._tile_start,
                                          "x": round(self._tile_start["x"] + delta.x()/self._scale),
                                          "y": round(self._tile_start["y"] + delta.y()/self._scale)}
            self._geometry()
            self.update()
            event.accept()
            return
        third = self._third_segment_at(event.position())
        hovered = next((peer for peer in self.tiles if peer not in self.shelf_ids and self.tile_rect(peer).contains(event.position())), None)
        if hovered != self._hover:
            self._hover = hovered
            self.update()
        resize_peer = self._resize_at(event.position())
        if resize_peer is not None:
            self.setToolTip(self.labels.get(resize_peer, ""))
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif third is not None:
            self.setToolTip(self._third_tooltip(*third))
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setToolTip(self.labels.get(hovered, "") if hovered else "")
            self.setCursor(Qt.CursorShape.OpenHandCursor if hovered and hovered != self._own_id() and not self.read_only
                           else Qt.CursorShape.PointingHandCursor if hovered and self.profile_mode
                           else Qt.CursorShape.ArrowCursor)
        if resize_peer is None and hovered and self._shows_cycle(hovered) and self._cycle_hit_rect(self.tile_rect(hovered)).contains(event.position()):
            QToolTip.showText(self.mapToGlobal(event.position().toPoint()), tr("In the shortcut's cycle"), self)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = None
        if not self._drag:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        profile_peer = self._profile_press
        self._profile_press = None
        if (self.profile_mode and profile_peer is not None and self._profile_press_point is not None
                and not self._split_on_release and not self._group_on_release
                and (event.position() - self._profile_press_point).manhattanLength() < 4):
            if self._drag is not None:
                self.tiles[self._drag] = dict(self._tile_start)
                self._geometry()
            self._drag = None
            self._drag_display = None
            self._display_offset_start = None
            self._dragged_display = False
            self._split_on_release = self._group_on_release = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.on_edit_machine(profile_peer)
            self.update()
            event.accept()
            return
        if self._third_press is not None:
            pressed = self._third_press
            self._third_press = None
            if self._third_at(event.position()) == pressed:
                self.on_third(*pressed)
            event.accept()
            return
        peer = self._drag
        if peer:
            resized = self._resizing
            snapped = self.snap_preview()
            display = self._drag_display
            moved_display = self._dragged_display
            split_on_release = self._split_on_release
            group_on_release = self._group_on_release
            self._drag = None
            self._resizing = False
            self._drag_display = None
            self._display_offset_start = None
            self._dragged_display = False
            self._split_on_release = False
            self._group_on_release = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if resized:
                self._commit_tile(peer, resized=True)
                event.accept()
                return
            if display is not None and not moved_display and (split_on_release or group_on_release):
                tile = dict(self.tiles[peer])
                offsets = dict(tile.get("display_offsets", {}))
                if split_on_release:
                    offsets[display] = {"x": 0, "y": 0}
                else:
                    offsets.pop(display, None)
                updated = {**tile, "display_offsets": offsets}
                if not offsets:
                    updated.pop("display_offsets", None)
                self.tiles[peer] = updated
                self.on_drop({key: dict(value) for key, value in self.tiles.items()}, peer)
                self.update()
                event.accept()
                return
            if display is not None and not moved_display:
                self.update()
                event.accept()
                return
            if display is None and not self.remote and event.position().y() > self.height() - 4:
                self.on_leave_out(peer, True)
                self.update()
                event.accept()
                return
            if snapped is not None and snapped != self.tiles[peer]:
                self.animate_tile(peer, snapped, done=lambda: self._commit_tile(peer))
            else:
                self._commit_tile(peer)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.remote or self.read_only:
            event.accept()
            return
        peer = next((key for key in self.tiles if key not in self.shelf_ids
                     and self.tile_rect(key).contains(event.position())), None)
        if peer == self._own_id():
            if self.on_hint:
                self.on_hint(tr("Rename this computer on Overview."))
            event.accept()
            return
        if peer is not None and peer != self._own_id():
            self.begin_rename(peer)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        self._keyboard_focus = True
        if (self.profile_mode and self.selected in self.tiles
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)):
            self.on_edit_machine(self.selected)
            event.accept()
            return
        if self.read_only:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_C and not event.modifiers():
            self.recentre()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_F2, Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.selected is not None:
            self.begin_rename(self.selected)
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Space and self.cycle_mode == "ticked"
                and self.selected in self.tiles and self.selected != self._own_id()):
            self.set_cycle(self.selected, not self.cycle.get(self.selected, True))
            event.accept()
            return
        moves = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                 Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() in moves and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            if self._can_resize(self.selected) and self._drag is None:
                peer = self.selected
                motion.stop(self, f"tile:{peer}")
                tile = self.tiles[peer]
                long_side = max(tile["w"], tile["h"])
                dx, dy = moves[event.key()]
                self.tiles[peer] = ways.resize_tile(tile, long_side + (dx+dy)*long_side/8)
                self._commit_tile(peer, resized=True)
            event.accept()
            return
        if event.key() in moves and self.selected in self.shelf_ids:
            event.accept()
            return
        if event.key() in moves and self.selected in self.tiles and self.selected != self._own_id():
            dx, dy = moves[event.key()]
            own = self.tiles[self._own_id()]
            tile = self.tiles[self.selected]
            self.tiles[self.selected] = {**tile, "x": tile["x"] + round(own["w"]/3)*dx,
                                         "y": tile["y"] + round(own["h"]/3)*dy}
            accepted = self.on_drop({key: dict(value) for key, value in self.tiles.items()}, self.selected) is not False
            if accepted:
                self._announce_move(self.selected)
            self._geometry()
            self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusNextPrevChild(self, next):
        peers = [peer for peer in self.tiles if self.profile_mode or
                 (peer != self._own_id() and peer not in self.shelf_ids)]
        peers.sort(key=lambda peer: (self.tiles[peer]["y"] + self.tiles[peer]["h"] / 2,
                                     self.tiles[peer]["x"] + self.tiles[peer]["w"] / 2))
        rows = []
        for peer in peers:
            tile = self.tiles[peer]
            centre = tile["y"] + tile["h"] / 2
            if not rows or centre - rows[-1][0][0] > min(tile["h"], rows[-1][0][1]) / 2:
                rows.append([])
            rows[-1].append((centre, tile["h"], peer))
        peers = [peer for row in rows for _centre, _height, peer in
                 sorted(row, key=lambda item: self.tiles[item[2]]["x"] + self.tiles[item[2]]["w"] / 2)]
        if not peers:
            return super().focusNextPrevChild(next)
        index = peers.index(self.selected) if self.selected in peers else (-1 if next else len(peers))
        target = index + (1 if next else -1)
        if 0 <= target < len(peers):
            self.selected = peers[target]
            if not self.profile_mode:
                self.on_select(self.selected)
            self._keyboard_focus = True
            self.update()
            return True
        return super().focusNextPrevChild(next)

    def _announce_move(self, peer):
        own = self.tiles.get(self._own_id())
        contact = ways._rect_contact(own, self.tiles[peer]) if own else None
        tile = self.tiles[peer]
        if contact and contact[0] != "corner":
            side = contact[0]
        elif own:
            dx = tile["x"] + tile["w"] / 2 - own["x"] - own["w"] / 2
            dy = tile["y"] + tile["h"] / 2 - own["y"] - own["h"] / 2
            side = ("left" if dx < 0 else "right") if abs(dx) >= abs(dy) else ("top" if dy < 0 else "bottom")
        else:
            side = "corner"
        state = self.states.get(peer, {})
        position = tr("{side} of This PC").format(side=tr(DIRECTION_NAMES[side])) if side != "corner" else tr("at a corner of This PC")
        part = None
        if own:
            along, start, span = ((tile["y"] + tile["h"] / 2, own["y"], own["h"])
                                  if side in ("left", "right") else
                                  (tile["x"] + tile["w"] / 2, own["x"], own["w"]))
            part = ways.ATLAS_PARTS[min(2, max(0, int((along-start) / (span/3))))]
        parts = state.get("thirds", [])
        chosen_part = parts[0] if parts else part
        part_name = pages_win.part_names(side).get(chosen_part, chosen_part) if chosen_part else ""
        detail = tr(", {part} third").format(part=tr(ways.PART_NAMES_LOWER[part_name.lower()])) if part_name else ""
        result = state.get("announcement", tr("Crosses."))
        # Translators: {name} is a machine name; {position} is relative to this PC; {detail} optionally names the third crossed.
        message = tr("{name}, {position}{detail}. {result}").format(
            name=self.labels.get(peer, OTHER), position=position, detail=detail, result=result)
        self.announce(message)

    def announce(self, message):
        description = message
        if not self.read_only and any(peer not in self.shelf_ids for peer in self.tiles):
            description += " " + tr(RESIZE_HELP)
        self.setAccessibleDescription(description)
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self, message))
        if self.on_announce:
            self.on_announce(message)

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() != Qt.FocusReason.MouseFocusReason
        self.update()
        super().focusInEvent(event)

    def begin_rename(self, peer):
        if self.remote or self.read_only or peer not in self.tiles or peer in self.shelf_ids or peer == self._own_id():
            return
        rect = self.tile_rect(peer).toRect()
        self.selected = peer
        self._rename_peer = peer
        self.rename_edit.setGeometry(rect.adjusted(8, rect.height()//3, -8, -rect.height()//3))
        self.rename_edit.setText(self.rename_values.get(peer, ""))
        self.rename_edit.setVisible(True)
        if self.on_rename_state:
            self.on_rename_state(True)
        self.rename_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.rename_edit.selectAll()

    def _save_rename(self):
        peer, value = self._rename_peer, self.rename_edit.text().strip()[:64]
        self._rename_peer = None
        self.rename_edit.setVisible(False)
        if self.on_rename_state:
            self.on_rename_state(False)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if peer and not self.remote and not self.read_only:
            self.on_rename(peer, value)

    def eventFilter(self, watched, event):
        if (watched is self.recentre_button and event.type() == event.Type.KeyPress
                and event.key() == Qt.Key.Key_C and not event.modifiers()):
            self.recentre()
            return True
        if watched is self.rename_edit and event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.rename_edit.setVisible(False)
            self._rename_peer = None
            if self.on_rename_state:
                self.on_rename_state(False)
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            return True
        if watched is self.rename_edit and event.type() == event.Type.FocusOut and self._rename_peer:
            self._save_rename()
        return super().eventFilter(watched, event)



class PushStrip(QSlider):
    """The Crossing page's one Resistance slider, with its live pressure drawn on the same scale."""

    HEIGHT = 72
    INSET = 18.0
    TRACK_TOP = 20.0
    TRACK_HEIGHT = 12.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, MAX_RESISTANCE)
        self.setSingleStep(10)
        self.setPageStep(50)
        self.setAccessibleName(tr("Resistance"))
        self.setMinimumHeight(self.HEIGHT)
        self.setMaximumHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._other = tr(OTHER)
        self._active_edge = "right"
        self._pressure = 0.0
        self._crossing = False
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(120)
        self._flash_timer.timeout.connect(self._clear_crossing_flash)
        self._update_accessibility_description()
        self.valueChanged.connect(self._update_value_description)

    def minimumSizeHint(self) -> QSize:
        return QSize(160, self.HEIGHT)

    def set_other_name(self, name: str) -> None:
        name = name or tr(OTHER)
        if name != self._other:
            self._other = name
            self.update()

    def peer_label_text(self) -> str:
        metrics = QFontMetrics(theme.font(tokens.TYPE["eyebrow"], 600))
        return metrics.elidedText(self._other.upper(), Qt.TextElideMode.ElideRight,
                                  max(1, round(self.width() / 2 - 16)))

    def set_edge(self, edge: str) -> None:
        if edge:
            self._active_edge = edge
            self._update_accessibility_description()

    def set_value(self, value: int) -> None:
        self.setValue(int(value))

    def set_pressure(self, pressure: float, edge: str | None = None, crossed: bool = False) -> None:
        self._flash_timer.stop()
        self._crossing = bool(crossed)
        if edge:
            self._active_edge = edge
        self._pressure = min(float(MAX_RESISTANCE), max(0.0, float(pressure)))
        if self._crossing:
            self._flash_timer.start()
        self._update_accessibility_description()
        self.update()

    def _clear_crossing_flash(self) -> None:
        self._crossing = False
        self._pressure = 0.0
        self._update_accessibility_description()
        self.update()

    def _update_value_description(self, _value: int) -> None:
        self._update_accessibility_description()
        self.update()

    def _update_accessibility_description(self) -> None:
        pressure = int(round(self._pressure))
        threshold = self.value()
        edge = tr(DIRECTION_NAMES[self._active_edge])
        description = (tr("Current pressure {pressure} of {threshold} pointer units at the {edge} edge.").format(
            pressure=pressure, threshold=threshold, edge=edge) if pressure > 0 else
            tr("No push. Current pressure is 0 of {threshold} pointer units.").format(threshold=threshold))
        self.setAccessibleDescription(description)

    def keyPressEvent(self, event) -> None:
        steps = {Qt.Key.Key_Left: -1, Qt.Key.Key_Down: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: 1}
        direction = steps.get(event.key())
        if direction is not None and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.setValue(self.value() + direction)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._move_to(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown():
            self._move_to(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.isSliderDown() and event.button() == Qt.MouseButton.LeftButton:
            self._move_to(event.position().x())
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _move_to(self, x: float) -> None:
        fraction = (float(x) - self.INSET) / max(1.0, self.width() - 2 * self.INSET)
        self.setValue(round(min(1.0, max(0.0, fraction)) * MAX_RESISTANCE))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _colour("ground"))
        painter.setPen(QPen(_colour("rule"), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 3, 3)

        left = resistance_x(self.width(), 0)
        right = resistance_x(self.width(), MAX_RESISTANCE)
        span = right - left
        track = QRectF(left, self.TRACK_TOP, span, self.TRACK_HEIGHT)
        painter.setPen(QPen(_colour("ink_3"), 1.0))
        painter.setBrush(_colour("well"))
        painter.drawRoundedRect(track, 3, 3)

        head = resistance_x(self.width(), self._pressure)
        if self._pressure > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_colour("signal"))
            painter.drawRoundedRect(QRectF(left, self.TRACK_TOP + 0.5, max(0.0, head - left),
                                           self.TRACK_HEIGHT - 1), 2.5, 2.5)

        thumb_x = resistance_x(self.width(), self.value())
        painter.setPen(QPen(_colour("ink"), 2.0))
        painter.drawLine(QPointF(thumb_x, 17.5), QPointF(thumb_x, 38.0))
        marker = "resistance_flash" if self._crossing else "signal" if self._pressure > 0 else "edge"
        painter.setPen(QPen(_colour(marker), 3.0 if self._crossing else 2.0))
        painter.drawLine(QPointF(left, 17.0), QPointF(left, 41.0))

        if self.hasFocus():
            painter.setPen(QPen(_colour("signal"), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-3, -3, 3, 3), 4, 4)

        painter.setFont(theme.font(tokens.TYPE["eyebrow"], 600))
        painter.setPen(_colour("ink_3"))
        local_rect = QRectF(8, 2, self.width() / 2 - 8, 15)
        peer_rect = QRectF(self.width() / 2, 2, self.width() / 2 - 8, 15)
        painter.drawText(local_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tr("THIS PC"))
        painter.drawText(peer_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         self.peer_label_text())

        for value in range(0, MAX_RESISTANCE + 1, 25):
            x = resistance_x(self.width(), value)
            major = value % 100 == 0
            painter.setPen(QPen(_colour("ink_3" if major else "edge"), 1.0))
            painter.drawLine(QPointF(x, track.bottom()), QPointF(x, track.bottom() + (12 if major else 4)))
            if major:
                painter.setFont(theme.mono_font(tokens.TYPE["eyebrow"]))
                painter.setPen(_colour("ink_2"))
                painter.drawText(QRectF(x - 22, 52, 44, 17), Qt.AlignmentFlag.AlignCenter, str(value))
        painter.end()
