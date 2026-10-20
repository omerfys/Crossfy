"""Synthetic crossing rows and registers; no desktop imports or real settings."""

import copy
import random
import unittest

from core import protocol, settings_sync, ways

A, B, C, P = [protocol.id_text(bytes([n]) * 16) for n in (1, 2, 3, 4)]


def raw():
    return dict(schema=6, machine_id=A, peers=[dict(id=B, port=24820, send=True,
        allow_drive=True, linked=True, side="right", ways=dict(edge=False, thirds=["start"],
        edges=["left"], corner=False, notch=False))], zones=[],
        layout={A: dict(x=0, y=0, w=160, h=100), B: dict(x=160, y=0, w=160, h=100)})


class ProfilesTests(unittest.TestCase):
    def api(self):
        from core import profiles
        return profiles

    def upgraded(self):
        p = self.api()
        saved, notes = p.before_load(raw(), now=100)
        self.assertIn("upgraded", notes)
        return p.after_load(saved, platform="mac", now=100)[0]

    def test_upgrade_and_normalisation_do_not_lose_raw_ways(self):
        p = self.api()
        original = raw()
        saved, _ = p.before_load(original, now=100)
        self.assertEqual(saved["crossing_own"]["saved"][0]["row"], p.live_row(original))
        saved["peers"][0]["ways"]["notch"] = True
        saved, _ = p.after_load(saved, platform="mac", now=100)
        self.assertEqual(saved["crossing_own"]["row"], p.live_row(saved))
        self.assertNotIn("crossing_own", original)

    def test_reconcile_captures_local_edit_once_and_applied_is_actual(self):
        p = self.api()
        saved = self.upgraded()
        previous = copy.deepcopy(saved["crossing_own"]["row"])
        saved["peers"][0]["ways"]["edge"] = True
        saved, paths = p.reconcile(saved, platform="mac", now=101)
        self.assertTrue(saved["crossing_own"]["row"][B]["ways"]["edge"])
        self.assertEqual(saved["crossing_own"]["applied"], p.live_row(saved))
        self.assertIn(previous, [x["row"] for x in saved["crossing_own"]["saved"]])
        count = len(saved["crossing_own"]["saved"])
        saved["peers"][0]["ways"]["thirds"] = ["end"]
        saved, _ = p.reconcile(saved, platform="mac", now=102)
        self.assertEqual(count, len(saved["crossing_own"]["saved"]))

    def test_edit_while_sending_is_off_is_kept_when_it_is_turned_back_on(self):
        # Review of ccce011e, finding 1: the edit was never captured and was projected over.
        p = self.api()
        saved = self.upgraded()
        saved["peers"].append(dict(id=C, port=24820, send=True, ways={"edge": False}))
        saved["peers"][0]["send"] = False
        saved, _ = p.reconcile(saved, platform="mac", now=101)
        saved["peers"][0]["ways"]["thirds"] = ["end"]
        saved["peers"][0]["notch_return"] = True
        saved, _ = p.reconcile(saved, platform="mac", now=102)
        self.assertEqual(saved["crossing_own"]["row"][B]["ways"]["thirds"], ["end"])
        self.assertTrue(saved["crossing_own"]["row"][B]["notch_return"])
        self.assertFalse(saved["crossing_own"]["row"][C]["ways"]["edge"])
        saved["peers"][0]["send"] = True
        saved, _ = p.reconcile(saved, platform="mac", now=103)
        self.assertEqual(saved["peers"][0]["ways"]["thirds"], ["end"])
        self.assertTrue(saved["peers"][0]["notch_return"])

    def test_edit_while_sending_is_off_in_an_older_beamer_is_kept(self):
        p = self.api()
        saved = self.upgraded()
        saved["peers"][0]["send"] = False
        saved, _ = p.reconcile(saved, platform="mac", now=101)
        saved["peers"][0]["ways"]["thirds"] = ["end"]
        saved, notes = p.before_load(saved, now=102)
        self.assertIn("older_version", notes)
        saved["peers"][0]["send"] = True
        saved, _ = p.after_load(saved, platform="mac", now=102)
        self.assertEqual(saved["peers"][0]["ways"]["thirds"], ["end"])

    def test_a_left_out_machine_never_takes_the_notch_from_one_in_use(self):
        # Review finding 4: row order gave the notch to a left-out machine and cleared the active one's.
        from core import crossing_state
        p = self.api()
        saved = self.upgraded()
        saved["peers"].insert(0, dict(id=C, port=24820, send=True, left_out=True,
                                      ways=dict(edge=False, notch=False)))
        saved, _ = p.reconcile(saved, platform="mac", now=101)
        saved = crossing_state.set_same_ways(saved, True, platform="mac", now=102)["settings"]
        desk = saved["crossing_desk"]
        row = copy.deepcopy(desk["profiles"][p.DESK_ID]["rows"][A]["value"])
        row = {C: row[C], B: row[B]}
        row[C]["ways"]["notch"] = row[B]["ways"]["notch"] = True
        desk["profiles"][p.DESK_ID]["rows"][A] = dict(value=row, set_at=200, by=B)
        saved, _ = p.reconcile(saved, platform="mac", now=201)
        live = {entry["id"]: entry["ways"]["notch"] for entry in saved["peers"]}
        self.assertEqual(live, {C: False, B: True})
        self.assertEqual([zone["peer"] for zone in saved["zones"] if zone.get("kind") == "notch"], [B])
        again, _ = p.reconcile(saved, platform="mac", now=202)
        self.assertEqual(again["peers"], saved["peers"])

    def test_profiles_made_apart_still_merge(self):
        # Review finding 2: two machines each making an eighth profile rejected each other's desk.
        from core import crossing_state
        p = self.api()
        base = self.upgraded()
        base["peers"][0].update(linked=True, allow_drive=True)
        for n in range(6):
            base = crossing_state.new_profile(base, f"P{n}", platform="mac", now=110 + n)["settings"]
        one = crossing_state.new_profile(base, "Mine", platform="mac", now=120)["settings"]
        two = crossing_state.new_profile(base, "Theirs", platform="mac", now=121)["settings"]
        self.assertEqual(len(p.profile_list(one)), 8)
        for frame in p.frames(p.desk_message(two)):
            merged = crossing_state.desk_arrived(one, frame, source=B, platform="mac", now=130)
            self.assertTrue(merged["accepted"], merged["reason"])
            one = merged["settings"]
        self.assertEqual(len(p.profile_list(one)), 9)
        self.assertTrue(all(len(p._json(f)) <= p.MAX_DESK_BYTES for f in p.frames(p.desk_message(one))))

    def test_a_profile_grown_on_two_machines_apart_still_travels_and_merges(self):
        # Re-review, finding 2: whole-profile frames could outgrow the frame bound once merged.
        p = self.api()
        peers = [protocol.id_text(bytes([n]) * 15 + b"\x01") for n in range(10, 42)]
        row = {peer: {"ways": {"edge": True, "thirds": ["start", "middle", "end"], "edges": ["left", "top"],
                               "corner": True, "corner_at": "top_left", "corners": ["top_left", "bottom_right"],
                               "notch": False}, "notch_return": False} for peer in peers}
        machines = [protocol.id_text(bytes([n]) * 15 + b"\x02") for n in range(50, 82)]
        saved = self.upgraded()
        saved["peers"][0].update(linked=True, allow_drive=True)
        rows = {m: dict(value=copy.deepcopy(row), set_at=300 + i, by=B) for i, m in enumerate(machines)}
        desk = {"profiles": {p.DESK_ID: {"rows": rows}}}
        sent = p.frames(desk)
        self.assertGreater(len(sent), 1)
        self.assertTrue(all(len(p._json(frame)) <= p.MAX_DESK_BYTES for frame in sent))
        for frame in sent:
            saved, *_rest, accepted, reason = p.merge_desk(saved, frame, source=B, now=400)
            self.assertTrue(accepted, reason)
        self.assertEqual(set(saved["crossing_desk"]["profiles"][p.DESK_ID]["rows"]) & set(machines), set(machines))
        self.assertLess(p.desk_size(saved), p.MAX_DESK_BYTES)

    def test_making_profiles_prunes_removed_profiles_at_receiver_limit(self):
        from core import crossing_state
        p = self.api()
        saved = self.upgraded()
        for n in range(p.MAX_HELD - 1):
            out = crossing_state.new_profile(saved, f"P{n}", platform="mac", now=500 + 2 * n)
            self.assertTrue(out["accepted"], out["reason"])
            saved = out["settings"]
            pid = next(pid for pid, profile in saved["crossing_desk"]["profiles"].items()
                       if profile.get("name", {}).get("value") == f"P{n}")
            saved = crossing_state.remove_profile(saved, pid, platform="mac", now=501 + 2 * n)["settings"]
        desk = saved["crossing_desk"]
        self.assertEqual(len(desk["profiles"]), p.MAX_HELD)
        self.assertEqual([pid for pid in desk["profiles"] if not p.removed(desk, pid)], [p.DESK_ID])

        out = crossing_state.new_profile(saved, "After cleanup", platform="mac", now=700)
        self.assertTrue(out["accepted"], out["reason"])
        self.assertLessEqual(len(out["settings"]["crossing_desk"]["profiles"]), p.MAX_HELD)

    def test_merging_oversize_tombstone_unions_is_order_independent(self):
        from core import crossing_state
        p = self.api()

        def tombstones(start, count):
            return {protocol.id_text(bytes([n]) * 16): {"removed": {"set_at": n % 10 + 10, "by": B}}
                    for n in range(start, start + count)}

        left = {"profiles": tombstones(10, 40)}
        right = {"profiles": tombstones(60, 40)}
        results = []
        for order in ((left, right), (right, left)):
            saved = self.upgraded()
            saved["peers"][0].update(linked=True, allow_drive=True)
            for state in order:
                saved, *_rest, accepted, reason = p.merge_desk(saved, state, source=B, now=200)
                self.assertTrue(accepted, reason)
            results.append(saved["crossing_desk"]["profiles"])

        self.assertEqual(set(results[0]), set(results[1]))
        self.assertEqual(len(results[0]), p.MAX_HELD)
        self.assertIn(p.DESK_ID, results[0])
        all_tombstones = left["profiles"] | right["profiles"]
        retained = sorted(all_tombstones, key=lambda pid: (
            all_tombstones[pid]["removed"]["set_at"], pid))[-(p.MAX_HELD - 1):]
        self.assertEqual(set(results[0]) - {p.DESK_ID}, set(retained))

    def test_pruning_never_drops_the_active_profile(self):
        p = self.api()
        settings = {"crossing_own": {}, "crossing_desk": {"active": {"value": P}, "profiles": {
            P: {"removed": {"set_at": 0, "by": B}},
            A: {"removed": {"set_at": 1, "by": B}},
            B: {"removed": {"set_at": 2, "by": B}},
        }}}

        p.prune_removed(settings, 2)

        profiles = settings["crossing_desk"]["profiles"]
        self.assertIn(P, profiles)
        self.assertNotIn(A, profiles)
        self.assertIn(B, profiles)
        self.assertEqual(p.pruned(settings), [A])

    def test_a_late_delta_for_a_pruned_profile_does_not_bring_it_back(self):
        # Sol review: Q prunes the oldest tombstone, then that profile's own name arrives late.
        p = self.api()
        ids = [protocol.id_text(bytes([n]) * 16) for n in range(1, 66)]
        oldest, others, q = ids[0], ids[1:63], ids[63]
        tombs = {"profiles": {pid: {"removed": {"set_at": 10 + n, "by": B}}
                              for n, pid in enumerate([oldest, *others])}}
        name = {"profiles": {oldest: {"name": {"value": "Old", "set_at": 5, "by": B}}}}
        new = {"profiles": {q: {"name": {"value": "Q", "set_at": 150, "by": B}}}}
        results = []
        for order in ((tombs, new, name), (tombs, name, new)):
            saved = self.upgraded()
            saved["peers"][0].update(linked=True, allow_drive=True)
            for state in order:
                saved, *_rest, accepted, reason = p.merge_desk(saved, state, source=B, now=200)
                self.assertTrue(accepted, reason)
            results.append(saved["crossing_desk"]["profiles"])
        self.assertEqual(set(results[0]), set(results[1]))
        self.assertNotIn(oldest, results[0])
        self.assertIn(q, results[0])

    def test_a_late_active_register_for_a_pruned_profile_is_rejected(self):
        from core import crossing_state
        p = self.api()
        saved = self.upgraded()
        saved["peers"][0].update(linked=True, allow_drive=True)
        saved["crossing_desk"]["profiles"][p.DESK_ID]["home"]["shake"] = dict(
            value=False, set_at=100, by=A)
        saved = crossing_state.set_same_ways(saved, True, platform="mac", now=100)["settings"]
        made = crossing_state.new_profile(saved, "Q", platform="mac", now=101)
        self.assertTrue(made["accepted"], made["reason"])
        saved = made["settings"]
        q = saved["crossing_desk"]["profiles"].keys() - {p.DESK_ID}
        self.assertEqual(len(q), 1)
        q = q.pop()
        selected = crossing_state.switch_profile(saved, q, platform="mac", now=102)
        self.assertTrue(selected["accepted"], selected["reason"])
        saved = selected["settings"]
        previous = p.DESK_ID
        returned = crossing_state.switch_profile(saved, previous, platform="mac", now=103)
        self.assertTrue(returned["accepted"], returned["reason"])
        saved = crossing_state.remove_profile(returned["settings"], q, platform="mac", now=104)["settings"]

        tombstones = {protocol.id_text(bytes([n]) * 16): {
            "removed": {"set_at": 200 + n, "by": B}}
            for n in range(1, p.MAX_HELD)}
        saved, _, _, _, accepted, reason = p.merge_desk(
            saved, {"profiles": tombstones}, source=B, now=400)
        self.assertTrue(accepted, reason)
        self.assertIn(q, p.pruned(saved))
        self.assertNotIn(q, saved["crossing_desk"]["profiles"])
        before_active = copy.deepcopy(saved["crossing_desk"]["active"])
        before_shake = p.shake_on(saved)

        newer = {"active": {"value": q, "set_at": before_active["set_at"] + 50, "by": B},
                 "profiles": {q: {"name": {"value": "Q", "set_at": 900, "by": B},
                                  "home": {"shake": {"value": False, "set_at": 900, "by": B}}}}}
        merged, _, forward, answer, accepted, reason = p.merge_desk(
            saved, newer, source=B, now=1000)
        self.assertTrue(accepted, reason)
        self.assertEqual(merged["crossing_desk"]["active"]["value"], previous)
        self.assertGreater(merged["crossing_desk"]["active"]["set_at"], newer["active"]["set_at"])
        self.assertNotIn(q, merged["crossing_desk"]["profiles"])
        self.assertEqual(forward["active"]["value"], previous)
        self.assertGreater(forward["active"]["set_at"], newer["active"]["set_at"])
        self.assertEqual(answer["active"]["value"], previous)
        self.assertGreater(answer["active"]["set_at"], newer["active"]["set_at"])
        self.assertEqual(p.shake_on(merged), before_shake)

        older = {"active": {"value": q, "set_at": before_active["set_at"] - 1, "by": B}}
        unchanged, _, _, older_reply, accepted, reason = p.merge_desk(
            saved, older, source=B, now=1001)
        self.assertTrue(accepted, reason)
        self.assertEqual(unchanged["crossing_desk"]["active"], before_active)
        self.assertEqual(older_reply["active"], before_active)

    def test_merge_still_refuses_live_profile_overflow(self):
        p = self.api()
        saved = self.upgraded()
        saved["peers"][0].update(linked=True, allow_drive=True)
        live = {protocol.id_text(bytes([n]) * 16): {
            "name": {"value": f"P{n}", "set_at": n, "by": B}}
            for n in range(1, p.MAX_HELD + 1)}

        result = p.merge_desk(saved, {"profiles": live}, source=B, now=200)

        self.assertFalse(result[4])
        self.assertEqual(result[5], "desk_full")

    def test_notch_from_a_received_row_is_stable_through_events(self):
        # reconcile and _initial must agree, or each event's untick reads as a page edit and is sent.
        from core import crossing_state
        p = self.api()
        saved = self.upgraded()
        saved["peers"].append(dict(id=C, port=24820, send=True, ways=dict(edge=False, notch=False)))
        saved, _ = p.reconcile(saved, platform="mac", now=101)
        saved = crossing_state.set_same_ways(saved, True, platform="mac", now=102)["settings"]
        desk = saved["crossing_desk"]
        row = copy.deepcopy(desk["profiles"][p.DESK_ID]["rows"][A]["value"])
        row[B]["ways"]["notch"] = row[C]["ways"]["notch"] = True
        desk["profiles"][p.DESK_ID]["rows"][A] = dict(value=row, set_at=200, by=B)
        saved, _ = p.reconcile(saved, platform="mac", now=201)
        held = copy.deepcopy(desk["profiles"][p.DESK_ID]["rows"][A])
        for now in (202, 203):
            out = crossing_state.link_up(saved, B, platform="mac", own_displays={}, now=now)
            self.assertEqual(out["settings"]["crossing_desk"]["profiles"][p.DESK_ID]["rows"][A], held)
            self.assertNotIn(("row", p.DESK_ID, A), [tuple(x) for x in out["send_desk"]])
            saved = out["settings"]

    def test_another_machines_row_draws_through_the_same_ledger_reach(self):
        from core import crossing_state
        p = self.api()
        saved = self.upgraded()
        saved["peers"][0].update(linked=True, allow_drive=True, name="PC")
        saved = crossing_state.set_same_ways(saved, True, platform="mac", now=101)["settings"]
        row = {A: {"ways": {"edge": True, "thirds": ["middle"], "edges": [], "corner": False,
                            "corner_at": "top_left", "corners": [], "notch": False}, "notch_return": False}}
        saved["crossing_desk"]["profiles"][p.DESK_ID]["rows"][B] = dict(value=row, set_at=200, by=B)
        view = p.view_settings(saved, B)
        self.assertEqual(view["machine_id"], B)
        self.assertNotIn("token", view["peers"][0])
        self.assertEqual(view["peers"][0]["side"], "left")
        held = ways.ways(view, A)
        self.assertEqual((held["side"], held["parts"]), ("left", ["middle"]))
        sides = ways.reach(view, A, platform=p.view_platform(saved, B))["sides"]
        self.assertEqual(sides["left"]["state"], "contact")
        self.assertEqual(p.tile_word(saved, A, linked=True, caps=()), "Desk")
        self.assertEqual(p.tile_word(saved, B, linked=True, caps=("profiles",)), "Desk")
        self.assertEqual(p.tile_word(saved, B, linked=False, caps=("profiles",)), "Offline")
        self.assertEqual(p.tile_word(saved, B, linked=True, caps=()), "Older")

    def test_same_ways_views_shelf_a_left_out_peer_with_its_stale_tile(self):
        from core import crossing_state
        p = self.api()
        saved = self.upgraded()
        saved["peers"][0].update(linked=True, allow_drive=True, name="Rig", side="left")
        saved["peers"].append(dict(id=C, port=24821, send=True, allow_drive=True, linked=True,
                                   left_out=True, ways=dict(edge=True, thirds=list(ways.PARTS),
                                   edges=[], corner=False, notch=False)))
        saved["layout"] = {
            A: dict(x=-640, y=-50, w=160, h=100),
            B: dict(x=-820, y=-50, w=180, h=112),
            C: dict(x=-800, y=-50, w=160, h=100),
        }
        saved["zones"] = [{"peer": B, "kind": "edge", "side": "left"}]
        own_zones = copy.deepcopy(saved["zones"])
        saved = crossing_state.set_same_ways(saved, True, platform="mac", now=102)["settings"]

        self.assertTrue(next(peer for peer in saved["peers"] if peer["id"] == C)["left_out"])
        self.assertEqual(saved["zones"], own_zones)
        viewed = p.view_settings(saved, B)
        states = ways.compile_layout(viewed, viewed["layout"], platform="mac", now=103)["tiles"]
        self.assertNotEqual(states.get(A, {}).get("state"), "overlap")
        self.assertNotEqual(states.get(B, {}).get("state"), "overlap")
        self.assertEqual(states[C]["state"], "dormant")
        self.assertNotIn(C, p.machines_on_desk(saved))
        self.assertIn(B, p.machines_on_desk(saved))

    def test_received_desk_view_shelves_a_peer_left_out_here(self):
        from core import crossing_state
        p = self.api()
        sender = self.upgraded()
        sender["peers"][0].update(linked=True, allow_drive=True, name="Rig", side="left")
        sender["peers"].append(dict(id=C, port=24821, send=True, allow_drive=True, linked=True,
                                    left_out=True, ways=dict(edge=True, thirds=list(ways.PARTS),
                                    edges=[], corner=False, notch=False)))
        sender["layout"] = {
            A: dict(x=-640, y=-50, w=160, h=100),
            B: dict(x=-820, y=-50, w=180, h=112),
            C: dict(x=-800, y=-50, w=160, h=100),
        }
        sender = crossing_state.set_same_ways(sender, True, platform="mac", now=102)["settings"]
        receiver_raw = copy.deepcopy(raw())
        receiver_raw["machine_id"] = B
        receiver_raw["peers"] = [
            dict(id=A, port=24820, send=True, allow_drive=True, linked=True, side="right",
                 ways=dict(edge=True, thirds=list(ways.PARTS), edges=[], corner=False, notch=False)),
            dict(id=C, port=24821, send=True, allow_drive=True, linked=True, left_out=True,
                 ways=dict(edge=True, thirds=list(ways.PARTS), edges=[], corner=False, notch=False)),
        ]
        receiver_raw["layout"] = {
            B: dict(x=-820, y=-50, w=180, h=112),
            A: dict(x=-640, y=-50, w=160, h=100),
            C: dict(x=-800, y=-50, w=160, h=100),
        }
        receiver, _ = p.before_load(receiver_raw, now=100)
        receiver = p.after_load(receiver, platform="pc", now=101)[0]
        receiver_zones = copy.deepcopy(receiver["zones"])
        received = crossing_state.desk_arrived(
            receiver, p.desk_message(sender), source=A, platform="pc", now=103)["settings"]

        self.assertEqual(received["zones"], receiver_zones)
        viewed = p.view_settings(received, A)
        states = ways.compile_layout(viewed, viewed["layout"], platform="pc", now=104)["tiles"]
        self.assertNotEqual(states.get(A, {}).get("state"), "overlap")
        self.assertNotEqual(states.get(B, {}).get("state"), "overlap")
        self.assertEqual(states[C]["state"], "dormant")
        self.assertTrue(next(peer for peer in received["peers"] if peer["id"] == C)["left_out"])
        self.assertIn(A, p.machines_on_desk(received))
        self.assertNotIn(C, p.machines_on_desk(received))

    def test_no_way_back_ignores_a_shelved_peers_stale_tile(self):
        p = self.api()
        saved = self.upgraded()
        saved["peers"][0].update(linked=True, allow_drive=True, side="left")
        saved["peers"].append(dict(id=C, port=24821, send=True, left_out=True,
                                   ways=dict(edge=True, thirds=list(ways.PARTS), edges=[], corner=False, notch=False)))
        saved["crossing_own"]["row"][B]["ways"].update(edge=True, thirds=list(ways.PARTS))
        from core import crossing_state
        saved = crossing_state.set_same_ways(saved, True, platform="mac", now=102)["settings"]
        remote_row = dict(
            value=p.canonical_row({
                A: {"ways": {"edge": True, "thirds": list(ways.PARTS), "edges": [],
                             "corner": False, "notch": False}},
                C: {"ways": {"edge": True, "thirds": list(ways.PARTS), "edges": [],
                             "corner": False, "notch": False}},
            }),
            set_at=200, by=B)
        saved["crossing_desk"]["profiles"][p.DESK_ID]["rows"][B] = remote_row
        saved["crossing_desk"]["status"][B] = dict(set_at=201, by=B, value={
            "platform": "pc", "app": "1.5.5", "in_force": "desk", "profile": p.DESK_ID,
            "row": [200, B], "waiting": [],
        })
        saved["layout"] = {
            A: dict(x=-640, y=-50, w=160, h=100),
            B: dict(x=-820, y=-50, w=180, h=112),
            C: dict(x=-640, y=-50, w=160, h=100),
        }

        self.assertEqual(p.no_way_back(saved, A), [])

    def test_removal_and_switch_in_either_order_leave_the_same_desk(self):
        # Review finding 3: a removal arriving before the switch away from it was erased.
        p = self.api()
        desk = {"on": dict(value=True, set_at=100, by=B), "active": dict(value=P, set_at=101, by=B),
                "profiles": {p.DESK_ID: {"removed": dict(set_at=102, by=B)},
                             P: {"name": dict(value="Sofa", set_at=99, by=B), "rows": {}, "home": {}}}}
        switch = {"active": desk["active"], "profiles": {P: desk["profiles"][P]}}
        removal = {"profiles": {p.DESK_ID: desk["profiles"][p.DESK_ID]}}
        results = []
        for order in ((switch, removal), (removal, switch)):
            saved = self.upgraded()
            saved["peers"][0].update(linked=True, allow_drive=True)
            for part in order:
                saved, *_rest, accepted, reason = p.merge_desk(saved, part, source=B, now=200)
                self.assertTrue(accepted, reason)
            results.append(saved["crossing_desk"]["profiles"])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][p.DESK_ID]["removed"], dict(set_at=102, by=B))

    def test_old_version_edits_override_without_writing_desk(self):
        p = self.api()
        saved = self.upgraded()
        desk = copy.deepcopy(saved["crossing_desk"])
        saved["peers"][0]["ways"]["edge"] = True
        saved, notes = p.before_load(saved, now=101)
        self.assertIn("older_version", notes)
        self.assertTrue(saved["crossing_own"]["use_own"])
        self.assertEqual(saved["crossing_desk"], desk)

    def test_wire_invalid_row_drops_alone_and_ahead_bound(self):
        p = self.api()
        row = p.live_row(raw())
        invalid = copy.deepcopy(row)
        invalid[B]["ways"]["thirds"] = []
        data = dict(on=False, set_at=0, by="", desk=dict(on=dict(value=True, set_at=700, by=A),
            profiles={p.DESK_ID: dict(rows={A: dict(value=invalid, set_at=1, by=A),
                B: dict(value=row, set_at=2, by=B)})}, status={}))
        parsed = p.read_desk_state(data, now=100)
        self.assertNotIn(A, parsed["profiles"][p.DESK_ID]["rows"])
        self.assertIn(B, parsed["profiles"][p.DESK_ID]["rows"])
        self.assertIn("on", parsed)
        data["desk"]["on"]["set_at"] += 1
        self.assertNotIn("on", p.read_desk_state(data, now=100))

    def test_wire_size_and_capability_and_separate_envelope(self):
        p = self.api()
        data = dict(on=False, set_at=0, by="", layout={"large": "picture"}, design_sync={},
                    desk={"padding": "x" * p.MAX_DESK_BYTES})
        self.assertIsNone(p.read_desk_state(data, now=100))
        self.assertNotIn("desk", settings_sync.for_capabilities(data, ()))
        packet = settings_sync.desk_message_data(data, {"on": {"value": True}})
        self.assertEqual(set(packet), {"on", "set_at", "by", "desk"})

    def test_unreadable_objects_are_kept_aside(self):
        p = self.api()
        saved = raw()
        saved.update(crossing_own=[1], crossing_desk="bad")
        saved, notes = p.before_load(saved, now=100)
        self.assertEqual(saved["crossing_own_unreadable"], [1])
        self.assertEqual(saved["crossing_desk_unreadable"], "bad")
        self.assertIn("upgraded", notes)

    def test_partial_profile_delta_survives_reload(self):
        p = self.api()
        saved = self.upgraded()
        state = {"profiles": {P: {"rows": {C: dict(value={}, set_at=101, by=B)}}}}
        saved, _, _, _, accepted, _ = p.merge_desk(saved, state, source=B, now=101)
        self.assertTrue(accepted)
        loaded, notes = p.before_load(saved, now=102)
        self.assertEqual(notes, [])
        self.assertIn(P, loaded["crossing_desk"]["profiles"])

    def test_bad_nested_register_is_preserved_not_executed(self):
        p = self.api()
        for path in ("on", "status", "row", "active"):
            with self.subTest(path=path):
                saved = self.upgraded()
                desk = saved["crossing_desk"]
                if path in ("on", "active"):
                    desk[path]["set_at"] = "bad"
                elif path == "status":
                    desk["status"][A]["set_at"] = "bad"
                else:
                    desk["profiles"][p.DESK_ID]["rows"][A] = dict(value={}, set_at="bad", by=A)
                loaded, notes = p.before_load(saved, now=102)
                self.assertIn("upgraded", notes)
                self.assertIn("crossing_desk_unreadable", loaded)
                p.after_load(loaded, platform="pc", now=102)

    def test_gap_fill_does_not_consume_first_edit_archive(self):
        p = self.api()
        saved = self.upgraded()
        saved["peers"].append(dict(id=C, port=24820, send=True, ways={"edge": False}))
        saved, _ = p.reconcile(saved, platform="mac", now=101)
        before_edit = copy.deepcopy(saved["crossing_own"]["row"])
        saved["peers"][0]["ways"]["edge"] = True
        saved, _ = p.reconcile(saved, platform="mac", now=102)
        self.assertIn(before_edit, [item["row"] for item in saved["crossing_own"]["saved"]])

    def test_register_merge_forward_answer_tie_and_no_echo(self):
        p = self.api()
        saved = self.upgraded()
        pid = p.DESK_ID
        state = {"profiles": {pid: {"rows": {A: dict(value=p.live_row(saved), set_at=101, by=B)}}}}
        saved, _, forward, answer, accepted, _ = p.merge_desk(saved, state, source=B, now=101)
        self.assertTrue(accepted)
        self.assertEqual(forward, state)
        self.assertEqual(answer, {})
        same, paths, forward, answer, _, _ = p.merge_desk(saved, state, source=B, now=101)
        self.assertEqual((paths, forward, answer), ([], {}, {}))
        older = copy.deepcopy(state)
        older["profiles"][pid]["rows"][A]["by"] = A
        _, _, forward, answer, _, _ = p.merge_desk(saved, older, source=B, now=101)
        self.assertEqual(forward, {})
        self.assertEqual(answer, state)
        newer = copy.deepcopy(state)
        newer["profiles"][pid]["rows"][A]["by"] = C
        newer["profiles"][pid]["rows"][A]["value"][B]["ways"]["edge"] = True
        saved, _, forward, _, _, _ = p.merge_desk(saved, newer, source=B, now=101)
        self.assertEqual(forward, newer)
        self.assertEqual(saved["crossing_own"]["saved"][-1]["why"], "replaced_by")

    def test_duplicate_delivery_keeps_a_pending_local_edit_and_does_not_echo_again(self):
        from core import crossing_state as events
        from unittest import mock
        p = self.api()
        saved = events.set_same_ways(self.upgraded(), True, platform="mac", now=101)["settings"]
        incoming = p.desk_message(saved)
        saved["peers"][0]["ways"]["thirds"] = ["end"]
        before = copy.deepcopy(saved)

        out = events.desk_arrived(saved, incoming, source=B, platform="mac", now=102)
        self.assertEqual(saved, before, "receiving must not mutate the caller's settings")
        self.assertEqual(p.in_force(out["settings"])[0][B]["ways"]["thirds"], ["end"])
        self.assertIn(("row", p.DESK_ID, A), out["send_desk"])
        self.assertEqual(out["answer"]["profiles"][p.DESK_ID]["rows"][A]["value"][B]["ways"]["thirds"],
                         ["end"])
        settled = out["settings"]
        with mock.patch.object(p, "reconcile", wraps=p.reconcile) as reconcile:
            again = events.desk_arrived(settled, p.desk_message(settled), source=B, platform="mac", now=103)
        self.assertLessEqual(reconcile.call_count, 1, "a duplicate must not repeat the full projection")
        self.assertFalse(again["changed"])
        self.assertEqual((again["send_desk"], again["forward"], again["answer"]), ([], {}, {}))
        again["settings"]["peers"][0]["ways"]["thirds"].append("start")
        self.assertEqual(p.live_row(settled)[B]["ways"]["thirds"], ["end"])

    def test_reconciled_holds_exactly_where_reconcile_would_change_nothing(self):
        from core import crossing_state as events
        p = self.api()
        settled = events.set_same_ways(self.upgraded(), True, platform="mac", now=101)["settings"]

        def variant(change):
            changed = copy.deepcopy(settled)
            change(changed)
            return changed

        cases = {
            "settled": settled,
            "a pending local edit": variant(lambda s: s["peers"][0]["ways"].update(thirds=["end"])),
            "notch_return missing": variant(lambda s: s["peers"][0].pop("notch_return")),
            "applied missing": variant(lambda s: s["crossing_own"].pop("applied")),
            "a new machine": variant(lambda s: s["peers"].append(
                dict(id=C, port=24820, send=True, ways={"edge": False}))),
            "own row missing": variant(lambda s: s["crossing_desk"]["profiles"][p.DESK_ID]["rows"].pop(A)),
            "an older app in status": variant(
                lambda s: s["crossing_desk"]["status"][A]["value"].update(app="1.5.4")),
            "own ways in force": variant(lambda s: s["crossing_own"].update(use_own=True)),
            "sync off": variant(lambda s: s["crossing_desk"]["on"].update(value=False)),
        }
        for platform in ("mac", "pc"):
            for name, settings in cases.items():
                with self.subTest(name, platform=platform):
                    before = copy.deepcopy(settings)
                    again, paths = p.reconcile(settings, platform=platform, now=102)
                    self.assertEqual(p.reconciled(settings, platform=platform),
                                     again == settings and paths == [])
                    self.assertEqual(settings, before)
        self.assertTrue(p.reconciled(settled, platform="mac"))

    def test_a_merge_that_takes_nothing_lends_the_settings_back(self):
        from core import crossing_state as events
        p = self.api()
        settled = events.set_same_ways(self.upgraded(), True, platform="mac", now=101)["settings"]
        held = p.desk_message(settled)
        stale, newer = copy.deepcopy(held), copy.deepcopy(held)
        stale["profiles"][p.DESK_ID]["rows"][A]["set_at"] -= 1
        newer["profiles"][p.DESK_ID]["rows"][A].update(set_at=held["profiles"][p.DESK_ID]["rows"][A]["set_at"] + 1,
                                                      by=B)
        for name, state in (("duplicate", held), ("stale", stale), ("newer", newer)):
            with self.subTest(name):
                before = copy.deepcopy(settled)
                lent = p.merge_desk(settled, state, source=B, now=102, borrow=True)
                copied = p.merge_desk(settled, state, source=B, now=102)
                self.assertEqual(settled, before, "merging must not mutate the caller's settings")
                self.assertEqual(lent, copied)
                self.assertIsNot(copied[0], settled)
                self.assertEqual(lent[0] is settled, name != "newer")
        self.assertTrue(lent[2], "the newer row is forwarded")
        self.assertTrue(p.merge_desk(settled, stale, source=B, now=102, borrow=True)[3], "the stale row is answered")

    def test_active_removal_is_void_and_other_tombstones_survive(self):
        p = self.api()
        saved = self.upgraded()
        saved["crossing_desk"]["profiles"][P] = copy.deepcopy(saved["crossing_desk"]["profiles"][p.DESK_ID])
        state = {"profiles": {pid: {"removed": dict(set_at=101, by=B)} for pid in (P, p.DESK_ID)}}
        saved, _, forward, _, _, _ = p.merge_desk(saved, state, source=B, now=101)
        # The active profile's tombstone is kept, so every machine holds the same desk, but is void.
        self.assertEqual(saved["crossing_desk"]["profiles"][p.DESK_ID]["removed"]["set_at"], 101)
        self.assertFalse(p.removed(saved["crossing_desk"], p.DESK_ID))
        self.assertTrue(p.removed(saved["crossing_desk"], P))
        self.assertIn(p.DESK_ID, forward["profiles"])

    def test_stale_switch_on_never_reseeds_a_live_desk(self):
        from core import crossing_state as events
        p = self.api()
        saved = events.set_same_ways(self.upgraded(), True, platform="mac", now=101)["settings"]
        saved = events.edit_ways(saved, B, edge=True, platform="mac", now=102, live=None, gone=None)["settings"]
        held = copy.deepcopy(saved["crossing_desk"]["profiles"][p.DESK_ID]["rows"][A])
        state = {"on": dict(value=True, set_at=200, by=B)}
        out = events.desk_arrived(saved, state, source=B, platform="mac", now=200)
        self.assertEqual(out["settings"]["crossing_desk"]["profiles"][p.DESK_ID]["rows"][A], held)

    def test_sync_off_keeps_live_and_then_on_keeps_it_again(self):
        from core import crossing_state as events
        p = self.api()
        saved = events.set_same_ways(self.upgraded(), True, platform="mac", now=101)["settings"]
        saved = events.edit_ways(saved, B, edge=True, platform="mac", now=102, live=None, gone=None)["settings"]
        before = p.live_row(saved)
        for enabled in (False, True):
            saved = events.set_same_ways(saved, enabled, platform="mac", now=103)["settings"]
            self.assertEqual(p.live_row(saved), before)
        self.assertTrue(any(item["why"] == "sync_off" for item in saved["crossing_own"]["saved"]))

    def test_notch_resolution_uses_peer_order_and_nonmac_ignores_it(self):
        p = self.api()
        saved = self.upgraded()
        saved["peers"].append(dict(id=C, port=24820, send=True, ways={"edge": False}))
        row = p.live_row(saved)
        row[B]["ways"]["notch"] = row[C]["ways"]["notch"] = True
        saved["crossing_own"]["row"] = {C: row[C], B: row[B]}
        saved["crossing_own"]["applied"] = p.live_row(saved)
        saved, _ = p.reconcile(saved, platform="mac", now=101)
        # The receiving machine's peer order decides, as for corners (spec section 4), not row order.
        self.assertTrue(p.live_row(saved)[B]["ways"]["notch"])
        self.assertFalse(p.live_row(saved)[C]["ways"]["notch"])
        self.assertEqual([zone["peer"] for zone in saved["zones"] if zone.get("kind") == "notch"], [B])
        saved, _ = p.reconcile(saved, platform="pc", now=102)
        self.assertFalse(any(entry["ways"]["notch"] for entry in p.live_row(saved).values()))
        self.assertEqual(saved["crossing_own"]["applied"], p.live_row(saved))

    def test_invalid_status_missing_field_is_dropped_alone(self):
        p = self.api()
        saved = self.upgraded()
        status = copy.deepcopy(saved["crossing_desk"]["status"][A])
        status["value"].pop("row")
        parsed = p.read_desk_state(dict(on=False, set_at=0, by="", desk={"status": {A: status}}), 101)
        self.assertEqual(parsed, {})

    def test_no_way_back_checks_actual_contacts_and_permissions(self):
        p = self.api()
        saved = self.upgraded()
        saved["crossing_own"]["row"][B]["ways"].update(edge=True, edges=[])
        # The target has a return edge enabled, but its chosen third misses the contact.
        back = p.canonical_row({A: {"ways": {"edge": True, "thirds": ["end"]}}})
        saved["crossing_desk"]["profiles"][p.DESK_ID]["rows"][B] = dict(value=back, set_at=1, by=B)
        saved["layout"][B] = dict(x=160, y=0, w=160, h=300)
        self.assertEqual(p.no_way_back(saved, A), [B])
        saved["layout"][B]["x"] = 400
        self.assertEqual(p.no_way_back(saved, A), [])
        saved["layout"][B]["x"] = 160
        saved["peers"][0]["send"] = False
        self.assertEqual(p.no_way_back(saved, A), [])

    def test_no_way_back_does_not_warn_about_machines_it_knows_nothing_of(self):
        # Critique: with Same ways off, and for an older Beamer, every peer was listed.
        p = self.api()
        saved = self.upgraded()
        saved["crossing_own"]["row"][B]["ways"].update(edge=True, edges=[])
        saved["layout"][B] = dict(x=160, y=0, w=160, h=100)
        self.assertEqual(p.no_way_back(saved, A), [])

    def test_active_delta_before_profile_name_converges_after_metadata_arrives(self):
        p = self.api()
        saved = self.upgraded()
        active = {"active": dict(value=P, set_at=101, by=B)}
        saved, _, _, _, _, _ = p.merge_desk(saved, active, source=B, now=101)
        metadata = {"profiles": {P: dict(name=dict(value="Sofa", set_at=100, by=B),
                                         home={"shake": dict(value=True, set_at=100, by=B)}, rows={})}}
        saved, _, _, _, _, _ = p.merge_desk(saved, metadata, source=B, now=102)
        self.assertEqual(saved["crossing_desk"]["active"]["value"], P)
        saved, notes = p.before_load(saved, now=103)
        self.assertEqual(notes, [])

    def test_rows_never_copy_credentials_permissions_or_addresses(self):
        p = self.api()
        saved = raw()
        saved["peers"][0].update(token="synthetic", host="192.0.2.1", send=True, allow_drive=True)
        self.assertEqual(set(p.row_entry(saved, B)), {"ways", "notch_return"})
        row = p.canonical_row({B: {**saved["peers"][0], "notch_return": True}})
        self.assertEqual(set(row[B]), {"ways", "notch_return"})

    def test_status_stamps_only_change_with_value_and_edits_floor_above_on(self):
        from core import crossing_state as events
        p = self.api()
        saved = self.upgraded()
        twice, paths = p.reconcile(saved, platform="mac", now=200)
        self.assertEqual(twice, saved)
        self.assertEqual(paths, [])
        saved = events.set_same_ways(saved, True, platform="mac", now=200)["settings"]
        saved = events.edit_ways(saved, B, edge=True, platform="mac", now=150, live=None, gone=None)["settings"]
        desk = saved["crossing_desk"]
        self.assertGreater(desk["profiles"][p.DESK_ID]["rows"][A]["set_at"], desk["on"]["set_at"])

    def test_caller_version_survives_event_reconciliation(self):
        from core import crossing_state as events
        p = self.api()
        saved, _ = p.reconcile(self.upgraded(), platform="mac", now=101, app="1.5.4-test")
        saved = events.set_same_ways(saved, True, platform="mac", now=102)["settings"]
        self.assertEqual(saved["crossing_desk"]["status"][A]["value"]["app"], "1.5.4-test")

    def test_archive_deduplicates_content_keeping_latest_attribution(self):
        p = self.api()
        saved = self.upgraded()
        row = saved["crossing_own"]["row"]
        p.archive(saved, row, "restored", 200, by=B)
        self.assertEqual(len(saved["crossing_own"]["saved"]), 1)
        self.assertEqual(saved["crossing_own"]["saved"][0]["at"], 200)
        self.assertEqual(saved["crossing_own"]["saved"][0]["by"], B)

    def test_profile_limit_and_whole_oversize_receipt(self):
        from core import crossing_state as events
        p = self.api()
        saved = self.upgraded()
        for n in range(7):
            out = events.new_profile(saved, f"Place {n}", platform="mac", now=101 + n)
            self.assertTrue(out["accepted"])
            saved = out["settings"]
        out = events.new_profile(saved, "Ninth", platform="mac", now=110)
        self.assertFalse(out["accepted"])
        self.assertEqual(out["reason"], "desk_full")
        self.assertEqual(out["settings"], saved)
        state = {"padding": "x" * p.MAX_DESK_BYTES, "on": dict(value=True, set_at=110, by=B)}
        out = events.desk_arrived(saved, state, source=B, platform="mac", now=110)
        self.assertFalse(out["accepted"])
        self.assertEqual(out["settings"], saved)

    def test_removed_peer_repair_uses_kept_ways_without_permissions(self):
        p = self.api()
        saved = self.upgraded()
        wanted = copy.deepcopy(saved["crossing_own"]["row"][B])
        saved["peers"] = []
        saved, _ = p.reconcile(saved, platform="mac", now=101)
        self.assertEqual(saved["crossing_own"]["row"][B], wanted)
        saved["peers"] = [dict(id=B, port=24820, send=True, allow_drive=False, ways={"edge": True})]
        saved, _ = p.reconcile(saved, platform="mac", now=102)
        self.assertEqual(p.row_entry(saved, B), wanted)
        self.assertFalse(saved["peers"][0]["allow_drive"])

    def test_return_warning_uses_the_profile_reported_in_force(self):
        p = self.api()
        saved = self.upgraded()
        saved["crossing_own"]["row"][B]["ways"].update(edge=True, edges=[])
        desk = saved["crossing_desk"]
        back = p.canonical_row({A: {"ways": {"edge": True}}})
        desk["profiles"][p.DESK_ID]["rows"][B] = dict(value=back, set_at=10, by=B)
        desk["profiles"][P] = dict(rows={B: dict(value={}, set_at=11, by=B)}, home={})
        desk["status"][B] = dict(set_at=12, by=B, value=dict(platform="pc", in_force="desk", profile=P, row=[11, B]))
        self.assertEqual(p.no_way_back(saved, A), [B])
        desk["status"][B]["value"]["in_force"] = "own"
        self.assertEqual(p.no_way_back(saved, A), [])

    def test_two_machines_seed_different_ways_and_converge(self):
        from core import crossing_state as events
        p = self.api()
        a = self.upgraded()
        b = raw()
        b["machine_id"], b["peers"][0]["id"] = B, A
        b["peers"][0]["ways"].update(edge=True, thirds=["end"], edges=[])
        b, _ = p.before_load(b, now=100)
        b, _ = p.after_load(b, platform="pc", now=100)
        a_live, b_live = p.live_row(a), p.live_row(b)
        a = events.set_same_ways(a, True, platform="mac", now=101)["settings"]
        arrival = events.desk_arrived(b, p.desk_message(a), source=A, platform="pc", now=102)
        b = arrival["settings"]
        a = events.desk_arrived(a, p.desk_message(b), source=B, platform="mac", now=103)["settings"]
        self.assertEqual(p.live_row(a), a_live)
        self.assertEqual(p.live_row(b), b_live)
        self.assertEqual(a["crossing_desk"]["profiles"], b["crossing_desk"]["profiles"])
        for own, state in ((A, a), (B, b)):
            self.assertIn(own, state["crossing_desk"]["profiles"][p.DESK_ID]["rows"])

    def test_offline_row_edit_wins_seed_but_waits_for_local_override(self):
        from core import crossing_state as events
        p = self.api()
        saved = self.upgraded()
        own = copy.deepcopy(saved["crossing_own"]["row"])
        wanted = copy.deepcopy(own)
        wanted[B]["ways"]["edge"] = True
        state = {"on": dict(value=True, set_at=101, by=B), "profiles": {p.DESK_ID: {
            "rows": {A: dict(value=wanted, set_at=102, by=B)}}}}
        saved = events.set_own_ways(saved, True, platform="mac", now=100)["settings"]
        saved = events.desk_arrived(saved, state, source=B, platform="mac", now=604900)["settings"]
        self.assertEqual(p.live_row(saved), own)
        self.assertEqual(saved["crossing_desk"]["profiles"][p.DESK_ID]["rows"][A]["value"], wanted)
        saved = events.set_own_ways(saved, False, platform="mac", now=604901)["settings"]
        self.assertEqual(p.live_row(saved), wanted)
        self.assertEqual(saved["crossing_own"]["row"], own)

    def test_offline_profile_switch_and_recreated_identity_do_not_reuse_old_row(self):
        from core import crossing_state as events
        p = self.api()
        saved = events.set_same_ways(self.upgraded(), True, platform="mac", now=101)["settings"]
        old = copy.deepcopy(p.in_force(saved)[0])
        wanted = copy.deepcopy(old)
        wanted[B]["ways"]["thirds"] = ["end"]
        profile = dict(name=dict(value="Sofa", set_at=102, by=B), removed=None,
                       home={"shake": dict(value=True, set_at=102, by=B)},
                       rows={A: dict(value=wanted, set_at=103, by=B)})
        state = {"active": dict(value=P, set_at=104, by=B), "profiles": {P: profile}}
        saved = events.desk_arrived(saved, state, source=B, platform="mac", now=604900)["settings"]
        self.assertEqual(p.live_row(saved), wanted)
        self.assertIn(old, [item["row"] for item in saved["crossing_own"]["saved"]])
        fresh = raw()
        fresh["machine_id"] = C
        fresh, _ = p.before_load(fresh, now=604900)
        fresh, _ = p.after_load(fresh, platform="mac", now=604900)
        new_live = p.live_row(fresh)
        fresh = events.desk_arrived(fresh, p.desk_message(saved), source=B, platform="mac", now=604901)["settings"]
        self.assertEqual(p.live_row(fresh), new_live)
        self.assertEqual(fresh["crossing_desk"]["profiles"][P]["rows"][A]["value"], wanted)

    def test_seeded_state_transitions_preserve_replaced_rows_and_projection(self):
        """Archive boundaries, rather than intermediate edits in one editing session."""
        from core import crossing_state as events
        p = self.api()
        rng = random.Random(154)
        saved = self.upgraded()
        protected = []
        choices = ("remote", "same", "own", "profile", "switch", "remove", "older", "pair", "edit")
        peer = copy.deepcopy(saved["peers"][0])
        for step in range(160):
            now = 1000 + step * 65 + rng.randint(-30, 30)
            operation = rng.choice(choices)
            before = copy.deepcopy(p.in_force(saved)[0])
            if operation == "edit" and saved["peers"]:
                key = saved["crossing_desk"]["active"]["value"] if p.in_force(saved)[1] else "own"
                if not saved["crossing_own"].get("editing", {}).get(key):
                    protected.append(before)
                saved = events.edit_ways(saved, B, edge=bool(rng.randrange(2)), thirds=[rng.choice(ways.PARTS)],
                    platform="mac", live=None, gone=None, now=now)["settings"]
            elif operation == "remote" and saved["peers"]:
                pid = saved["crossing_desk"]["active"]["value"]
                held = saved["crossing_desk"]["profiles"][pid]["rows"].get(A)
                if held:
                    protected.append(copy.deepcopy(held["value"]))
                row = p.live_row(raw())
                row[B]["ways"]["thirds"] = [rng.choice(ways.PARTS)]
                state = {"profiles": {pid: {"rows": {A: dict(value=row, set_at=now, by=B)}}}}
                saved = events.desk_arrived(saved, state, source=B, platform="mac", now=now)["settings"]
            elif operation == "same":
                protected.append(copy.deepcopy(saved["crossing_own"]["row"]))
                saved = events.set_same_ways(saved, not p.same_ways_on(saved), platform="mac", now=now)["settings"]
            elif operation == "own":
                saved = events.set_own_ways(saved, not saved["crossing_own"]["use_own"], platform="mac", now=now)["settings"]
            elif operation == "profile":
                saved = events.new_profile(saved, "Place", platform="mac", now=now)["settings"]
            elif operation in ("switch", "remove"):
                ids = [item["id"] for item in p.profile_list(saved)]
                method = events.switch_profile if operation == "switch" else events.remove_profile
                saved = method(saved, rng.choice(ids), platform="mac", now=now)["settings"]
            elif operation == "older" and saved["peers"]:
                protected.append(copy.deepcopy(saved["crossing_own"]["row"]))
                saved["peers"][0]["ways"]["edge"] = not saved["peers"][0]["ways"]["edge"]
                saved, _ = p.before_load(saved, now=now)
                saved, _ = p.after_load(saved, platform="mac", now=now)
            elif operation == "pair":
                saved["peers"] = [] if saved["peers"] else [copy.deepcopy(peer)]
                saved, _ = p.reconcile(saved, platform="mac", now=now)
            available = [saved["crossing_own"]["row"], p.live_row(saved)]
            available += [item["row"] for item in saved["crossing_own"]["saved"]]
            available += [profile["rows"][A]["value"] for profile in saved["crossing_desk"]["profiles"].values()
                          if A in profile.get("rows", {})]
            for row in protected:
                self.assertIn(row, available, (step, operation))
            self.assertEqual(saved["crossing_own"]["applied"], p.live_row(saved), (step, operation))


if __name__ == "__main__":
    unittest.main()
