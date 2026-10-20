"""Settings-load migration and its backup boundary for Crossing profiles."""

import copy
import importlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "win_app"))


class GuiImportBlocked(ImportError):
    pass


class BlockGuiImports:
    # Importing objc and AppKit registers nothing with the WindowServer, so the Mac legs run on a Mac;
    # BEAMER_TEST_NO_APPKIT=1 (a sandbox that refuses them) skips those legs instead.
    blocked = {"PySide2", "PySide6", "PyQt5", "PyQt6", "qtpy", "tkinter"} | (
        {"AppKit", "objc"} if os.environ.get("BEAMER_TEST_NO_APPKIT") == "1" else set())

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in self.blocked:
            raise GuiImportBlocked("blocked before import: " + fullname)


# Installed only around this module's own imports: left in place it would refuse GUI imports to
# every module the shared Windows suite (win_app/tests/test_core.py) imports after this one.
_BLOCKER = BlockGuiImports()
sys.meta_path.insert(0, _BLOCKER)
try:
    from core import profiles
    from core import crossing_state
    from core.tests.test_profiles import raw as profiles_raw
finally:
    sys.meta_path.remove(_BLOCKER)


def _profileless(settings):
    result = copy.deepcopy(settings)
    result.pop("crossing_own", None)
    result.pop("crossing_desk", None)
    return result


class MigrationBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    _mac_module = None

    def _mac_store_and_153_file(self):
        # Loaded once per process: an Objective-C class cannot be defined twice, so the Mac modules
        # are never purged and re-imported between tests.
        if MigrationBackupTests._mac_module is None:
            if sys.platform != "darwin":
                # Not even attempted: a failed import still leaves mac_app's config and crossing
                # modules in sys.modules for the rest of a shared suite.
                self.skipTest("Mac SettingsStore leg runs on macOS only")
            old_path = sys.path[:]
            sys.meta_path.insert(0, _BLOCKER)
            try:
                sys.path.insert(0, str(ROOT / "mac_app"))
                MigrationBackupTests._mac_module = importlib.import_module("settings_store")
            except ImportError as exc:
                # Off the Mac there is no PyObjC, and another module's blocker is an ImportError too;
                # the Windows and Linux legs still run.
                self.skipTest(f"Mac SettingsStore leg skipped: {exc}")
            finally:
                sys.meta_path.remove(_BLOCKER)
                sys.path[:] = old_path
        settings_store = MigrationBackupTests._mac_module
        store = settings_store.SettingsStore(self.folder / "settings.json")
        normalised = store.load_settings()
        raw = _profileless(normalised)
        original = json.dumps(raw, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        store.path.write_bytes(original)
        return store, original, settings_store

    def _windows_file(self):
        import app_config
        path = self.folder / "settings.json"
        settings = app_config.load_settings(path)
        raw = _profileless(settings)
        original = json.dumps(raw, indent=2).encode("utf-8") + b"\n"
        path.write_bytes(original)
        return app_config, path, original

    def _assert_backup_before_write(self, path, original, writer):
        backup = path.with_name("settings.json.before-1.5.5")
        self.assertEqual(path.read_bytes(), original, "load alone must leave a 1.5.3 file byte-for-byte intact")
        writer()
        self.assertEqual(backup.read_bytes(), original)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("crossing_own", loaded)
        backup.write_bytes(b"existing backup")
        writer()
        self.assertEqual(backup.read_bytes(), b"existing backup", "an existing backup is never overwritten")

    def test_windows_upgrade_backup_is_made_once_before_first_save(self):
        app_config, path, original = self._windows_file()
        settings = app_config.load_settings(path)
        self._assert_backup_before_write(path, original, lambda: app_config.write_settings(path, settings))

    def test_mac_upgrade_backup_is_made_once_before_first_save(self):
        store, original, _module = self._mac_store_and_153_file()
        settings = store.load_settings()
        self._assert_backup_before_write(store.path, original, lambda: store.save_settings(settings))

    def test_windows_backup_failure_leaves_original_settings_untouched(self):
        app_config, path, original = self._windows_file()
        settings = app_config.load_settings(path)
        with mock.patch.object(app_config.shutil, "copyfile", side_effect=OSError("backup denied")):
            with self.assertRaises(OSError):
                app_config.write_settings(path, settings)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(path.with_name("settings.json.before-1.5.5").exists())

    def test_windows_backup_source_read_failure_aborts_save(self):
        app_config, path, original = self._windows_file()
        settings = app_config.load_settings(path)
        real_read_bytes = Path.read_bytes

        def fail_source(this):
            if this == path:
                raise OSError("source read denied")
            return real_read_bytes(this)

        with mock.patch.object(Path, "read_bytes", fail_source):
            with self.assertRaises(OSError):
                app_config.write_settings(path, settings)
        with path.open("rb") as handle:
            self.assertEqual(handle.read(), original)
        self.assertFalse(path.with_name("settings.json.before-1.5.5").exists())

    def test_mac_backup_failure_leaves_original_settings_untouched(self):
        store, original, store_module = self._mac_store_and_153_file()
        settings = store.load_settings()
        with mock.patch.object(store_module, "shutil", create=True):
            store_module.shutil.copyfile.side_effect = OSError("backup denied")
            with self.assertRaises(Exception):
                store.save_settings(settings)
        self.assertEqual(store.path.read_bytes(), original)
        self.assertFalse(store.path.with_name("settings.json.before-1.5.5").exists())

    def test_mac_backup_source_read_failure_aborts_save(self):
        store, original, _module = self._mac_store_and_153_file()
        settings = store.load_settings()
        real_read_bytes = Path.read_bytes

        def fail_source(this):
            if this == store.path:
                raise OSError("source read denied")
            return real_read_bytes(this)

        with mock.patch.object(Path, "read_bytes", fail_source):
            with self.assertRaises(OSError):
                store.save_settings(settings)
        with store.path.open("rb") as handle:
            self.assertEqual(handle.read(), original)
        self.assertFalse(store.path.with_name("settings.json.before-1.5.5").exists())

    def test_windows_row_and_archive_write_fail_together(self):
        app_config, path, original = self._windows_file()
        settings = app_config.load_settings(path)
        settings["crossing_own"]["row"]["synthetic"] = {"ways": {"edge": False}, "notch_return": False}
        settings["crossing_own"]["saved"].append(
            {"id": "synthetic", "why": "edited", "at": 100, "row": {"synthetic": {"ways": {}, "notch_return": False}}}
        )
        with mock.patch.object(app_config.os, "replace", side_effect=OSError("atomic replace denied")):
            with self.assertRaises(OSError):
                app_config.write_settings(path, settings)
        self.assertEqual(path.read_bytes(), original)

    def test_mac_row_and_archive_write_fail_together(self):
        store, original, store_module = self._mac_store_and_153_file()
        settings = store.load_settings()
        settings["crossing_own"]["row"]["synthetic"] = {"ways": {"edge": False}, "notch_return": False}
        settings["crossing_own"]["saved"].append(
            {"id": "synthetic", "why": "edited", "at": 100, "row": {"synthetic": {"ways": {}, "notch_return": False}}}
        )
        with mock.patch.object(store_module.os, "replace", side_effect=OSError("atomic replace denied")):
            with self.assertRaises(Exception):
                store.save_settings(settings)
        self.assertEqual(store.path.read_bytes(), original)


class MigrationCoreTests(unittest.TestCase):
    def test_upgrade_archives_raw_crossing_choices_before_normalisation(self):
        peer = "AQEBAQEBAQEBAQEBAQEBAQ"
        raw = {
            "schema": 6,
            "machine_id": "AgICAgICAgICAgICAgICAg",
            "peers": [{"id": peer, "send": True, "ways": {"edge": True, "thirds": ["start", "end"]},
                       "notch_return": True}],
        }
        settings, notes = profiles.before_load(raw, now=100)
        self.assertIn("upgraded", notes)
        self.assertEqual(settings["crossing_own"]["saved"][0]["why"], "upgrade")
        self.assertEqual(settings["crossing_own"]["saved"][0]["row"], settings["crossing_own"]["row"])
        self.assertTrue(settings.get("_crossing_profiles_upgrade_pending"))


class DowngradeCompatibilityTests(unittest.TestCase):
    def _frozen_153(self, folder):
        archive = subprocess.run(
            ["git", "archive", "be9661d1", "core", "win_app", "mac_app"],
            cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout
        frozen = folder / "frozen"
        frozen.mkdir()
        with tarfile.open(fileobj=__import__("io").BytesIO(archive)) as bundle:
            bundle.extractall(frozen, filter="data")
        return frozen

    @staticmethod
    def _gui_blocker():
        return r'''\
import sys
class GuiImportBlocked(RuntimeError):
    pass
class BlockGuiImports:
    blocked = {"PySide2", "PySide6", "PyQt5", "PyQt6", "qtpy", "tkinter"} | (
        {"AppKit", "objc"} if __import__("os").environ.get("BEAMER_TEST_NO_APPKIT") == "1" else set())
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in self.blocked:
            raise GuiImportBlocked("blocked before import: " + fullname)
sys.meta_path.insert(0, BlockGuiImports())
'''

    def test_153_code_keeps_new_top_level_settings_and_peer_fields(self):
        """Run the frozen 1.5.3 readers from their own tree in a child interpreter."""
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            work = Path(temp)
            frozen = self._frozen_153(work)
            script = r'''\
''' + self._gui_blocker() + r'''
import copy, json, os, pathlib, sys, tempfile
root = pathlib.Path(sys.argv[1])
work = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(root / "win_app"))
sys.path.insert(0, str(root))
from core import crossing_state
mid = lambda n: __import__("base64").urlsafe_b64encode(bytes([n])*16).decode().rstrip("=")
me, peer = mid(1), mid(2)
s = {"schema":6,"machine_id":me,"name":"","port":24820,"shortcut":True,"migrated_token_sha256":"",
     "peers":[{"id":peer,"name":"PC","platform":"windows","token":"t"*43,"host":"192.0.2.5","port":24820,
       "hw":"","send":True,"allow_drive":True,"in_use":True,"side":"right","side_set_at":1,"side_by":me,
       "paired_with":[],"paired_at":1,"linked":True,"from_1_4":False,
       "ways":{"edge":True,"thirds":["start","middle","end"],"edges":[],"corner":True,"corner_at":"top_left",
         "corners":[],"notch":False},"crossing_future_peer_field":{"keep":True}}],
     "zones":[],"layout":{me:{"x":0,"y":0,"w":100,"h":100},peer:{"x":100,"y":0,"w":100,"h":100}},
     "layout_set_at":0,"layout_by":"","crossing_own":{"sentinel":1},"crossing_desk":{"sentinel":2}}
core = crossing_state.migrate(copy.deepcopy(s), "pc")["settings"]
assert core["crossing_own"] == {"sentinel":1} and core["crossing_desk"] == {"sentinel":2}
assert core["peers"][0]["crossing_future_peer_field"] == {"keep":True}
from app_config import load_settings, write_settings
folder = pathlib.Path(tempfile.mkdtemp(dir=work)); path = folder / "settings.json"
path.write_text(json.dumps(core)); loaded = load_settings(path); write_settings(path, loaded)
win = json.loads(path.read_text())
assert win["crossing_own"] == {"sentinel":1} and win["crossing_desk"] == {"sentinel":2}
assert win["peers"][0]["crossing_future_peer_field"] == {"keep":True}
sys.path.insert(0, str(root / "mac_app"))
try:
    from settings_store import SettingsStore
except (GuiImportBlocked, ImportError) as exc:
    print("frozen Mac load/save skipped: " + str(exc))
else:
    path = folder / "mac-settings.json"; path.write_text(json.dumps(core))
    store = SettingsStore(path); loaded = store.load_settings(); store.save_settings(loaded)
    mac = json.loads(path.read_text())
    assert mac["crossing_own"] == {"sentinel":1} and mac["crossing_desk"] == {"sentinel":2}
    assert mac["peers"][0]["crossing_future_peer_field"] == {"keep":True}
    print("core, Windows and Mac 1.5.3 loads/saves kept profile objects and peer fields")
'''
            result = subprocess.run(
                [sys.executable, "-c", script, str(frozen), str(work)], cwd=ROOT,
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if "Mac load/save skipped" in result.stdout:
                self.assertTrue("blocked before import: objc" in result.stdout or sys.platform != "darwin",
                                    result.stdout)
            else:
                self.assertIn("kept profile objects", result.stdout)

    def test_153_round_trips_keep_or_fold_live_crossing_edits(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            work = Path(temp)
            frozen = self._frozen_153(work)
            initial, _ = profiles.before_load(profiles_raw(), now=100)
            initial = crossing_state.migrate(initial, "mac")["settings"]
            initial, _ = profiles.after_load(initial, platform="mac", now=100)
            initial = crossing_state.set_same_ways(initial, True, platform="mac", now=101)["settings"]
            peer = initial["peers"][0]["id"]
            self.assertEqual(profiles.in_force(initial)[0], initial["crossing_desk"]["profiles"][
                initial["crossing_desk"]["active"]["value"]]["rows"][initial["machine_id"]]["value"])

            script = r'''\
''' + self._gui_blocker() + r'''
import copy, json, pathlib, sys
root, path, mode, peer = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, str(root / "win_app")); sys.path.insert(0, str(root))
from core import crossing_state
settings = json.loads(path.read_text(encoding="utf-8"))
if mode == "normalise":
    settings["peers"][0]["ways"]["future_in_ways"] = {"ignored": True}
settings = crossing_state.migrate(settings, "pc")["settings"]
if mode == "edit":
    settings = crossing_state.edit_ways(settings, peer, platform="pc", edge=True,
        live=lambda _p: True, gone=lambda _p: False, now=102)["settings"]
path.write_text(json.dumps(settings), encoding="utf-8")
from app_config import load_settings, write_settings
settings = load_settings(path); write_settings(path, settings)
sys.path.insert(0, str(root / "mac_app"))
try:
    from settings_store import SettingsStore
except (GuiImportBlocked, ImportError) as exc:
    print("frozen Mac 1.5.3 load/save skipped: " + str(exc))
else:
    store = SettingsStore(path); settings = store.load_settings(); store.save_settings(settings)
    print("frozen Mac 1.5.3 load/save complete")
print("frozen 1.5.3 core and Windows round trip complete")
'''
            for mode in ("unchanged", "normalise", "edit"):
                with self.subTest(mode=mode):
                    path = work / f"{mode}.json"
                    path.write_text(json.dumps(initial), encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, "-c", script, str(frozen), str(path), mode, peer],
                        cwd=ROOT, text=True, capture_output=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("round trip complete", result.stdout)
                    if "Mac 1.5.3 load/save skipped" in result.stdout:
                        self.assertTrue("blocked before import: objc" in result.stdout or sys.platform != "darwin",
                                    result.stdout)
                    old_roundtrip = json.loads(path.read_text(encoding="utf-8"))
                    if mode == "normalise":
                        self.assertNotIn("future_in_ways", old_roundtrip["peers"][0]["ways"])
                    migrated, notes = profiles.before_load(old_roundtrip, now=103)
                    migrated, _ = profiles.after_load(migrated, platform="mac", now=103)
                    self.assertEqual(migrated["crossing_own"]["applied"], profiles.live_row(migrated))
                    if mode == "edit":
                        self.assertIn("older_version", notes)
                        self.assertTrue(migrated["crossing_own"]["use_own"])
                        self.assertEqual(migrated["crossing_own"]["saved"][-1]["why"], "older_version")
                        self.assertTrue(migrated["crossing_own"]["row"][peer]["ways"]["edge"])
                    else:
                        self.assertNotIn("older_version", notes)
                        self.assertFalse(migrated["crossing_own"]["use_own"])
                        self.assertEqual(migrated["crossing_own"]["row"], initial["crossing_own"]["row"])

    def test_malformed_profile_state_is_preserved_under_unreadable_keys(self):
        raw = {"schema": 6, "machine_id": "AgICAgICAgICAgICAgICAg", "peers": [],
               "crossing_own": [], "crossing_desk": "bad"}
        settings, notes = profiles.before_load(raw, now=100)
        self.assertIn("crossing_own_unreadable", settings)
        self.assertIn("crossing_desk_unreadable", settings)
        self.assertIn("upgraded", notes)


if __name__ == "__main__":
    unittest.main()
