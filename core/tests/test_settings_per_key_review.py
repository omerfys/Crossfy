"""Review cases for per-key sync (10-10-2026): a trigger clash round four desks, and a slider stamped apart from its preset.
"""

import copy
import time
import unittest

from core import protocol, settings_sync
from core.tests import settings_behaviour
from core.tests.settings_behaviour import IDS, fixture
from core.tests.test_settings_per_key_desks import Desks

FOURTH = protocol.id_text(bytes([4]) * 16)


class RoutedDesks(Desks):
    """Desks whose forwarding honours `source`, as recipients() does: a copy is never sent back to
    the peer it came from."""

    def __init__(self, test, platforms):
        super().__init__(test, platforms)
        for app in self.apps:
            app.routed = []
            app._send_same = (lambda app: lambda data=None, source=None: app.routed.append(
                (copy.deepcopy(data if data is not None else app.state()), source)))(app)

    def run(self, queue):
        delivered = 0
        while queue:
            source, data, targets = queue.pop(0)
            for target in sorted(targets):
                if target == source or target not in self.online or (source, target) not in self.links:
                    continue
                delivered += 1
                self.test.assertLess(delivered, 200, "the desks kept announcing")
                app = self.apps[target]
                app.receive(IDS[source], {key: value for key, value in data.items() if key != "names"})
                everyone = set(range(len(self.apps))) - {target}
                for message, came_from in app.routed:
                    came_from = protocol.id_text(came_from) if isinstance(came_from, bytes) else came_from
                    skip = {IDS.index(came_from)} if came_from in IDS else set()
                    queue.append((target, message, everyone - skip))
                app.routed.clear()


class TriggerClashFlood(unittest.TestCase):
    def setUp(self):
        # A fourth desk for this case only: IDS is shared, and other suites assert on its length.
        IDS.append(FOURTH)
        self.addCleanup(IDS.remove, FOURTH)

    def test_three_machines_that_keep_their_trigger_on_a_clash_stop_forwarding(self):
        # Mac 0 chooses f13 as the trigger; PCs 1-3 each hold a jump chord using f13, so each keeps
        # its own trigger and its older stamp, and every copy of the message counts as "taken" again.
        desks = RoutedDesks(self, ("mac", "win", "win", "win"))
        for index in (1, 2, 3):
            peers = desks.apps[index].peers
            peers[0] = dict(peers[0], jump_key="ctrl+f13")
        desks.apps[0]._set_same(True)
        desks.apps[0].routed.clear()
        for one in range(4):
            for other in range(one + 1, 4):
                desks.link(one, other)
        desks.edit(0, trigger_key="f13")


class SliderAndPresetSplit(unittest.TestCase):
    def test_the_latest_pace_choice_survives_a_machine_that_missed_a_length_change(self):
        desks = Desks(self, ("mac", "win"))
        desks.apps[0]._set_same(True)
        desks.apps[0].sent.clear()
        desks.link(0, 1)
        desks.online.discard(1)
        desks.edit(0, effect_length="long")          # pace 2.0 and length long, stamped together
        desks.online.add(1)
        time.sleep(1.1)
        desks.edit(1, effect_pace=1.3)              # later; length on the PC stays "normal", so only pace is stamped
        for index in (0, 1):
            self.assertEqual(desks.apps[index].values()["effect_pace"], 1.3, f"desk {index}")


if __name__ == "__main__":
    unittest.main()
