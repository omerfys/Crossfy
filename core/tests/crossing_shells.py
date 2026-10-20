"""Thin headless shells for the crossing model, shared by both desktop platforms.

Every crossing event calls core.crossing_state and carries out its Outcome. AppKit and Qt
are absent; the only platform difference is the platform argument supplied to the core.
The harness uses real responders, owners and wire messages beneath these shells.
"""

import copy
import json
import threading
import time
import traceback

from core import crossing_state, profiles, protocol, return_edge, settings_sync, ways

SNAP_RADIUS = 12


class Shell:
    platform = None

    def __init__(self, desk):
        self.desk = desk
        self.sent_count = 0
        self.handled_count = 0
        self.lock = threading.RLock()
        self.refused = []
        self.refused_desks = []
        self.skew = 0
        self.frames = []
        self.errors = []
        callbacks = desk.machine.responder._callbacks
        callbacks["arrangement"] = self._arrangement_arrived
        callbacks["settings"] = self._settings_arrived

    def busy(self):
        return False

    def live(self, peer):
        return peer in self.desk.hand.links

    def gone(self, peer):
        return False

    def capable(self):
        return {peer for peer, caps in self.desk.hand.capabilities.items() if "layout" in caps} | {self.desk.id}

    def current(self):
        return copy.deepcopy(self.desk.settings)

    def now(self):
        """This machine's clock, `skew` seconds off the real one."""
        return time.time() + self.skew

    def _args(self):
        return dict(platform=self.platform, live=self.live, gone=self.gone, now=self.now())

    def _send(self, peer, message):
        if self.desk.hand.send(peer, message):
            self.sent_count += 1
            data = message.get("data") or {}
            self.frames.append({"peer": peer, "type": message.get("type"), "desk": "desk" in data,
                                "size": len(json.dumps(message, separators=(",", ":")).encode("utf-8"))})
            return True
        return False

    # Desk sync, as the 1.5.5 apps do it. A desk that does not advertise `profiles` keeps
    # the 1.5.3 behaviour: no crossing_own, nothing sent or taken.

    def profile_aware(self):
        return self.desk.profiles

    def load(self, settings):
        """The apps' load path: profiles.before_load, the app's normalisation (the PC's
        crossing_state.migrate), profiles.after_load."""
        saved, _ = profiles.before_load(settings, now=self.now())
        saved = crossing_state.migrate(saved, self.platform)["settings"]
        saved, _ = profiles.after_load(saved, platform=self.platform, now=self.now())
        settings.clear()
        settings.update(saved)

    def profile_peers(self, exclude=None):
        """Linked peers that advertise `profiles`, never `exclude`."""
        return [peer for peer in self.desk.hand.links if peer != exclude
                and "profiles" in self.desk.hand.capabilities.get(peer, ())]

    def send_desk(self, peers, desk):
        if not desk:
            return
        envelope = settings_sync.message_data(False, self.current().get("same_set_at", 0), {}, by=self.desk.id)
        frames = profiles.frames(desk)
        for peer in peers:
            for frame in frames:
                self._send(peer, protocol.settings_msg(settings_sync.desk_message_data(envelope, frame)))

    def send_desk_outcome(self, outcome, source=None):
        if not self.profile_aware():
            return
        if outcome["send_desk"]:
            self.send_desk(self.profile_peers(), profiles.desk_message(outcome["settings"], outcome["send_desk"]))
        if outcome["forward"]:
            self.send_desk(self.profile_peers(exclude=source), outcome["forward"])
        if outcome["answer"] and source is not None and source in self.profile_peers():
            self.send_desk([source], outcome["answer"])

    def _arrangement_arrived(self, peer, read):
        try:
            with self.lock:
                self.on_arrangement(protocol.id_text(peer), read)
        except Exception:
            self.errors.append(traceback.format_exc())
            raise
        finally:
            self.handled_count += 1

    def _settings_arrived(self, peer, data):
        try:
            with self.lock:
                self.on_settings(protocol.id_text(peer), data)
        except Exception:
            self.errors.append(traceback.format_exc())
            raise
        finally:
            self.handled_count += 1

    def carry_out(self, outcome, source=None, arrived=None):
        if outcome["changed"]:
            self.desk.save(outcome["settings"])
        for peer in outcome["tell"]:
            self.tell(peer)
        if outcome["send_picture"]:
            self.send_same()
        if outcome["forward_picture"] and arrived is not None:
            self.send_same(exclude=source, data=arrived)
        self.send_desk_outcome(outcome, source)
        if outcome["changed"]:
            self.after_change()
        return outcome

    def paired(self, settings):
        outcome = crossing_state.paired(settings, platform=self.platform,
                                       own_displays=self.desk.screen.display_map(), now=self.now())
        settings.clear()
        settings.update(outcome["settings"])
        if self.profile_aware():
            self.load(settings)

    def same_state(self):
        settings = self.current()
        tiles = copy.deepcopy(settings.get("layout", {}))
        for entry in settings.get("peers", []):
            tile = tiles.get(entry.get("id"))
            if isinstance(tile, dict) and entry.get("name", "").strip():
                tile["name"] = entry["name"].strip()[:64]
        state = {"set_at": settings.get("layout_set_at", 0),
                 "by": settings.get("layout_by") or self.desk.id, "tiles": tiles}
        return settings_sync.message_data(False, settings.get("same_set_at", 0), {},
                                          by=self.desk.id, layout_state=state)

    def send_same(self, exclude=None, data=None):
        data = self.same_state() if data is None else data
        for peer in list(self.desk.hand.links):
            if peer != exclude and peer in self.capable():
                self._send(peer, protocol.settings_msg(data))

    def link_up(self, other):
        with self.lock:
            outcome = crossing_state.link_up(self.current(), other.id, platform=self.platform,
                         own_displays=self.desk.screen.display_map(), now=self.now(), capable=self.capable())
            self.carry_out(outcome)
            if self.profile_aware() and other.id in self.profile_peers():
                self.send_desk([other.id], profiles.desk_message(self.current()))

    def tell(self, peer):
        settings = self.current()
        entry = ways._entry(settings, peer)
        if entry is None or entry.get("side") not in return_edge.EDGES:
            return
        author = protocol.read_id(entry.get("side_by")) or self.desk.own
        self._send(peer, protocol.arrangement_v6(
            entry["side"], int(entry.get("side_set_at", 0)), author,
            way_back=ways.has_way(settings, peer),
            way_back_by=protocol.read_id(ways.way_back_by(settings, peer))))

    def after_change(self):
        server = self.desk.machine.responder
        server.peers_changed()
        server.rearm()

    def stop(self):
        pass

    def drop(self, moved, x, y, snap=True):
        with self.lock:
            settings = self.current()
            tiles = copy.deepcopy(settings["layout"])
            tile = tiles.get(moved.id, dict(w=moved.tile_size[0], h=moved.tile_size[1]))
            tiles[moved.id] = dict(tile, x=int(x), y=int(y))
            outcome = crossing_state.drop(settings, tiles, moved.id, capable=self.capable(),
                                          snap_radius=SNAP_RADIUS if snap else 0, **self._args())
            if not outcome["accepted"]:
                self.refused.append(moved.id)
                return False
            self.carry_out(outcome)
            return True

    def edit(self, other, methods, parts=None, corner=None, *, edges=None, corners=None):
        with self.lock:
            settings = self.current()
            held = ways.ways(settings, other.id)
            thirds = list(ways.PARTS) if "edge" in methods else (parts if parts is not None else held["parts"])
            outcome = crossing_state.edit_ways(settings, other.id, edge=bool(set(methods) & {"edge", "part"}),
                         thirds=thirds, edges=edges, corners=corners,
                         corner="corner" in methods if corners is None else None, corner_at=corner,
                         notch="notch" in methods, capable=self.capable(), **self._args())
            self.carry_out(outcome)
            return True

    def pick_third(self, other, third):
        return self.click_third(other, third)

    def click_third(self, other, third):
        with self.lock:
            settings = self.current()
            held = ways.ways(settings, other.id)
            if ways._entry(settings, other.id).get("left_out") or held["side"] not in ways.EDGES:
                return False
            methods, parts = ways.toggle_third(held["methods"], held["parts"], third)
            outcome = crossing_state.edit_ways(settings, other.id,
                         edge=bool(set(methods) & {"edge", "part"}), thirds=parts,
                         capable=self.capable(), **self._args())
            self.carry_out(outcome)
            return True

    def click_edge_text(self, other):
        with self.lock:
            settings = self.current()
            if ways._entry(settings, other.id).get("left_out"):
                return False
            held = ways.ways(settings, other.id)
            methods, parts = ways.toggle_edge(held["methods"], held["parts"])
            outcome = crossing_state.edit_ways(settings, other.id,
                         edge=bool(set(methods) & {"edge", "part"}), thirds=parts,
                         capable=self.capable(), **self._args())
            self.carry_out(outcome)
            return True

    def click_corner(self, other, corner):
        with self.lock:
            settings = self.current()
            if (ways._entry(settings, other.id).get("left_out")
                    or ways.corner_holder(settings, corner, exclude=other.id) is not None):
                return False
            held = ways.ways(settings, other.id)
            on = not ("corner" in held["methods"] and held["corner"] == corner)
            outcome = crossing_state.edit_ways(settings, other.id, corner=on, corner_at=corner,
                                             capable=self.capable(), **self._args())
            self.carry_out(outcome)
            return True

    def leave_out(self, other):
        with self.lock:
            return self.carry_out(crossing_state.leave_out(self.current(), other.id,
                                                         capable=self.capable(), **self._args()))

    def put_back(self, other):
        with self.lock:
            return self.carry_out(crossing_state.put_back(self.current(), other.id,
                                                        capable=self.capable(), **self._args()))

    # What a person does on the Crossing page's profile controls.

    def _desk_event(self, event, *args, capable=True, **kwargs):
        with self.lock:
            kwargs.update(platform=self.platform, now=self.now())
            if capable:
                kwargs.update(capable=self.capable(), live=self.live, gone=self.gone)
            outcome = event(self.current(), *args, **kwargs)
            self.carry_out(outcome)
            return outcome

    def same_ways(self, on):
        return self._desk_event(crossing_state.set_same_ways, bool(on))

    def own_ways(self, use_own):
        return self._desk_event(crossing_state.set_own_ways, bool(use_own))

    def edit_other(self, machine, peer, **choices):
        return self._desk_event(crossing_state.edit_other, getattr(machine, "id", machine),
                                getattr(peer, "id", peer), capable=False, **choices)

    def new_profile(self, name):
        return self._desk_event(crossing_state.new_profile, name, capable=False)

    def switch_profile(self, profile_id):
        return self._desk_event(crossing_state.switch_profile, profile_id)

    def displays_changed(self):
        with self.lock:
            return self.carry_out(crossing_state.displays_changed(self.current(), platform=self.platform,
                                 own_displays=self.desk.screen.display_map(), now=self.now(),
                                 capable=self.capable()))

    def on_arrangement(self, peer, read):
        outcome = crossing_state.receive_arrangement(self.current(), peer, read,
                                                     capable=self.capable(), **self._args())
        return self.carry_out(outcome)["changed"]

    def on_settings(self, peer, data):
        if "desk" in data:
            if not self.profile_aware():
                return False
            state = profiles.read_desk_state(data, now=self.now())
            if state is None:
                return False
            entry = ways._entry(self.current(), peer)
            outcome = crossing_state.desk_arrived(
                self.current(), state, source=peer, linked=bool(entry and entry.get("linked") is True),
                capable=self.capable(), **self._args())
            if not outcome["accepted"]:
                self.refused_desks.append((peer, outcome["reason"]))
            return self.carry_out(outcome, source=peer)["changed"]
        state = settings_sync.read_layout_state(data)
        if state is None:
            return False
        outcome = crossing_state.receive_picture(self.current(), state, source=peer,
                         capable=self.capable(), own_displays=self.desk.screen.display_map(), **self._args())
        return self.carry_out(outcome, source=peer, arrived=data)["changed"]


class MacShell(Shell):
    platform = "mac"


class PcShell(Shell):
    platform = "pc"


SHELLS = {"mac": MacShell, "pc": PcShell}
