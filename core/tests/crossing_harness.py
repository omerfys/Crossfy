"""End-to-end crossing: two or three desktops on loopback, each a real responder and a real owner,
linked as a full mesh with real pairing tokens and handshakes, whose Crossing pages and maps are
driven as each app drives them, and whose pointers are pushed through every edge and corner.

A desk is one machine:
- `machine`, its core/receiver.LinkResponder (what another desk's input lands on, and the zones
  that send a driven pointer onward or home), with a screen of real display rectangles;
- `hand`, its own keyboard and mouse: core/owner.Owner over one scripted initiator per other desk;
- `shell`, the app around them (crossing_shells.py): what a map drop, a page edit, an incoming
  `arrangement` or `settings`, and a link coming up do to the settings and who is told.

A push is decided by the code that decides it in the product: at home, the Mac's
mac_app/crossing.CrossingEngine or the PC's receiver.zone_models (win_app/sender.py's own path);
on a driven desk, that desk's responder and its armed zones. Assertions are by effect: which desk
holds a hand's input, and where the pointer landed on it.

Platform edges only are faked: the injector, the cursor and the clipboard (responder_harness)."""

import copy
import threading
import time

from core import owner as owner_module
from core import protocol, receiver, return_edge
from core.return_edge import Rect
from core.tests.responder_harness import FakeDesktop, Initiator, Machine, entry, ident, token, wait_for

try:
    from mac_app import crossing as mac_crossing
except ImportError:  # pragma: no cover - mac_app/crossing.py is pure and ships in the tree
    mac_crossing = None

CAPS = ["clipboard", "clipboard_image", "gestures", "media_keys", "text", "settings", "design_sync",
        "layout", "displays", "ping_rtt"]
# The way a push goes through each side, and how hard: well past the 120 px resistance.
PUSH = {"left": (-40, 0), "right": (40, 0), "top": (0, -40), "bottom": (0, 40)}
PUSHES = 8
CORNER_PUSH = {"top_left": (-30, -30), "top_right": (30, -30), "bottom_left": (-30, 30),
               "bottom_right": (30, 30)}
# The fraction along an edge at the middle of each third.
THIRD_AT = {"start": 1 / 6, "middle": 0.5, "end": 5 / 6}


def per_screen_layout(a_id, b_id, *, b1_x=None, a_sizes=((100, 100), (100, 100)),
                      b_sizes=((100, 100), (100, 100))):
    """A0–B0–A1 / B1-below; display offsets move screens beyond the nominal machine tile."""
    a0, a1 = a_sizes
    b0, b1 = b_sizes
    b_x = a0[0]
    a1_x = a0[0]
    b1_x = b_x if b1_x is None else b1_x
    a_tile = {"x": 0, "y": 0, "w": a0[0] + a1[0], "h": max(a0[1], a1[1]), "displays": {
            "0": {"x": 0, "y": 0, "w": a0[0], "h": a0[1]},
            "1": {"x": a1_x, "y": 0, "w": a1[0], "h": a1[1]},
        }, "display_offsets": {"1": {"x": b0[0], "y": 0}}}
    b_tile = {"x": b_x, "y": 0, "w": max(b0[0], b1[0]), "h": b0[1] + b1[1], "displays": {
            "0": {"x": 0, "y": 0, "w": b0[0], "h": b0[1]},
            "1": {"x": 0, "y": b0[1], "w": b1[0], "h": b1[1]},
        }}
    b_offset = b1_x - b_x
    if b_offset:
        b_tile["display_offsets"] = {"1": {"x": b_offset, "y": 0}}
    return {a_id: a_tile, b_id: b_tile}


def key(one, other):
    """The token one pair shares, whichever end asks."""
    low, high = sorted((one, other))
    return token(low[0] * 3 + high[0])


def text(peer):
    return protocol.id_text(peer)


class Screen(FakeDesktop):
    """A desk's displays, keyed as the app keys them (`display_map`)."""

    def __init__(self, displays):
        self.displays = dict(displays)
        first = next(iter(self.displays.values()))
        super().__init__(monitors=list(self.displays.values()),
                         cursor=(first.x + first.width // 2, first.y + first.height // 2))

    def display_map(self):
        return dict(self.displays)

    def point(self, display, side, along=0.5):
        """The pixel on `side` of `display`, `along` of the way down or across it."""
        rect = self.displays[display]
        if side in ("left", "right"):
            y = rect.y + min(rect.height - 1, int(along * rect.height))
            return (rect.x if side == "left" else rect.right, y)
        x = rect.x + min(rect.width - 1, int(along * rect.width))
        return (x, rect.y if side == "top" else rect.bottom)

    def corner(self, display, corner):
        rect = self.displays[display]
        vertical, horizontal = corner.split("_")
        return (rect.x if horizontal == "left" else rect.right, rect.y if vertical == "top" else rect.bottom)

    def on_display(self, point):
        for name, rect in self.displays.items():
            if rect.x <= point[0] <= rect.right and rect.y <= point[1] <= rect.bottom:
                return name
        return None


class Hand:
    """A desk's own keyboard and mouse: every decision core/owner.Owner's, carried out over one
    initiator per other desk. Messages the app sends (`arrangement`, `settings`) go out on these
    links too, and the other desk's responder hands them to its shell."""

    def __init__(self, desk):
        self.desk = desk
        self.owner = owner_module.Owner(text(desk.own), time.monotonic)
        self.links = {}
        self.capabilities = {}
        self.lock = threading.RLock()
        self.sent = []
        self.moved = []
        self._closed = threading.Event()
        self._keep_alive_thread = threading.Thread(target=self._keep_alive, name="hand-pings", daemon=True)
        self._keep_alive_thread.start()

    def _keep_alive(self):
        # core/link.py pings every PING_SECONDS while nothing else is sent; without it the responder
        # ends a quiet link after LINK_READ_TIMEOUT_SECONDS.
        from core.link import PING_SECONDS
        while not self._closed.wait(PING_SECONDS):
            with self.lock:
                for link in list(self.links.values()):
                    try:
                        link.send(protocol.ping_msg())
                    except OSError:
                        pass

    def connect(self, other):
        link = Initiator(other.machine, self.desk.own, key(self.desk.own, other.own))
        welcome = link.handshake(hello=link.hello(id=self.desk.own, name=self.desk.name,
                                                  platform=self.desk.platform_name, caps=list(self.desk.caps)))
        with self.lock:
            self.links[text(other.own)] = link
            self.capabilities[text(other.own)] = set(welcome["caps"])
            self.carry_out(self.owner.link_up(text(other.own), welcome["accepts"]))
        return link

    def drop(self, other):
        with self.lock:
            link = self.links.pop(text(other.own), None)
            if link is not None:
                link.close()
            self.carry_out(self.owner.link_down(text(other.own)))

    def close(self):
        self._closed.set()
        for link in list(self.links.values()):
            link.close()
        self._keep_alive_thread.join()

    def carry_out(self, actions):
        for action in actions:
            if isinstance(action, owner_module.Send):
                message = action.message
                link = self.links.get(action.peer)
                if link is None:
                    continue
                if message["type"] == protocol.MSG_FOCUS:
                    self.sent.append((action.peer, dict(message["data"])))
                try:
                    if message["type"] in protocol.INPUT_TYPES:
                        link.input(message)
                    else:
                        link.send(message)
                except OSError:
                    pass
            elif isinstance(action, owner_module.SendClipboard):
                link = self.links.get(action.peer)
                if link is not None:
                    link.send(protocol.clipboard_msg(text="hand's"))
            elif isinstance(action, owner_module.Moved):
                self.moved.append(action)
                if action.to is None and action.edge in return_edge.EDGES and action.offset is not None:
                    screen = self.desk.screen
                    point = return_edge.arrival_position(screen.monitors(), action.edge, action.offset,
                                                         action.display, action.side, screen.display_map())
                    screen.set_cursor_position(*point)
            elif isinstance(action, owner_module.Drop):
                link = self.links.get(action.peer)
                if link is not None:
                    link.close()

    def send(self, peer, message):
        """An app message to `peer` (an id text) over this desk's link to it; False with none."""
        with self.lock:
            link = self.links.get(peer)
            if link is None:
                return False
            try:
                link.send(message)
            except OSError:
                return False
            return True

    def pump(self):
        with self.lock:
            for peer, link in list(self.links.items()):
                while not link.inbox.empty():
                    message = link.inbox.get_nowait()
                    kind, data = message.get("type"), message.get("data") or {}
                    if kind == protocol.MSG_SWITCH:
                        self.carry_out(self.owner.switch(peer, data))
                    elif kind == protocol.MSG_ACCEPT:
                        self.carry_out(self.owner.accept(peer, data))
                    elif kind == protocol.MSG_REFUSE:
                        self.carry_out(self.owner.refuse(peer, data))
                    elif kind == protocol.MSG_ACCEPTS:
                        self.carry_out(self.owner.accepts(peer, data.get("accepts")))
            self.carry_out(self.owner.tick())

    def until(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if predicate():
                return True
            time.sleep(0.003)
        self.pump()
        return bool(predicate())

    def go(self, peer, edge=None, offset=None, display=None, side=None):
        with self.lock:
            self.carry_out(self.owner.go(peer, edge, offset, display=display, side=side))

    def move(self, dx, dy):
        with self.lock:
            self.carry_out(self.owner.input(protocol.mousemove_msg(dx, dy)))

    @property
    def on(self):
        return self.owner.on


class Desk:
    """One machine. `platform` is "mac" or "pc"; `displays` maps the app's display keys to their
    rectangles in its own pixels (points on a Mac)."""

    def __init__(self, net, own, name, platform, displays, tile=(160, 100), profiles=False):
        self.net = net
        self.own = own
        self.id = text(own)
        self.name = name
        self.platform = platform
        self.platform_name = "macos" if platform == "mac" else "windows"
        self.screen = Screen(displays)
        self.tile_size = tile
        self.profiles = profiles
        self.caps = CAPS + ["profiles"] if profiles else list(CAPS)
        self.lock = threading.RLock()
        self.machine = Machine([], [], caps=self.caps, desktop=self.screen, own=own, name=name)
        self.machine.settings.data.update({"layout": {}, "layout_set_at": 0, "layout_by": "",
                                           "same_on_both": False})
        self.machine.book = receiver.PeerBook(self.machine.settings.load, self.machine.settings.save, self.lock)
        self.machine.responder._book = self.machine.book
        self.hand = Hand(self)
        self.shell = None
        self.started = False

    # The settings, as the app holds them.

    @property
    def settings(self):
        return self.machine.settings.data

    def save(self, settings):
        with self.lock:
            self.machine.settings.save(settings)

    def peer(self, other):
        return next((item for item in self.settings["peers"] if item["id"] == other.id), None)

    # What this desk's own hand does at home.

    def own_models(self):
        """The ways out of this desk's own screen as its app arms them: [(peer id text, push)]."""
        settings = copy.deepcopy(self.settings)
        ready = {peer for peer in self.hand.owner.reach_for(None)}
        if self.platform == "mac":
            peers = [item for item in settings["peers"] if item.get("id") in ready]
            engine = mac_crossing.CrossingEngine.from_zones(
                {"resistance_px": 120, "block_while_dragging": True}, settings["zones"], peers)
            return ("mac", engine)
        allowed = {protocol.read_id(peer) for peer in ready}
        return ("pc", receiver.zone_models(settings["zones"], settings["peers"], allowed, 120, None))

    def push_home(self, point, delta):
        """This desk's own pointer at `point`, pushed by `delta` until something gives. The peer
        id it crossed to, or None."""
        kind, models = self.own_models()
        self.screen.cursor = point
        if kind == "mac":
            displays = [(rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
                        for rect in self.screen.displays.values()]
            union = return_edge.union(self.screen.monitors())
            bounds = (union.x, union.y, union.x + union.width, union.y + union.height)
            now = time.monotonic()
            x, y = point
            # The Mac's event tap sees the pointer pinned at the wall and the delta beyond it.
            for index in range(PUSHES * 2):
                step = models.feed(x, y, delta[0], delta[1], bounds, now + index * 0.004, displays=displays,
                                   ready=lambda peer: True)
                if step is not None and step.crossed:
                    self.hand.go(step.peer, step.edge, step.offset, display=step.display, side=step.side)
                    return step.peer
            return None
        monitors, display_map = self.screen.monitors(), self.screen.display_map()
        for _ in range(PUSHES * 2):
            for peer, model in models:
                outcome = model.feed(monitors, point, delta[0], delta[1], display_map=display_map)
                if outcome.action == return_edge.CROSS:
                    offset = (receiver.corner_offset(model.corner, model.edge)
                              if isinstance(model, return_edge.CornerPush) else outcome.offset)
                    # win_app/sender.py's own crossing, display and side included.
                    self.hand.go(protocol.id_text(peer), outcome.edge, offset, display=outcome.display,
                                 side=outcome.side)
                    return protocol.id_text(peer)
        return None


class Net:
    """The desks, all paired with each other. `test` owns their cleanup."""

    def __init__(self, test, shells):
        self.test = test
        self.desks = {}
        self.shells = shells

    def add(self, name, platform, displays, seed, tile=(160, 100), profiles=False):
        """`profiles` makes it a 1.5.5 desk: it advertises `profiles` and its shell syncs the desk."""
        desk = Desk(self, ident(seed), name, platform, displays, tile, profiles)
        self.test.addCleanup(desk.hand.close)
        desk.shell = self.shells[platform](desk)
        self.test.addCleanup(desk.shell.stop)
        self.desks[name] = desk
        return desk

    def pair_all(self):
        """Every desk paired with every other as pairing leaves them: the peer entry, its whole edge,
        no side yet (the Mac's one peer holds Right, unstamped), and each desk's own tile."""
        for desk in self.desks.values():
            others = [other for other in self.desks.values() if other is not desk]
            with desk.lock:
                settings = copy.deepcopy(desk.settings)
                settings["peers"] = [entry(other.own, other.name, token=key(desk.own, other.own),
                                           platform=other.platform_name, linked=False,
                                           paired_with=[item.id for item in self.desks.values()
                                                        if item is not other])
                                     for other in others]
                for item in settings["peers"]:
                    item["side"] = ""
                settings["zones"] = []
                desk.shell.paired(settings)
                desk.save(settings)

    def start(self):
        for desk in self.desks.values():
            desk.machine.start()
            self.test.addCleanup(desk.machine.stop)
            desk.started = True
        for desk in self.desks.values():
            for other in self.desks.values():
                if other is not desk:
                    desk.hand.connect(other)
        for desk in self.desks.values():
            for other in self.desks.values():
                if other is not desk:
                    desk.shell.link_up(other)
        self.settle()

    def settle(self, timeout=2.0):
        """Wait until every desk's shell has nothing in flight and every message sent has landed:
        each shell counts what it sent and what it handled."""
        deadline = time.monotonic() + timeout
        quiet_since = None
        while time.monotonic() < deadline:
            for desk in self.desks.values():
                desk.hand.pump()
            busy = any(desk.shell.busy() for desk in self.desks.values())
            sent = sum(desk.shell.sent_count for desk in self.desks.values())
            handled = sum(desk.shell.handled_count for desk in self.desks.values())
            if not busy and sent == handled:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since > 0.05:
                    return True
            else:
                quiet_since = None
            time.sleep(0.003)
        return False

    # Where input is.

    def at(self, holder):
        """The desk whose screen `holder`'s pointer is on."""
        on = holder.hand.on
        return holder if on is None else next(desk for desk in self.desks.values() if desk.id == on)

    def push(self, holder, side, along=0.5, display=None):
        """`holder`'s pointer, on whichever desk it is, pushed through `side` of `display` (that
        desk's first display by default) at `along` of the way along it. The desk it is on after."""
        here = self.at(holder)
        display = display or next(iter(here.screen.displays))
        point = here.screen.point(display, side, along)
        return self._push(holder, here, point, PUSH[side])

    def push_corner(self, holder, corner, display=None):
        here = self.at(holder)
        display = display or next(iter(here.screen.displays))
        point = here.screen.corner(display, corner)
        return self._push(holder, here, point, CORNER_PUSH[corner])

    def _push(self, holder, here, point, delta):
        if here is holder:
            holder.push_home(point, delta)
        else:
            here.screen.cursor = point
            for _ in range(PUSHES):
                holder.hand.move(*delta)
                here.screen.cursor = point
            # Every move is acked or acted on before the result is read.
            holder.hand.until(lambda: False, timeout=0.15)
        holder.hand.until(lambda: getattr(holder.hand.owner, "_wait", None) is None, timeout=0.5)
        self.settle(0.5)
        return self.at(holder)

    def shortcut(self, holder, other=None):
        """`holder`'s shortcut, menu or Send button: to `other`, or home with None."""
        holder.hand.go(None if other is None or other is holder else other.id)
        holder.hand.until(lambda: getattr(holder.hand.owner, "_wait", None) is None, timeout=0.5)
        self.settle(0.5)
        return self.at(holder)

    def driven_by(self, desk):
        """The desk whose input `desk`'s responder takes now, or None."""
        owner = desk.machine.responder.owner
        return None if owner is None else next(other for other in self.desks.values() if other.own == owner)

    def views_agree(self):
        """[(problem)] where two desks disagree about the picture or the sides: every pair's sides
        face each other, and every desk holds the same tiles, each with its own displays."""
        problems = []
        desks = list(self.desks.values())
        for one in desks:
            for two in desks:
                if one is two:
                    continue
                mine, theirs = one.peer(two), two.peer(one)
                if mine is None or theirs is None:
                    continue
                if mine.get("side") in return_edge.EDGES and theirs.get("side") in return_edge.EDGES:
                    if return_edge.OPPOSITE[mine["side"]] != theirs["side"]:
                        problems.append(f"{one.name} holds {two.name} {mine['side']}, {two.name} holds {one.name} "
                                        f"{theirs['side']}")
        first = desks[0]
        for other in desks[1:]:
            a = {key: (tile["x"], tile["y"], tile["w"], tile["h"]) for key, tile in first.settings["layout"].items()}
            b = {key: (tile["x"], tile["y"], tile["w"], tile["h"]) for key, tile in other.settings["layout"].items()}
            if {key: value for key, value in a.items() if key in b} != {key: value for key, value in b.items() if key in a}:
                problems.append(f"{first.name} and {other.name} hold different pictures: {a} / {b}")
        for desk in desks:
            for holder in desks:
                tile = holder.settings["layout"].get(desk.id)
                if isinstance(tile, dict) and "displays" not in tile:
                    problems.append(f"{holder.name}'s picture has {desk.name}'s tile without its displays")
        return problems

    def bad_zones(self):
        """Zones whose target side has no target display: the switch they would send is malformed."""
        return [(desk.name, zone) for desk in self.desks.values() for zone in desk.settings["zones"]
                if zone.get("target_side") and not zone.get("target_display")]

    def landed(self, desk):
        """Where `desk`'s cursor was last placed by an arrival: (display, side it is on or None)."""
        if not desk.screen.placed:
            return None
        point = desk.screen.placed[-1]
        name = desk.screen.on_display(point)
        rect = desk.screen.displays.get(name)
        if rect is None:
            return (None, None)
        side = ("left" if point[0] <= rect.x + 2 else "right" if point[0] >= rect.right - 2
                else "top" if point[1] <= rect.y + 2 else "bottom" if point[1] >= rect.bottom - 2 else None)
        return (name, side)
