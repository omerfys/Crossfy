import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import global_shortcut_portal
import portal
from portal_fakes import FakeBus, wait_for


SESSION = "/org/freedesktop/portal/desktop/session/1_42/beamer2"
INTERFACE = global_shortcut_portal.INTERFACE


class GlobalShortcutPortalTest(unittest.TestCase):
    def start_shortcut(self, bus, callback=None, stopping=lambda: False):
        bus.answers.setdefault("CreateSession", (0, {"session_handle": SESSION}))
        bus.answers.setdefault("BindShortcuts", (0, {"shortcuts": [
            (global_shortcut_portal.SHORTCUT_ID, {"trigger_description": "Super+Shift+B"})
        ]}))
        shortcut = global_shortcut_portal.GlobalShortcut(lambda: bus, callback or (lambda: None), stopping)
        shortcut.start()
        return shortcut

    def test_binds_with_the_portal_signature_description_and_preferred_trigger(self):
        bus = FakeBus(versions={INTERFACE: 1})
        shortcut = self.start_shortcut(bus)
        self.addCleanup(shortcut.stop)
        wait_for(lambda: shortcut.trigger_description is not None, what="the bound trigger")

        call = next(item for item in bus.calls if item[1] == "BindShortcuts")
        self.assertEqual(call[0], INTERFACE)
        self.assertEqual(dict(bus.signatures)["BindShortcuts"], "oa(sa{sv})sa{sv}")
        self.assertEqual(call[2][0], SESSION)
        self.assertEqual(call[2][1][0][0], global_shortcut_portal.SHORTCUT_ID)
        self.assertEqual(call[2][1][0][1]["description"], ("s", "Send input to another machine"))
        self.assertEqual(call[2][1][0][1]["preferred_trigger"], ("s", global_shortcut_portal.PREFERRED_TRIGGER))
        self.assertEqual(bus.made("BindShortcuts")[0], (SESSION, [(global_shortcut_portal.SHORTCUT_ID, {
            "description": ("s", "Send input to another machine"),
            "preferred_trigger": ("s", global_shortcut_portal.PREFERRED_TRIGGER),
        })], "", {"handle_token": ("s", "beamer3")}))
        self.assertTrue(shortcut.available)
        self.assertEqual(shortcut.trigger_description, "Super+Shift+B")

    def test_activated_requires_our_session_and_shortcut_id(self):
        bus = FakeBus(versions={INTERFACE: 1})
        fired = []
        shortcut = self.start_shortcut(bus, lambda: fired.append(True))
        self.addCleanup(shortcut.stop)
        wait_for(lambda: shortcut.trigger_description is not None, what="the bound trigger")
        bus.emit(portal.OBJECT_PATH, INTERFACE, "Activated", (SESSION, "other", 1, {}))
        bus.emit(portal.OBJECT_PATH, INTERFACE, "Activated", (SESSION + "-other", global_shortcut_portal.SHORTCUT_ID, 1, {}))
        time.sleep(0.03)
        self.assertEqual(fired, [])

        bus.emit(portal.OBJECT_PATH, INTERFACE, "Activated", (SESSION, global_shortcut_portal.SHORTCUT_ID, 1, {}))
        wait_for(lambda: len(fired) == 1, what="the activation callback")

    def test_shortcuts_changed_updates_the_trigger_description(self):
        bus = FakeBus(versions={INTERFACE: 1})
        shortcut = self.start_shortcut(bus)
        self.addCleanup(shortcut.stop)
        wait_for(lambda: shortcut.trigger_description is not None, what="the bound trigger")
        bus.emit(portal.OBJECT_PATH, INTERFACE, "ShortcutsChanged", (SESSION, [
            (global_shortcut_portal.SHORTCUT_ID, {"trigger_description": "Ctrl+Alt+K"})
        ]))
        wait_for(lambda: shortcut.trigger_description == "Ctrl+Alt+K", what="the changed trigger")

    def test_missing_interface_is_unavailable_without_creating_a_session(self):
        bus = FakeBus(versions={INTERFACE: 0})
        shortcut = self.start_shortcut(bus)
        shortcut._thread.join(timeout=1)

        self.assertFalse(shortcut.available)
        self.assertEqual(bus.made("CreateSession"), [])
        shortcut.stop()

    def test_refused_binding_sets_refused_without_escaping(self):
        bus = FakeBus(versions={INTERFACE: 1})
        bus.answers["BindShortcuts"] = (1, {})
        shortcut = self.start_shortcut(bus)
        shortcut._thread.join(timeout=1)

        self.assertTrue(shortcut.available)
        self.assertTrue(shortcut.refused)
        self.assertIsNone(shortcut.trigger_description)
        shortcut.stop()

    def test_callback_exception_does_not_end_the_signal_loop(self):
        bus = FakeBus(versions={INTERFACE: 1})
        fired = []

        def callback():
            fired.append(True)
            if len(fired) == 1:
                raise RuntimeError("callback failure")

        shortcut = self.start_shortcut(bus, callback)
        self.addCleanup(shortcut.stop)
        wait_for(lambda: shortcut.trigger_description is not None, what="the bound trigger")
        with self.assertLogs(global_shortcut_portal.LOGGER, level="ERROR"):
            bus.emit(portal.OBJECT_PATH, INTERFACE, "Activated", (SESSION, global_shortcut_portal.SHORTCUT_ID, 1, {}))
            wait_for(lambda: len(fired) == 1, what="the first callback")
        bus.emit(portal.OBJECT_PATH, INTERFACE, "Activated", (SESSION, global_shortcut_portal.SHORTCUT_ID, 2, {}))
        wait_for(lambda: len(fired) == 2, what="the second callback")

    def test_stop_closes_session_and_bus_and_ends_the_thread(self):
        bus = FakeBus(versions={INTERFACE: 1})
        shortcut = self.start_shortcut(bus)
        wait_for(lambda: shortcut.trigger_description is not None, what="the bound trigger")
        thread = shortcut._thread

        shortcut.stop()

        self.assertTrue(bus.closed)
        self.assertIn((portal.SESSION, "Close", ()), [(iface, method, body) for iface, method, body in bus.calls])
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
