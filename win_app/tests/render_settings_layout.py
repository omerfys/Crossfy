"""Render the synthetic Qt settings pages offscreen across the layout matrix.

Run with the worktree's Qt Python. The matrix mode starts a fresh process for every
width and scale because Qt reads scale settings before QApplication is constructed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "win_app"))
sys.path.insert(0, str(TESTS))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QFont
from PySide6.QtWidgets import QApplication, QFrame, QWidget

import pages_win
import theme
from test_settings_layout_acceptance import SyntheticWindow, write_synthetic_settings


WIDTHS = (320, 640, 900, 1440, 1920)
SCALES = ("1.0", "1.25", "1.5", "2.0")
HEIGHT = 900
OUT = Path(os.environ.get("BEAMER_RENDER_OUT", ROOT / "win_app" / "renders"))


def capture_document(page):
    raster = page.grab().toImage()
    canvas = QImage(raster.size(), QImage.Format.Format_ARGB32_Premultiplied)
    canvas.setDevicePixelRatio(raster.devicePixelRatio())
    canvas.fill(QColor(theme.colour("ground")))
    painter = QPainter(canvas)
    painter.drawImage(0, 0, raster)
    painter.end()
    return canvas


def settle(app):
    for _ in range(8):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        app.processEvents()


def rect_in(widget, origin):
    point = widget.mapTo(origin, QPoint())
    return [point.x(), point.y(), widget.width(), widget.height()]


def descendants(widget):
    return [widget, *widget.findChildren(QWidget)]


def widget_record(widget, origin):
    return {
        "class": type(widget).__name__,
        "name": widget.objectName(),
        "text": widget.text() if hasattr(widget, "text") else None,
        "rect": rect_in(widget, origin),
        "minimum": [widget.minimumWidth(), widget.minimumHeight()],
        "maximum": [widget.maximumWidth(), widget.maximumHeight()],
        "visible": widget.isVisible(),
        "dpr": widget.devicePixelRatioF(),
    }


def measurements(window, key, width, scale):
    scroll = window.stack.currentWidget()
    page = scroll.widget()
    column = page.findChild(QWidget, "page_column")
    modules = [child for child in page.findChildren(QFrame)
               if child.property("vernier") == "module" and child.isVisible()]
    visible = [child for child in descendants(column) if child.isVisible()]
    overflowing = []
    for child in visible:
        rect = child.rect()
        point = child.mapTo(column, QPoint())
        if point.x() < 0 or point.x() + rect.width() > column.width() + 1:
            overflowing.append(widget_record(child, column))
    row_groups = {}
    for attr in ("glow_style_choice", "switch_style_choice"):
        group = getattr(window, attr, None)
        if group is None:
            continue
        row_groups[attr] = {
            family: [widget_record(tile, group.view) for tile in choices._tiles.values()]
            for family, choices in group.groups.items()
        }
    swatches = getattr(window, "glow_colour_choice", None)
    return {
        "page": key,
        "requested_width_dip": width,
        "requested_height_dip": HEIGHT,
        "actual_window_dip": [window.width(), window.height()],
        "actual_client_dip": [window.contentsRect().width(), window.contentsRect().height()],
        "scale": float(scale),
        "window_dpr": window.devicePixelRatioF(),
        "raster_size": [window.grab().width(), window.grab().height()],
        "application_font": {
            "family": QApplication.instance().font().family(),
            "point_size": QApplication.instance().font().pointSizeF(),
            "pixel_size": QApplication.instance().font().pixelSize(),
            "weight": int(QApplication.instance().font().weight()),
        },
        "sidebar": widget_record(window.sidebar, window),
        "page_column": widget_record(column, page),
        "viewport": [scroll.viewport().width(), scroll.viewport().height()],
        "document": [page.width(), page.height()],
        "sections": [widget_record(module, page) for module in modules],
        "overflowing_children": overflowing,
        "style_families": row_groups,
        "swatches": ({value: widget_record(sw, swatches.view)
                      for value, sw in swatches._swatches.items()} if swatches else {}),
        "selected_sidebar": [name for name, button in window.sidebar._buttons.items()
                             if button.isChecked()],
        "focused_sidebar": [name for name, button in window.sidebar._buttons.items()
                            if button.hasFocus()],
    }


def make_contact_sheet(images, destination, title, columns=4, tile_width=260, tile_height=190):
    label_height, padding = 25, 12
    rows = (len(images) + columns - 1) // columns
    sheet = QImage(columns * (tile_width + padding) + padding,
                   rows * (tile_height + label_height + padding) + padding + 30,
                   QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(0xFF202124)
    painter = QPainter(sheet)
    painter.setPen(Qt.GlobalColor.white)
    painter.setFont(QFont("Hanken Grotesk", 11))
    painter.drawText(padding, 18, title)
    for index, (label, path) in enumerate(images):
        image = QImage(str(path))
        if image.isNull():
            painter.end()
            raise RuntimeError(f"could not read render {path}")
        col, row = index % columns, index // columns
        x = padding + col * (tile_width + padding)
        y = 30 + padding + row * (tile_height + label_height + padding)
        scaled = image.scaled(tile_width, tile_height, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        painter.drawText(x, y + label_height - 6, label)
        painter.drawImage(x, y + label_height, scaled)
    painter.end()
    if not sheet.save(str(destination)):
        raise RuntimeError(f"could not save contact sheet {destination}")


def run_case(width, scale):
    cell = OUT / f"width-{width}-scale-{scale}"
    cell.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    theme.init_fonts()
    app.setFont(theme.font(theme.TYPE["body"]))
    font = app.font()
    if not font.family().lower().startswith("hanken"):
        raise RuntimeError(f"real application font not active: {font.family()!r}")

    import tempfile
    from core.tests import responder_harness

    scratch = OUT / "test-working"
    scratch.mkdir(parents=True, exist_ok=True)
    synthetic_dir = tempfile.TemporaryDirectory(prefix="beamer-layout-render-", dir=scratch)
    config_dir = Path(synthetic_dir.name)
    window = SyntheticWindow(write_synthetic_settings(config_dir))
    window.full_screen_timer.stop()
    window.refresh_timer.stop()
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    window.resize(width, HEIGHT)
    window.show()
    settle(app)
    actual_dpr = window.devicePixelRatioF()
    if abs(actual_dpr - float(scale)) > 0.01:
        window.server.stop()
        window.close()
        synthetic_dir.cleanup()
        raise RuntimeError(f"requested Qt scale {scale}, window reports DPR {actual_dpr}")
    all_measures, sheet_images = [], []
    try:
        for key, _name, _purpose in pages_win.PAGES:
            window._select_page(key)
            settle(app)
            scroll = window.stack.currentWidget()
            page = scroll.widget()
            page_images = []
            for position in ("top", "middle", "bottom"):
                bar = scroll.verticalScrollBar()
                if position == "top":
                    bar.setValue(bar.minimum())
                elif position == "middle":
                    bar.setValue((bar.minimum() + bar.maximum()) // 2)
                else:
                    bar.setValue(bar.maximum())
                settle(app)
                path = cell / f"{key}-{position}.png"
                image = window.grab().toImage()
                if image.isNull() or not image.save(str(path)):
                    raise RuntimeError(f"QWidget.grab() failed for {path}")
                page_images.append((position, path))
                sheet_images.append((f"{key} {position}", path))
            full_path = cell / f"{key}-full-document.png"
            full_image = capture_document(page)
            if full_image.isNull() or not full_image.save(str(full_path)):
                raise RuntimeError(f"full document grab failed for {full_path}")
            sheet_images.append((f"{key} full", full_path))
            all_measures.append(measurements(window, key, width, scale))
            print(f"rendered {key}: window={window.width()}x{window.height()} DIP, "
                  f"dpr={window.devicePixelRatioF()}, font={font.family()}", flush=True)
        (cell / "measurements.json").write_text(json.dumps(all_measures, indent=2) + "\n")
        make_contact_sheet(sheet_images, cell / "contact-sheet.png",
                           f"Qt settings · {width} DIP · {scale}x · Hanken Grotesk")
    finally:
        window.server.stop()
        window.close()
        window.deleteLater()
        app.processEvents()
        synthetic_dir.cleanup()


def run_matrix():
    cells = [(width, scale) for width in WIDTHS for scale in SCALES]

    def render_cell(cell):
        width, scale = cell
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_SCALE_FACTOR"] = scale
        env["BEAMER_LAYOUT_WIDTH"] = str(width)
        log_path = OUT / f"width-{width}-scale-{scale}.log"
        OUT.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--case", str(width), scale],
                env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True,
            )
        return cell, result.returncode, log_path

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(render_cell, cells))
    failures = [item for item in results if item[1]]
    print(f"render matrix: cells={len(results)} passed={len(results) - len(failures)} "
          f"failed={len(failures)} contact-sheets={len(results)} path={OUT}")
    if failures:
        print("failed cells: " + ", ".join(
            f"{cell[0]}@{cell[1]}x" for cell, _status, _log in failures), file=sys.stderr)
        raise SystemExit(1)


def run_crossing_state(state, destination):
    """Build the seven review states from valid saved settings in a fresh Qt process."""
    import tempfile
    import app_config
    from core import crossing_state, protocol
    from core.tests import responder_harness as harness

    if state not in range(1, 8):
        raise ValueError("crossing state must be 1..7")
    app = QApplication.instance() or QApplication([])
    theme.init_fonts()
    app.setFont(theme.font(theme.TYPE["body"]))
    scratch = ROOT / "win_app" / ".test-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"ledger-state-{state}-", dir=scratch) as working:
        own = protocol.id_text(harness.HERE)
        first, second, third = (protocol.id_text(peer) for peer in (harness.B, harness.C, harness.D))
        peer_ids = [second] if state in (2, 3) else [first, second, third] if state == 6 else [first]
        all_peers = {first: harness.entry(harness.B, "MacBook Pro", platform="macos"),
                     second: harness.entry(harness.C, "Fedora laptop", platform="linux"),
                     third: harness.entry(harness.D, "Studio PC", platform="windows", shortcut_cycle=False)}
        settings = app_config.migrate(None, machine_id=own)
        settings.update(appearance="dark", name="Desktop PC", check_updates=False,
                        port=harness.free_port(), shortcut_goes_to="ticked",
                        peers=[all_peers[peer] for peer in peer_ids])
        settings["layout"] = {own: {"x": 0, "y": 0, "w": 160, "h": 100}}
        positions = {first: (0, -100), second: (-160, 0), third: (160, 0)}
        for peer in peer_ids:
            x, y = positions[peer]
            settings["layout"][peer] = {"x": x, "y": y, "w": 160, "h": 100}
        for peer in peer_ids:
            thirds = ["start", "end"] if state == 3 else ["middle"] if state == 6 and peer == second else list(("start", "middle", "end"))
            corner = "top_left" if state in (4, 7) else "bottom_left" if state == 6 and peer == second else ""
            settings = crossing_state.edit_ways(settings, peer, platform="pc", edge=state != 5,
                                                 thirds=thirds, corner=bool(corner),
                                                 corner_at=corner or None,
                                                 live=lambda _peer: True, gone=lambda _peer: False,
                                                 capable=peer_ids, now=1791619200)["settings"]
        if state == 6:
            next(entry for entry in settings["peers"] if entry["id"] == second)["jump_key"] = "alt+f18"
        path = Path(working) / "settings.json"
        app_config.write_settings(path, settings)
        window = SyntheticWindow(path)
        window.full_screen_timer.stop()
        window.refresh_timer.stop()
        window._live = lambda peer: state != 6 or peer != third
        window._design_peer_caps = lambda: {peer: {"layout"} for peer in peer_ids}
        window._chosen = peer_ids[0]
        window._reflect_ways()
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        width, height = (640, 600) if state == 7 else (960, 760)
        window.resize(width, height)
        window.show()
        window._select_page("crossing")
        settle(app)
        scroll = window.stack.currentWidget()
        chrome = window.height() - scroll.viewport().height()
        window.resize(width, scroll.widget().sizeHint().height() + chrome + 2)
        settle(app)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        raster = window.grab().toImage()
        if raster.isNull() or not raster.save(str(destination)):
            raise RuntimeError(f"could not save built Crossing state {destination}")
        record = {"state": state, "file": str(destination), "size": [raster.width(), raster.height()],
                  "ledger_narrow": window.crossing_ledger.narrow,
                  "map_height": window.atlas_canvas.height(),
                  "hint_gap": (window.atlas_canvas_hint.mapTo(window.ways_module, QPoint()).y()
                               - window.atlas_canvas.mapTo(window.ways_module, QPoint(0, window.atlas_canvas.height())).y()),
                  "horizontal_scroll": scroll.horizontalScrollBar().maximum(),
                  "rows": [{"name": row.name.full_text, "status": row.status.text(),
                             "edges": {side: chip.kind for side, chip in row.edge_chips.chips.items() if not chip.isHidden()},
                             "corners": [corner for corner, button in row.corner_grid.buttons.items() if button.isChecked()],
                             "jump": row.jump.value} for row in window.crossing_ledger.rows.values()]}
        (scratch / f"ledger-render-{state}.json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps(record))
        window.server.stop()
        window.close()
        window.deleteLater()
        settle(app)


def comparison_sheets(qt_root):
    mac_root = ROOT.parent / "laymac" / "renders"
    app = QApplication.instance() or QApplication([])
    theme.init_fonts()
    app.setFont(theme.font(theme.TYPE["body"]))
    for width in WIDTHS:
        images = []
        for key, name, _purpose in pages_win.PAGES:
            mac = mac_root / f"{key}-{width}-2x-top.png"
            qt = qt_root / f"width-{width}-scale-2.0" / f"{key}-top.png"
            if not mac.exists() or not qt.exists():
                raise RuntimeError(f"missing comparison render: {mac} or {qt}")
            images.extend(((f"Mac · {name}", mac), (f"Qt · {name}", qt)))
        make_contact_sheet(images, OUT / f"mac-against-qt-{width}-2x.png",
                           f"Mac / Qt · {width} logical units · 2x", columns=2,
                           tile_width=640, tile_height=600)
    print(f"comparison sheets: widths={len(WIDTHS)} pages={len(pages_win.PAGES)} path={OUT}")


def run_test_suite(selectors=()):
    app = QApplication.instance() or QApplication([])
    theme.init_fonts()
    app.setFont(theme.font(theme.TYPE["body"]))
    if not app.font().family().lower().startswith("hanken"):
        raise RuntimeError(f"suite did not start with Hanken Grotesk: {app.font().family()!r}")
    print(f"test suite application font={app.font().family()} point={app.font().pointSizeF()} "
          f"pixel={app.font().pixelSize()}", flush=True)
    if selectors:
        suite = unittest.TestSuite(
            unittest.defaultTestLoader.loadTestsFromName(selector) for selector in selectors
        )
    else:
        suite = unittest.defaultTestLoader.discover(str(TESTS), pattern="test*.py")
    class QtTestResult(unittest.TextTestResult):
        def stopTest(self, test):
            # processEvents alone retains deleteLater windows and their refresh timers.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            super().stopTest(test)

    result = unittest.TextTestRunner(verbosity=2, resultclass=QtTestResult).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--crossing-state":
        run_crossing_state(int(sys.argv[2]), sys.argv[3])
    elif len(sys.argv) == 2 and sys.argv[1] == "--matrix":
        run_matrix()
    elif len(sys.argv) == 3 and sys.argv[1] == "--compare":
        comparison_sheets(Path(sys.argv[2]))
    elif len(sys.argv) >= 2 and sys.argv[1] == "--test-suite":
        run_test_suite(sys.argv[2:])
    elif len(sys.argv) == 4 and sys.argv[1] == "--case":
        run_case(int(sys.argv[2]), sys.argv[3])
    else:
        print("usage: render_settings_layout.py --matrix | --case WIDTH SCALE", file=sys.stderr)
        raise SystemExit(2)
