"""Saved destination choices survive discovery and authenticated reverse links."""

import unittest

from core import protocol, receiver
from core.tests.test_link import FakeClock, Side
from core.tests.responder_harness import HERE


class ChosenAddressTests(unittest.TestCase):
    def test_discovery_does_not_try_another_interface_for_a_saved_choice(self):
        for pinned in (None, True):
            with self.subTest(pinned=pinned):
                side = Side()
                side.peer()["host"] = "192.0.2.10"
                if pinned is not None:
                    side.peer()["host_pinned"] = pinned
                clock = FakeClock()
                link = side.link(clock=clock)
                clock.now += 11
                link.follow([{"name": "Far", "address": "198.51.100.10"}])
                self.assertIsNone(link._try_host)
                self.assertEqual(side.peer()["host"], "192.0.2.10")

    def test_reverse_link_cannot_overwrite_a_saved_choice(self):
        side = Side()
        side.peer()["host"] = "192.0.2.10"
        changes = {"host": "198.51.100.10", "name": "New name"}
        outcome, saved = side.book.admit(protocol.key_id(side.peer()["token"]),
                                        side.own, HERE, changes)
        self.assertEqual(outcome, receiver.ADMITTED)
        self.assertEqual(saved["host"], "192.0.2.10")
        self.assertEqual(saved["name"], "New name")
        self.assertEqual(changes["host"], "198.51.100.10")

    def test_an_empty_address_can_be_learnt_and_followed(self):
        side = Side()
        side.peer()["host"] = ""
        key = protocol.key_id(side.peer()["token"])
        outcome, saved = side.book.admit(key, side.own, HERE, {"host": "192.0.2.10"})
        self.assertEqual(outcome, receiver.ADMITTED)
        self.assertEqual(saved["host"], "192.0.2.10")
        self.assertIs(saved.get("host_pinned"), False)
        clock = FakeClock()
        link = side.link(clock=clock)
        clock.now += 11
        link.follow([{"name": "Far", "address": "198.51.100.10"}])
        self.assertEqual(link._try_host, "198.51.100.10")
        _, saved = side.book.admit(key, side.own, HERE, {"host": "198.51.100.10"})
        self.assertEqual(saved["host"], "198.51.100.10")

    def test_choice_made_after_a_beacon_was_queued_is_used_for_dialling(self):
        side = Side()
        side.peer().update(host="192.0.2.10", host_pinned=True)
        tried = []

        def factory(address, timeout=None):
            tried.append(address)
            link._stop.set()
            raise OSError("synthetic offline peer")

        link = side.link(socket_factory=factory)
        link._try_host = "198.51.100.10"
        link._run()
        self.assertEqual(tried, [("192.0.2.10", 24820)])

    def test_choice_made_during_handshake_wins_over_learned_address(self):
        side = Side()
        side.peer().update(host="192.0.2.10", host_pinned=False)
        key = protocol.key_id(side.peer()["token"])
        side.peer().update(host="203.0.113.10", host_pinned=True)
        _, saved = side.book.admit(key, side.own, HERE, {"host": "198.51.100.10"})
        self.assertEqual(saved["host"], "203.0.113.10")


class PairedAddressTests(unittest.TestCase):
    def test_pairing_saves_a_followable_address(self):
        from core import pairing
        entry = pairing.peer_entry(bytes(16), "Far", "windows", 24820, "t", "192.0.2.10", 1)
        self.assertIs(entry["host_pinned"], False)
