"""Pure tile resizing, layout compilation, profile storage and old-peer compatibility."""

import copy
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


class GuiImportBlocked(ImportError):
    pass


class BlockGuiImports:
    blocked = {"AppKit", "objc", "PySide2", "PySide6", "PyQt5", "PyQt6", "qtpy", "tkinter"}

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in self.blocked:
            raise GuiImportBlocked("blocked before import: " + fullname)


# Only while core loads: left in place it would refuse GUI imports to every module the shared
# Windows suite (win_app/tests/test_core.py) imports after this one.
_BLOCKER = BlockGuiImports()
sys.meta_path.insert(0, _BLOCKER)
try:
    from core import crossing_state, profiles, protocol, ways
finally:
    sys.meta_path.remove(_BLOCKER)

ROOT = Path(__file__).resolve().parents[2]
OWN, A, B = [protocol.id_text(bytes([number]) * 16) for number in (31, 32, 33)]


def picture_settings():
    return {
        "machine_id": OWN,
        "peers": [{"id": A, "port": 24820, "side": "right"}],
        "zones": [],
        "layout": {
            OWN: {"x": 0, "y": 0, "w": 160, "h": 100},
            A: {"x": 160, "y": 0, "w": 160, "h": 100},
        },
        "layout_set_at": 1,
        "layout_by": OWN,
    }


class TileResizeTests(unittest.TestCase):
    def test_resize_keeps_aspect_position_and_scaled_offsets(self):
        source = {"x": 12, "y": -7, "w": 160, "h": 100,
                  "displays": {"1": {"x": 1920, "y": 0, "w": 1920, "h": 1080}},
                  "display_offsets": {"1": {"x": 12, "y": -8}}}

        result = ways.resize_tile(source, 240)

        self.assertEqual((result["x"], result["y"], result["w"], result["h"]),
                         (12, -7, 240, 150))
        self.assertEqual(result["display_offsets"], {"1": {"x": 18, "y": -12}})
        self.assertEqual(result["displays"], source["displays"])
        self.assertEqual(source["w"], 160)

    def test_resize_clamps_long_side_and_rounds_dimensions_to_positive_integers(self):
        source = {"x": 0, "y": 0, "w": 3, "h": 2}

        small = ways.resize_tile(source, 1)
        large = ways.resize_tile(source, 1000)

        self.assertEqual((small["w"], small["h"]), (40, 27))
        self.assertEqual((large["w"], large["h"]), (480, 320))
        self.assertTrue(all(type(value) is int and value >= 1
                            for result in (small, large) for value in (result["w"], result["h"])))

    def test_resize_from_drag_uses_the_larger_proportional_axis_change(self):
        source = {"x": 10, "y": 20, "w": 160, "h": 100}

        result = ways.resize_from_drag(source, 32, 10)

        self.assertEqual((result["x"], result["y"], result["w"], result["h"]),
                         (10, 20, 192, 120))

    def test_drop_accepts_stamps_and_compiles_resized_tile(self):
        held = picture_settings()
        tiles = copy.deepcopy(held["layout"])
        tiles[A] = {**tiles[A], "w": 240, "h": 150}

        outcome = crossing_state.drop(held, tiles, A, platform="pc", capable={OWN, A},
                                      live=lambda _peer: True, gone=lambda _peer: False,
                                      now=100, snap_radius=0)

        self.assertTrue(outcome["accepted"])
        self.assertEqual((outcome["settings"]["layout"][A]["w"],
                          outcome["settings"]["layout"][A]["h"]), (240, 150))
        self.assertGreater(outcome["settings"]["layout_set_at"], held["layout_set_at"])
        edge = next(zone for zone in outcome["settings"]["zones"]
                    if zone["peer"] == A and zone["kind"] == "edge")
        self.assertEqual(edge["side"], "right")
        self.assertEqual(edge["contact_span"], [0.0, 1.0])
        self.assertEqual(edge["target_span"], [0.0, 2 / 3])

    def test_taller_resized_peer_maps_contact_to_its_lower_half(self):
        held = picture_settings()
        held["layout"][A] = ways.resize_tile(held["layout"][A], 320)
        held["layout"][A].update(y=-100)

        compiled = ways.compile_layout(held, held["layout"], platform="pc", capable={OWN, A}, now=100)

        edge = next(zone for zone in compiled["settings"]["zones"]
                    if zone["peer"] == A and zone["kind"] == "edge")
        self.assertEqual(edge["side"], "right")
        self.assertEqual(edge["contact_span"], [0.0, 1.0])
        self.assertEqual(edge["target_span"], [0.5, 1.0])

    def test_profile_switch_keeps_each_profile_tile_size(self):
        loaded, _notes = profiles.before_load({
            "schema": 6, "machine_id": OWN,
            "peers": [{"id": A, "port": 24820, "send": True, "allow_drive": True,
                       "linked": True, "side": "right", "ways": {"edge": True}}],
            "zones": [],
            "layout": {OWN: {"x": 0, "y": 0, "w": 160, "h": 100},
                       A: {"x": 160, "y": 0, "w": 160, "h": 100}},
        }, now=100)
        held, _notes = profiles.after_load(loaded, platform="pc", now=100)
        first = held["crossing_desk"]["active"]["value"]
        made = crossing_state.new_profile(held, "Second", platform="pc", now=101)
        second = next(pid for pid in made["settings"]["crossing_desk"]["profiles"] if pid != first)
        switched = crossing_state.switch_profile(made["settings"], second, platform="pc", now=102)
        resized = copy.deepcopy(switched["settings"])
        resized["layout"][A].update(w=240, h=150)

        back = crossing_state.switch_profile(resized, first, platform="pc", now=103)
        again = crossing_state.switch_profile(back["settings"], second, platform="pc", now=104)

        self.assertTrue(made["accepted"])
        self.assertTrue(switched["accepted"])
        self.assertEqual((back["settings"]["layout"][A]["w"], back["settings"]["layout"][A]["h"]),
                         (160, 100))
        self.assertEqual((again["settings"]["layout"][A]["w"], again["settings"]["layout"][A]["h"]),
                         (240, 150))


class OlderPeerResizeCompatibilityTests(unittest.TestCase):
    revisions = ("be9661d1", "2dbe44ab")

    def test_old_picture_readers_and_drops_preserve_resized_dimensions(self):
        script = r'''\
import base64, copy, sys
root = sys.argv[1]
sys.path.insert(0, root)
from core import crossing_state, settings_sync
mid = lambda n: base64.urlsafe_b64encode(bytes([n]) * 16).decode().rstrip("=")
own, resized, moved = mid(41), mid(42), mid(43)
layout = {
    own: {"x": 0, "y": 0, "w": 160, "h": 100},
    resized: {"x": 160, "y": 0, "w": 240, "h": 150},
    moved: {"x": -160, "y": 0, "w": 160, "h": 100},
}
wire = {"on": True, "set_at": 10, "by": own, "layout": {"set_at": 10, "by": own,
        "tiles": copy.deepcopy(layout)}}
read = settings_sync.read_layout_state(wire, now=100)
assert read and read["tiles"][resized]["w"] == 240
settings = {"machine_id": own, "peers": [
    {"id": resized, "port": 24820, "side": "right"},
    {"id": moved, "port": 24820, "side": "left"}],
    "zones": [], "layout": {own: layout[own], resized: layout[resized]},
    "layout_set_at": 1, "layout_by": own}
out = crossing_state.receive_picture(settings, read, source=resized, platform="pc",
    capable={own, resized, moved}, live=lambda _: True, gone=lambda _: False,
    own_displays={}, now=100)
assert out["settings"]["layout"][resized]["w"] == 240
tiles = copy.deepcopy(out["settings"]["layout"])
tiles[moved] = {**tiles[moved], "x": -160, "y": 0}
dropped = crossing_state.drop(out["settings"], tiles, moved, platform="pc",
    capable={own, resized, moved}, live=lambda _: True, gone=lambda _: False,
    now=101, snap_radius=0)
assert dropped["accepted"]
assert (dropped["settings"]["layout"][resized]["w"],
        dropped["settings"]["layout"][resized]["h"]) == (240, 150)
print("old reader, receive_picture and drop kept resized tile at 240x150")
'''
        for revision in self.revisions:
            with self.subTest(revision=revision), tempfile.TemporaryDirectory(dir=ROOT) as temp:
                archive = subprocess.run(
                    ["git", "archive", revision, "core"], cwd=ROOT, check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                ).stdout
                frozen = Path(temp) / "frozen"
                frozen.mkdir()
                with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
                    bundle.extractall(frozen, filter="data")
                result = subprocess.run([sys.executable, "-c", script, str(frozen)], cwd=ROOT,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("kept resized tile at 240x150", result.stdout)


if __name__ == "__main__":
    unittest.main()
