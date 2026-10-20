import copy
import hashlib
import unittest

from core import pairing
from core.easy_pair import EasyPairWindow, PAIR_MODES


def windows():
    clock = [100.0]
    a = EasyPairWindow("Mac", b"a" * 16, "mac", 24800, clock=lambda: clock[0])
    b = EasyPairWindow("PC", b"b" * 16, "win", 24801, clock=lambda: clock[0])
    a.select(b.offer("192.0.2.2", 9002))
    b.select(a.offer("192.0.2.1", 9001))
    return a, b, clock


def exchange(a, b):
    for _ in range(4):
        for sender, receiver, address in ((a, b, "192.0.2.1"), (b, a, "192.0.2.2")):
            for message in sender.messages():
                receiver.receive(message, address)


def deterministic(label):
    counter = 0

    def entropy(size):
        nonlocal counter
        counter += 1
        return hashlib.sha512(label + bytes([counter])).digest()[:size]

    return entropy


class EasyPairWindowTests(unittest.TestCase):
    def test_matching_confirmation_requires_both_approvals(self):
        a, b, _ = windows()
        exchange(a, b)
        assert a.state == b.state == "confirm"
        assert a.sas == b.sas and len(a.sas) == 6
        assert not a.ready and not b.ready
        a.approve(a.sas, a.attempt)
        exchange(a, b)
        assert not a.ready and not b.ready
        b.approve(b.sas, b.attempt)
        exchange(a, b)
        assert a.ready and b.ready
        assert a.token == b.token

    def test_mismatch_consumes_window(self):
        a, b, _ = windows()
        exchange(a, b)
        with self.assertRaises(pairing.PairingError):
            a.approve("999999" if a.sas != "999999" else "000000", a.attempt)
        assert a.state == "refused" and not a.messages() and not a.ready

    def test_third_machine_and_cross_window_replay_do_not_advance(self):
        a, b, _ = windows()
        commit = b.messages()[0]
        a.receive(commit, "192.0.2.3")
        assert a.remote_commit is None
        wrong = {**commit, "to": "c" * 32}
        a.receive(wrong, "192.0.2.2")
        assert a.remote_commit is None
        a.receive(commit, "192.0.2.2")
        changed = {**commit, "commit": pairing._b64(b"x" * 64)}
        a.receive(changed, "192.0.2.2")
        assert a.state == "refused"

    def test_expiry_discards_keys_and_approval(self):
        a, b, clock = windows()
        exchange(a, b)
        sas, attempt = a.sas, a.attempt
        clock[0] += 60
        assert a.state == "expired"
        with self.assertRaises(pairing.PairingError):
            a.approve(sas, attempt)
        assert not a.ready and not a.messages() and a.token is None

    def test_old_peer_cannot_select_nearby(self):
        a, b, _ = windows()
        c = EasyPairWindow("New", b"c" * 16, "linux", 24802)
        offer = b.offer("192.0.2.2", 9002)
        offer.pop("pair_modes")
        with self.assertRaises(pairing.PairingError):
            c.select(offer)
        assert c.state == "searching"

    def test_reveal_before_commit_and_modified_reveal(self):
        a, b, _ = windows()
        a.receive(b._message("easy_reveal", reveal=b.reveal), "192.0.2.2")
        assert a.remote_reveal is None
        a.receive(b.messages()[0], "192.0.2.2")
        reveal = copy.deepcopy(b.reveal)
        reveal["name"] = "Intruder"
        a.receive(b._message("easy_reveal", reveal=reveal), "192.0.2.2")
        assert a.state == "refused"

    def test_invalid_proof_and_replayed_approval_are_refused(self):
        a, b, _ = windows()
        a.receive(b.messages()[0], "192.0.2.2")
        b.receive(a.messages()[0], "192.0.2.1")
        for msg in b.messages():
            a.receive(msg, "192.0.2.2")
        a.receive(b._message("easy_proof", tag=pairing._b64(bytes(64))), "192.0.2.2")
        assert a.state == "refused"
        a, b, _ = windows()
        exchange(a, b)
        with self.assertRaises(pairing.PairingError):
            a.approve(a.sas, "old-attempt")
        assert a.state == "refused"

    def test_duplicate_messages_do_not_change_transcript(self):
        a, b, _ = windows()
        exchange(a, b)
        sas, token = a.sas, a.token
        exchange(a, b)
        assert (a.sas, a.token) == (sas, token)
        assert a.reveal["pair_modes"] == PAIR_MODES

    def test_committed_interleaved_mitm_has_different_confirmations(self):
        a = EasyPairWindow("Mac", b"a" * 16, "mac", 24800, entropy=deterministic(b"a"))
        b = EasyPairWindow("PC", b"b" * 16, "win", 24801, entropy=deterministic(b"b"))
        fake_b = EasyPairWindow("PC", b"b" * 16, "win", 24801, entropy=deterministic(b"fake-b"))
        fake_a = EasyPairWindow("Mac", b"a" * 16, "mac", 24800, entropy=deterministic(b"fake-a"))
        a.select(fake_b.offer("192.0.2.2", 9002))
        fake_b.select(a.offer("192.0.2.1", 9001))
        # Attacker fully learns one leg before committing to the other. The fresh honest
        # nonce on that second leg was still hidden when its attacker commitment was fixed.
        exchange(a, fake_b)
        b.select(fake_a.offer("192.0.2.1", 9001))
        fake_a.select(b.offer("192.0.2.2", 9002))
        exchange(fake_a, b)
        assert a.sas == fake_b.sas and b.sas == fake_a.sas
        assert a.sas != b.sas and a.token != b.token
        assert not a.ready and not b.ready

    def test_invalid_but_committed_peer_payload_is_refused(self):
        from core.easy_pair import canonical, DOMAIN
        cases = [("port", True), ("pair_modes", ["sas_v1"]),
                 ("id", pairing._b64(bytes(16))), ("share", pairing._b64(bytes(32))),
                 ("nonce", "invalid"), ("extra", "unexpected")]
        for field, value in cases:
            with self.subTest(field=field):
                a, b, _ = windows()
                reveal = {**b.reveal, field: value}
                commitment = hashlib.sha512(DOMAIN + b"commit\0" + canonical(reveal)).digest()
                a.receive(b._message("easy_commit", commit=pairing._b64(commitment)), "192.0.2.2")
                a.receive(b._message("easy_reveal", reveal=reveal), "192.0.2.2")
                assert a.state == "refused" and a.token is None

    def test_cannot_confirm_before_key_proof_or_after_cancellation(self):
        a, b, _ = windows()
        with self.assertRaises(pairing.PairingError):
            a.approve("000000", a.attempt)
        assert a.state == "refused"
        a, b, _ = windows()
        exchange(a, b)
        sas, attempt = a.sas, a.attempt
        a.cancel()
        with self.assertRaises(pairing.PairingError):
            a.approve(sas, attempt)
        assert not a.ready

    def test_approval_replay_from_previous_window_and_reflected_proof(self):
        a, b, _ = windows()
        exchange(a, b)
        b.approve(b.sas, b.attempt)
        old = next(msg for msg in b.messages() if msg["type"] == "easy_approve")
        a, b, _ = windows()
        exchange(a, b)
        a.receive({**old, "from": b.window, "to": a.window}, "192.0.2.2")
        assert a.state == "refused" and not a.ready
        a, b, _ = windows()
        exchange(a, b)
        proof = next(msg for msg in a.messages() if msg["type"] == "easy_proof")
        a.receive({**proof, "from": b.window, "to": a.window}, "192.0.2.2")
        assert a.state == "refused"

    def test_full_length_unicode_reveal_fits_existing_datagram_ceiling(self):
        import json
        a = EasyPairWindow("\U00020000" * 48, b"a" * 16, "macos", 24800)
        b = EasyPairWindow("PC", b"b" * 16, "windows", 24801)
        a.select(b.offer("192.0.2.2", 9002))
        b.select(a.offer("192.0.2.1", 9001))
        a.receive(b.messages()[0], "192.0.2.2")
        for message in a.messages():
            datagram = json.dumps({"beamy": 1, **message}, ensure_ascii=False, separators=(",", ":")).encode()
            assert len(datagram) <= pairing.MAX_DATAGRAM_BYTES
            assert pairing.decode(datagram) == {"beamy": 1, **message}
