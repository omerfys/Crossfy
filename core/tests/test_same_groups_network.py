"""Three synthetic desks synchronise and revert over encrypted loopback links."""

import unittest

from core import protocol, settings_sync
from core.tests.responder_harness import Machine, Initiator, entry, ident, token, wait_for


class ThreeDeskGroupsTests(unittest.TestCase):
    def setUp(self):
        self.ids = [ident(seed) for seed in (30, 60, 90)]
        self.states = [{"on": False, "groups": [], "set_at": 0, "by": "",
                        "values": {"resistance_px": resistance, "glow_colour": colour}}
                       for resistance, colour in ((120, "signal"), (140, "ocean"), (160, "sunset"))]
        self.machines = []
        self.links = {}
        for target, own in enumerate(self.ids):
            peers = [entry(peer, "Synthetic desk", token=token(source * 3 + target))
                     for source, peer in enumerate(self.ids) if source != target]
            machine = Machine(peers, own=own).start()
            self.addCleanup(machine.stop)
            self.machines.append(machine)
        for source, own in enumerate(self.ids):
            for target, machine in enumerate(self.machines):
                if source == target:
                    continue
                link = Initiator(machine, peer=own, key=token(source * 3 + target))
                self.addCleanup(link.close)
                link.handshake()
                self.links[source, target] = link

    def send(self, source, target, data):
        machine = self.machines[target]
        count = len(machine.settings_seen)
        self.links[source, target].send(protocol.settings_msg(data))
        self.assertTrue(wait_for(lambda: len(machine.settings_seen) > count))
        peer, received = machine.settings_seen[-1]
        self.assertEqual(peer, self.ids[source])
        state = self.states[target]
        taken = settings_sync.arrived(received, state["set_at"], {"alt_r"},
                                      by_here=state["by"], current_groups=state["groups"])
        if taken is None:
            return False
        snapshot = settings_sync.snapshot_for_arrival(received, state["set_at"], {"alt_r"},
            state["by"], state["groups"], state["values"])
        if snapshot is not None:
            state["snapshot"] = snapshot
        on, stamp, values = taken
        state.update(on=on, set_at=stamp, by=received["by"],
                     groups=list(settings_sync.arrival_groups(received, state["groups"])))
        if on:
            state["values"].update(values)
        return True

    def test_crossing_and_revert_converge_while_design_stays_local(self):
        author = protocol.id_text(self.ids[0])
        data = settings_sync.message_data(True, 100, self.states[0]["values"],
                                          by=author, groups=["crossing"])
        self.states[0].update(on=True, groups=["crossing"], set_at=100, by=author)
        self.assertTrue(self.send(0, 1, data))
        self.assertTrue(self.send(1, 2, data))
        self.assertFalse(self.send(2, 0, data))
        self.assertEqual([state["values"]["resistance_px"] for state in self.states], [120] * 3)
        before = self.states[1]["snapshot"]
        restored = settings_sync.restore_snapshot(before)
        self.states[1]["values"].update(restored["values"])
        groups = settings_sync.revert_groups(before, self.states[1]["groups"])
        author = protocol.id_text(self.ids[1])
        stamp = settings_sync.next_stamp(100, 101)
        self.states[1].update(groups=groups, set_at=stamp, by=author)
        undo = settings_sync.message_data(True, stamp, self.states[1]["values"], by=author, groups=groups)
        self.assertTrue(self.send(1, 2, undo))
        self.assertTrue(self.send(2, 0, undo))
        self.assertFalse(self.send(0, 1, undo))
        self.assertEqual([state["values"]["resistance_px"] for state in self.states], [140] * 3)
        self.assertTrue(all(state["on"] and state["groups"] == ["crossing"] for state in self.states))
        self.assertEqual([state["values"]["glow_colour"] for state in self.states], ["signal", "ocean", "sunset"])
        self.assertNotIn("same_before_sync", undo)

    def test_legacy_state_keeps_each_selected_policy_and_filters_known_values(self):
        self.states[1].update(on=True, groups=["crossing"])
        data = settings_sync.message_data(True, 100, {"resistance_px": 60, "glow_colour": "mono"},
                                          by=protocol.id_text(self.ids[0]))
        self.assertTrue(self.send(0, 1, data))
        self.assertEqual(self.states[1]["groups"], ["crossing"])
        self.assertEqual(self.states[1]["values"], {"resistance_px": 60, "glow_colour": "ocean"})
