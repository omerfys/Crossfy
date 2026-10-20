import unittest

from core import settings_sync, ways


HOME = "home"
A, B, C = "a", "b", "c"


def peer(ident, **values):
    return {"id": ident, "send": True, "in_use": True, "port": 5000, **values}


class ShortcutCycleTests(unittest.TestCase):
    def test_order_sorts_rows_then_columns_and_rotates_after_this_machine(self):
        peers = [peer(A), peer(B), peer(C)]
        positions = {HOME: (100, 100, 100, 100), A: (0, 100, 100, 100),
                     B: (200, 130, 100, 100), C: (200, 220, 100, 100)}
        self.assertEqual(ways.shortcut_order(peers, HOME, positions), [B, C, A, None])

    def test_home_split_uses_the_same_row_tolerance_as_reading_order(self):
        peers = [peer(A), peer(B)]
        positions = {HOME: (100, 100, 100, 100), A: (0, 120, 100, 100),
                     B: (200, 100, 100, 100)}
        self.assertEqual(ways.shortcut_order(peers, HOME, positions), [B, A, None])

    def test_unplaced_peers_follow_in_peer_order_and_left_out_stays_in_cycle(self):
        peers = [peer(A, left_out=True), peer(B), peer(C)]
        positions = {HOME: (0, 0, 100, 100), B: (100, 0, 100, 100)}
        self.assertEqual(ways.shortcut_order(peers, HOME, positions), [B, A, C, None])

    def test_not_sendable_peers_are_excluded(self):
        peers = [peer(A), peer(B, in_use=False), peer(C, send=False)]
        self.assertEqual(ways.shortcut_order(peers, HOME, {HOME: (0, 0, 100, 100)}), [A, None])

    def test_ticked_mode_omits_only_explicitly_unticked_peers(self):
        peers = [peer(A, shortcut_cycle=False), peer(B), peer(C, shortcut_cycle=None)]
        positions = {HOME: (0, 0, 100, 100)}
        self.assertEqual(ways.shortcut_order(peers, HOME, positions, "ticked"), [B, C, None])

    def test_next_target_skips_unready_peers_and_returns_home_after_the_last(self):
        order = [A, B, C, None]
        target, skipped = ways.next_target({"shortcut_goes_to": "next"}, order, None,
                                           lambda ident: ident != A)
        self.assertEqual((target, skipped), (B, [A]))
        self.assertEqual(ways.next_target({}, order, C, lambda ident: True), (None, []))

    def test_when_no_peer_is_ready_first_machine_is_named_for_the_refusal(self):
        self.assertEqual(ways.next_target({}, [A, B, None], None, lambda _ident: False),
                         (A, [A, B]))

    def test_hold_uses_last_machine_or_first_ready_cycle_machine(self):
        order = [A, B, None]
        self.assertEqual(ways.hold_target({"shortcut_goes_to": "last"}, order, A,
                                          lambda _ident: True), (A, []))
        self.assertEqual(ways.hold_target({"shortcut_goes_to": "next"}, order, A,
                                          lambda ident: ident == B), (B, [A]))

    def test_shortcut_mode_is_a_valid_optional_crossing_sync_value(self):
        data = settings_sync.message_data(True, 7, {"shortcut_goes_to": "ticked"})
        self.assertEqual(data["crossing"], {"shortcut_goes_to": "ticked"})
        self.assertEqual(settings_sync.read(data, set())[2], {"shortcut_goes_to": "ticked"})


# A synced layout: a Windows PC, a Linux machine and the Mac in a row, a fourth machine up to the
# right and switched off. With Linux home the cycle from the Mac is the fourth, the PC, then home.
RIG, FEDORA, MAC, FAR = "rig", "fedora", "mac", "far"
SYNCED = {RIG: (-960, -50, 160, 100), FEDORA: (-800, -50, 160, 100),
          MAC: (-640, -50, 160, 100), FAR: (-198, -119, 160, 100)}


class WayHomeTests(unittest.TestCase):
    """An offline machine in the cycle never costs a press or keeps input from home, and a machine
    that refused a moment ago (the owner holds it back, so a take there does nothing) is passed
    over, never chosen: choosing it left input on the Mac with "<machine> isn't connected" on
    every press."""

    def presses_home(self, home, mode, start, held):
        peers = [peer(ident) for ident in SYNCED if ident != home]
        order = ways.shortcut_order(peers, home, SYNCED, mode)
        ready = lambda ident: ident != FAR
        on, pressed = start, 0
        while on is not None:
            target, _skipped = ways.next_target({"shortcut_goes_to": mode}, order, on, ready,
                                                held=lambda ident: ident in held)
            self.assertNotIn(target, {FAR} | set(held), (home, mode, on))
            self.assertNotEqual(target, on, (home, mode, on))
            on, pressed = target, pressed + 1
            self.assertLessEqual(pressed, len(order), (home, mode, start))
        return pressed

    def test_every_press_moves_on_and_ends_home_for_each_home(self):
        for home in (FEDORA, MAC, RIG):
            for mode in ("ticked", "next"):
                for start in [ident for ident in SYNCED if ident not in (home, FAR)]:
                    for held in ((), tuple(ident for ident in SYNCED if ident not in (home, start, FAR))):
                        with self.subTest(home=home, mode=mode, start=start, held=held):
                            self.presses_home(home, mode, start, held)

    def test_fedora_home_from_the_mac_with_the_rig_held_back_goes_home_in_one_press(self):
        peers = [peer(RIG), peer(MAC), peer(FAR)]
        order = ways.shortcut_order(peers, FEDORA, SYNCED, "ticked")
        self.assertEqual(order, [MAC, FAR, RIG, None])
        target, skipped = ways.next_target({"shortcut_goes_to": "ticked"}, order, MAC,
                                           lambda ident: ident != FAR, held=lambda ident: ident == RIG)
        self.assertEqual((target, skipped), (None, [FAR]))

    def test_a_held_back_machine_is_not_named_as_not_connected(self):
        target, skipped = ways.next_target({}, [A, B, None], None, lambda _ident: True,
                                           held=lambda ident: ident == A)
        self.assertEqual((target, skipped), (B, []))

    def test_hold_passes_over_a_held_back_last_machine(self):
        self.assertEqual(ways.hold_target({"shortcut_goes_to": "last"}, [A, B, None], A,
                                          lambda _ident: True, held=lambda ident: ident == A), (B, []))

    def test_nothing_to_name_when_every_machine_is_held_back(self):
        held = lambda _ident: True
        self.assertEqual(ways.next_target({}, [A, B, None], None, lambda _ident: False, held=held), (None, []))
        self.assertEqual(ways.hold_target({}, [A, B, None], None, lambda _ident: False, held=held), (None, []))


if __name__ == "__main__":
    unittest.main()
