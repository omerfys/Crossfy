"""The portal client over a fake bus: a request waits for its own Response however the signals
interleave, a refusal and a failure are told apart, other signals are kept, a stop ends a wait
for the user, a restore token is kept for this user only, and a message goes out through the
Notification portal."""

import os
import stat
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portal
from portal_fakes import FakeBus, vardict


class PlainTest(unittest.TestCase):
    def test_variants_in_a_vardict_become_their_values_and_structs_stay(self):
        body = ("/session/1", {"cursor_position": ("(dd)", (10.0, 20.0)), "zones": ("a(uuii)", [(1920, 1080, 0, 0)])})
        self.assertEqual(portal.plain(body), ("/session/1", {"cursor_position": (10.0, 20.0), "zones": [(1920, 1080, 0, 0)]}))

    def test_a_struct_whose_first_member_is_a_short_string_is_not_taken_for_a_variant(self):
        self.assertEqual(portal.plain(("/path", "u")), ("/path", "u"))


class RequestTest(unittest.TestCase):
    def test_a_granted_request_returns_its_results(self):
        bus = FakeBus()
        bus.answers["CreateSession"] = (0, {"session_handle": "/session/1", "capabilities": 3})
        results = portal.Portal(bus).request("I", "CreateSession", "sa{sv}", lambda token: ("", {"handle_token": ("s", token)}))
        self.assertEqual(results, {"session_handle": "/session/1", "capabilities": 3})

    def test_a_request_unanswered_for_a_minute_is_logged_once_and_still_waited_for(self):
        bus = FakeBus()
        bus.answers["CreateSession"] = None
        with unittest.mock.patch.object(portal, "SLOW_ANSWER_SECONDS", 0.05), \
                self.assertLogs(portal.LOGGER, level="WARNING") as said, self.assertRaises(portal.PortalError):
            portal.Portal(bus).request("org.freedesktop.portal.InputCapture", "CreateSession", "sa{sv}",
                                       lambda token: ("", {"handle_token": ("s", token)}), timeout=0.4)
        self.assertEqual(said.output, ["WARNING:portal:Still waiting for the desktop's answer to "
                                       "InputCapture.CreateSession after 0 s"])

    def test_a_refusal_and_another_ending_are_told_apart(self):
        bus = FakeBus()
        bus.answers["Start"] = (1, {})
        with self.assertRaises(portal.Refused):
            portal.Portal(bus).request("I", "Start", "osa{sv}", lambda token: ("/s", "", {"handle_token": ("s", token)}))
        bus.answers["Start"] = (2, {})
        with self.assertRaises(portal.PortalError):
            portal.Portal(bus).request("I", "Start", "osa{sv}", lambda token: ("/s", "", {"handle_token": ("s", token)}))

    def test_other_signals_and_another_requests_response_are_kept_for_later(self):
        bus = FakeBus()
        bus.answers["GetZones"] = None  # answered by hand below
        client = portal.Portal(bus)
        bus.emit("/org/freedesktop/portal/desktop", "org.freedesktop.portal.InputCapture", "Activated", ("/s", vardict({"activation_id": 4})))
        result = []

        def answer():
            time.sleep(0.05)
            bus.emit("/org/freedesktop/portal/desktop/request/1_42/other", portal.REQUEST, "Response", (0, {}))
            bus.emit("/org/freedesktop/portal/desktop/request/1_42/beamer1", portal.REQUEST, "Response", (0, vardict({"zone_set": 9})))

        threading.Thread(target=answer).start()
        result = client.request("I", "GetZones", "oa{sv}", lambda token: ("/s", {"handle_token": ("s", token)}), timeout=2)
        self.assertEqual(result, {"zone_set": 9})
        kept = client.signals()
        self.assertEqual([(member, body) for _path, _i, member, body in kept],
                         [("Activated", ("/s", {"activation_id": 4})), ("Response", (0, {}))])

    def test_a_stop_ends_a_wait_for_the_user(self):
        bus = FakeBus()
        bus.answers["Start"] = None  # the user never answers
        stopping = threading.Event()
        threading.Timer(0.1, stopping.set).start()
        with self.assertRaises(portal.PortalError):
            portal.Portal(bus, stopping.is_set).request("I", "Start", "osa{sv}", lambda token: ("/s", "", {"handle_token": ("s", token)}))

    def test_a_missing_interface_is_version_zero(self):
        bus = FakeBus(versions={"org.freedesktop.portal.InputCapture": 2})
        client = portal.Portal(bus)
        self.assertEqual(client.version("org.freedesktop.portal.InputCapture"), 2)
        self.assertEqual(client.version("org.freedesktop.portal.RemoteDesktop"), 0)


class NotifyTest(unittest.TestCase):
    def test_a_message_goes_to_the_notification_portal_in_place_of_the_last_and_the_bus_is_closed(self):
        bus = FakeBus()
        portal.notify("Beamer", "Cannot switch", connect=lambda: bus).join(2)
        self.assertEqual(bus.calls, [(portal.NOTIFICATION, "AddNotification",
                                      ("alert", {"title": ("s", "Beamer"), "body": ("s", "Cannot switch")}))])
        self.assertTrue(bus.closed)

    def test_a_portal_that_fails_or_a_bus_out_of_reach_costs_only_the_message(self):
        bus = FakeBus()
        bus.failures["AddNotification"] = portal.PortalError("No such interface")
        portal.notify("Beamer", "x", connect=lambda: bus).join(2)
        self.assertTrue(bus.closed)

        def unreachable():
            raise portal.PortalError("Could not reach the session bus")

        portal.notify("Beamer", "x", connect=unreachable).join(2)


class TokenStoreTest(unittest.TestCase):
    def test_a_token_is_kept_for_this_user_only_and_an_empty_one_forgets_it(self):
        with tempfile.TemporaryDirectory() as directory:
            store = portal.TokenStore("remote-desktop", Path(directory) / "beamer")
            self.assertEqual(store.read(), "")
            store.write("abc")
            self.assertEqual(store.read(), "abc")
            if sys.platform != "win32":  # POSIX modes; the store is only used on Linux
                self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)
            store.write("def")
            self.assertEqual(store.read(), "def")
            store.write("")
            self.assertFalse(store.path.exists())
            self.assertEqual(store.read(), "")


if __name__ == "__main__":
    unittest.main()
