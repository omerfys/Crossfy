"""The control window's pages, and which carry a dot in the sidebar.

Pure, so the rules are tested without Qt.
"""

from __future__ import annotations

import re
import threading
import time

from core import effects
from core import peerlist
from core.i18n import N_, joined, tr, trc
from core.ways import CORNER_NAMES_LOWER, EDGE_NAMES, part_names, parts_phrase, toggle_part

# (key, name, what the page is for), in sidebar order, which is setup order; Ctrl+1 is the first.
PAGES = (
    ("overview", N_("Overview"),
     N_("The machines paired with this PC, where input is right now, and the controls you reach for "
     "every day. Pair a machine here first.")),
    ("crossing", N_("Crossing"),
     N_("Choose how the pointer or a key moves input to each machine, and how hard the edge "
     "pushes back first.")),
    ("keyboard", N_("Keyboard"),
     N_("How this PC's Ctrl and Windows keys arrive on another machine, the keys and buttons that stay "
     "here, and how fast another machine's pointer moves here.")),
    ("design", N_("Design"),
     N_("How crossing looks on this PC: the light as you push toward another machine, and where the "
     "pointer lands.")),
    ("connection", N_("Connection"),
     N_("This PC's network access, address and listening port; hide addresses in this window and tray.")),
)
KEYS = tuple(page[0] for page in PAGES)
# Under the purpose on the pages whose settings are this PC's alone, so nobody looks for another
# machine's on the PC: each app sets only its own machine.
SCOPE = {
    "crossing": N_("Ways below lead to the selected machine. Its side is shared with that machine. Resistance, drag protection and Shortcut apply to this PC's input for every destination."),
    "design": N_("Used on this screen. Shared animation settings may follow another machine; Animate and window appearance stay on this PC."),
    "keyboard": N_("Modifier keys and Stays here belong to this PC's input. Pointer speed and scrolling belong to this screen when another machine drives it. Every machine keeps its own."),
}
# With Same on all machines on, under each row of the shared pages that stays this PC's own.
OWN_ROW = N_("This PC only.")
# The window's footer; the first sentence goes on Connection, whose changes wait for its button.
FOOTER_APPLY = N_("Changes apply as you make them.")
FOOTER_TRAY = N_("Closing this window keeps Beamer running in the tray.")
FOOTER_BOTH = N_("Changes apply as you make them. Closing this window keeps Beamer running in the tray.")


PERMISSION_STATUS_LABELS = {
    "not_requested": N_("Not requested"), "ready": N_("Ready"),
    "refused": N_("Refused"), "unavailable": N_("Unavailable"),
}


def saved_ways_label(item, settings):
    reasons = {
        "upgrade": N_("Before Beamer 1.5.5"), "older_version": N_("From an older Beamer"),
        "sync_off": N_("When Same ways went off"), "seeded": N_("When Same ways went on"),
        "edited": N_("Before you changed it"), "restored": N_("Before a restore"),
    }
    if item.get("why") == "replaced_by":
        author = item.get("by")
        name = (settings.get("name") if author == settings.get("machine_id") else
                peerlist.label_for(settings.get("peers", []), peer_id=author)) or tr("another machine")
        reason = tr("Before {name} changed it").format(name=name)
    else:
        reason = tr(reasons.get(item.get("why"), N_("Earlier ways")))  # N_ table: saved ways archive reasons
    date = time.strftime("%d-%m-%Y", time.localtime(item.get("at", 0)))
    return tr("{date} · {reason}").format(date=date, reason=reason)


class LinuxPermissionState:
    """The two Wayland portal rows, independent of Qt and D-Bus."""

    STATUSES = {"not_requested", "ready", "refused", "unavailable"}
    DIRECTIONS = {"capture", "remote"}

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows = {direction: ("not_requested", "", False) for direction in self.DIRECTIONS}
        self._requesters = {}
        self.on_change = None

    def status(self, direction: str) -> tuple[str, str]:
        with self._lock:
            return self._rows[direction][:2]

    def can_ask_again(self, direction: str) -> bool:
        with self._lock:
            return self._rows[direction][2]

    def bind_requester(self, direction: str, request) -> None:
        with self._lock:
            self._requesters[direction] = request

    def report(self, direction: str, status: str, detail: str = "", retryable: bool = False) -> None:
        if direction not in self.DIRECTIONS or status not in self.STATUSES:
            raise ValueError("Unknown Linux permission row or status")
        value = (status, detail if status in ("refused", "unavailable") else "",
                 status == "refused" or retryable)
        with self._lock:
            self._rows[direction] = value
            changed = self.on_change
        if changed is not None:
            changed(direction, *value)

    def ask_again(self, direction: str) -> bool:
        with self._lock:
            if not self._rows[direction][2]:
                return False
            request = self._requesters.get(direction)
            if request is None:
                return False
        self.report(direction, "not_requested")
        request()
        return True


def linux_permissions_visible(platform: str, wayland: bool) -> bool:
    return platform.startswith("linux") and wayland


def footer(page: str) -> str:
    return tr(FOOTER_TRAY if page == "connection" else FOOTER_BOTH)


def dots(config_error: bool, firewall_tone: str | None, dormant: bool = False) -> dict:
    """Page key to the tone of its sidebar dot, for the pages that need one.

    `firewall_tone` is the note tone Connection's firewall module is already showing -- "note" is
    its healthy end-state (the button just offers a manual re-check), so only "note-amber" and
    "note-fault" earn a dot; a plain boolean would also mark the healthy state. Both problems sit
    on Connection, and a fault outranks amber. A dormant pairing marks Overview and Crossing amber."""
    marks = {}
    if config_error or firewall_tone == "note-fault":
        marks["connection"] = "fault"
    elif firewall_tone == "note-amber":
        marks["connection"] = "amber"
    if dormant:
        marks.update({"overview": "amber", "crossing": "amber"})
    return marks


# The Design page's styles and colours: Light first, then each crossing effects direction in
# effects.DIRECTIONS order. Light's Glow, Beam and Aperture draw this PC's edge or corner as the pointer
# leaves; the effects draw the departure and the arrival, at an edge, a corner or the Mac's notch.
CLASSIC = N_("Light")
TODAY_STYLES = (
    ("glow", N_("Glow"), N_("A band of light that deepens the harder you push.")),
    ("beam", N_("Beam"), N_("A thin line with a comet of light running along it.")),
    ("aperture", N_("Aperture"), N_("A fine lens of light opens under pressure and closes softly behind the arriving pointer.")),
)
TODAY_COLOURS = (("signal", N_("Signal")), ("colourful", N_("Colourful")), ("ocean", N_("Ocean")),
                 ("sunset", N_("Sunset")), ("mono", N_("Mono")), ("aurora", N_("Aurora")))


def effects_load_error():
    """None when every crossing effect loads, else the exception: the Design page then offers only
    Light's styles and colours rather than failing to build, and Beamer still starts."""
    try:
        effects._load()
    except Exception as exc:
        return exc
    return None


def style_groups() -> tuple:
    """(group title, ((style id, name, detail), ...)) in the page's order. An effect's detail is
    its intensity: quiet, medium or showpiece."""
    # Glow and Beam's detail is their kind, as an effect's is its intensity; what they do is said
    # under the preview.
    if effects_load_error() is not None:
        return ((CLASSIC, tuple((value, name, effects.intensity_name(effects.CLASSIC[value].intensity))
                               for value, name, _blurb in TODAY_STYLES[:2])),)
    groups = [(CLASSIC, tuple((value, name, effects.intensity_name(effects.CLASSIC[value].intensity))
                              for value, name, _blurb in TODAY_STYLES))]
    for _module, title, effect_ids, _packs in effects.DIRECTIONS:
        found = [effects.effect(effect_id) for effect_id in effect_ids]
        groups.append((title, tuple((fx.id, fx.name, effects.intensity_name(fx.intensity)) for fx in found)))
    return tuple(groups)


def colour_groups() -> tuple:
    """(group title, ((colour id, name), ...)) in the page's order, grouped as the styles are."""
    return tuple((title, tuple(choices)) for title, choices in
                 effects.colour_groups(TODAY_COLOURS, effects_load_error() is None))


def is_effect(style: str) -> bool:
    """Whether `style` is one of the crossing effects, which draw the arrival as well as the push."""
    return style in effects.EFFECT_IDS

PLACES = {"edge": "the edge", "corner": "a corner"}


def preview_place(methods) -> str:
    """Where the Design page's preview opens: the first of this PC's ways in it can show, Part of
    the edge shown as the edge, or the edge when the only way in is the shortcut."""
    chosen = set(methods)
    if chosen & {"edge", "part"}:
        return "edge"
    return "corner" if "corner" in chosen else "edge"


def place_note(style: str, place: str, methods) -> str:
    """The line under Show at: why nothing would cross at `place`, or empty when it does."""
    ways = {"edge": {"edge", "part"}, "corner": {"corner"}}[place]
    if set(methods) & ways:
        return ""
    return tr("{place} is not one of this PC's ways in, so this only shows how it would look. Turn it on under Crossing.").format(
        place=PLACES[place].capitalize())



def share_sentence(holders, side, name):
    """Name the machines already using the side the chosen machine wants."""
    names = joined(holders)
    if len(holders) == 1:
        # Translators: {side} is the direction of the screen edge.
        return tr("{names} already crosses from the {side} edge of this PC. The thirds you pick go to {name}; the rest stay with {holder}.").format(
            names=names, side=tr(EDGE_NAMES.get(side, side)) if side in EDGE_NAMES else side, name=name, holder=holders[0])
    # Translators: {side} is the direction of the screen edge.
    return tr("{names} already cross from the {side} edge of this PC. The thirds you pick go to {name}; the rest stay where they are.").format(
        names=names, side=tr(EDGE_NAMES.get(side, side)) if side in EDGE_NAMES else side, name=name)


# The Crossing page's ways in, in the page's order. Edge and Part of the edge are two readings of
# one edge, so choosing either drops the other.
WAYS = ("shortcut", "edge", "part", "corner")
EXCLUSIVE_WAYS = ("edge", "part")


def toggle_way(methods, way, on) -> list:
    """`methods` with `way` turned on or off, in WAYS order."""
    chosen = {method for method in methods if method != way}
    if on:
        if way in EXCLUSIVE_WAYS:
            chosen -= set(EXCLUSIVE_WAYS)
        chosen.add(way)
    return [method for method in WAYS if method in chosen]


def not_learned_edge(name: str = "the other machine") -> str:
    """Under Where it is, while this PC holds no side for the machine named."""
    return tr("Not learned yet: choose a side here or on {name}.").format(name=name)


def crossing_machines(peers: list) -> list:
    """(id, label) for every paired machine a zone can lead to, in the list's order: never a phone,
    which is never dialled (WIRE.md section 5). The entry migrated from 1.4.x has the id ""."""
    labels = peerlist.labels(peers)
    return [(entry.get("id") or "", labels[entry["token"]]) for entry in peers
            if entry.get("in_use", True) is True and entry.get("port") != 0]


def crossing_state_sentence(paired, heard, sending, connected, armed, paused, full_screen_app, name="the other machine") -> str:
    """The Crossing page's line under Pause: why nothing can cross, first match wins, and only then
    whether crossing is on, held or paused. `name` is the machine it is about."""
    if not paired:
        return tr("Not paired yet, so no edge or shortcut moves input until you pair a machine above.")
    if not heard:
        return tr("Waiting to hear from {name}. This PC cannot push into it until it has connected once.").format(name=name)
    if not sending:
        return tr("This PC does not drive {name}, so edges and the shortcut do nothing.").format(name=name)
    if not connected:
        return tr("Not connected to {name}, so edges and the shortcut do nothing yet. Check that it is switched on and lets this PC drive it.").format(name=name)
    if not armed:
        return tr("Only the shortcut is switched on; there is nothing to pause.")
    if paused:
        return tr("Pauses pointer crossing through this screen, including another machine's pointer. Shortcuts and jump keys still work. Resets when Beamer restarts.")
    if full_screen_app is not None:
        return tr("Held: an app is full screen.")
    return tr("On. Pause it to lean on an edge without switching.")


def crossing_state_blocked(paired, mac_heard, sending, connected) -> bool:
    """Whether crossing_state_sentence is giving a reason nothing can cross."""
    return not (paired and mac_heard and sending and connected)


def crossing_rows(methods) -> frozenset:
    """The Crossing rows used by these ways; the page may keep the drag guard visible but disabled."""
    methods = set(methods)
    rows = set()
    # Where the Mac sits, which every way in uses: a crossing lands by it, and this PC's edge facing
    # the Mac leads there whatever the Mac's own ways in are.
    rows.add("edge")
    if "part" in methods:
        rows.add("parts")
    if "corner" in methods:
        rows.add("corner")
    if methods & {"edge", "part", "corner"}:
        rows |= {"dragging", "resistance"}
    if "shortcut" in methods:
        rows.add("shortcut")
    return frozenset(rows)


# What a switch into this PC plays, as the Design page's Shortcut and menu tiles: the first group
# stands in for Classic's Glow and Beam, which have no arrival of their own. Named as the Mac's is.
SIMPLE = "Simple"
SWITCH_SIMPLE = (
    ("match", "Same as crossing", "Plays Glow"),
    ("locator", "Ring", "Closes onto the pointer"),
)


def switch_groups() -> tuple:
    """style_groups() for a switch: SWITCH_SIMPLE in place of Classic, then the same directions."""
    if effects_load_error() is not None:
        return ((SIMPLE, SWITCH_SIMPLE),)
    aperture = ((CLASSIC, (("aperture", effects.CLASSIC["aperture"].name,
                           effects.CLASSIC["aperture"].intensity.capitalize()),)),)
    return ((SIMPLE, SWITCH_SIMPLE),) + aperture + style_groups()[1:]


# The Crossing page's "Where your Mac is": the value is the edge of this PC that leads to the Mac.
SIDE_CHOICES = (("left", N_("Left")), ("right", N_("Right")), ("top", N_("Above")), ("bottom", N_("Below")))
# The ways in, as their rows read: the pointer's first, then the shortcut.
WAY_ROWS = (
    ("edge", "Edge", "One whole side"),
    ("corner", "Corner", "Push diagonally into a corner"),
    ("shortcut", "Shortcut", "Press a key to switch input"),
)
CORNER_NAMES = {"top_left": N_("top-left"), "top_right": N_("top-right"), "bottom_left": N_("bottom-left"), "bottom_right": N_("bottom-right")}


def trigger_phrase(key_name: str, style: str) -> str:
    """The shortcut as the arrangement diagram's key cap line reads it: "Right Ctrl, twice"."""
    if style == "hold":
        return tr("{key}, held").format(key=key_name)
    return tr("{key}, twice").format(key=key_name)


SHORTCUT_SEVERAL = N_("The shortcut switches home or to the last available machine; if it is unavailable, another available machine can take input.")


def _or_join(items) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        # Translators: Two ways to move input, offered as alternatives.
        return trc("ways list", "{first} or {last}").format(first=items[0], last=items[1])
    # Translators: Several ways to move input, offered as alternatives.
    return trc("ways list", "{head} or {last}").format(head=", ".join(items[:-1]), last=items[-1])


def ways_summary(methods, edge, parts, corner, key_name, style, name=None, several=False) -> str:
    """The Ways in module's first line: every way input leaves for the machine `name`, in one
    sentence. With `several` machines paired the shortcut is not this one's, so it gets a sentence of
    its own."""
    if name is None:
        name = tr("the other machine")
    methods = set(methods)
    if not edge:
        # A PC's edge, thirds and corner all cross the side it holds; only the shortcut needs none.
        if "shortcut" in methods and not several:
            if style == "hold":
                return tr("Input moves to {name} when you hold {key}. Its edges and corner wait until this PC knows which side {name} is on.").format(name=name, key=key_name)
            return tr("Input moves to {name} when you press {key} twice. Its edges and corner wait until this PC knows which side {name} is on.").format(name=name, key=key_name)
        return tr("Nothing moves input to {name} until this PC knows which side it is on.").format(name=name)
    ways = []
    if "edge" in methods:
        ways.append(tr("push through the whole {edge} edge").format(edge=tr(EDGE_NAMES[edge])))
    if "part" in methods:
        ways.append(tr("push through {parts}").format(parts=parts_phrase(edge, parts)))
    if "corner" in methods:
        ways.append(tr("push diagonally into the {corner} corner").format(
            corner=tr(CORNER_NAMES[corner]) if corner in CORNER_NAMES else corner))
    shortcut = "shortcut" in methods
    if shortcut and not several:
        ways.append(tr("hold {key}").format(key=key_name) if style == "hold" else tr("press {key} twice").format(key=key_name))
    if not ways and several:
        return (tr("No edge or corner leads to {name} yet: choose one below. The shortcut switches home or to the last available machine; if it is unavailable, another available machine can take input.").format(name=name) if shortcut else
                tr("No edge or corner leads to {name} yet: choose one below.").format(name=name))
    if not ways:
        return tr("Nothing moves input to {name}: choose at least one way below.").format(name=name)
    phrase = _or_join(ways)
    if shortcut and several:
        return tr("Input moves to {name} when you {ways}. The shortcut switches home or to the last available machine; if it is unavailable, another available machine can take input.").format(name=name, ways=phrase)
    return tr("Input moves to {name} when you {ways}.").format(name=name, ways=phrase)


def ways_note(methods, edge, parts, corner, key_name, style, name, several=False) -> str:
    methods = set(methods)
    shortcut = tr("Hold {key}").format(key=key_name) if style == "hold" else tr("Double-tap {key}").format(key=key_name)
    pointer = []
    if edge:
        if "part" in methods:
            pointer.append(parts_phrase(edge, parts))
        elif "edge" in methods:
            pointer.append(tr("the {edge} edge").format(edge=tr(EDGE_NAMES[edge])))
    if "corner" in methods:
        pointer_corner = corner or "top_right"
        pointer_name = (tr(CORNER_NAMES_LOWER[pointer_corner]) if pointer_corner in CORNER_NAMES_LOWER
                        else pointer_corner.replace("_", " "))
        pointer.append(tr("the {corner} corner").format(corner=pointer_name))
    if pointer:
        detail = _or_join(pointer)
        action = tr("push through {ways}").format(ways=detail)
        action = tr("push through {ways} to reach {name}").format(ways=detail, name=name) if several else action
        if "shortcut" in methods:
            return tr("{shortcut}, or {action}.").format(shortcut=shortcut, action=action)
        sentence = tr("{action}.").format(action=action)
        return sentence[0].upper() + sentence[1:]
    if "shortcut" in methods:
        return tr("{shortcut}.").format(shortcut=shortcut)
    return tr("This PC is always in the shortcut's cycle.")


def shortcut_destination_note(mode: str, hold: bool) -> str:
    if mode == "last":
        note = tr("With Hold, input goes to the last machine.")
    elif hold:
        note = tr("With Hold, input goes to the first ready machine in order.")
    else:
        note = tr("The order follows the tiles from top to bottom, then left to right. This PC is always in the cycle.")
    if mode == "ticked":
        note += " " + tr("Choose which machines join the cycle with the tick boxes on their tiles.")
    return note


# The arrangement diagram. Each side of this PC has an angle, and a machine's screen travels round
# this PC's between them: through a corner position, never across it.
SIDE_ANGLE = {"right": 0.0, "top": 90.0, "left": 180.0, "bottom": 270.0}
SIDE_WORDS = {"right": N_("to the right of this PC"), "left": N_("to the left of this PC"), "top": N_("above this PC"),
              "bottom": N_("below this PC")}
PART_ORDER = ("start", "middle", "end")


def turn_to(angle: float, side: str) -> float:
    """The angle to animate to from `angle`, which may be part-way through a turn, to reach `side`
    the short way round. Half a turn goes over the top from left or right, and round by the left
    from above or below."""
    delta = (SIDE_ANGLE[side] - angle) % 360.0
    if delta > 180.0:
        delta -= 360.0
    if delta == 180.0:
        current = angle % 360.0
        via = 90.0 if current in (0.0, 180.0) else 180.0
        delta = 180.0 if (current + 90.0) % 360.0 == via else -180.0
    return angle + delta


def square_point(angle: float) -> tuple:
    """Where a ray at `angle` degrees meets the unit square's edge, y up: (1, 0) at 0, (1, 1) at 45."""
    import math

    radians = math.radians(angle)
    x, y = math.cos(radians), math.sin(radians)
    scale = max(abs(x), abs(y))
    return round(x / scale, 9), round(y / scale, 9)


def _thirds_rank(machine: dict) -> int:
    parts = machine.get("parts") or ()
    if "part" in (machine.get("methods") or ()) and any(part in PART_ORDER for part in parts):
        return min(PART_ORDER.index(part) for part in parts if part in PART_ORDER)
    return PART_ORDER.index("middle")


def side_slots(machines: list) -> list:
    """Where each machine's screen sits beside this PC's: (side, start, end), the fractions of that
    side it takes, or None when it has no side. Machines that share a side share its length equally,
    in the order of the thirds they cross by, then of the list."""
    slots = [None] * len(machines)
    by_side: dict = {}
    for index, machine in enumerate(machines):
        if machine.get("side") in SIDE_ANGLE:
            by_side.setdefault(machine["side"], []).append(index)
    for side, indexes in by_side.items():
        order = sorted(indexes, key=lambda index: (_thirds_rank(machines[index]), index))
        for slot, index in enumerate(order):
            slots[index] = (side, slot / len(order), (slot + 1) / len(order))
    return slots


def neighbour_offset(angle: float, start: float, end: float, screen: tuple, gap: float) -> tuple:
    """(centre x, centre y, w, h) of a machine's screen from the centre of this PC's, y down: at `angle`
    round this PC's as `arrangement` placed one, scaled to the share of the side from `start` to `end`
    and moved along it to that share. Through a corner the share's offset fades out, so the screen
    goes round this PC's, never across it."""
    w, h = screen
    share = end - start
    nw, nh = w * share, h * share
    sx, sy = square_point(angle)
    along = (start + end) / 2.0 - 0.5
    cx = sx * (w / 2.0 + gap + nw / 2.0) + along * w * (1.0 - abs(sx))
    cy = -sy * (h / 2.0 + gap + nh / 2.0) + along * h * (1.0 - abs(sy))
    return cx, cy, nw, nh


def layout_rects(width: float, top: float, placed: list, screen: tuple, gap: float, centre_pc: bool = False) -> tuple:
    """(this PC's screen, [each machine's screen], the drawing's height) as (x, y, w, h) rects, for
    `placed` as (angle, start, end) per machine. The drawing is centred across `width` from `top`, or
    with `centre_pc` this PC's screen is, so it stays put while the machines round it move; either way
    it is shrunk whole when it would not fit."""

    def rects(scale):
        w, h, g = screen[0] * scale, screen[1] * scale, gap * scale
        others = []
        for angle, start, end in placed:
            cx, cy, nw, nh = neighbour_offset(angle, start, end, (w, h), g)
            others.append((cx - nw / 2.0, cy - nh / 2.0, nw, nh))
        return (-w / 2.0, -h / 2.0, w, h), others

    def span(pc, others):
        left = min(rect[0] for rect in [pc, *others])
        right = max(rect[0] + rect[2] for rect in [pc, *others])
        # This PC's centre is 0, so centred on it the drawing needs its wider half twice over.
        return (-max(-left, right), max(-left, right)) if centre_pc else (left, right)

    pc, others = rects(1.0)
    left, right = span(pc, others)
    if right - left > width > 0:
        pc, others = rects(width / (right - left))
        left, right = span(pc, others)
    upper = min(rect[1] for rect in [pc, *others])
    lower = max(rect[1] + rect[3] for rect in [pc, *others])
    dx, dy = width / 2.0 - (left + right) / 2.0, top - upper

    def moved(rect):
        return rect[0] + dx, rect[1] + dy, rect[2], rect[3]

    return moved(pc), [moved(rect) for rect in others], lower - upper


def unplaced_line(labels: list) -> str:
    """The line under the diagram naming the machines that have no side yet; "" when none."""
    return tr("Not placed yet: {machines}").format(machines=joined(labels)) if labels else ""


def diagram_description(machines: list, key_name: str, style: str, shortcut: bool) -> str:
    """The diagram's accessible description: where every machine is, then the chosen one's ways in.
    Each machine is a dict with `label`, `side`, `methods`, `parts`, `corner` and `chosen`."""
    placed = [tr("{name} is {position}").format(name=machine["label"], position=tr(SIDE_WORDS[machine["side"]]))
              for machine in machines
              if machine.get("side") in SIDE_WORDS]
    sentences = [tr("{machines}.").format(machines=joined(placed))] if placed else []
    line = unplaced_line([machine["label"] for machine in machines if machine.get("side") not in SIDE_WORDS])
    if line:
        sentences.append(tr("{line}.").format(line=line))
    chosen = next((machine for machine in machines if machine.get("chosen")), machines[0] if machines else None)
    if chosen is not None:
        methods = list(chosen.get("methods") or ()) + (["shortcut"] if shortcut else [])
        sentences.append(ways_summary(methods, chosen.get("side") or "", chosen.get("parts") or (), chosen.get("corner") or "",
                                      key_name, style, chosen["label"], several=len(machines) > 1))
    if len(sentences) == 0:
        return ""
    if len(sentences) == 1:
        return sentences[0]
    if len(sentences) == 2:
        return tr("{first} {second}").format(first=sentences[0], second=sentences[1])
    return tr("{first} {second} {third}").format(first=sentences[0], second=sentences[1], third=sentences[2])


def side_segment(rect: tuple, side: str, start: float = 0.0, end: float = 1.0, inset: float = 0.0) -> tuple:
    """The stretch of `rect`'s `side` from `start` to `end` (fractions, top to bottom or left to
    right, as return_edge's parts run), as a line (x1, y1, x2, y2) `inset` inside the edge."""
    x, y, w, h = rect
    if side in ("left", "right"):
        line_x = x + inset if side == "left" else x + w - inset
        return line_x, y + h * start, line_x, y + h * end
    line_y = y + inset if side == "top" else y + h - inset
    return x + w * start, line_y, x + w * end, line_y


PART_SPANS = {"start": (0.0, 1.0 / 3.0), "middle": (1.0 / 3.0, 2.0 / 3.0), "end": (2.0 / 3.0, 1.0)}


def corner_box(rect: tuple, corner: str, size: float) -> tuple:
    """The `size` square in `rect`'s `corner` ("top_left" and so on)."""
    x, y, w, h = rect
    vertical, horizontal = corner.split("_")
    return (x if horizontal == "left" else x + w - size, y if vertical == "top" else y + h - size, size, size)


RESISTANCE_MAX = 500


def push_depth(resistance: float, track: float) -> float:
    """How far the push strip's fill reaches from the edge: 0 to RESISTANCE_MAX px across `track`."""
    return max(0.0, min(1.0, resistance / RESISTANCE_MAX)) * track


# An IPv4 address or a hardware address, anywhere in a line of text.
_ADDRESS = re.compile(r"\b(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})\b")
HIDDEN = "•••"


def redact(text: str, hide: bool) -> str:
    """`text` with every address in it replaced when `hide` is on."""
    return _ADDRESS.sub(HIDDEN, text) if hide and text else text
