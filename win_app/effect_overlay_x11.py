"""Run crossing windows on XWayland when the compositor permits edge overlays."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import sys


def available(wayland, environ):
    return bool(wayland and environ.get("DISPLAY"))


def mapped_point(x, y, source, target):
    """Map a desktop point by fraction between the source and helper desktop bounds."""
    sx, sy, sw, sh = source
    return (target.x() + (x - sx) * target.width() / sw,
            target.y() + (y - sy) * target.height() / sh)


def dispatch(command, overlay, glow, target, point_factory=None):
    op = command["op"]
    if op in ("effect_configure", "glow_configure"):
        # The helper is its own process: the Design page's Frame rate reaches its clocks only here.
        import frame_clock
        frame_clock.set_divisor(command.get("divisor", 1))
    if op == "effect_configure":
        overlay.configure(command["style"], command["colour"], command["length"], command["size"],
                          command.get("effect_pace"), command.get("size_fraction"))
    elif op == "push":
        if "x" in command:
            point = mapped_point(command["x"], command["y"], command["desk"], target)
            if point_factory is not None:
                point = point_factory(*point)
            overlay.push(command["edge"], command["pressure"], command["crossed"], cursor=point,
                         part=command.get("part"))
        else:
            overlay.push(command["edge"], command["pressure"], command["crossed"], part=command.get("part"))
    elif op == "arrive":
        point = mapped_point(command["x"], command["y"], command["desk"], target)
        if point_factory is not None:
            point = point_factory(*point)
        overlay.arrive(command["method"], command["edge"], point)
    elif op == "crossed_in":
        overlay.crossed_in()
    elif op == "switched":
        point = mapped_point(command["x"], command["y"], command["desk"], target)
        if point_factory is not None:
            point = point_factory(*point)
        overlay.switched(point, command["choice"])
    elif op == "glow_configure":
        glow.configure(command["style"], command["colour"], command["length"], command["size"],
                       command.get("effect_pace"), command.get("size_fraction"))
    elif op == "glow_pressure":
        glow.set_pressure(command["edge"], command["pressure"], command["crossed"], command.get("part"))
    elif op == "stop":
        overlay.stop()
        glow.hide()
    return True


class EffectOverlayX11Proxy:
    def __init__(self, on_failure=None, popen=subprocess.Popen):
        self._on_failure = on_failure
        self._popen = popen
        self._process = None
        self._reader = None
        self._timer = None
        self._failed = False
        self._effect_ready = False
        self._showing = False
        self._pending = False

    @property
    def failed(self):
        self.check_process()
        return self._failed

    @property
    def effect_ready(self):
        return self._effect_ready

    def configure(self, style, colour, length="normal", size="medium", effect_pace=None, size_fraction=None):
        self._effect_ready = bool(style)
        import frame_clock
        self._send("effect_configure", style=style, colour=colour, length=length, size=size,
                   effect_pace=effect_pace, size_fraction=size_fraction, divisor=frame_clock.divisor())

    def configure_glow(self, style, colour, length="normal", size="medium", effect_pace=None, size_fraction=None):
        import frame_clock
        self._send("glow_configure", style=style, colour=colour, length=length, size=size,
                   effect_pace=effect_pace, size_fraction=size_fraction, divisor=frame_clock.divisor())

    def push(self, edge, pressure, crossed, cursor=None, part=None, desk=None):
        self._showing = bool(pressure > 0.0 or crossed)
        values = {"edge": edge, "pressure": pressure, "crossed": crossed, "part": part}
        if cursor is not None:
            values.update(x=cursor.x(), y=cursor.y(),
                          desk=[desk.x(), desk.y(), desk.width(), desk.height()])
        self._send("push", **values)

    def set_pressure(self, edge, pressure, crossed, part=None):
        self._showing = bool(pressure > 0.0 or crossed)
        self._send("glow_pressure", edge=edge, pressure=pressure, crossed=crossed, part=part)

    def arrive(self, method, edge, x, y, desk):
        self._showing = True
        self._send("arrive", method=method, edge=edge, x=x, y=y, desk=desk)

    def crossed_in(self):
        self._showing = True
        self._send("crossed_in")

    def switched(self, x, y, desk, choice="match"):
        self._showing = True
        self._send("switched", x=x, y=y, desk=desk, choice=choice)

    def hide(self):
        self.stop()

    def stop(self):
        # Hides both windows and keeps the helper: _hide_crossing runs on every settings change
        # and departure, and a new helper costs a Python and Qt start. It exits when this
        # process closes its stdin, at quit.
        self._showing = False
        self._pending = False
        if self._process is not None:
            self._send("stop")
        self._update_timer()

    def _ensure_timer(self):
        if self._timer is None:
            try:
                from PySide6.QtWidgets import QApplication

                app = QApplication.instance()
            except ImportError:
                app = None
            if app is not None:
                from PySide6.QtCore import QTimer

                self._timer = QTimer()
                self._timer.setInterval(100)
                self._timer.timeout.connect(self._on_timer)
        return self._timer

    def _update_timer(self):
        timer = self._ensure_timer()
        if timer is None:
            return
        # Fast while something shows or a change is pending; slow while the helper idles, so one that
        # dies or fails at start is still noticed before the next crossing.
        busy = self._showing or self._pending
        should_run = not self._failed and (busy or self._process is not None)
        interval = 100 if busy else 1000
        if timer.interval() != interval:
            timer.setInterval(interval)
        if should_run and not timer.isActive():
            timer.start()
        elif not should_run and timer.isActive():
            timer.stop()

    def _on_timer(self):
        self.check_process()
        self._pending = False
        self._update_timer()

    def check_process(self):
        process = self._process
        if process is None:
            return
        if process.stdout is not None:
            try:
                ready, _, _ = select.select([process.stdout], [], [], 0)
                if ready:
                    line = process.stdout.readline()
                    if line.startswith("failed "):
                        self._fail()
            except (OSError, ValueError):
                pass
        if process.poll() is not None:
            self._fail()

    def _send(self, op, check=True, **values):
        if self._failed:
            return
        if self._process is None:
            try:
                env = dict(os.environ, QT_QPA_PLATFORM="xcb")
                self._process = self._popen(
                    [sys.executable, str(Path(__file__).with_name("effect_overlay_x11.py"))],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1, env=env,
                )
                self._ensure_timer()
            except OSError:
                self._fail()
                return
        if check:
            self.check_process()
        if self._failed:
            return
        if op != "stop":
            self._pending = True
        try:
            self._process.stdin.write(json.dumps({"op": op, **values}, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self._fail()
        self._update_timer()

    def _fail(self):
        if self._failed:
            return
        self._failed = True
        self._showing = False
        self._pending = False
        if self._timer is not None:
            self._timer.stop()
        process, self._process = self._process, None
        if process is not None:
            try:
                process.stdin.close()
            except (AttributeError, OSError, ValueError):
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if self._on_failure is not None:
            self._on_failure()


def create_overlays(on_failure=None):
    from PySide6.QtCore import QRect, Qt
    from edge_glow import EdgeGlow
    from effect_overlay import EffectOverlay

    class X11Overlay(EffectOverlay):
        def _clear_fixed(self):
            # Keep the transparent surface mapped so compositor map/unmap handling
            # cannot flash the desktop or obscure the beginning of the next effect.
            dirty, self._dirty_rect = self._dirty_rect, QRect()
            self._hide_after_paint = False
            if not dirty.isNull():
                self.update(dirty)
            if not self.player.busy:
                self._timer.stop()

    overlay = X11Overlay(on_failure=on_failure, fixed_geometry=True)
    glow = EdgeGlow()
    for widget in (overlay, glow):
        # Identify an overlay rather than a utility window to the shell; the bypass
        # hint alone still leaves Qt's utility window type on the X surface.
        widget.setWindowFlags((widget.windowFlags() & ~Qt.WindowType.WindowType_Mask)
                              | Qt.WindowType.ToolTip | Qt.WindowType.X11BypassWindowManagerHint)
    return overlay, glow


def run_helper():
    from PySide6.QtCore import QPointF, QSocketNotifier
    from PySide6.QtWidgets import QApplication
    from effect_overlay import desktop_box

    app = QApplication(sys.argv)
    overlay, glow = create_overlays(on_failure=lambda: print("failed effect", flush=True))
    box = desktop_box()
    notifier = QSocketNotifier(0, QSocketNotifier.Type.Read)
    pending = bytearray()

    def read_input():
        try:
            data = os.read(0, 65536)
        except OSError:
            data = b""
        if not data:
            # End of input stays readable, so the notifier would fire until the loop exits.
            notifier.setEnabled(False)
            app.quit()
            return
        pending.extend(data)
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending[:] = rest
            try:
                if not dispatch(json.loads(line), overlay, glow, box, QPointF):
                    app.quit()
                    return
            except Exception as exc:
                print(f"failed {type(exc).__name__}", flush=True)
                app.quit()
                return

    notifier.activated.connect(read_input)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_helper())
