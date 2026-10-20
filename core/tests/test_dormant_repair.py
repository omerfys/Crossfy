import copy
import base64
import unittest

from core import pairing, peerlist, protocol, receiver, ways


PEER = protocol.id_text(bytes(range(20, 36)))
OWN = protocol.id_text(bytes(range(1, 17)))
TOKEN = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


def entry(**fields):
    return {"id": PEER, "name": "Desk", "token": TOKEN, "linked": True, "from_1_4": False,
            "side": "left", **fields}


class DormantPeerTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"machine_id": OWN, "peers": [entry()], "zones": [{"peer": PEER, "kind": "edge"}],
                         "layout": {PEER: {"x": 20, "y": 30, "w": 160, "h": 100}}}
        self.book = receiver.PeerBook(lambda: self.settings, self.save)

    def save(self, settings):
        self.settings.clear()
        self.settings.update(copy.deepcopy(settings))

    def test_wrong_id_marks_the_peer_dormant_with_a_reason(self):
        self.book.mark_dormant(TOKEN, "wrong_id")
        peer = self.settings["peers"][0]
        self.assertTrue(peer["dormant"])
        self.assertEqual(peer["dormant_reason"], "wrong_id")
        self.assertEqual(peerlist.dormant_reason(peer), "The saved pairing now identifies a different machine.")

    def test_forgotten_marks_the_peer_dormant_with_a_reason(self):
        self.book.mark_dormant(TOKEN, "forgotten")
        self.assertEqual(peerlist.dormant_reason(self.settings["peers"][0]),
                         "The other machine no longer has this pairing.")

    def test_dormant_without_a_reason_still_needs_repair(self):
        self.assertEqual(peerlist.dormant_reason(entry(dormant=True)), "This pairing needs to be set up again.")

    def test_layout_compilation_keeps_dormant_zones_and_saved_position(self):
        self.settings["peers"][0].update(dormant=True, dormant_reason="forgotten")
        self.settings["layout"][OWN] = {"x": 0, "y": 0, "w": 160, "h": 100}
        before = copy.deepcopy(self.settings)
        result = ways.compile_layout(self.settings, self.settings["layout"], now=100)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["settings"]["zones"], [])
        self.assertEqual(ways.ways(result["settings"], PEER)["methods"], ["edge"])
        self.assertEqual(result["settings"]["layout"], before["layout"])
        self.assertEqual(result["tiles"][PEER]["state"], "dormant")

    def test_dormant_tile_does_not_block_another_tile(self):
        other = protocol.id_text(bytes(range(40, 56)))
        self.settings["peers"][0].update(dormant=True, dormant_reason="forgotten")
        self.settings["peers"].append(entry(id=other, token="other"))
        layout = {OWN: {"x": 0, "y": 0, "w": 160, "h": 100},
                  PEER: {"x": 160, "y": 0, "w": 160, "h": 100},
                  other: {"x": 160, "y": 0, "w": 160, "h": 100}}
        result = ways.compile_layout(self.settings, layout, moved=other, now=100)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["tiles"][other]["state"], "edge")

    def test_successful_link_clears_dormant_state(self):
        self.book.mark_dormant(TOKEN, "wrong_id")
        outcome, _ = self.book.admit(protocol.key_id(TOKEN), bytes(range(1, 17)), bytes(range(20, 36)), {})
        self.assertEqual(outcome, receiver.ADMITTED)
        self.assertNotIn("dormant", self.settings["peers"][0])
        self.assertNotIn("dormant_reason", self.settings["peers"][0])

    def test_successful_link_keeps_intent_and_compile_allocates_the_shared_stretch(self):
        other_id = protocol.id_text(bytes(range(40, 56)))
        self.settings["peers"].append({**entry(id=other_id, token="other"), "side": "left"})
        self.settings["peers"][0].update(dormant=True, dormant_reason="forgotten")
        self.settings["peers"][0].update(side="left", side_set_at=42, side_by=OWN)
        self.settings["zones"].append({"peer": other_id, "kind": "edge"})
        self.settings["layout"] = {
            OWN: {"x": 0, "y": 0, "w": 160, "h": 100},
            PEER: {"x": -160, "y": 0, "w": 160, "h": 50},
            other_id: {"x": -160, "y": 50, "w": 160, "h": 50},
        }

        outcome, _ = self.book.admit(protocol.key_id(TOKEN), bytes(range(1, 17)), bytes(range(20, 36)), {})
        ways.ensure_zones(self.settings)

        self.assertEqual(outcome, receiver.ADMITTED)
        self.assertEqual(self.settings["zones"], [
            {"peer": PEER, "kind": "part", "parts": ["start"], "side": "left",
             "contact_span": [0.0, 0.5], "target_span": [0.0, 1.0]},
            {"peer": other_id, "kind": "part", "parts": ["middle", "end"], "side": "left",
             "contact_span": [0.5, 1.0], "target_span": [0.0, 1.0]},
        ])
        self.assertEqual(ways.ways(self.settings, PEER)["methods"], ["edge"])
        self.assertTrue(all("off" not in zone for zone in self.settings["zones"]))

    def test_repair_replaces_the_entry_and_keeps_local_machine_fields(self):
        old = self.settings["peers"][0]
        old.update(label="Office", left_out=True, left_out_ways=["edge"], dormant=True, dormant_reason="forgotten")
        old.update(side="left", side_set_at=42, side_by=OWN)
        repaired = {"id": PEER, "name": "Desk 2", "token": "new", "side": "", "linked": False}
        peerlist.add_peer(self.settings, repaired, copy.deepcopy(old))
        self.assertEqual(self.settings["peers"][0]["id"], PEER)
        self.assertEqual((repaired["label"], repaired["left_out"], repaired["left_out_ways"]),
                         ("Office", True, ["edge"]))
        self.assertEqual((repaired["side"], repaired["side_set_at"], repaired["side_by"]), ("left", 42, OWN))
        self.assertEqual(self.settings["zones"], [])
        self.assertEqual(ways.ways(self.settings, PEER)["methods"], ["edge"])
        self.assertEqual(self.settings["layout"][PEER], {"x": 20, "y": 30, "w": 160, "h": 100})
        self.assertNotIn("dormant", repaired)

    def test_repaired_peer_with_retained_side_and_intent_crosses_at_its_picture_contact(self):
        old = self.settings["peers"][0]
        old.update(side="left", side_set_at=42, side_by=OWN)
        repaired = {"id": PEER, "name": "Desk 2", "token": "new", "side": "", "linked": False}
        self.settings["layout"] = {
            OWN: {"x": 0, "y": 0, "w": 160, "h": 100},
            PEER: {"x": -160, "y": 0, "w": 160, "h": 100},
        }

        peerlist.add_peer(self.settings, repaired, copy.deepcopy(old))

        self.assertTrue(ways.has_way(self.settings, PEER))
        self.assertEqual(ways.ways(self.settings, PEER)["methods"], ["edge"])
        self.assertEqual(self.settings["zones"], [{"peer": PEER, "kind": "edge", "side": "left",
                                                   "contact_span": [0.0, 1.0], "target_span": [0.0, 1.0]}])

    def test_qr_known_check_allows_a_dormant_same_id_peer(self):
        service = pairing.PairingService.__new__(pairing.PairingService)
        service.identity = bytes(range(1, 17))
        service._peer_entries = lambda: [entry(dormant=True, dormant_reason="forgotten")]

        service._not_paired_already(PEER)

    def test_pairing_client_allows_capacity_when_a_peer_might_be_repaired(self):
        peers = [entry(id=protocol.id_text(bytes([i]) * 16), dormant=True) for i in range(pairing.MAX_PEERS)]
        pairing.PairingClient("pair", "123456", "Desk", bytes(range(1, 17)), version=pairing.PAIRING_V3,
                              platform="windows", port=24820, peers=lambda: peers)

    def test_host_rejects_a_distinct_addition_at_capacity(self):
        peers = [entry(id=protocol.id_text(bytes([i]) * 16)) for i in range(pairing.MAX_PEERS)]
        host = pairing.PairingHost(lambda: 0, "Host", bytes(range(1, 17)), version=pairing.PAIRING_V3,
                                   platform="windows", port=24820, peers=lambda: peers,
                                   store=lambda *_: self.fail("full host stored an additional peer"))
        bound = {"identity": bytes(range(60, 76)), "name": "New", "platform": "windows", "port": 24820,
                 "token": base64.urlsafe_b64encode(bytes(range(100, 132))).decode().rstrip("="),
                 "address": "192.0.2.5", "done_tag": b"done"}

        host._keep(bound, [], "pair")

        self.assertEqual(host.outcome, "full")

    def test_host_replaces_a_dormant_peer_at_capacity(self):
        repaired_id = bytes(range(60, 76))
        peers = [entry(id=protocol.id_text(bytes([i + 1]) * 16), token=f"peer-{i}")
                 for i in range(pairing.MAX_PEERS)]
        peers[0].update(id=protocol.id_text(repaired_id), dormant=True, dormant_reason="forgotten")
        stored = []
        host = pairing.PairingHost(lambda: 0, "Host", bytes(range(1, 17)), version=pairing.PAIRING_V3,
                                   platform="windows", port=24820, peers=lambda: peers,
                                   store=lambda item, old: stored.append((item, old)))
        bound = {"identity": repaired_id, "name": "Desk", "platform": "windows", "port": 24820,
                 "token": base64.urlsafe_b64encode(bytes(range(100, 132))).decode().rstrip("="),
                 "address": "192.0.2.5", "done_tag": b"done"}

        host._keep(bound, [], "pair")

        self.assertEqual(host.outcome, "paired")
        self.assertEqual(stored[0][1], peers[0])

    def test_a_dormant_id_is_replaceable_by_the_pairing_service(self):
        old = entry(dormant=True, dormant_reason="forgotten")
        refused, replaced = pairing._find_known(
            [old], bytes(range(1, 17)), bytes(range(20, 36)), "Desk", "windows", 2_000_000_000)
        self.assertIsNone(refused)
        self.assertEqual(replaced, old)

    def test_dormant_peer_does_not_hold_or_block_a_zone_stretch(self):
        stretch = ways._stretch({"peer": PEER, "kind": "edge"}, {PEER: "left"}, [entry(dormant=True)])
        self.assertEqual(stretch, set())

    def test_dormant_state_is_saved_by_peer_book(self):
        self.book.mark_dormant(TOKEN, "forgotten")
        reopened = receiver.PeerBook(lambda: self.settings, self.save)
        self.assertEqual(peerlist.dormant_reason(reopened.peers()[0]), "The other machine no longer has this pairing.")


if __name__ == "__main__":
    unittest.main()
