"""The README's Windows screenshots: the real settings window, built offscreen from a synthetic
config (documentation addresses, no house detail) and grabbed page by page. Starts nothing: no
receiver, no hooks, no announcer.

APPEARANCE=light|dark (default dark) is the palette the window is built in. SWITCH_TO=light|dark,
set as well, has the window built in APPEARANCE and then live-switched with _apply_appearance
before anything is shot -- proving the live switch renders the same as building in the target
appearance directly, not just the initial build."""

import json
import getpass
import os
import platform
import socket
import sys
import tempfile
import time
from pathlib import Path

if len(sys.argv) != 3 or (sys.argv[1] != "--linux" and not Path(sys.argv[1]).is_dir()):
    raise SystemExit("Usage: readme_shots_win.py <repository-dir> <outdir> | --linux <outdir>")

LINUX = sys.argv[1] == "--linux"
if LINUX:
    REPO = Path(__file__).resolve().parents[1]
    OUT = Path(sys.argv[2])
    os.environ.setdefault("QT_SCALE_FACTOR", "2")
else:
    REPO = Path(sys.argv[1])
    OUT = Path(sys.argv[2])
sys.path.insert(0, str(REPO / "win_app"))

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget, QLabel, QAbstractButton, QLineEdit, QComboBox  # noqa: E402

import theme  # noqa: E402

app = QApplication(sys.argv[:1])
theme.init_fonts()
appearance = os.environ.get("APPEARANCE", "light" if LINUX else "dark").strip().lower()
app.setFont(theme.font(theme.TYPE["body"]))

import kvm_bridge_win  # noqa: E402
import app_config  # noqa: E402
from core.receiver import ServerState  # noqa: E402
from core import pairing, peerlist, protocol, crossing_state  # noqa: E402

kvm_bridge_win.VERSION = os.environ.get("SHOT_VERSION", kvm_bridge_win.VERSION)
# Drawn as the installed app is, not as a run from source, which cannot start at sign-in.
kvm_bridge_win.autostart_win.installed_exe = lambda: Path("Beamer.exe")
kvm_bridge_win.autostart_win.is_enabled = lambda: not LINUX
folder = Path(tempfile.mkdtemp())
four = os.environ.get("FOUR", "1" if LINUX else "0") == "1"
real_hostname = socket.gethostname() if four else ""
real_username = getpass.getuser() if four else ""
own_name = ("Linux box" if LINUX else "Desk PC") if four else ("Linux PC" if LINUX else "Desktop PC")
if four:
    # Over SSH there is no signed-in desktop session to name, which would draw the sign-in row as unavailable.
    kvm_bridge_win.autostart_win.can_run_for_current_user = lambda: True
# Always: the window falls back to the machine's own hostname wherever the config names none.
platform.node = lambda: own_name
socket.gethostname = lambda: own_name
pairing.machine_name = lambda: own_name
fixture = {
    "host": "192.168.1.20", "port": 24820, "auth_token": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", "paired_with": "MacBook Pro",
    "mac_host": "192.168.1.10", "mac_return_edge": "left", "glow_colour": "signal",
    "ignored_inputs": ["button:back", "button:forward", "key:175", "key:174"],
    "appearance": appearance,
}
if four:
    names = ("Desk PC", "Studio Mac", "Laptop", "Linux box")
    platforms = ("windows", "macos", "windows", "linux")
    hosts = ("192.0.2.10", "192.0.2.11", "192.0.2.12", "192.0.2.13")
    ids = [bytes([index + 31]) * 16 for index in range(4)]
    tokens = [pairing._b64(bytes([index + 41]) * 32) for index in range(4)]  # pairing's shape, or the app shows "Pair again"
    own_index = 3 if LINUX else 0
    fixture.update(name=names[own_index], paired_with="", peers=[])
    fixture["auth_token"] = ""
    fixture["host"] = ""
    settings = app_config.migrate(fixture, machine_id=protocol.id_text(ids[own_index]))
    settings["name"] = names[own_index]
    for index, name in enumerate(names):
        if index == own_index:
            continue
        entry = pairing.peer_entry(ids[index], name, platforms[index], fixture["port"], tokens[index],
                                   hosts[index], 1791321600 + index)
        entry["linked"] = True
        peerlist.add_peer(settings, entry)
    # This machine in the middle with one machine left, one right and one below, so every one
    # touches it and crosses: a machine that touches none reads "Drag to connect" in amber.
    others = [index for index in range(4) if index != own_index]
    spots = [(160, 0)] + [(0, 0), (320, 0), (160, 100)]
    settings["layout"] = {
        protocol.id_text(ids[index]): {"x": x, "y": y, "w": 160, "h": 100}
        for index, (x, y) in zip([own_index] + others, spots)
    }
    settings = crossing_state.migrate(settings, "pc")["settings"]
    config_path = folder / "settings.json"
    app_config.write_settings(config_path, settings)
elif LINUX:
    fixture["paired_with"] = ""
    token_32 = pairing._b64(bytes([42]) * 32)
    fixture["peers"] = [pairing.peer_entry(
        bytes([1]) * 16, "MacBook Pro", "macos", fixture["port"], token_32,
        fixture["mac_host"], 1791321600,
    )]
if four:
    pass
elif LINUX:
    settings = app_config.migrate(fixture)
    peerlist.add_peer(settings, fixture["peers"][0], settings["peers"][0])
    for p in settings["peers"]:
        p["from_1_4"] = False
        p["linked"] = True
    app_config.write_settings(folder / "settings.json", settings)
else:
    (folder / "config.json").write_text(json.dumps(fixture))
window = kvm_bridge_win.WindowsApplication(folder / "settings.json")
window._set_status(ServerState.CONNECTED, "Connected to 192.0.2.11" if four else "Connected to 192.168.1.10")
if LINUX or four:
    window.sender.links.up = lambda _peer: True
if four:
    class _UpLink:
        # The sidebar's "Response: 3 ms" reads the link's own measurement; with none it shows a dash.
        response_time_ms = 3
        peer_locked = via_tunnel = False
        status, kind, caps = "", "live", {"settings", "layout"}  # without "layout" a peer reads as pre-1.5.2

        def live(self):
            return True

    window.sender.links._link = lambda _peer: _UpLink()
if four or LINUX:
    window.sender.refresh()
    window._reflect_ways()
# This PC's own link to the Mac, as the Mac tool's CONNECTED fakes its socket: without it Overview
# says "not connected" under "Mac connected".
window.sender._sock = object()
if os.environ.get("SIZE"):
    window.resize(*(int(v) for v in os.environ["SIZE"].split("x")))
else:
    window.resize(1200, 675) if LINUX else window.resize(820, 700)
window.show()
# _set_status only takes effect on the next _refresh_window, whose status heading then cross-fades
# in: forced and settled here, before anything is timed, so that fade never lands mid-shot.
window._refresh_window()
started = time.monotonic()
while time.monotonic() - started < 0.25:
    app.processEvents()
    time.sleep(0.01)

switch_to = os.environ.get("SWITCH_TO", "").strip().lower()
if switch_to:
    started = time.monotonic()
    while time.monotonic() - started < 0.1:
        app.processEvents()
        time.sleep(0.01)
    window._apply_appearance(switch_to)
    # Past the 200ms cross-fade (motion.DURATION), so the switch has fully settled.
    started = time.monotonic()
    while time.monotonic() - started < 0.5:
        app.processEvents()
        time.sleep(0.01)

OUT.mkdir(parents=True, exist_ok=True)
# PAGES names pages, space-separated; the README's three by default.
pages = os.environ.get("PAGES", "overview crossing design" if LINUX else "overview design keyboard").split()
rendered_texts = []
def visible_widget_texts():
    texts = []
    for widget in window.findChildren(QWidget):
        if not widget.isVisibleTo(window):
            continue
        if isinstance(widget, QLabel) or isinstance(widget, QAbstractButton):
            texts.append(widget.text())
        if isinstance(widget, QLineEdit):
            texts.append(widget.text())
        if isinstance(widget, QComboBox):
            texts.extend([widget.currentText(), *(widget.itemText(i) for i in range(widget.count()))])
    return texts

for key in pages:
    settle = 0.3
    window._select_page(key)
    if key == "crossing":
        window._reflect_ways()
    window.stack.setFocus()
    started = time.monotonic()
    while time.monotonic() - started < settle:
        app.processEvents()
        time.sleep(0.01)
    window._refresh_window()
    app.processEvents()
    prefix = "linux" if LINUX else "windows"
    suffix = os.environ.get("SUFFIX", "")
    shot = window.grab()
    shot.save(str(OUT / f"{prefix}-{key}{suffix}.png"))
    if four and key == "crossing" and not LINUX:
        map_rect = QRect(window.atlas_canvas.mapTo(window, QPoint(0, 0)), window.atlas_canvas.size())
        ledger_rect = QRect(window.crossing_ledger.mapTo(window, QPoint(0, 0)), window.crossing_ledger.size())
        # Clipped to the page's scroll viewport: past it the ledger runs under the footer.
        scroller = window.atlas_canvas.parentWidget()
        while scroller is not None and not isinstance(scroller, QAbstractScrollArea):
            scroller = scroller.parentWidget()
        visible = window.rect() if scroller is None else QRect(
            scroller.viewport().mapTo(window, QPoint(0, 0)), scroller.viewport().size())
        crop = map_rect.united(ledger_rect).adjusted(-16, -8, 16, 8).intersected(visible)
        ratio = shot.devicePixelRatio()
        pixels = QRect(round(crop.x() * ratio), round(crop.y() * ratio),
                       round(crop.width() * ratio), round(crop.height() * ratio))
        shot.copy(pixels).save(str(OUT / f"{prefix}-crossing-map{suffix}.png"))
        # The map alone, for README widths where the ledger's small text cannot be read.
        crop = map_rect.adjusted(-16, -8, 16, 8).intersected(visible)
        shot.copy(QRect(round(crop.x() * ratio), round(crop.y() * ratio), round(crop.width() * ratio),
                        round(crop.height() * ratio))).save(str(OUT / f"{prefix}-crossing-mapview{suffix}.png"))
    if four:
        rendered_texts.extend(visible_widget_texts())

if four:
    banned = [real_hostname, real_hostname.split(".", 1)[0], real_username,
              "10.0.0.", "fedora",
              *filter(None, os.environ.get("BEAMER_SHOT_DENY", "").split(","))]
    rendered_texts.extend(("Desk PC", "Studio Mac", "Laptop", "Linux box"))
    found = [text for text in rendered_texts if text and
             any(term and term.casefold() in text.casefold() for term in banned)]
    if found:
        print("Forbidden visible text: " + "; ".join(found), file=sys.stderr)
        raise SystemExit(1)
print(OUT)
