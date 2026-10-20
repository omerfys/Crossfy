"""The Design page's pictures of the crossing styles: a still for each tile at the place the page's
Show at chooses, played on from while the pointer is over it, drawn from effects.preview_scene, the
same loop the Mac's Design page plays, replayed by the overlay's own `replay`."""

from __future__ import annotations

import logging
import time
import math

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

import edge_glow
from core import effects
from frame_clock import PREVIEW_MAX_RATE, frame_timer, start_paced
import motion
import theme
import tokens
from effect_overlay import replay, system_reduced_motion

LOGGER = logging.getLogger(__name__)

# One effect layer, reused while the preview's size holds, rather than a new image every frame.
_LAYERS = {}
_SHADOWS = {}
STILL_HEIGHT = 56
_SCREEN_NAMES = {"mac": "MAC", "windows": "PC"}
# A specimen tile: the share of each side its marks fade over, how far below them their shadow
# falls and how much darker than the card it is (QColor.darker), and the seam tick's length, in px.
FEATHER = 0.1
SHADOW_DROP = 1.0
SHADOW_DEPTH = 125
SEAM_TICK = 10
# A pointer passing over tiles on its way elsewhere leaves the tiles it crosses still.
HOVER_INTENT_S = 0.1


def on_screen(widget: QWidget) -> bool:
    """Whether any of `widget` can be seen: shown in a window that is not minimised, and not
    scrolled out of its page."""
    return widget.isVisible() and not widget.window().isMinimized() and not widget.visibleRegion().isEmpty()


def _pointer_path(size: float) -> QPainterPath:
    """An arrow pointer `size` tall with its tip at the origin."""
    path = QPainterPath()
    for index, (x, y) in enumerate(effects.PREVIEW_POINTER):
        (path.lineTo if index else path.moveTo)(x * size, y * size)
    path.closeSubpath()
    return path


def paint_scene(painter: QPainter, rect: QRectF, view: QRectF, scene: dict, pointer_size: float, labels: bool) -> None:
    """Draws the `view` part of a preview_scene (in scene points) into `rect`, scaled to fit and
    centred: the screens, then the pens, then the pointer, then the notch, the order the scene
    asks for."""
    scale = min(rect.width() / view.width(), rect.height() / view.height())
    width, height = view.width(), view.height()
    left = rect.x() + (rect.width() - width * scale) / 2.0
    top = rect.y() + (rect.height() - height * scale) / 2.0
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    local_transform = painter.transform()
    painter.setClipRect(QRectF(left, top, width * scale, height * scale))
    painter.translate(left, top)
    painter.scale(scale, scale)
    painter.translate(-view.x(), -view.y())
    radius = tokens.RADIUS["field"] / scale
    for x, y, w, h, os_name in scene["screens"]:
        painter.setPen(QPen(QColor(theme.colour("rule")), 1.0 / scale))
        ground = theme.colour("ground") if "seam" in scene else effects.PREVIEW_TILE_GROUND
        painter.setBrush(QColor(ground))
        screen = QRectF(x, y, w, h)
        if not labels:
            screen = screen.intersected(view).adjusted(1 / scale, 1 / scale, -1 / scale, -1 / scale)
        painter.drawRoundedRect(screen, radius, radius)
        if labels:
            painter.setPen(QColor(theme.colour("ink_3")))
            painter.setFont(theme.eyebrow_font())
            # Bottom left of the part of the screen in view, which no crossing in the loop comes near.
            shown = QRectF(x, y, w, h).intersected(view)
            painter.save()
            painter.translate(shown.x(), shown.y())
            painter.scale(1.0 / scale, 1.0 / scale)
            corner = QRectF(10, shown.height() * scale - 26, shown.width() * scale - 20, 18)
            painter.drawText(corner, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, _SCREEN_NAMES.get(os_name, ""))
            painter.restore()
    if scene.get("seam") is not None:
        _paint_scene_seam(painter, scene["seam"], view, scale)
    # The effects draw on their own layer, as the overlay does over the desktop, so "lighter"
    # adds to the effect's own light rather than to the screens drawn under it.
    if not scene["pens"]:
        _paint_pointer_and_notch(painter, scene, scale, pointer_size)
        painter.restore()
        return
    ratio = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
    size = (int(width * scale * ratio) + 1, int(height * scale * ratio) + 1, ratio)
    layer = _LAYERS.get(size)
    if layer is None:
        _LAYERS.clear()
        layer = _LAYERS[size] = QImage(size[0], size[1], QImage.Format.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(ratio)
    layer.fill(Qt.GlobalColor.transparent)
    layer_painter = QPainter(layer)
    layer_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    layer_painter.scale(scale, scale)
    layer_painter.translate(-view.x(), -view.y())
    try:
        replay(layer_painter, scene["pens"])
    finally:
        layer_painter.end()
    painter.save()
    painter.setTransform(local_transform)
    painter.translate(left, top)
    if "seam" in scene:
        _feather(layer, width * scale, height * scale)
        painter.drawImage(0, SHADOW_DROP, _shadow(layer))
    painter.drawImage(0, 0, layer)
    if scene.get("seam") is not None:
        painter.translate(-left, -top)
        _paint_seam_tick(painter, scene["seam"], view, scale, QPointF(left, top))
    painter.restore()
    _paint_pointer_and_notch(painter, scene, scale, pointer_size)
    painter.restore()


def _feather(layer: QImage, width: float, height: float) -> None:
    """Fades `layer` out over FEATHER of each side, so a specimen whose marks run past its view
    thins away into the card rather than stopping at a cut edge."""
    painter = QPainter(layer)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    for end in (QPointF(width, 0), QPointF(0, height)):
        ramp = QLinearGradient(QPointF(0, 0), end)
        ramp.setColorAt(0.0, QColor(0, 0, 0, 0))
        ramp.setColorAt(FEATHER, QColor(0, 0, 0, 255))
        ramp.setColorAt(1.0 - FEATHER, QColor(0, 0, 0, 255))
        ramp.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(QRectF(0, 0, width, height), ramp)
    painter.end()


def _shadow(layer: QImage) -> QImage:
    """The faint shadow a specimen casts on its card: the marks' shape, softened by a pixel, in the
    card colour taken a step down, so the marks lift off the card in Light. On the near-black Dark
    card it all but vanishes, as additive light needs nothing under it."""
    key = (layer.width(), layer.height(), layer.devicePixelRatio())
    shadow = _SHADOWS.get(key)
    if shadow is None:
        _SHADOWS.clear()
        shadow = _SHADOWS[key] = QImage(layer.size(), QImage.Format.Format_ARGB32_Premultiplied)
        shadow.setDevicePixelRatio(layer.devicePixelRatio())
    shadow.fill(Qt.GlobalColor.transparent)
    painter = QPainter(shadow)
    painter.setOpacity(0.35)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (0, 0)):
        painter.drawImage(QPointF(dx * 0.75, dy * 0.75), layer)
    painter.setOpacity(1.0)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(shadow.rect(), QColor(theme.colour("ground")).darker(SHADOW_DEPTH))
    painter.end()
    return shadow


def _paint_seam_tick(painter: QPainter, seam, view: QRectF, scale: float, origin: QPointF) -> None:
    """The crossing as one short rule where the seam leaves the bottom of the view (the left, for
    the notch's level seam), in the card's quietest ink, on whole pixels so it stays a hairline."""
    x0, y0, x1, _y1 = seam
    painter.setPen(QPen(QColor(theme.colour("ink_2")), 1.0))
    if x0 == x1:
        x = math.floor(origin.x() + (x0 - view.x()) * scale) + 0.5
        bottom = math.floor(origin.y() + view.height() * scale)
        painter.drawLine(QPointF(x, bottom - SEAM_TICK), QPointF(x, bottom - 1))
    else:
        y = math.floor(origin.y() + (y0 - view.y()) * scale) + 0.5
        left = math.ceil(origin.x())
        painter.drawLine(QPointF(left, y), QPointF(left + SEAM_TICK - 1, y))


def _paint_scene_seam(painter: QPainter, seam, view: QRectF, scale: float) -> None:
    """Draw the quiet screen boundary through the visible part of the crossing seam."""
    x0, y0, x1, y1 = seam
    painter.setPen(QPen(QColor(theme.colour("rule")), 1.0 / scale))
    if x0 == x1:
        x = view.x() + (math.floor((x0 - view.x()) * scale) + 0.5) / scale
        painter.drawLine(QPointF(x, view.y()), QPointF(x, view.bottom()))
    else:
        y = view.y() + (math.floor((y0 - view.y()) * scale) + 0.5) / scale
        painter.drawLine(QPointF(view.x(), y), QPointF(view.right(), y))


def _paint_pointer_and_notch(painter: QPainter, scene: dict, scale: float, pointer_size: float) -> None:
    if scene["pointer"] is not None:
        px, py, _os = scene["pointer"]
        painter.save()
        painter.translate(px, py)
        painter.scale(1.0 / scale, 1.0 / scale)
        arrow = _pointer_path(pointer_size)
        painter.setPen(QPen(QColor("#000000"), 1.2 * pointer_size / 18.0,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor("#ffffff"))
        painter.drawPath(arrow)
        painter.restore()
    if scene["notch"] is not None:
        nx, ny, nw, nh, nr = scene["notch"]
        notch = QPainterPath()
        notch.addRoundedRect(QRectF(nx, ny - nr, nw, nh + nr), nr, nr)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#000000"))
        painter.drawPath(notch)


class EffectStill(QWidget):
    """A crossing tile holds its canonical mid-crossing frame, then plays the full timeline on hover."""

    def __init__(self, effect_id: str, palette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.effect_id = effect_id
        self.palette = tuple(palette)
        self.place = "edge"
        self.pace = 1.0
        self.effect_size = "medium"
        self.effect_size_fraction = None
        self._image = None
        self.playing_since = None
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(1, round(width / 2))

    def sizeHint(self):
        return QSize(STILL_HEIGHT * 2, STILL_HEIGHT)

    def set_palette(self, palette) -> None:
        if tuple(palette) != self.palette:
            self.palette = tuple(palette)
            self._image = None
            self.update()

    def set_place(self, place: str) -> None:
        if place != self.place:
            self.place = place
            self._image = None
            self.update()

    def set_pace(self, pace: float) -> None:
        # The still is the same frame of the effect at every Length (effects.still_time), so its
        # picture stands; only playing it reads the pace, and redrawing every tile at each step of
        # the slider was most of the page's lag.
        self.pace = pace

    def set_effect_size(self, size: str, fraction: float | None = None) -> None:
        if (size, fraction) != (self.effect_size, self.effect_size_fraction):
            self.effect_size = size
            self.effect_size_fraction = fraction
            self._image = None
            self.update()

    def refresh_colours(self) -> None:
        # A cached image, not a live paint: without this an appearance switch leaves it showing
        # the old palette until something else invalidates the cache.
        self._image = None

    def paintEvent(self, _event) -> None:
        elapsed = None if self.playing_since is None else time.monotonic() - self.playing_since
        reduced = system_reduced_motion()
        live = elapsed is not None and elapsed >= 0.0 and not reduced
        t = effects.preview_time(self._still_time(), elapsed, reduced=reduced,
                                 switch=isinstance(self, SwitchStill))
        if live:
            painter = QPainter(self)
            try:
                self._paint_still(painter, t, still=False)
            except Exception:
                LOGGER.exception("Could not draw crossing effect %s", self.effect_id)
                self.playing_since = None
            painter.end()
            return
        ratio = self.devicePixelRatioF()
        size = QSize(math.ceil(self.width() * ratio), math.ceil(self.height() * ratio))
        if self._image is None or self._image.size() != size or self._image.devicePixelRatio() != ratio:
            self._image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            self._image.setDevicePixelRatio(ratio)
            self._image.fill(Qt.GlobalColor.transparent)
            image_painter = QPainter(self._image)
            try:
                self._paint_still(image_painter, t, still=True)
            except Exception:
                LOGGER.exception("Could not draw the still of crossing effect %s", self.effect_id)
            finally:
                image_painter.end()
        painter = QPainter(self)
        painter.drawImage(0, 0, self._image)
        painter.end()

    def _paint_still(self, painter: QPainter, t: float, still: bool = False) -> None:
        view = QRectF(*effects.still_view(self.effect_id, self.place, self.effect_size, self.pace,
                                          self.effect_size_fraction))
        scene = effects.preview_still_scene(effects.preview_effect(self.effect_id), t, self.place, self.palette,
                                            system_reduced_motion(), theme.is_dark(), self.pace, self.effect_size,
                                            live=not still, view_width=view.width(),
                                            effect_size_fraction=self.effect_size_fraction)
        paint_scene(painter, QRectF(self.rect()), view, scene, 11.0, labels=False)

    def _still_time(self) -> float:
        return effects.still_time(self.effect_id, self.place, self.effect_size, self.pace,
                                  self.effect_size_fraction)


class SwitchStill(EffectStill):
    """A Switch tile's picture: what a switch plays for `choice` beside the crossing style, round a
    still pointer, part-way through."""

    def __init__(self, choice: str, crossing_style: str, palette, parent: QWidget | None = None) -> None:
        super().__init__(choice, palette, parent)
        self.crossing_style = crossing_style

    def set_crossing_style(self, style: str) -> None:
        if style != self.crossing_style:
            self.crossing_style = style
            self._image = None
            self.update()

    def _paint_still(self, painter: QPainter, t: float, still: bool = False) -> None:
        fx = effects.switch_effect(self.effect_id, self.crossing_style)
        view = QRectF(*effects.still_view(fx, "switch", self.effect_size, self.pace,
                                          self.effect_size_fraction))
        scene = effects.preview_still_scene(fx, t, "switch", self.palette, reduced=system_reduced_motion(),
                                            dark=theme.is_dark(), pace=self.pace, effect_size=self.effect_size,
                                            live=not still, view_width=view.width(),
                                            effect_size_fraction=self.effect_size_fraction)
        paint_scene(painter, QRectF(self.rect()), view, scene, 11.0, labels=False)

    def _still_time(self) -> float:
        return effects.still_time(effects.switch_effect(self.effect_id, self.crossing_style), "switch",
                                  self.effect_size, self.pace, self.effect_size_fraction)


class TileHover(QObject):
    """The one tile under the pointer plays its animation and settles back to its still when the
    pointer leaves; under Reduce Motion it keeps its still. An effect's still plays on from the
    frame it shows, and Glow and Beam from their held push, so a tile starts without a jump."""

    def __init__(self, loop: edge_glow.PreviewLoop, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.loop = loop
        self._pictures: dict = {}
        self.current = None
        self._timer = frame_timer(self, self._tick, max_rate=PREVIEW_MAX_RATE)

    def track(self, tile: QWidget, picture: QWidget) -> None:
        self._pictures[tile] = picture
        tile.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Enter and watched in self._pictures:
            self.enter(self._pictures[watched])
        elif kind == QEvent.Type.Leave and watched in self._pictures and self._pictures[watched] is self.current:
            self.stop()
        return False

    def enter(self, picture: QWidget) -> None:
        if picture is self.current:
            return
        self.stop()
        self.current = picture
        if system_reduced_motion():
            return
        if isinstance(picture, edge_glow.GlowPreview):
            self.loop.hover(picture)
            return
        picture.playing_since = time.monotonic() + HOVER_INTENT_S
        start_paced(self._timer, picture, PREVIEW_MAX_RATE)

    def stop(self) -> None:
        picture, self.current = self.current, None
        self._timer.stop()
        if picture is None:
            return
        played = (self.loop.hovered is picture and self.loop.playing(picture)) or (
            getattr(picture, "playing_since", None) is not None and time.monotonic() > picture.playing_since
        )
        shot = motion.snapshot(picture) if played else None
        if isinstance(picture, edge_glow.GlowPreview):
            self.loop.hover(None)
        else:
            picture.playing_since = None
            picture.update()
        motion.fade_from(picture, shot)

    def _tick(self) -> None:
        if self.current is not None and on_screen(self.current):
            self.current.update()
