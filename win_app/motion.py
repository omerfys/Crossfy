"""The settings window's motion: every visual change runs 200 ms with an ease-out, the next change
interrupts it from wherever it had got to, and nothing moves while the window cannot be seen or
while Windows' "Show animations in Windows" is off. Qt's own animations only, no library."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QRect, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

DURATION = 200
QWIDGETSIZE_MAX = 16777215


def reduced() -> bool:
    """Read at each change, as the setting can flip while the window is open."""
    try:
        from effect_overlay import system_reduced_motion
    except Exception:
        return False
    return system_reduced_motion()


def should_animate(widget: QWidget) -> bool:
    window = widget.window()
    return window.isVisible() and not window.isMinimized() and not reduced()


def _runs(owner) -> dict:
    runs = getattr(owner, "_motion_runs", None)
    if runs is None:
        runs = {}
        owner._motion_runs = runs
    return runs


def running(owner, key: str) -> bool:
    return key in _runs(owner)


def stop(owner, key: str) -> None:
    animation = _runs(owner).pop(key, None)
    if animation is not None:
        animation.stop()
        animation.deleteLater()


def animate(owner: QWidget, key: str, start, end, apply, done=None, duration: int = DURATION,
            curve=QEasingCurve.Type.OutCubic, force: bool = False):
    """Runs `apply(value)` from `start` to `end`, then `done()`. A second call with the same key
    replaces the first without calling its `done`, so the caller restarts from the current value.
    Instant, `apply(end)` then `done()`, when the window cannot be seen or motion is reduced."""
    stop(owner, key)
    if not force and not should_animate(owner):
        apply(end)
        if done is not None:
            done()
        return None
    animation = QVariantAnimation(owner)
    animation.setDuration(duration)
    animation.setEasingCurve(QEasingCurve(curve))
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.valueChanged.connect(apply)
    runs = _runs(owner)

    def finished():
        if runs.get(key) is animation:
            del runs[key]
            animation.deleteLater()
        if done is not None:
            done()

    animation.finished.connect(finished)
    runs[key] = animation
    apply(start)
    animation.start()
    return animation


class _Fade(QGraphicsOpacityEffect):
    """Marks an opacity effect as motion's own, so it is never mistaken for a widget's dimming."""


def _fade_of(widget: QWidget):
    effect = widget.graphicsEffect()
    if isinstance(effect, _Fade):
        return effect
    if effect is not None:
        return None
    effect = _Fade(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    return effect


def _drop_fade(widget: QWidget) -> None:
    if isinstance(widget.graphicsEffect(), _Fade):
        widget.setGraphicsEffect(None)


def _width_for(widget: QWidget) -> int:
    width = widget.width()
    parent = widget.parentWidget()
    if parent is not None and (width <= 0 or widget.isHidden()):
        margins = parent.contentsMargins()
        width = parent.width() - margins.left() - margins.right()
        if parent.layout() is not None:
            inner = parent.layout().contentsMargins()
            width -= inner.left() + inner.right()
    return width


def _natural_height(widget: QWidget) -> int:
    width = _width_for(widget)
    if widget.hasHeightForWidth() and width > 0:
        height = widget.heightForWidth(width)
        if height > 0:
            return height
    return widget.sizeHint().height()


def target_shown(widget: QWidget) -> bool:
    """Where `set_shown` is taking the widget, which may not be where it is yet."""
    target = getattr(widget, "_motion_shown", None)
    return (not widget.isHidden()) if target is None else target


def set_shown(widget: QWidget, shown: bool, *, fade: bool = True) -> None:
    """Shows or hides a row or module by sliding its height open or shut and fading it; the cap on
    its height comes off at the end, so later layout is never held to the animated size."""
    shown = bool(shown)
    if target_shown(widget) == shown:
        return
    moving = running(widget, "shown")
    widget._motion_shown = shown

    layout = widget.layout()

    def finish():
        widget.setMaximumHeight(QWIDGETSIZE_MAX)
        _drop_fade(widget)
        if layout is not None and not layout.isEnabled():
            layout.setEnabled(True)
            layout.invalidate()
        widget.setVisible(shown)
        widget._motion_shown = None

    if not should_animate(widget):
        stop(widget, "shown")
        finish()
        return
    # Crossing rows uncover at full opacity: an opacity effect composites the whole subtree.
    fade = _fade_of(widget) if fade else None
    start_height = widget.height() if (moving or not widget.isHidden()) else 0
    start_opacity = fade.opacity() if (fade is not None and moving) else (0.0 if shown else 1.0)
    end_height = _natural_height(widget) if shown else 0
    if layout is not None and layout.isEnabled():
        # The contents keep their full-size places while the height changes, so the row is
        # uncovered or covered like a blind rather than squeezed; the layout comes back at the end.
        full = end_height if shown else widget.height()
        layout.setGeometry(QRect(0, 0, _width_for(widget), full))
        layout.setEnabled(False)
    widget.setMaximumHeight(start_height)
    widget.setVisible(True)

    def apply(t):
        widget.setMaximumHeight(round(start_height + (end_height - start_height) * t))
        if fade is not None:
            fade.setOpacity(start_opacity + ((1.0 if shown else 0.0) - start_opacity) * t)

    animate(widget, "shown", 0.0, 1.0, apply, finish)


def snapshot(widget: QWidget):
    """What `widget` looks like now, for `fade_from` after the change; None when no fade would
    play, so the caller changes it straight away."""
    # Scrolled out of its page, the fade would play where no one sees it, and the grab costs a paint.
    if not widget.isVisible() or widget.width() <= 0 or widget.visibleRegion().isEmpty() or not should_animate(widget):
        return None
    return widget.grab(), widget.geometry()


def fade_from(widget: QWidget, shot, fade_in: bool = False) -> None:
    """Lays `shot`, taken by `snapshot` before a change, over `widget` and fades it out, so the old
    picture dissolves into the new. `fade_in` also brings the widget itself up from nothing, for a
    widget with no background of its own, where the old would otherwise sit on top of the new."""
    old = getattr(widget, "_motion_ghost", None)
    if old is not None:
        stop(old, "ghost")
        old.deleteLater()
        widget._motion_ghost = None
        # Stopped, the old fade never ran its finish: a widget it was bringing up would stay
        # part faded until some later change.
        _drop_fade(widget)
    if shot is None or widget.parentWidget() is None:
        return
    pixmap, geometry = shot
    ghost = QLabel(widget.parentWidget())
    ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    ghost.setStyleSheet("background: transparent;")
    ghost.setPixmap(pixmap)
    ghost.setGeometry(geometry)
    ghost.show()
    ghost.raise_()
    widget._motion_ghost = ghost
    ghost_fade = _Fade(ghost)
    ghost.setGraphicsEffect(ghost_fade)
    new_fade = _fade_of(widget) if fade_in else None

    def apply(t):
        ghost_fade.setOpacity(1.0 - t)
        if new_fade is not None:
            new_fade.setOpacity(t)

    def finish():
        if getattr(widget, "_motion_ghost", None) is ghost:
            widget._motion_ghost = None
        ghost.deleteLater()
        if new_fade is not None:
            _drop_fade(widget)

    animate(ghost, "ghost", 0.0, 1.0, apply, finish, force=True)


def lerp_rect(a: QRectF, b: QRectF, t: float) -> QRectF:
    return QRectF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t,
                  a.width() + (b.width() - a.width()) * t, a.height() + (b.height() - a.height()) * t)


class Ring(QWidget):
    """The chosen choice's ring, drawn over a group of choices and slid from one to the next, across
    the group's rows. `locate(widget)` gives the rect to ring in that widget's own coordinates. The
    ring is worked out at paint time, so it follows the layout as the window resizes."""

    def __init__(self, host: QWidget, locate, colour, radius: float, width: float = 2.0) -> None:
        super().__init__(host)
        self._host = host
        self._locate = locate
        self._colour = colour
        self._radius = radius
        self._width = width
        self._target = None
        self._from = None
        self._t = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")
        self.setGeometry(host.rect())
        host.installEventFilter(self)
        self.show()

    def eventFilter(self, watched, event) -> bool:
        # A ring being collected can still be asked, its host outliving it, with its fields gone.
        if watched is getattr(self, "_host", None) and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self.setGeometry(self._host.rect())
            self.raise_()
            self.update()
        return False

    def _rect_of(self, widget):
        if widget is None or not widget.isVisibleTo(self._host):
            return None
        rect = self._locate(widget)
        return QRectF(rect).translated(widget.mapTo(self._host, widget.rect().topLeft()).toPointF())

    def current(self):
        """The rect the ring is drawn at now, in the host's coordinates."""
        end = self._rect_of(self._target)
        if end is None:
            return None
        if self._from is None or self._t >= 1.0:
            return end
        return lerp_rect(self._from, end, self._t)

    def follow(self, target: QWidget | None) -> None:
        if target is self._target:
            return
        start = self.current()
        self._target = target
        self.raise_()
        if start is None or target is None:
            stop(self, "ring")
            self._from, self._t = None, 1.0
            self.update()
            return
        self._from = start

        def apply(t):
            self._t = t
            self.update()

        animate(self, "ring", 0.0, 1.0, apply)

    def paintEvent(self, _event) -> None:
        rect = self.current()
        if rect is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = self._colour() if callable(self._colour) else self._colour
        painter.setPen(QPen(QColor(colour), self._width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, self._radius, self._radius)
