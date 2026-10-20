"""Pure crossing profiles, migration, and independently stamped desk registers.

Only the live projection contains permissions or connection details. Rows and wire
messages are constructed field by field, never by copying a peer entry.
"""

import copy
import hashlib
import json
import time

from core import peerlist, protocol, settings_sync, ways
from core.i18n import joined, tr

FORMAT = 1
DESK_ID = protocol.id_text(bytes(16))
MAX_PROFILES = 8
MAX_HELD = 64
PRUNED_KEPT = 4 * MAX_HELD
MAX_DESK_BYTES = 48 * 1024
AHEAD = 600
APP_VERSION = "1.5.5"
UPGRADE_PENDING = "_crossing_profiles_upgrade_pending"


def _now(now):
    return int(time.time() if now is None else now)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def frames(desk):
    """A desk message packed register by register into frames of at most MAX_DESK_BYTES, so only a
    single register is ever bounded (a row of 32 peers, a picture of 33 tiles, both far below it):
    the whole desk never is, and two valid desks always merge. Each frame is read and taken alone."""
    result, frame, size = [], {}, 0
    for path, register in _paths(desk):
        one = {}
        _store(one, path, register)
        length = len(_json(one))
        if frame and size + length > MAX_DESK_BYTES:
            result.append(frame)
            frame, size = {}, 0
        _store(frame, path, register)
        size += length
    return result + ([frame] if frame else [])


def desk_size(settings):
    """The largest single register this desk holds, which is what MAX_DESK_BYTES bounds."""
    # Every crossing event measures its result, so this reads the registers in place: copying the
    # desk to measure it cost more than most events.
    return max((len(_json(_nest(path, register)))
                for path, register in _paths(settings.get("crossing_desk", {}))), default=0)


def removed(desk, profile_id):
    """Whether a profile's tombstone takes effect: never for the active profile."""
    profile = desk.get("profiles", {}).get(profile_id)
    return (not isinstance(profile, dict) or profile.get("removed") is not None
            and profile_id != desk.get("active", {}).get("value"))


def prune_removed(settings, limit):
    """Drop whole removed profiles, oldest tombstone first (ties by id), until at most `limit` are
    held: the same rule on every machine, so desks still agree. Their ids are kept, never sent, so
    a late delta for one is ignored rather than making it again without its tombstone."""
    profiles, own = settings["crossing_desk"].get("profiles", {}), settings["crossing_own"]
    while len(profiles) > limit:
        candidates = [pid for pid in profiles if removed(settings["crossing_desk"], pid)]
        if not candidates:
            break
        oldest = min(candidates, key=lambda pid: (_pair(profiles[pid].get("removed")), pid))
        del profiles[oldest]
        own["pruned"] = [*pruned(settings), oldest][-PRUNED_KEPT:]


def pruned(settings):
    held = settings.get("crossing_own", {}).get("pruned")
    return [pid for pid in held if isinstance(pid, str)] if isinstance(held, list) else []


def row_entry(settings, peer):
    entry = ways._entry(settings, peer) or {}
    # A malformed local JSON must still be recoverable; the legacy reader assumes
    # thirds is iterable, whereas a hand-edited file need not satisfy that.
    if isinstance(entry.get("ways"), dict) and not isinstance(entry["ways"].get("thirds", []), (list, tuple)):
        settings = copy.deepcopy(settings)
        ways._entry(settings, peer)["ways"].pop("thirds", None)
    return {"ways": ways._read_intent(settings, peer), "notch_return": entry.get("notch_return") is True}


def live_row(settings, send_only=True):
    return {entry["id"]: row_entry(settings, entry["id"])
            for entry in settings.get("peers", []) if isinstance(entry, dict) and ways._zoned(entry)
            and (not send_only or entry.get("send", True) is True)}


def canonical_row(row):
    if not isinstance(row, dict):
        return {}
    scratch = {"peers": [{"id": peer, "port": 24820,
                          "ways": value.get("ways", {}), "notch_return": value.get("notch_return") is True}
                         for peer, value in row.items() if isinstance(peer, str) and peer
                         and isinstance(value, dict)]}
    return live_row(scratch)


def register(value, now, by, held=None, floor=0):
    return {"value": copy.deepcopy(value), "set_at": max(_now(now), (held or {}).get("set_at", 0) + 1, floor),
            "by": by}


def _pair(reg):
    return ((reg or {}).get("set_at", -1), settings_sync._id((reg or {}).get("by", "")) or b"")


def _blank_desk():
    return {"format": FORMAT, "on": {"value": False, "set_at": 0, "by": ""},
            "active": {"value": DESK_ID, "set_at": 0, "by": ""},
            "profiles": {DESK_ID: {"name": {"value": "Desk", "set_at": 0, "by": ""},
                "removed": None, "home": {"shake": {"value": True, "set_at": 0, "by": ""},
                         "sensitivity": {"value": 100, "set_at": 0, "by": ""}}, "rows": {}}},
            "status": {}}


def same_ways_on(settings):
    return settings.get("crossing_desk", {}).get("on", {}).get("value") is True


def in_force(settings):
    own = settings["crossing_own"]
    desk = settings["crossing_desk"]
    if not same_ways_on(settings) or own.get("use_own") is True:
        return own["row"], False
    profile = desk["profiles"].get(desk["active"]["value"], {})
    return profile.get("rows", {}).get(settings.get("machine_id"), {}).get("value", {}), True


def archive(settings, row, why, now, by=None):
    row = canonical_row(row)
    ident = hashlib.sha256(_json(row)).hexdigest()
    item = {"id": ident, "why": why, "at": _now(now), "row": row}
    if by is not None:
        item["by"] = by
    saved = settings["crossing_own"].setdefault("saved", [])
    saved[:] = [entry for entry in saved if entry.get("id") != ident]
    saved.append(item)


def _archive_edit(settings, row, key, now):
    editing = settings["crossing_own"].setdefault("editing", {})
    if not editing.get(key):
        archive(settings, row, "edited", now)
        editing[key] = True


def put_row(settings, profile_id, machine, row, now, why="edited", by=None, stamp=None):
    desk = settings["crossing_desk"]
    rows = desk["profiles"][profile_id].setdefault("rows", {})
    held = rows.get(machine)
    if machine == settings.get("machine_id"):
        if held is not None:
            if why == "edited":
                _archive_edit(settings, held["value"], profile_id, now)
            else:
                archive(settings, held["value"], why, now, by=by)
        if why != "edited":
            settings["crossing_own"].setdefault("editing", {}).pop(profile_id, None)
    author = settings.get("machine_id", "") if by is None else by
    reg = register(canonical_row(row), now, author, held, floor=desk["on"]["set_at"] + 1)
    if stamp is not None:
        reg["set_at"] = stamp
    rows[machine] = reg
    return ("row", profile_id, machine)


def _local_shape(own, desk):
    def row_shape(row):
        return (isinstance(row, dict) and all(isinstance(peer, str) and isinstance(entry, dict)
                and isinstance(entry.get("ways"), dict) and type(entry.get("notch_return", False)) is bool
                for peer, entry in row.items()))
    shape = (isinstance(own, dict) and type(own.get("format")) is int and own["format"] == FORMAT
            and type(own.get("use_own")) is bool and type(own.get("shake")) is bool
            and type(own.get("shake_sensitivity", 100)) is int
            and 50 <= own.get("shake_sensitivity", 100) <= 200
            and row_shape(own.get("row")) and row_shape(own.get("applied"))
            and isinstance(own.get("saved"), list)
            and all(isinstance(item, dict) and row_shape(item.get("row"))
                    and isinstance(item.get("id"), str) and type(item.get("at")) is int
                    and isinstance(item.get("why"), str) for item in own["saved"])
            and isinstance(desk, dict) and type(desk.get("format")) is int and desk["format"] == FORMAT
            and isinstance(desk.get("on"), dict) and type(desk["on"].get("value")) is bool
            and isinstance(desk.get("active"), dict) and isinstance(desk.get("profiles"), dict)
            and isinstance(desk.get("status"), dict)
            and isinstance(desk["active"].get("value"), str)
            and desk["active"].get("value") in desk["profiles"]
            and all(isinstance(p, dict) and isinstance(p.get("rows"), dict)
                    and isinstance(p.get("home"), dict)
                    and all(isinstance(r, dict) and isinstance(r.get("value"), dict)
                            for r in p["rows"].values()) for p in desk["profiles"].values()))
    if not shape or not isinstance(own.get("editing", {}), dict):
        return False
    if any(not _profile_id(pid) for pid in desk["profiles"]):
        return False
    for path, reg in _paths(desk):
        if not _valid_stamp(reg, settings_sync.MAX_STAMP):
            return False
        kind, value = path[0], reg.get("value")
        if kind == "active" and not _profile_id(value):
            return False
        if kind == "name" and (not isinstance(value, str) or not 1 <= len(value.strip()) <= 32):
            return False
        if kind == "home" and not (path[2] == "shake" and type(value) is bool
                or path[2] == "sensitivity" and type(value) is int and 50 <= value <= 200):
            return False
        if kind == "row" and (protocol.read_id(path[2]) is None or not _valid_row(value)):
            return False
        if kind == "status" and (reg["by"] != path[1] or not _valid_status(value)):
            return False
        if kind == "picture" and _picture(reg) is None:
            return False
    return True


def before_load(raw, *, now=None):
    saved = copy.deepcopy(raw)
    now = _now(now)
    notes = []
    own, desk = saved.get("crossing_own"), saved.get("crossing_desk")
    if not _local_shape(own, desk):
        for key in ("crossing_own", "crossing_desk"):
            if key in saved:
                aside = key + "_unreadable"
                if aside in saved:
                    saved.setdefault(aside + "_history", []).append(saved[aside])
                saved[aside] = saved[key]
        row = live_row(saved, send_only=False)
        saved["crossing_own"] = dict(format=FORMAT, use_own=False, row=row, shake=True,
                                     shake_sensitivity=100,
                                     applied=copy.deepcopy(row), saved=[])
        saved["crossing_desk"] = _blank_desk()
        archive(saved, row, "upgrade", now)
        saved[UPGRADE_PENDING] = True
        return saved, ["upgraded"]
    own["row"] = canonical_row(own["row"])
    own["applied"] = canonical_row(own["applied"])
    own.setdefault("shake_sensitivity", 100)
    current = live_row(saved, send_only=False)
    changed = {peer: entry for peer, entry in current.items()
               if peer in own["applied"] and entry != own["applied"][peer]}
    if changed:
        archive(saved, own["row"], "older_version", now)
        own["row"].update(copy.deepcopy(changed))
        own["use_own"] = True
        own.setdefault("editing", {}).pop("own", None)
        notes.append("older_version")
    for peer, entry in current.items():
        if peer not in own["applied"] and peer not in own["row"]:
            own["row"][peer] = entry
    # The loader has acknowledged these changes; reconcile must not misattribute
    # them to a fresh page edit or send them back into the shared desk.
    own["applied"] = current
    return saved, notes


def after_load(settings, *, platform, capable=(), now=None, app=APP_VERSION):
    saved = copy.deepcopy(settings)
    if saved.pop(UPGRADE_PENDING, False):
        saved["crossing_own"]["row"] = live_row(saved, send_only=False)
        saved["crossing_own"]["applied"] = live_row(saved, send_only=False)
    return reconcile(saved, platform=platform, capable=capable, now=now, app=app)


def apply_transitions(settings, before_desk, now):
    desk, own = settings["crossing_desk"], settings["crossing_own"]
    machine = settings.get("machine_id", "")
    was_on = before_desk["on"]["value"] is True
    is_on = desk["on"]["value"] is True
    old_id, active = before_desk["active"]["value"], desk["active"]["value"]
    paths = []
    if was_on and not is_on and not own["use_own"]:
        old = before_desk["profiles"].get(old_id, {}).get("rows", {}).get(machine)
        if old is not None:
            archive(settings, own["row"], "sync_off", now)
            own["row"] = canonical_row(old["value"])
            own.setdefault("editing", {}).pop("own", None)
    profile = desk["profiles"].get(active)
    if profile is None:
        return paths
    row = profile.setdefault("rows", {}).get(machine)
    if not was_on and is_on and (row is None or row["set_at"] <= desk["on"]["set_at"]):
        paths.append(put_row(settings, active, machine, own["row"], now, why="seeded",
                             stamp=desk["on"]["set_at"]))
    elif is_on and row is None:
        paths.append(put_row(settings, active, machine, own["row"], now, why="seeded", stamp=0))
    if old_id != active and was_on and not own["use_own"]:
        old = before_desk["profiles"].get(old_id, {}).get("rows", {}).get(machine)
        if old:
            archive(settings, old["value"], "replaced_by", now, by=desk["active"]["by"])
    return paths


def reconcile(settings, *, platform, capable=(), live=None, gone=None, now=None, app=APP_VERSION):
    saved = copy.deepcopy(settings)
    if "crossing_own" not in saved or saved.get(UPGRADE_PENDING):
        return saved, []
    now = _now(now)
    own, desk = saved["crossing_own"], saved["crossing_desk"]
    active, machine = desk["active"]["value"], saved.get("machine_id", "")
    # The caller's desk is the one before: apply_transitions only reads it, and `saved` is a copy.
    paths = apply_transitions(saved, settings["crossing_desk"], now)
    row, shared = in_force(saved)
    row = canonical_row(row)
    # Every desktop peer is captured, whether or not this machine sends to it, so an edit made while
    # sending is off is never projected over when it is turned back on.
    current, applied = live_row(saved, send_only=False), canonical_row(own.get("applied", {}))
    edits = {peer: value for peer, value in current.items() if peer in applied and value != applied[peer]}
    updates = {peer: value for peer, value in current.items() if peer not in row}
    updates.update(edits)
    if updates:
        if shared:
            updated = {**row, **updates}
            paths.append(put_row(saved, active, machine, updated, now))
            row = updated
        else:
            if edits:
                _archive_edit(saved, row, "own", now)
            row.update(copy.deepcopy(updates))
            own["row"] = row
    entries = {entry["id"]: entry for entry in saved.get("peers", [])
               if isinstance(entry, dict) and ways._zoned(entry) and entry.get("send", True) is True}
    for peer, intent in row.items():
        if peer in entries:
            entries[peer]["ways"] = copy.deepcopy(intent["ways"])
            entries[peer]["ways"]["notch"] = platform == "mac" and intent["ways"]["notch"]
            entries[peer]["notch_return"] = intent["notch_return"]
    # One notch, by exactly the rule every crossing event applies first (crossing_state._initial):
    # ways.notch_holder, the first machine in peer order that is in use, not left out and not dormant.
    # A different rule here would have each event untick what this ticks, and the next reconcile would
    # take that for a person's edit.
    holder = ways.notch_holder(saved)
    if holder is not None:
        for entry in saved.get("peers", []):
            if ways._zoned(entry) and entry.get("id") != holder and isinstance(entry.get("ways"), dict):
                entry["ways"]["notch"] = False
    changed = live_row(saved, send_only=False) != current
    if changed:
        layout = saved.get("layout") or ways.derive_layout(saved)
        result = ways.compile_layout(saved, layout, platform=platform, capable=capable,
                                     live=live, gone=gone, now=now)
        if result.get("accepted"):
            saved = result["settings"]
            own, desk = saved["crossing_own"], saved["crossing_desk"]
    own["applied"] = live_row(saved, send_only=False)
    peer_ids = {p.get("id") for p in saved.get("peers", []) if isinstance(p, dict)}
    held_row = desk["profiles"][active].get("rows", {}).get(machine)
    value = {"app": app, "platform": platform, "in_force": "desk" if shared else "own", "profile": active,
             "row": [held_row["set_at"], held_row["by"]] if shared and held_row else None,
             "waiting": [peer for peer in row if peer not in peer_ids]}
    held = desk["status"].get(machine)
    if held is None or held.get("value") != value:
        desk["status"][machine] = register(value, now, machine, held)
        paths.append(("status", machine))
    return saved, list(dict.fromkeys(paths))


def reconciled(settings, *, platform, app=APP_VERSION):
    """True only when reconcile would give these settings back as they are (by ==) and send nothing:
    reconcile's own steps, read without copying. A machine relaying a burst meets this on nearly
    every message, and reconcile's copy of the whole settings was most of what each one cost. False
    whenever any step would write, so the caller runs reconcile itself."""
    if "crossing_own" not in settings or settings.get(UPGRADE_PENDING):
        return False
    own, desk = settings["crossing_own"], settings["crossing_desk"]
    active, machine = desk["active"]["value"], settings.get("machine_id", "")
    profile = desk["profiles"].get(active)
    if not isinstance(profile, dict) or not isinstance(profile.get("rows"), dict):
        return False
    # apply_transitions, with nothing having changed since: only seeding this machine's row.
    if desk["on"]["value"] is True and profile["rows"].get(machine) is None:
        return False
    row, shared = in_force(settings)
    row = canonical_row(row)
    current, applied = live_row(settings, send_only=False), canonical_row(own.get("applied", {}))
    if any(peer not in row or peer in applied and value != applied[peer] for peer, value in current.items()):
        return False
    # The in-force row projected onto the peers, then the notch unticked from all but its holder.
    entries = {entry["id"]: entry for entry in settings.get("peers", [])
               if isinstance(entry, dict) and ways._zoned(entry) and entry.get("send", True) is True}
    for peer, intent in row.items():
        entry = entries.get(peer)
        if entry is None:
            continue
        projected = {**intent["ways"], "notch": platform == "mac" and intent["ways"]["notch"]}
        if entry.get("ways") != projected or entry.get("notch_return", None) != intent["notch_return"]:
            return False
    holder = ways.notch_holder(settings)
    if holder is not None and any(
            ways._zoned(entry) and entry.get("id") != holder and isinstance(entry.get("ways"), dict)
            and entry["ways"].get("notch") is not False for entry in settings.get("peers", [])):
        return False
    if own.get("applied") != current:
        return False
    peer_ids = {p.get("id") for p in settings.get("peers", []) if isinstance(p, dict)}
    held_row = profile["rows"].get(machine)
    value = {"app": app, "platform": platform, "in_force": "desk" if shared else "own", "profile": active,
             "row": [held_row["set_at"], held_row["by"]] if shared and held_row else None,
             "waiting": [peer for peer in row if peer not in peer_ids]}
    held = desk.get("status", {}).get(machine)
    return held is not None and held.get("value") == value


def _profile_id(value):
    return value == DESK_ID or protocol.read_id(value) is not None


def _valid_stamp(reg, now):
    if not isinstance(reg, dict) or type(reg.get("set_at")) is not int:
        return False
    stamp, by = reg["set_at"], reg.get("by")
    return (0 <= stamp <= settings_sync.MAX_STAMP and stamp <= now + AHEAD
            and (by == "" and stamp == 0 or protocol.read_id(by) is not None))


def _valid_row(row):
    if not isinstance(row, dict) or len(row) > 32:
        return False
    for peer, entry in row.items():
        if protocol.read_id(peer) is None or not isinstance(entry, dict) or not isinstance(entry.get("ways"), dict):
            return False
        intent = entry["ways"]
        if set(entry) - {"ways", "notch_return"} or set(intent) - {"edge", "thirds", "edges", "corner", "corner_at", "corners", "notch"}:
            return False
        if any(type(intent[key]) is not bool for key in ("edge", "corner", "notch") if key in intent):
            return False
        if "notch_return" in entry and type(entry["notch_return"]) is not bool:
            return False
        for key, choices in (("thirds", ways.PARTS), ("edges", ways.EDGES), ("corners", ways.CORNERS)):
            if key in intent:
                picked = intent[key]
                if (not isinstance(picked, list) or key == "thirds" and not picked
                        or any(not isinstance(v, str) or v not in choices for v in picked)
                        or len(picked) != len(set(picked))):
                    return False
        if "corner_at" in intent and intent["corner_at"] not in ways.CORNERS:
            return False
    return True


def _valid_status(value):
    return (isinstance(value, dict) and "row" in value
            and isinstance(value.get("app"), str) and len(value["app"]) <= 64
            and value.get("platform") in ("mac", "pc", "windows", "linux")
            and value.get("in_force") in ("own", "desk") and _profile_id(value.get("profile"))
            and isinstance(value.get("waiting"), list) and len(value["waiting"]) <= 32
            and all(protocol.read_id(peer) is not None for peer in value["waiting"])
            and (value.get("row") is None or isinstance(value["row"], list) and len(value["row"]) == 2
                 and type(value["row"][0]) is int and 0 <= value["row"][0] <= settings_sync.MAX_STAMP
                 and (value["row"][1] == "" or protocol.read_id(value["row"][1]) is not None)))


def _picture(reg):
    tiles = reg.get("tiles")
    if not isinstance(tiles, dict) or len(tiles) > 33:
        return None
    result = {}
    for peer, tile in tiles.items():
        if (protocol.read_id(peer) is None or not isinstance(tile, dict)
                or any(type(tile.get(key)) is not int for key in ("x", "y", "w", "h"))
                or tile["w"] <= 0 or tile["h"] <= 0):
            return None
        result[peer] = {key: tile[key] for key in ("x", "y", "w", "h")}
        offsets = tile.get("display_offsets", {})
        if (not isinstance(offsets, dict) or len(offsets) > 16 or any(
            not isinstance(key, str) or not key.isascii() or not 1 <= len(key) <= 64
            or not isinstance(offset, dict) or any(type(offset.get(k)) is not int for k in ("x", "y"))
            for key, offset in offsets.items())):
            return None
        if offsets:
            result[peer]["display_offsets"] = {key: {k: offset[k] for k in ("x", "y")}
                                              for key, offset in offsets.items()}
    return {"set_at": reg["set_at"], "by": reg["by"], "tiles": result}


def _paths(desk):
    for key in ("on", "active"):
        if key in desk:
            yield (key,), desk[key]
    for pid, profile in desk.get("profiles", {}).items():
        for key in ("name", "removed", "picture"):
            if profile.get(key) is not None:
                yield (key, pid), profile[key]
        for key, value in profile.get("home", {}).items():
            yield ("home", pid, key), value
        for machine, row in profile.get("rows", {}).items():
            yield ("row", pid, machine), row
    for machine, status in desk.get("status", {}).items():
        yield ("status", machine), status


def _nest(path, value):
    """`value` alone at `path`, shaped as _store would place it in an empty desk, not copied."""
    kind = path[0]
    if kind in ("on", "active"):
        return {kind: value}
    if kind == "status":
        return {"status": {path[1]: value}}
    if kind in ("row", "home"):
        return {"profiles": {path[1]: {"rows" if kind == "row" else "home": {path[2]: value}}}}
    return {"profiles": {path[1]: {kind: value}}}


def _store(desk, path, value):
    kind = path[0]
    if kind in ("on", "active"):
        desk[kind] = copy.deepcopy(value)
    elif kind == "status":
        desk.setdefault("status", {})[path[1]] = copy.deepcopy(value)
    else:
        profile = desk.setdefault("profiles", {}).setdefault(path[1], {})
        if kind in ("row", "home"):
            profile.setdefault("rows" if kind == "row" else "home", {})[path[2]] = copy.deepcopy(value)
        else:
            profile[kind] = copy.deepcopy(value)


def changed_paths(before, after):
    """The register paths whose register differs between two desks (each a desk_message), for
    sending whatever changed a desk, whichever event changed it."""
    held = dict(_paths(before or {}))
    return [path for path, register in _paths(after or {}) if held.get(path) != register]


def desk_message(settings, paths=None):
    desk = settings.get("crossing_desk", {})
    if paths is None:
        return copy.deepcopy({key: value for key, value in desk.items() if key != "format"})
    selected = {tuple(path) for path in paths}
    result = {}
    for path, value in _paths(desk):
        if path in selected:
            _store(result, path, value)
    return result


def read_desk_state(data, now=None):
    now = _now(now)
    if not settings_sync._valid_envelope(data, now):
        return None
    desk = data.get("desk")
    if not isinstance(desk, dict):
        return None
    try:
        if len(_json(desk)) > MAX_DESK_BYTES:
            return None
    except (TypeError, ValueError, UnicodeError):
        return None
    clean = {}
    # Structural containers are checked before walking them; each leaf stands alone.
    source = {key: desk[key] for key in ("on", "active") if key in desk}
    source["status"] = desk.get("status") if isinstance(desk.get("status"), dict) else {}
    source["profiles"] = {}
    if isinstance(desk.get("profiles"), dict):
        for pid, profile in desk["profiles"].items():
            if not _profile_id(pid) or not isinstance(profile, dict):
                continue
            source["profiles"][pid] = {key: profile[key] for key in ("name", "removed", "picture") if key in profile}
            for key in ("home", "rows"):
                if isinstance(profile.get(key), dict):
                    source["profiles"][pid][key] = profile[key]
    for path, reg in _paths(source):
        if not _valid_stamp(reg, now):
            continue
        kind, value = path[0], reg.get("value")
        good = False
        if kind == "on":
            good = type(value) is bool
        elif kind == "active":
            good = _profile_id(value)
        elif kind == "name":
            good = isinstance(value, str) and 1 <= len(value.strip()) <= 32
            if good:
                value = value.strip()
        elif kind == "removed":
            _store(clean, path, {"set_at": reg["set_at"], "by": reg["by"]})
            continue
        elif kind == "home":
            good = (path[2] == "shake" and type(value) is bool
                    or path[2] == "sensitivity" and type(value) is int and 50 <= value <= 200)
        elif kind == "row":
            good = protocol.read_id(path[2]) is not None and _valid_row(value)
            if good:
                value = canonical_row(value)
        elif kind == "status":
            good = protocol.read_id(path[1]) is not None and reg["by"] == path[1] and _valid_status(value)
            if good:
                value = {key: value[key] for key in ("app", "platform", "in_force", "profile", "row", "waiting")}
        elif kind == "picture":
            picture = _picture(reg)
            if picture is not None:
                _store(clean, path, picture)
            continue
        if good:
            _store(clean, path, {"value": copy.deepcopy(value), "set_at": reg["set_at"], "by": reg["by"]})
    return clean


def _sort_incoming(desk, incoming, gone, machine):
    """The incoming registers merge_desk takes, each with its register, and the paths it answers
    because this desk holds them newer. Read only."""
    held = dict(_paths(desk))
    taken, answer = [], []
    for path, reg in _paths(incoming):
        if path[0] not in ("on", "active", "status") and path[1] in gone:
            continue
        old = held.get(path)
        if path == ("active",) and reg["value"] in gone:
            if _pair(reg) > _pair(old):
                taken.append((path, reg))
            answer.append(path)
        elif path[0] == "status" and path[1] == machine:
            if old is not None and _pair(old) > _pair(reg):
                answer.append(path)
        elif _pair(reg) > _pair(old):
            taken.append((path, reg))
        elif _pair(old) > _pair(reg):
            answer.append(path)
    return taken, answer


def merge_desk(settings, state, *, source, now=None, borrow=False):
    """Take the newer registers of a desk `state` from `source`: (settings, paths, forward, answer,
    accepted, reason). With `borrow`, a merge that changes nothing hands back `settings` itself, not
    a copy, for a caller that copies what it keeps."""
    now = _now(now)
    unchanged = (lambda: settings) if borrow else (lambda: copy.deepcopy(settings))
    entry = ways._entry(settings, source)
    if (entry is None or entry.get("allow_drive") is not True or entry.get("linked") is not True
            or peerlist.dormant_reason(entry) is not None):
        return unchanged(), [], {}, {}, False, "not_allowed"
    incoming = read_desk_state({"on": False, "set_at": 0, "by": "", "desk": state}, now)
    if incoming is None:
        return unchanged(), [], {}, {}, False, "invalid_desk"
    machine, gone = settings.get("machine_id", ""), set(pruned(settings))
    # The caller's desk is the one before: nothing below writes to `settings`.
    before = settings["crossing_desk"]
    taken, answer = _sort_incoming(before, incoming, gone, machine)
    active = before["active"]["value"]
    if (not taken and active in before["profiles"] and len(before["profiles"]) <= MAX_HELD
            and all(isinstance(p, dict) and "rows" in p and "home" in p for p in before["profiles"].values())
            and not (before["on"]["value"] is True and before["profiles"][active]["rows"].get(machine) is None)):
        # A duplicate or a stale register, the most of what a mesh relays: the full path below would
        # copy everything only to change nothing (no container to add, nothing to prune or seed).
        return unchanged(), [], {}, desk_message(settings, answer), True, ""
    saved = copy.deepcopy(settings)
    desk = saved["crossing_desk"]
    held = dict(_paths(before))
    for path, reg in taken:
        if path == ("active",) and reg["value"] in gone:
            desk["active"] = register(desk["active"]["value"], now, machine, held=desk["active"],
                                      floor=reg["set_at"] + 1)
            continue
        old = held.get(path)
        if path[0] == "row" and path[2] == machine and old is not None:
            archive(saved, old["value"], "replaced_by", now, by=reg["by"])
            saved["crossing_own"].setdefault("editing", {}).pop(path[1], None)
        _store(desk, path, reg)
    taken = [path for path, _ in taken]
    # Independently forwarded deltas can precede the profile's name/home. Keep
    # their active stamp and an empty container so later metadata can complete it.
    active = desk["active"]["value"]
    desk["profiles"].setdefault(active, {"rows": {}, "home": {}})
    for profile in desk["profiles"].values():
        profile.setdefault("rows", {})
        profile.setdefault("home", {})
    # MAX_PROFILES limits making one here; two machines apart can each make one, and their union is
    # still taken, or the desk could never agree. Tombstones past MAX_HELD go oldest first, by the
    # same rule on every machine, so MAX_HELD only stops a peer flooding the file with live ones.
    prune_removed(saved, MAX_HELD)
    if len(desk["profiles"]) > MAX_HELD:
        return unchanged(), [], {}, {}, False, "desk_full"
    forward = desk_message(saved, taken)
    reply = desk_message(saved, answer)
    paths = apply_transitions(saved, before, now)
    return saved, paths, forward, reply, True, ""


def _shelved_peers(settings):
    return {entry.get("id") for entry in settings.get("peers", [])
            if entry.get("left_out") is True or entry.get("in_use", True) is False
            or peerlist.dormant_reason(entry) is not None}


def machines_on_desk(settings):
    shelved = _shelved_peers(settings)
    found = [settings.get("machine_id", "")]
    found.extend(entry.get("id") for entry in settings.get("peers", [])
                 if ways._zoned(entry) and entry.get("id") not in shelved)
    desk = settings.get("crossing_desk", {})
    found.extend(desk.get("status", {}))
    for pid, profile in desk.get("profiles", {}).items():
        if not removed(desk, pid):
            found.extend(profile.get("rows", {}))
            for row in profile.get("rows", {}).values():
                found.extend(row.get("value", {}))
    return list(dict.fromkeys(peer for peer in found if peer and peer not in shelved))


def view_row(settings, machine):
    if machine == settings.get("machine_id"):
        return copy.deepcopy(in_force(settings)[0])
    desk = settings["crossing_desk"]
    return copy.deepcopy(desk["profiles"][desk["active"]["value"]].get("rows", {}).get(machine, {}).get("value", {}))


def view_platform(settings, machine):
    """"mac" or "pc", for drawing a machine's row: its own status says, else this machine's guess."""
    if machine == settings.get("machine_id"):
        return "mac" if settings.get("crossing_desk", {}).get("status", {}).get(machine, {}).get(
            "value", {}).get("platform") == "mac" else "pc"
    status = settings.get("crossing_desk", {}).get("status", {}).get(machine, {}).get("value", {})
    if status.get("platform"):
        return "mac" if status["platform"] == "mac" else "pc"
    return "mac" if (ways._entry(settings, machine) or {}).get("platform") in ("mac", "macos") else "pc"


def view_settings(settings, machine):
    """Settings shaped as `machine` would hold them, so its desk row is drawn by the same ledger and
    ways.reach as this machine's own: its id, the shared picture, and one entry per other machine in
    the picture carrying that row's ways. Built field by field: no token, address or permission."""
    if machine == settings.get("machine_id"):
        return copy.deepcopy(settings)
    row = view_row(settings, machine)
    # Machines not yet in the stored picture sit where the derived layout puts them, as the map
    # and ways.reach draw them, so none drops out of another machine's view.
    layout = {**ways.derive_layout(settings, gap=0), **copy.deepcopy(settings.get("layout", {}))}
    peers = []
    shelved = _shelved_peers(settings)
    for ident in layout:
        if ident == machine:
            continue
        intent = row.get(ident) or {"ways": ways._read_intent({"peers": []}, ident), "notch_return": False}
        contact = ways._rect_contact(layout[machine], layout[ident]) if machine in layout else None
        peers.append({"id": ident, "name": _name(settings, ident), "port": 24820, "send": True,
                      "allow_drive": True, "in_use": True,
                      **({"left_out": True} if ident in shelved else {}),
                      "side": contact[0] if contact and contact[0] in ways.EDGES else "",
                      "ways": copy.deepcopy(intent["ways"]), "notch_return": intent.get("notch_return") is True})
    return {"schema": 6, "machine_id": machine, "name": _name(settings, machine), "peers": peers,
            "zones": [], "layout": layout, "layout_set_at": settings.get("layout_set_at", 0),
            "layout_by": settings.get("layout_by", "")}


def tile_word(settings, machine, *, linked, caps):
    """The status word on a machine's tile while Same ways is on: Desk, Own, Offline, or Older for a
    machine without profiles. Empty while Same ways is off."""
    if not same_ways_on(settings):
        return ""
    if machine == settings.get("machine_id"):
        return tr("Desk") if in_force(settings)[1] else tr("Own")
    if "profiles" not in caps:
        # Translators: on a map tile, a machine running a Beamer too old to share ways. Keep it short.
        return tr("Older")
    if not linked:
        return tr("Offline")
    status = settings.get("crossing_desk", {}).get("status", {}).get(machine, {}).get("value", {})
    return tr("Own") if status.get("in_force") == "own" else tr("Desk")


def _name(settings, machine):
    if machine == settings.get("machine_id"):
        return settings.get("name") or tr("This machine")
    entry = ways._entry(settings, machine) or {}
    tile = settings.get("layout", {}).get(machine, {})
    return peerlist._name(entry) or tile.get("name") or machine


def machine_line(settings, machine, *, linked, caps, last_heard):
    """The line under a machine's name on the Crossing page. Its status is restamped only when it
    changes, so `last_heard` is the time its link came up only while no desk message has arrived
    from it on that link; the caller passes None once one has."""
    if "profiles" not in caps:
        return tr("An older Beamer. Its ways are set on it; update it to set them here. Read only")
    if not linked:
        return tr("Offline. It takes these when it next connects")
    desk = settings["crossing_desk"]
    status = desk.get("status", {}).get(machine)
    if status is None:
        return tr("Sending…")
    if isinstance(last_heard, (int, float)) and status["set_at"] < last_heard:
        # This machine's own clock: zoneinfo needs tzdata, which Windows' Python does not ship.
        when = time.strftime("%d-%m-%Y %H:%M", time.localtime(status["set_at"]))
        return tr("Last heard {time}").format(time=when)
    value = status["value"]
    if value.get("in_force") == "own":
        return tr("Keeps its own ways. The desk's are saved for when it uses them")
    if value.get("waiting"):
        return tr("Needs pairing with {name}").format(name=joined([_name(settings, p) for p in value["waiting"]]))
    row = desk["profiles"][desk["active"]["value"]].get("rows", {}).get(machine)
    if (row is None or value.get("profile") != desk["active"]["value"]
            or value.get("row") != [row["set_at"], row["by"]]):
        return tr("Sending…")
    if machine == settings.get("machine_id"):
        off = [p for p in row["value"] if (ways._entry(settings, p) or {}).get("send") is False]
        if off:
            return tr("{name} is off on that machine").format(name=joined([_name(settings, p) for p in off]))
    return tr("Uses the desk's ways")


def no_way_back(settings, machine):
    desk = settings["crossing_desk"]
    status = desk.get("status", {})
    def known_row(ident):
        value = status.get(ident, {}).get("value")
        if ident != settings.get("machine_id") and not value and not view_row(settings, ident):
            # Neither a status nor a desk row (Same ways off, an older Beamer): unknown, not a wall.
            return None
        if ident != settings.get("machine_id") and value:
            if value.get("in_force") == "own":
                return None  # Own rows never travel; absence of knowledge is not a wall.
            reg = desk["profiles"].get(value.get("profile"), {}).get("rows", {}).get(ident)
            if reg is None or value.get("row") != [reg["set_at"], reg["by"]]:
                return None
            return reg["value"]
        return view_row(settings, ident)
    def zones_from(ident):
        row = known_row(ident)
        if row is None:
            return None
        peers = []
        shelved = _shelved_peers(settings)
        for peer, intent in row.items():
            entry = {"id": peer, "port": 24820, "send": True, **copy.deepcopy(intent)}
            if ident == settings.get("machine_id"):
                actual = ways._entry(settings, peer)
                if actual is None or actual.get("send", True) is False:
                    continue
                for key in ("send", "in_use", "left_out", "side", "dormant"):
                    if key in actual:
                        entry[key] = actual[key]
                if peerlist.dormant_reason(actual) is not None:
                    entry["in_use"] = False
            elif peer in shelved:
                entry["left_out"] = True
            peers.append(entry)
        synthetic = {"machine_id": ident, "peers": peers, "layout": copy.deepcopy(settings.get("layout", {}))}
        platform = status.get(ident, {}).get("value", {}).get("platform", "pc")
        compiled = ways.compile_layout(synthetic, synthetic["layout"], platform=platform,
                                       capable=set(synthetic["layout"]), now=0)
        return [zone for zone in compiled.get("settings", {}).get("zones", []) if not zone.get("off")]
    outgoing = zones_from(machine)
    if outgoing is None:
        return []
    result = []
    for target in dict.fromkeys(zone["peer"] for zone in outgoing):
        back = zones_from(target)
        if back is not None and not any(zone.get("peer") == machine and zone.get("kind") in ("edge", "part")
                                        for zone in back):
            result.append(_name(settings, target))
    return result


def saved_list(settings):
    return sorted(copy.deepcopy(settings.get("crossing_own", {}).get("saved", [])),
                  key=lambda entry: entry["at"], reverse=True)


def shake_on(settings):
    if not same_ways_on(settings):
        return settings["crossing_own"]["shake"] is True
    desk = settings["crossing_desk"]
    return desk["profiles"][desk["active"]["value"]].get("home", {}).get("shake", {}).get("value", True) is True


def shake_sensitivity(settings):
    if not same_ways_on(settings):
        value = settings.get("crossing_own", {}).get("shake_sensitivity", 100)
    else:
        desk = settings.get("crossing_desk", {})
        profile = desk.get("profiles", {}).get(desk.get("active", {}).get("value"), {})
        value = profile.get("home", {}).get("sensitivity", {}).get("value", 100)
    return value if type(value) is int and 50 <= value <= 200 else 100


def profile_list(settings):
    profiles = settings["crossing_desk"]["profiles"]
    desk = settings["crossing_desk"]
    active = {pid: p for pid, p in profiles.items() if not removed(desk, pid) and p.get("name")}
    result = []
    for pid, profile in active.items():
        name = profile["name"]["value"]
        stamps = [reg["set_at"] for _, reg in _paths({"profiles": {pid: profile}}) if reg["set_at"]]
        made = min(stamps, default=0)
        label = name
        if sum(p["name"]["value"] == name for p in active.values()) > 1:
            date = time.strftime("%d-%m-%Y", time.localtime(made))
            label = tr("{name} · {date}").format(name=name, date=date)
        result.append({"id": pid, "name": name, "label": label, "made": made})
    return result
