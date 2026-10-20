"""The README's Mac screenshots and a layout check: the real settings window, built from a synthetic
config (documentation addresses, no house detail) and drawn page by page into a bitmap without
ever being put on screen. Starts nothing: no event tap, no link, no discovery."""

import json
import getpass
import logging
import os
import platform
import socket
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
PAGES = sys.argv[3:] or ["overview", "design", "keyboard"]
sys.path.insert(0, str(REPO / "mac_app"))

import AppKit  # noqa: E402
from Foundation import NSDate, NSRunLoop  # noqa: E402

AppKit.NSApplication.sharedApplication()

import kvm_bridge_app  # noqa: E402
import settings_store  # noqa: E402
from wake import WakingController as KVMController  # noqa: E402
from core import pairing, protocol, crossing_state  # noqa: E402

kvm_bridge_app.VERSION = os.environ.get("SHOT_VERSION", kvm_bridge_app.VERSION)
kvm_bridge_app.accessibility_granted = lambda: True
kvm_bridge_app.input_monitoring_granted = lambda: True

four = os.environ.get("FOUR") == "1"
real_hostname = socket.gethostname() if four else ""
real_username = getpass.getuser() if four else ""
# Always: the window falls back to the machine's own hostname wherever the config names none.
socket.gethostname = lambda: "Studio Mac"
platform.node = lambda: "Studio Mac"
getpass.getuser = lambda: "Studio Mac"
pairing.machine_name = lambda: "Studio Mac"

path = Path(tempfile.mkdtemp()) / "config.json"
raw = settings_store.config_to_raw(settings_store.editable_default_config())
raw.update(host="" if four else "192.168.1.20", auth_token="" if four else "synthetic", pc_name="" if four else "Desktop PC",
           ignored_inputs=["button:back", "button:forward", "media:volume_up", "key:105"],
           appearance=os.environ.get("APPEARANCE", "dark"))
path.write_text(json.dumps(raw))
store = settings_store.SettingsStore(path)
if four:
    names = ("Desk PC", "Studio Mac", "Laptop", "Linux box")
    platforms = ("windows", "macos", "windows", "linux")
    hosts = ("192.0.2.10", "192.0.2.11", "192.0.2.12", "192.0.2.13")
    ids = [bytes([index + 31]) * 16 for index in range(4)]
    tokens = [pairing._b64(bytes([index + 41]) * 32) for index in range(4)]  # pairing's shape, or the app shows "Pair again"
    own_index = 1
    current = store.load_settings()
    current["machine_id"] = protocol.id_text(ids[own_index])
    current["name"] = names[own_index]
    store.save_settings(current)
    for index, name in enumerate(names):
        if index == own_index:
            continue
        entry = pairing.peer_entry(ids[index], name, platforms[index], protocol.DEFAULT_PORT,
                                   tokens[index], hosts[index], 1791321600 + index)
        entry["linked"] = True
        store.add_peer(entry)
    current = store.current()
    current["name"] = names[own_index]
    # This machine in the middle with one machine left, one right and one below, so every one
    # touches it and crosses: a machine that touches none reads "Drag to connect" in amber.
    # Laptop left, Desk PC right, Linux box below: the mirror of the Windows shot, where the
    # Studio Mac sits left of Desk PC, so the two read as one setup side by side.
    others = [2, 0, 3]
    spots = [(160, 0)] + [(0, 0), (320, 0), (160, 100)]
    current["layout"] = {
        protocol.id_text(ids[index]): {"x": x, "y": y, "w": 160, "h": 100}
        for index, (x, y) in zip([own_index] + others, spots)
    }
    current = crossing_state.migrate(current, "mac")["settings"]
    store.save_settings(current)
logger = logging.getLogger("shots")
if four:
    # The app's own wiring: without the store's book the controller holds only the config's
    # migrated 1.4 peer, and Overview lists that one machine as "Pair again".
    import bridge  # noqa: E402
    book, identity = bridge.links_from_store(store, kvm_bridge_app.VERSION)
    controller = KVMController(store.load(), logger=logger, book=book, identity=identity)
else:
    controller = KVMController(store.load(), logger=logger)
if os.environ.get("CONNECTED"):
    controller.sock = object()
    controller.connected_at = controller.last_ack_at = time.monotonic()
    controller.tap_ready.set()
    controller.event_tap = object()
window = kvm_bridge_app.ControlWindow.alloc().initWithController_settingsStore_logger_(controller, store, logger)
if four:
    window._live = lambda _peer: True

    class _UpLink:
        # The sidebar reads `connected` from the link in question, not the CONNECTED socket stub.
        peer_locked = via_tunnel = False
        status, kind, caps = "", "live", {"settings", "layout"}  # without "layout" a peer reads as pre-1.5.2
        response_time_ms = 3

        def __init__(self, peer_id=protocol.id_text(ids[0])):
            self.peer_id = peer_id

        def live(self):
            return True

    controller._status_link = lambda *_args: _UpLink()
    controller._link_of = lambda peer, *_args: _UpLink(peer)
    # Each Overview row and map tile asks its own peer's link.
    for entry in store.current()["peers"]:
        controller.links[entry["token"]] = controller._peers_up[entry["id"]] = _UpLink(entry["id"])
window.has_notch = True
controller.notch_range = (656.0, 856.0)
width, height = (int(v) for v in os.environ.get("SIZE", "900x640").split("x"))
# SWITCH_TO builds the window in APPEARANCE and switches it live, the way a choice or the Mac
# switching does, so a shot proves the repaint rather than a fresh build.
if os.environ.get("SWITCH_TO"):
    window._apply_appearance(os.environ["SWITCH_TO"])
window.window.setContentSize_((width, height))
OUT.mkdir(parents=True, exist_ok=True)
rendered_texts = []
def visible_window_texts():
    texts = []
    def inspect(view):
        if isinstance(view, AppKit.NSTextField):
            value = view.stringValue()
            if value:
                texts.append(value)
            if isinstance(view, AppKit.NSComboBox):
                texts.extend(view.itemObjectValueAtIndex_(i) for i in range(view.numberOfItems()))
        if isinstance(view, AppKit.NSButton):
            value = view.title()
            if value:
                texts.append(value)
            if isinstance(view, AppKit.NSPopUpButton):
                texts.extend(item.title() for item in view.itemArray())
        for child in view.subviews():
            if not child.isHidden():
                inspect(child)
    inspect(window.window.contentView())
    return texts

for key in PAGES:
    window._select_page(key)
    window.refresh()
    if key == "design" and window.previews is not None:
        loop = window.previews
        loop.started_at = time.monotonic() - float(os.environ.get("PREVIEW_AT", "1.6"))
        loop._tick()
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.3))
    view = window.window.contentView().superview() or window.window.contentView()
    view.layoutSubtreeIfNeeded()
    rep = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
    view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), rep)
    data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    suffix = os.environ.get("SUFFIX", "")
    data.writeToFile_atomically_(str(OUT / f"mac-{key}{suffix}.png"), True)
    if four and key == "crossing":
        map_rect = window.atlas_canvas.convertRect_toView_(window.atlas_canvas.bounds(), view)
        ledger_rect = window.crossing_ledger.convertRect_toView_(window.crossing_ledger.bounds(), view)
        union = AppKit.NSUnionRect(map_rect, ledger_rect)
        # 8 points up and down: 16 slices the Machines heading above and the note below.
        crop = AppKit.NSIntersectionRect(AppKit.NSInsetRect(union, -16.0, -8.0), view.bounds())
        crop_rep = view.bitmapImageRepForCachingDisplayInRect_(crop)
        view.cacheDisplayInRect_toBitmapImageRep_(crop, crop_rep)
        crop_data = crop_rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
        crop_data.writeToFile_atomically_(str(OUT / f"mac-crossing-map{suffix}.png"), True)
        # The map alone, for README widths where the ledger's small text cannot be read.
        crop = AppKit.NSIntersectionRect(AppKit.NSInsetRect(map_rect, -16.0, -8.0), view.bounds())
        crop_rep = view.bitmapImageRepForCachingDisplayInRect_(crop)
        view.cacheDisplayInRect_toBitmapImageRep_(crop, crop_rep)
        crop_data = crop_rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
        crop_data.writeToFile_atomically_(str(OUT / f"mac-crossing-mapview{suffix}.png"), True)
    if four:
        rendered_texts.extend(visible_window_texts())

if four:
    banned = [real_hostname, real_hostname.split(".", 1)[0], real_username,
              "10.0.0.", "fedora",
              *filter(None, os.environ.get("BEAMER_SHOT_DENY", "").split(","))]
    rendered_texts.extend(("Desk PC", "Studio Mac", "Laptop", "Linux box"))
    matches = [text for text in rendered_texts
               if any(term and term.casefold() in str(text).casefold() for term in banned)]
    if matches:
        print("Forbidden visible text: " + "; ".join(map(str, matches)), file=sys.stderr)
        raise SystemExit(1)
print(OUT)
