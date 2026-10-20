"""Pure crossing events shared by both desktop apps and their headless shells.

The picture owns positions, each peer owns local intent, and zones are compiled output.
Callers save the Outcome and carry out its messages before re-arming their responder.
"""

import copy
import functools
import math
import os
import time
from typing import TypedDict

from core import profiles, protocol, return_edge, settings_sync, ways


class Outcome(TypedDict):
    settings: dict
    changed: bool
    accepted: bool
    snap: dict
    tiles: dict
    tell: list
    send_picture: bool
    forward_picture: bool
    send_desk: list
    forward: dict
    answer: dict
    reason: str


def _outcome(before, saved=None, result=None, *, accepted=True, tell=(),
             send_picture=False, forward_picture=False, send_desk=(), forward=None,
             answer=None, reason="", owned=False):
    """`owned`: `saved` is a copy this event made and nothing else holds, so it is kept, not copied."""
    saved = saved if owned and saved is not None else copy.deepcopy(before if saved is None else saved)
    return Outcome(settings=saved, changed=saved != before, accepted=accepted,
                   snap=copy.deepcopy((result or {}).get("snap", {})),
                   tiles=copy.deepcopy((result or {}).get("tiles", {})),
                   tell=list(dict.fromkeys(tell)), send_picture=send_picture,
                   forward_picture=forward_picture, send_desk=list(dict.fromkeys(send_desk)),
                   forward=copy.deepcopy(forward or {}), answer=copy.deepcopy(answer or {}),
                   reason=reason)


def _initial(settings, capable=(), fill=True):
    saved = copy.deepcopy(settings)
    for entry in saved.get("peers", []):
        if ways._zoned(entry):
            entry["ways"] = ways._read_intent(settings, entry["id"])
            entry.pop("left_out_ways", None)
    # With no machine in use holding the notch, a left-out one keeps its tick for Put back.
    holder = ways.notch_holder(saved)
    for entry in saved.get("peers", []):
        if holder is not None and ways._zoned(entry) and entry["id"] != holder:
            entry["ways"]["notch"] = False
    if not saved.get("layout"):
        saved["layout"] = ways.derive_layout(saved, gap=0)
    elif fill:
        # A peer paired after the layout existed gets its tile here, or compile clears its side for
        # want of a contact and every render invents a new place for it (rc13, the AC laptop). Not
        # stamped: a machine back from offline must not outrank the picture the others moved since.
        # Only a machine whose side is known: an unplaced one is never given a side it did not choose.
        # Only a picture machine: an old peer keeps its side without a tile, and a tile would make the
        # Mac count it as one until its link says otherwise, so every link-up re-armed the zones.
        picture = ways.picture_capable(saved, capable)
        derived = ways.derive_layout(saved, gap=0)
        for entry in saved.get("peers", []):
            if (ways._zoned(entry) and entry["id"] in picture and entry.get("side") in ways.EDGES
                    and entry["id"] not in saved["layout"] and entry["id"] in derived):
                saved["layout"][entry["id"]] = derived[entry["id"]]
    return saved


def _compile(saved, platform, *, capable=(), live=None, gone=None, now=None):
    return ways.compile_layout(saved, saved["layout"], platform=platform, capable=capable,
                               live=live, gone=gone, now=now)


def _tells(before, saved, *, sides=False):
    old = ways.way_back_state(before)
    told = [peer for peer, value in ways.way_back_state(saved).items() if old.get(peer) != value]
    if sides:
        held = {p.get("id"): p.get("side", "") for p in before.get("peers", [])}
        told += [p["id"] for p in saved.get("peers", [])
                 if ways._zoned(p) and held.get(p["id"], "") != p.get("side", "")]
    return list(dict.fromkeys(told))


def _stamp(saved, now):
    saved["layout_set_at"] = settings_sync.next_stamp(saved.get("layout_set_at"), now)
    saved["layout_by"] = saved.get("machine_id", "")


def _shelf(settings, gone=None):
    return {p.get("id") for p in settings.get("peers", [])
            if p.get("left_out") is True or p.get("in_use", True) is False
            or ways.peerlist.dormant_reason(p) is not None or gone is not None and gone(p.get("id"))}


def drop(settings, tiles, moved, *, platform, capable, live, gone, now, snap_radius):
    """Validate and snap a map drop, keeping shelved tiles aside."""
    saved = _initial(settings, capable)
    shelf = _shelf(saved, gone)
    if moved in shelf or not isinstance(tiles, dict):
        return _outcome(settings, accepted=False)
    held = saved["layout"]
    active = copy.deepcopy({peer: tile for peer, tile in tiles.items() if peer not in shelf})
    result = ways.compile_layout(saved, active, moved=moved, platform=platform,
                                capable=capable, live=live, gone=gone, now=now)
    if not result["accepted"]:
        snap = result.get("snap", {}).get(moved)
        if snap is None or snap == active.get(moved):
            return _outcome(settings, result=result, accepted=False)
        active[moved] = {**active[moved], **snap}
        result = ways.compile_layout(saved, active, moved=moved, platform=platform,
                                    capable=capable, live=live, gone=gone, now=now)
        if not result["accepted"]:
            return _outcome(settings, result=result, accepted=False)
    if moved in active and moved != saved.get("machine_id"):
        original = active[moved]
        others = {peer: tile for peer, tile in active.items() if peer != moved}
        snap = ways.snap_position(original, saved["machine_id"], others, radius=snap_radius)
        if ways.within_snap_radius(original, snap, saved["machine_id"], others, snap_radius):
            candidate = {**active, moved: {**original, **snap}}
            retry = ways.compile_layout(saved, candidate, moved=moved, platform=platform,
                                        capable=capable, live=live, gone=gone, now=now)
            if retry["accepted"]:
                active, result = candidate, retry
    saved["layout"] = {**{peer: copy.deepcopy(tile) for peer, tile in held.items() if peer in shelf},
                       **active}
    _stamp(saved, now)
    entry = ways._entry(saved, moved)
    own = saved["layout"].get(saved.get("machine_id"))
    if entry is not None and moved not in capable and own is not None and moved in saved["layout"]:
        # An old peer (no `layout`) crosses by its side, not the picture: a drop is how the map sets it,
        # and the side check below sends it the arrangement.
        contact = ways._rect_contact(own, saved["layout"][moved])
        if contact and contact[0] in ways.EDGES and contact[0] != entry.get("side"):
            entry.update(side=contact[0], side_set_at=settings_sync.next_stamp(entry.get("side_set_at"), now),
                         side_by=saved.get("machine_id", ""))
    result = _compile(saved, platform, capable=capable, live=live, gone=gone, now=now)
    saved = result["settings"]
    return _outcome(settings, saved, result, tell=_tells(settings, saved, sides=True), send_picture=True)


def edit_ways(settings, peer, *, platform, edge=None, thirds=None, edges=None, corners=None,
              corner=None, corner_at=None, notch=None, notch_return=None, live, gone, now, capable=()):
    """Update only specified choices; an empty third selection keeps the last choice."""
    saved = _initial(settings, capable)
    entry = ways._entry(saved, peer)
    if entry is None:
        raise KeyError(peer)
    if not ways._zoned(entry):
        raise ValueError("a phone cannot have ways")
    intent = entry["ways"]
    for key, value in (("edge", edge), ("corner", corner), ("notch", notch)):
        if value is not None and (key != "notch" or platform == "mac"):
            intent[key] = bool(value)
    if notch_return is not None and platform == "mac":
        entry["notch_return"] = bool(notch_return)
    if notch and platform == "mac":
        # One machine has the notch: ticking it here unticks it everywhere else.
        for other in saved.get("peers", []):
            if ways._zoned(other) and other["id"] != peer:
                other["ways"]["notch"] = False
    if thirds is not None:
        picked = [part for part in ways.PARTS if part in thirds]
        if picked:
            intent["thirds"] = picked
    if edges is not None:
        intent["edges"] = [side for side in ways.EDGES if isinstance(edges, list) and side in edges]
    if corners is not None:
        picked = [value for value in ways.CORNERS if isinstance(corners, list) and value in corners
                  and ways.corner_holder(saved, value, exclude=peer) is None]
        intent["corners"] = picked
        intent["corner"] = bool(picked)
        if picked:
            intent["corner_at"] = picked[0]
    if corners is None and (corner is not None or corner_at in ways.CORNERS):
        # 1.5.2's one-corner form: a held corner is refused without a write, keeping the one held.
        wanted = corner_at if corner_at in ways.CORNERS else intent["corner_at"]
        enabled = intent["corner"] if corner is None else bool(corner)
        if enabled and ways.corner_holder(saved, wanted, exclude=peer) is not None:
            return _outcome(settings, accepted=False)
        intent.update(corner_at=wanted, corners=[wanted] if enabled else [], corner=enabled)
    result = _compile(saved, platform, capable=capable, live=live, gone=gone, now=now)
    saved = result["settings"]
    return _outcome(settings, saved, result, tell=_tells(settings, saved))


def receive_picture(settings, state, *, source, platform, capable, live, gone, own_displays, now):
    """Take newer positions, retaining omitted displays and correcting only this owner's geometry."""
    if not settings_sync.layout_arrived(state, settings.get("layout_set_at"), settings.get("layout_by", "")):
        return _outcome(settings)
    # A missing tile is placed against the arriving picture (retain_held_peer_tiles), not this one.
    saved = _initial(settings, fill=False)
    layout = ways.retain_held_peer_tiles(saved, state["tiles"], saved["layout"])
    for peer, tile in layout.items():
        held = saved["layout"].get(peer, {})
        if "displays" in held and "displays" not in tile:
            tile["displays"] = copy.deepcopy(held["displays"])
            if "display_offsets" in tile:
                tile["display_offsets"] = {key: offset for key, offset in tile["display_offsets"].items()
                                           if key in tile["displays"]}
    own = saved.get("machine_id")
    saved.update(layout=layout, layout_set_at=state["set_at"], layout_by=state["by"])
    corrected = ways.refresh_displays(saved, own_displays, now=now)
    # A picture that has no tile for this machine is one relayed from a machine that does not know
    # it (A-B-C with A and C unpaired). Restamping against it would make each end answer the
    # other's picture for ever; link_up and paired already tell a new peer about this machine.
    if (own_displays and not corrected and own in state["tiles"]
            and state["tiles"][own].get("displays") != saved["layout"][own].get("displays")):
        _stamp(saved, now)
        corrected = True
    result = _compile(saved, platform, capable=capable, live=live, gone=gone, now=now)
    if not result["accepted"]:
        return _outcome(settings)
    saved = result["settings"]
    return _outcome(settings, saved, result, tell=_tells(settings, saved),
                    send_picture=corrected, forward_picture=True)


def receive_arrangement(settings, peer, read, *, platform, capable, live, gone, now):
    """Picture peers supply return-way status only; old peers settle a side by its stamp."""
    saved = copy.deepcopy(settings)
    entry = ways._entry(saved, peer)
    author = read.get("by")
    edge = read.get("edge")
    stamp = read.get("set_at")
    if (entry is None or not ways._zoned(entry) or edge not in ways.EDGES
            or not isinstance(author, bytes) or len(author) != 16 or not any(author)
            or type(stamp) is not int or not 0 <= stamp <= settings_sync.MAX_STAMP
            or stamp > now + settings_sync.DAY):
        return _outcome(settings)
    back = read.get("way_back")
    if isinstance(back, bool):
        entry["way_back"] = back
        holder = read.get("way_back_by")
        if (back is False and isinstance(holder, bytes) and len(holder) == 16 and any(holder)
                and holder != protocol.read_id(settings.get("machine_id"))):
            entry["way_back_by"] = protocol.id_text(holder)
        else:
            entry.pop("way_back_by", None)
    if peer in capable:
        return _outcome(settings, saved)
    held = (int(entry.get("side_set_at") or 0), protocol.read_id(entry.get("side_by")) or b"")
    newer = (stamp, author) > held
    if newer:
        entry.update(side=return_edge.OPPOSITE[edge], side_set_at=stamp, side_by=protocol.id_text(author))
        saved = _initial(saved, capable)
        saved["layout"].setdefault(peer, dict(x=0, y=0, w=160, h=100))
        own_id = saved["machine_id"]
        placed = ways.place_beside(saved["layout"], own_id, peer, entry["side"])
        contact = ways._rect_contact(saved["layout"][own_id], placed)
        # A side another machine already holds is shared, as derive_layout shares it, not cornered.
        shared = {} if contact and contact[0] == entry["side"] else ways.share_side(
            saved["layout"], own_id, peer, entry["side"], _shelf(saved, gone))
        saved["layout"].update(shared or {peer: placed})
        if saved["layout"] != settings.get("layout"):
            _stamp(saved, now)
        result = _compile(saved, platform, capable=capable, live=live, gone=gone, now=now)
        saved = result["settings"]
    else:
        result = None
    changed = saved != settings
    return _outcome(settings, saved, result, tell=[*_tells(settings, saved), peer] if changed else [],
                    send_picture=newer and saved.get("layout") != settings.get("layout"))


def link_up(settings, peer, *, platform, own_displays, now, capable=()):
    saved = _initial(settings, capable)
    ways.refresh_displays(saved, own_displays, now=now)
    result = _compile(saved, platform, capable=capable, now=now)
    saved = result["settings"]
    entry = ways._entry(saved, peer) or {}
    return _outcome(settings, saved, result, tell=[peer] if entry.get("side") in ways.EDGES else [],
                    send_picture=True)


def leave_out(settings, peer, *, platform, live=None, gone=None, now=None, capable=()):
    saved = _initial(settings, capable)
    entry = ways._entry(saved, peer)
    if entry is None:
        raise KeyError(peer)
    entry["left_out"] = True
    result = _compile(saved, platform, capable=capable, live=live, gone=gone, now=now)
    saved = result["settings"]
    return _outcome(settings, saved, result, tell=_tells(settings, saved))


def put_back(settings, peer, *, platform, live=None, gone=None, now=None, capable=()):
    saved = _initial(settings, capable)
    entry = ways._entry(saved, peer)
    if entry is None:
        raise KeyError(peer)
    entry.pop("left_out", None)
    # Its kept tile may sit where an active machine was placed while it was shelved: it moves, not them.
    tile, own = saved["layout"].get(peer), saved.get("machine_id")
    shelf = _shelf(saved, gone)
    others = {key: value for key, value in saved["layout"].items() if key != peer and key not in shelf}
    moved = False
    if (isinstance(tile, dict) and peer not in shelf and own in others
            and any(ways._overlaps(tile, other) for other in others.values())):
        side = entry.get("side") if entry.get("side") in ways.EDGES else ""
        shared = ways.share_side(saved["layout"], own, peer, side, shelf) if side else {}
        saved["layout"].update(shared or {peer: {**tile, **ways.snap_position(tile, own, others, radius=math.inf)}})
        moved = saved["layout"] != settings.get("layout")
        if moved:
            # Sent, or the next picture from another machine puts it back on top of the active one.
            _stamp(saved, time.time() if now is None else now)
    result = _compile(saved, platform, capable=capable, live=live, gone=gone, now=now)
    saved = result["settings"]
    return _outcome(settings, saved, result, tell=_tells(settings, saved), send_picture=moved)


def displays_changed(settings, *, platform, own_displays, now, capable=()):
    saved = _initial(settings, capable)
    changed = ways.refresh_displays(saved, own_displays, now=now)
    result = _compile(saved, platform, capable=capable, now=now)
    saved = result["settings"]
    return _outcome(settings, saved, result, tell=_tells(settings, saved), send_picture=changed)


def paired(settings, *, platform, own_displays, now, capable=()):
    saved = _initial(settings, capable)
    desktops = [p for p in saved.get("peers", []) if ways._zoned(p)]
    if platform == "mac" and len(desktops) == 1 and not settings.get("layout"):
        peer = desktops[0]["id"]
        saved["layout"][peer] = ways.place_beside(saved["layout"], saved["machine_id"], peer, "right")
    ways.refresh_displays(saved, own_displays, now=now)
    result = _compile(saved, platform, capable=capable, now=now)
    saved = result["settings"]
    return _outcome(settings, saved, result, tell=_tells(settings, saved, sides=True), send_picture=True)


def migrate(settings, platform, *, capable=()):
    """Read legacy zone choices once, then discard their historical marks by compiling."""
    saved = _initial(settings, capable)
    result = _compile(saved, platform, capable=capable)
    return _outcome(settings, result["settings"], result)


def _platform(settings, supplied=None):
    if supplied in ("mac", "pc", "windows", "linux"):
        return supplied
    own = settings.get("machine_id", "")
    state = settings.get("crossing_desk", {}).get("status", {}).get(own, {})
    value = state.get("value", {}) if isinstance(state, dict) else {}
    platform = value.get("platform") if isinstance(value, dict) else None
    return platform if platform in ("mac", "pc", "windows", "linux") else "windows"


def _profile_event(function):
    """Reconcile profile-aware events at their shared boundary, including no-op events."""
    @functools.wraps(function)
    def wrapped(settings, *args, **kwargs):
        if (not isinstance(settings, dict) or "crossing_own" not in settings
                or settings.get("_crossing_profiles_upgrade_pending") is True):
            return function(settings, *args, **kwargs)
        supplied_platform = kwargs.get("platform")
        if supplied_platform is None and function.__name__ == "migrate" and args:
            supplied_platform = args[0]
        platform = _platform(settings, supplied_platform)
        capable = kwargs.get("capable", ())
        live, gone, now = kwargs.get("live"), kwargs.get("gone"), kwargs.get("now")
        app = settings.get("crossing_desk", {}).get("status", {}).get(
            settings.get("machine_id"), {}).get("value", {}).get("app", profiles.APP_VERSION)
        original = settings
        # Settings reconcile would leave as they are go to the event uncopied: no event writes to its
        # argument (each copies first, as the unreconciled path above already relies on), so the
        # caller's settings stay untouched either way.
        if profiles.reconciled(settings, platform=platform, app=app):
            prepared, before_paths = settings, []
        else:
            prepared, before_paths = profiles.reconcile(settings, platform=platform,
                                                          capable=capable, live=live,
                                                          gone=gone, now=now, app=app)
        out = function(prepared, *args, **kwargs)
        if not out.get("accepted", True):
            out["settings"] = copy.deepcopy(original)
            out["changed"] = False
            out["send_desk"] = []
            out["tell"] = []
            out["send_picture"] = False
            out["forward_picture"] = False
            out["forward"] = {}
            out["answer"] = {}
            return out
        saved, after_paths = out["settings"], []
        # Forwarded duplicates and stale-register replies leave the prepared settings
        # untouched. Projecting them again multiplies the work of every mesh relay.
        if saved != prepared and not profiles.reconciled(saved, platform=platform, app=app):
            saved, after_paths = profiles.reconcile(saved, platform=platform,
                                                     capable=capable, live=live,
                                                     gone=gone, now=now, app=app)
        if profiles.desk_size(saved) > profiles.MAX_DESK_BYTES:
            out["settings"] = copy.deepcopy(original)
            out["changed"] = False
            out["accepted"] = False
            out["reason"] = "desk_full"
            out["send_desk"] = []
            out["tell"] = []
            out["send_picture"] = False
            out["forward_picture"] = False
            out["forward"] = {}
            out["answer"] = {}
            return out
        paths = [*before_paths, *out.get("send_desk", []), *after_paths]
        out["settings"] = saved
        out["changed"] = saved != original
        out["send_desk"] = list(dict.fromkeys(paths))
        if out["changed"]:
            out["tell"] = list(dict.fromkeys([*out.get("tell", []), *_tells(original, saved)]))
        return out
    return wrapped


def _register_value(register, default=None):
    return register.get("value", default) if isinstance(register, dict) else default


def _desk(settings):
    return settings["crossing_desk"]


def _own(settings):
    return settings["crossing_own"]


def _active(settings):
    return _register_value(_desk(settings).get("active"), profiles.DESK_ID)


def _profile_stamp(settings, held=None, now=None, floor=0):
    own = settings.get("machine_id", "")
    current = int(held.get("set_at", 0)) if isinstance(held, dict) else 0
    return max(int(time.time() if now is None else now), current + 1, floor), own


def _desk_size(settings):
    return profiles.desk_size(settings)


def set_same_ways(settings, enabled, *, platform=None, now=None, capable=(), live=None, gone=None):
    saved = copy.deepcopy(settings)
    desk = _desk(saved)
    held = desk.get("on", {})
    if _register_value(held) is bool(enabled):
        return _outcome(settings)
    before = copy.deepcopy(desk)
    desk["on"] = profiles.register(bool(enabled), now, saved.get("machine_id", ""), held=held)
    paths = list(profiles.apply_transitions(saved, before, now))
    return _outcome(settings, saved, send_desk=[("on",), *paths])


def set_own_ways(settings, use_own, *, platform=None, now=None, capable=(), live=None, gone=None):
    saved = copy.deepcopy(settings)
    _own(saved)["use_own"] = bool(use_own)
    return _outcome(settings, saved)


def share_mine(settings, *, platform=None, now=None):
    if not profiles.same_ways_on(settings):
        return _outcome(settings, accepted=False, reason="sync_off")
    saved = copy.deepcopy(settings)
    pid, own = _active(saved), saved.get("machine_id", "")
    path = profiles.put_row(saved, pid, own, _own(saved).get("row", {}), now,
                            why="replaced_by", by=own)
    return _outcome(settings, saved, send_desk=[path])


def _edit_choice_row(row, peer, *, edge=None, thirds=None, edges=None, corners=None,
                     corner=None, corner_at=None, notch=None, notch_return=None,
                     platform="mac"):
    row = profiles.canonical_row(row)
    ways_row = row.setdefault(peer, {"ways": ways._read_intent({"peers": []}, peer),
                                    "notch_return": False})
    intent = ways_row["ways"]
    for key, value in (("edge", edge), ("corner", corner), ("notch", notch)):
        if value is not None and (key != "notch" or platform == "mac"):
            intent[key] = bool(value)
    if notch_return is not None and platform == "mac":
        ways_row["notch_return"] = bool(notch_return)
    if notch and platform == "mac":
        for other, entry in row.items():
            if other != peer:
                entry["ways"]["notch"] = False
    if thirds is not None:
        picked = [part for part in ways.PARTS if part in thirds]
        if picked:
            intent["thirds"] = picked
    if edges is not None:
        intent["edges"] = [side for side in ways.EDGES if isinstance(edges, list) and side in edges]
    holders = {corner for ident, entry in row.items() if ident != peer
               for corner in entry["ways"].get("corners", [])}
    if corners is not None:
        picked = [value for value in ways.CORNERS if isinstance(corners, list) and value in corners
                  and value not in holders]
        intent["corners"] = picked
        intent["corner"] = bool(picked)
        if picked:
            intent["corner_at"] = picked[0]
    elif corner is not None or corner_at in ways.CORNERS:
        wanted = corner_at if corner_at in ways.CORNERS else intent["corner_at"]
        enabled = intent["corner"] if corner is None else bool(corner)
        if enabled and wanted in holders:
            return row, False
        intent.update(corner_at=wanted, corners=[wanted] if enabled else [], corner=enabled)
    return profiles.canonical_row(row), True


def edit_other(settings, machine, peer, *, platform=None, now=None, edge=None, thirds=None,
               edges=None, corners=None, corner=None, corner_at=None, notch=None,
               notch_return=None):
    saved = copy.deepcopy(settings)
    own = saved.get("machine_id", "")
    if machine == own:
        raise ValueError("edit_other requires another machine")
    if not profiles.same_ways_on(saved):
        return _outcome(settings, accepted=False, reason="sync_off")
    if protocol.read_id(machine) is None or protocol.read_id(peer) is None:
        return _outcome(settings, accepted=False, reason="invalid_machine")
    pid = _active(saved)
    target = _desk(saved).get("profiles", {}).get(pid)
    if not isinstance(target, dict):
        return _outcome(settings, accepted=False, reason="profile_missing")
    current = target.get("rows", {}).get(machine, {"value": {}})
    current_row = profiles.canonical_row(current.get("value", {}))
    if peer not in current_row and len(current_row) >= 32:
        return _outcome(settings, accepted=False, reason="row_full")
    # Its own status says, else what pairing recorded, so a Mac's notch can be set before it reports.
    target_platform = "mac" if profiles.view_platform(saved, machine) == "mac" else "windows"
    updated, accepted = _edit_choice_row(
        current_row, peer, edge=edge, thirds=thirds, edges=edges,
        corners=corners, corner=corner, corner_at=corner_at, notch=notch,
        notch_return=notch_return, platform=target_platform)
    if not accepted:
        return _outcome(settings, accepted=False)
    path = profiles.put_row(saved, pid, machine, updated, now, why="edited", by=own)
    if _desk_size(saved) > profiles.MAX_DESK_BYTES:
        return _outcome(settings, accepted=False, reason="desk_full")
    return _outcome(settings, saved, send_desk=[path])


def new_profile(settings, name, *, platform=None, now=None):
    trimmed = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(trimmed) <= 32:
        return _outcome(settings, accepted=False, reason="invalid_name")
    saved = copy.deepcopy(settings)
    desk, own, pid = _desk(saved), saved.get("machine_id", ""), _active(saved)
    profiles_map = desk.setdefault("profiles", {})
    profiles.prune_removed(saved, profiles.MAX_HELD - 1)
    live_profiles = [p for p in profiles_map if not profiles.removed(desk, p)]
    if len(live_profiles) >= profiles.MAX_PROFILES or len(profiles_map) >= profiles.MAX_HELD:
        return _outcome(settings, accepted=False, reason="desk_full")
    new_id = protocol.id_text(os.urandom(16))
    source = profiles_map[pid]
    stamp = max(int(time.time() if now is None else now),
                int(desk.get("on", {}).get("set_at", 0)) + 1)
    rows = {machine: {"set_at": stamp, "by": own,
                      "value": profiles.canonical_row(register.get("value", {}))}
            for machine, register in source.get("rows", {}).items()}
    source_home = source.get("home", {})
    source_shake = source_home.get("shake", {})
    shake = profiles.register(source_shake.get("value", True), now, own, held=source_shake,
                              floor=int(desk.get("on", {}).get("set_at", 0)) + 1)
    source_sensitivity = source_home.get("sensitivity", {})
    sensitivity = profiles.register(source_sensitivity.get("value", 100), now, own,
                                    held=source_sensitivity,
                                    floor=int(desk.get("on", {}).get("set_at", 0)) + 1)
    profile = {"name": profiles.register(trimmed, now, own), "removed": None,
               "home": {"shake": shake, "sensitivity": sensitivity}, "rows": rows}
    profiles_map[new_id] = profile
    if _desk_size(saved) > profiles.MAX_DESK_BYTES:
        return _outcome(settings, accepted=False, reason="desk_full")
    paths = [("name", new_id), ("home", new_id, "shake"),
             ("home", new_id, "sensitivity"),
             *(('row', new_id, machine) for machine in rows)]
    return _outcome(settings, saved, send_desk=paths)


def rename_profile(settings, profile_id, name, *, platform=None, now=None):
    trimmed = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(trimmed) <= 32:
        return _outcome(settings, accepted=False, reason="invalid_name")
    saved = copy.deepcopy(settings)
    profile = _desk(saved).get("profiles", {}).get(profile_id)
    if not isinstance(profile, dict) or profiles.removed(_desk(saved), profile_id):
        return _outcome(settings, accepted=False, reason="profile_missing")
    profile["name"] = profiles.register(trimmed, now, saved.get("machine_id", ""),
                                        held=profile.get("name"))
    if _desk_size(saved) > profiles.MAX_DESK_BYTES:
        return _outcome(settings, accepted=False, reason="desk_full")
    return _outcome(settings, saved, send_desk=[("name", profile_id)])


def remove_profile(settings, profile_id, *, platform=None, now=None):
    saved = copy.deepcopy(settings)
    desk = _desk(saved)
    profile = desk.get("profiles", {}).get(profile_id)
    count = sum(not profiles.removed(desk, pid) for pid in desk.get("profiles", {}))
    if (not isinstance(profile, dict) or profiles.removed(desk, profile_id)
            or profile_id == _active(saved) or count <= 1):
        return _outcome(settings, accepted=False, reason="active_or_last_profile")
    stamp, own = _profile_stamp(saved, profile.get("removed"), now)
    profile["removed"] = {"set_at": stamp, "by": own}
    return _outcome(settings, saved, send_desk=[("removed", profile_id)])


def switch_profile(settings, profile_id, *, platform=None, capable=(), live=None, gone=None, now=None):
    saved = copy.deepcopy(settings)
    desk = _desk(saved)
    profiles_map = desk.get("profiles", {})
    target = profiles_map.get(profile_id)
    if not isinstance(target, dict) or profiles.removed(desk, profile_id):
        return _outcome(settings, accepted=False, reason="profile_missing")
    old_id = _active(saved)
    if old_id == profile_id:
        return _outcome(settings)
    old = profiles_map[old_id]
    own = saved.get("machine_id", "")
    clock = int(time.time() if now is None else now)
    old_picture = old.get("picture") if isinstance(old.get("picture"), dict) else {}
    old_tiles = {}
    for peer, tile_value in saved.get("layout", {}).items():
        if not isinstance(tile_value, dict):
            continue
        tile = {key: copy.deepcopy(tile_value[key]) for key in ("x", "y", "w", "h", "display_offsets")
                if key in tile_value}
        displays = tile_value.get("displays")
        if isinstance(displays, dict):
            tile["display_offsets"] = {key: value for key, value in tile.get("display_offsets", {}).items()
                                       if key in displays}
            if not tile["display_offsets"]:
                tile.pop("display_offsets", None)
        else:
            tile.pop("display_offsets", None)
        old_tiles[peer] = tile
    old["picture"] = {"set_at": max(clock, int(old_picture.get("set_at", 0)) + 1),
                       "by": own, "tiles": old_tiles}
    target_picture = target.get("picture")
    picture_tiles = target_picture.get("tiles", {}) if isinstance(target_picture, dict) else None
    if not isinstance(picture_tiles, dict):
        picture_tiles = {peer: tile for peer, tile in old_tiles.items()}
    layout = {}
    for peer, tile_value in picture_tiles.items():
        if not isinstance(tile_value, dict):
            continue
        tile = copy.deepcopy(tile_value)
        held = saved.get("layout", {}).get(peer, {})
        if isinstance(held, dict) and isinstance(held.get("displays"), dict):
            tile["displays"] = copy.deepcopy(held["displays"])
            offsets = tile.get("display_offsets")
            if isinstance(offsets, dict):
                tile["display_offsets"] = {key: value for key, value in offsets.items()
                                            if key in held["displays"]}
                if not tile["display_offsets"]:
                    tile.pop("display_offsets", None)
        else:
            tile.pop("display_offsets", None)
        layout[peer] = tile
    layout = ways.retain_held_peer_tiles(saved, layout, saved.get("layout", {}), layout)
    saved["layout"] = layout
    saved["layout_set_at"] = max(clock, int(saved.get("layout_set_at", 0)) + 1)
    saved["layout_by"] = own
    # The target keeps its picture register: dropping it here alone would leave this machine's desk
    # different from every other's. While active it is simply not read.
    active = desk.get("active", {})
    desk["active"] = profiles.register(profile_id, now, own, held=active)
    paths = list(profiles.apply_transitions(saved, copy.deepcopy(settings["crossing_desk"]), now))
    compile_result = _compile(saved, _platform(saved, platform), capable=capable,
                              live=live, gone=gone, now=now)
    if not compile_result["accepted"]:
        return _outcome(settings, accepted=False, reason="invalid_picture")
    saved = compile_result["settings"]
    return _outcome(settings, saved, compile_result, send_picture=True,
                    send_desk=[("picture", old_id), ("picture", profile_id), ("active",), *paths])


def set_shake(settings, enabled, *, platform=None, now=None):
    saved = copy.deepcopy(settings)
    desk, own = _desk(saved), _own(saved)
    if profiles.same_ways_on(saved):
        pid = _active(saved)
        profile = desk["profiles"][pid]
        held = profile.setdefault("home", {}).get("shake")
        profile["home"]["shake"] = profiles.register(bool(enabled), now,
                                                     saved.get("machine_id", ""), held=held,
                                                     floor=int(desk.get("on", {}).get("set_at", 0)) + 1)
        paths = [("home", pid, "shake")]
    else:
        own["shake"] = bool(enabled)
        paths = []
    return _outcome(settings, saved, send_desk=paths)


def set_shake_sensitivity(settings, sensitivity, *, platform=None, now=None):
    if type(sensitivity) is not int or not 50 <= sensitivity <= 200:
        return _outcome(settings, accepted=False, reason="invalid_sensitivity")
    saved = copy.deepcopy(settings)
    desk, own = _desk(saved), _own(saved)
    if profiles.same_ways_on(saved):
        pid = _active(saved)
        profile = desk["profiles"][pid]
        held = profile.setdefault("home", {}).get("sensitivity")
        profile["home"]["sensitivity"] = profiles.register(
            sensitivity, now, saved.get("machine_id", ""), held=held,
            floor=int(desk.get("on", {}).get("set_at", 0)) + 1)
        paths = [("home", pid, "sensitivity")]
    else:
        own["shake_sensitivity"] = sensitivity
        paths = []
    return _outcome(settings, saved, send_desk=paths)


def restore_saved(settings, saved_id, *, platform=None, capable=(), live=None, gone=None, now=None):
    saved = copy.deepcopy(settings)
    archive = _own(saved).get("saved", [])
    item = next((entry for entry in archive if entry.get("id") == saved_id), None)
    if item is None or not isinstance(item.get("row"), dict):
        return _outcome(settings, accepted=False, reason="saved_missing")
    profiles.archive(saved, profiles.in_force(saved)[0], "restored", now)
    profiles.archive(saved, _own(saved).get("row", {}), "restored", now)
    _own(saved)["row"] = profiles.canonical_row(item["row"])
    _own(saved)["use_own"] = True
    _own(saved).setdefault("editing", {}).pop("own", None)
    result = _compile(saved, _platform(saved, platform), capable=capable,
                      live=live, gone=gone, now=now)
    return _outcome(settings, result["settings"], result)


def delete_saved(settings, saved_id, *, platform=None, now=None):
    saved = copy.deepcopy(settings)
    archive = _own(saved).setdefault("saved", [])
    kept = [entry for entry in archive if entry.get("id") != saved_id]
    if len(kept) == len(archive):
        return _outcome(settings, accepted=False, reason="saved_missing")
    _own(saved)["saved"] = kept
    return _outcome(settings, saved)


def desk_arrived(settings, state, *, source, platform=None, capable=(), linked=True,
                 live=None, gone=None, now=None):
    source = source if isinstance(source, str) else protocol.id_text(source)
    entry = ways._entry(settings, source)
    if (entry is None or entry.get("allow_drive") is not True or not linked
            or ways.peerlist.dormant_reason(entry) is not None):
        return _outcome(settings, accepted=False, reason="untrusted")
    saved, paths, forward, answer, accepted, reason = profiles.merge_desk(
        settings, state, source=source, now=now, borrow=True)
    if not accepted:
        return _outcome(settings, accepted=False, reason=reason)
    # A merge that took something made its own copy; one that took nothing lent `settings` back.
    return _outcome(settings, None if saved is settings else saved, accepted=True, send_desk=paths,
                    forward=forward, answer=answer, reason=reason, owned=True)


for _event in (drop, edit_ways, receive_picture, receive_arrangement, link_up, leave_out,
               put_back, displays_changed, paired, migrate, set_same_ways, set_own_ways,
               share_mine, edit_other, new_profile, rename_profile, remove_profile,
               switch_profile, set_shake, set_shake_sensitivity, restore_saved, delete_saved, desk_arrived):
    globals()[_event.__name__] = _profile_event(_event)
