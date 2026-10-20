import time
import unittest

from core import pairing


def service(name, ident, clock=None):
    entries, notified = [], []
    kwargs = {"clock": clock} if clock else {}
    instance = pairing.PairingService(name, ident * 16, "mac" if name == "Mac" else "win", lambda: 24800,
                                      lambda: entries, lambda entry, replaced: entries.append(entry),
                                      on_paired=notified.append, bind_port=0, tcp_port=0,
                                      announce_to=("127.0.0.1", 9), **kwargs)
    return instance, entries, notified


def note(a, b, address):
    a._note_beacon(pairing.decode(b._beacon()), address)


def pump(a, b):
    class Wire:
        def __init__(self, receiver, address):
            self.receiver, self.address = receiver, address

        def sendto(self, data, target):
            self.receiver._dispatch(None, pairing.decode(data), self.address, 0, {}, {})

    for _ in range(6):
        a._nearby_next = b._nearby_next = 0
        a._tick_nearby(Wire(b, ("192.0.2.1", 9001)))
        b._tick_nearby(Wire(a, ("192.0.2.2", 9002)))


class EasyPairServiceTests(unittest.TestCase):
    def test_service_stores_only_after_both_screens_confirm(self):
        a, ae, an = service("Mac", b"a")
        b, be, bn = service("PC", b"b")
        a.begin_nearby()
        b.begin_nearby()
        note(a, b, ("192.0.2.2", 9002))
        note(b, a, ("192.0.2.1", 9001))
        pump(a, b)
        sa, sb = a.nearby_status, b.nearby_status
        assert sa["state"] == sb["state"] == "confirm" and sa["sas"] == sb["sas"]
        a.confirm_nearby(sa["sas"], sa["attempt"])
        pump(a, b)
        assert ae == be == []
        b.confirm_nearby(sb["sas"], sb["attempt"])
        pump(a, b)
        assert len(ae) == len(be) == len(an) == len(bn) == 1
        assert ae[0]["token"] == be[0]["token"]
        assert a.nearby_status["state"] == b.nearby_status["state"] == "paired"
        assert "nearby" not in pairing.decode(a._beacon())
        pump(a, b)
        assert len(ae) == len(be) == 1

    def test_multiple_candidates_latch_explicit_selection(self):
        a, _, _ = service("Mac", b"a")
        b, _, _ = service("PC", b"b")
        c, _, _ = service("Third", b"c")
        for instance in (a, b, c):
            instance.begin_nearby()
        note(a, b, ("192.0.2.2", 9002))
        note(a, c, ("192.0.2.3", 9003))
        assert a.nearby_status["state"] == "choosing"
        assert len(a.nearby_status["peers"]) == 2
        a._tick_nearby(None)
        assert a.nearby_status["peer"] is None
        a.choose_nearby(a.nearby_status["peers"][1])
        assert a.nearby_status["peer"]["name"] == "Third"
        with self.assertRaises(pairing.PairingError):
            a.choose_nearby(a.machines()[0])

    def test_ambiguous_discovery_never_auto_selects_after_one_peer_disappears(self):
        a, _, _ = service("Mac", b"a")
        b, _, _ = service("PC", b"b")
        c, _, _ = service("Third", b"c")
        for instance in (a, b, c):
            instance.begin_nearby()
        note(a, b, ("192.0.2.2", 9002))
        note(a, c, ("192.0.2.3", 9003))
        assert a.nearby_status["state"] == "choosing"
        with a._lock:
            a._seen.pop("192.0.2.3")
        a._tick_nearby(None)
        assert a.nearby_status["state"] == "choosing" and a.nearby_status["peer"] is None

    def test_old_peer_and_expiry_preserve_code_route(self):
        clock = [100.0]
        a, entries, _ = service("Mac", b"a", lambda: clock[0])
        a.begin_nearby()
        a._note_beacon({"type": "beacon", "name": "Old", "port": 24800, "pairing": 3}, ("192.0.2.2", 9002))
        assert a.nearby_status["peers"] == []
        clock[0] += 60
        assert a.nearby_status["state"] == "expired" and not entries
        a.begin_pairing()
        assert a.code and a.nearby_status["state"] == "inactive"
        a.stop()

    def test_invalid_duplicate_keys_rejected(self):
        assert pairing.decode(b'{"beamy":1,"type":"easy_commit","from":"a","from":"b"}') is None
        assert pairing.decode(b'{"beamy":true,"type":"easy_commit"}') is None

    def test_storage_finishes_once_or_reports_failure(self):
        for slow, fail in [(True, False), (False, True)]:
            with self.subTest(slow=slow, fail=fail):
                clock = [100.0]
                a, ae, an = service("Mac", b"a", lambda: clock[0])
                b, _, _ = service("PC", b"b", lambda: clock[0])
                a.begin_nearby()
                b.begin_nearby()
                note(a, b, ("192.0.2.2", 9002))
                note(b, a, ("192.0.2.1", 9001))
                pump(a, b)
                for instance in (a, b):
                    status = instance.nearby_status
                    instance.confirm_nearby(status["sas"], status["attempt"])

                def store(entry, replaced):
                    if fail:
                        raise OSError("disk full")
                    ae.append(entry)
                    if slow:
                        clock[0] += 61

                a.store = store
                pump(a, b)
                assert a.nearby_status["state"] == ("not_saved" if fail else "paired")
                assert len(ae) == len(an) == (0 if fail else 1)

    def test_cancel_while_searching_and_known_peer_cannot_pair(self):
        a, ae, _ = service("Mac", b"a")
        b, _, _ = service("PC", b"b")
        a.begin_nearby()
        b.begin_nearby()
        note(a, b, ("192.0.2.2", 9002))
        ae.append({"id": pairing._b64(b.identity)})
        assert a.nearby_status["peers"] == []
        a.cancel_nearby()
        assert a.nearby_status["state"] == "inactive"

    def test_lost_final_approval_retransmits_after_local_save(self):
        a, ae, _ = service("Mac", b"a")
        b, be, _ = service("PC", b"b")
        a.begin_nearby()
        b.begin_nearby()
        note(a, b, ("192.0.2.2", 9002))
        note(b, a, ("192.0.2.1", 9001))
        pump(a, b)
        for instance in (a, b):
            status = instance.nearby_status
            instance.confirm_nearby(status["sas"], status["attempt"])
        # Deliver only A's approval. B saves, but A must still receive B's cached approval.
        approval = next(msg for msg in a._nearby.messages() if msg["type"] == "easy_approve")
        b._receive_nearby(approval, ("192.0.2.1", 9001))
        assert be and not ae
        pump(a, b)
        assert ae and len(be) == 1

    def test_real_loopback_udp_pairing(self):
        a, ae, _ = service("Mac", b"a")
        b, be, _ = service("PC", b"b")
        a.start()
        b.start()
        try:
            deadline = time.monotonic() + 6
            while not a.listening_port or not b.listening_port:
                assert time.monotonic() < deadline
                time.sleep(.01)
            a.announce_to = ("127.0.0.1", b.listening_port)
            b.announce_to = ("127.0.0.1", a.listening_port)
            a.begin_nearby()
            b.begin_nearby()
            while a.nearby_status["state"] != "confirm" or b.nearby_status["state"] != "confirm":
                assert time.monotonic() < deadline
                time.sleep(.02)
            sa, sb = a.nearby_status, b.nearby_status
            a.confirm_nearby(sa["sas"], sa["attempt"])
            b.confirm_nearby(sb["sas"], sb["attempt"])
            while not ae or not be:
                assert time.monotonic() < deadline
                time.sleep(.02)
            assert ae[0]["token"] == be[0]["token"]
        finally:
            a.stop()
            b.stop()
