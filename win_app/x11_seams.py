"""Directional XFixes pointer barriers on armed zones at internal X11 monitor seams."""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from core.return_edge import CORNER_PX, CornerPush, PartEdge, Rect

XI_ALL_MASTER_DEVICES = 1
BARRIER_POSITIVE_X = 1 << 0
BARRIER_POSITIVE_Y = 1 << 1
BARRIER_NEGATIVE_X = 1 << 2
BARRIER_NEGATIVE_Y = 1 << 3

_CREATE_POINTER_BARRIER = 31
_DESTROY_POINTER_BARRIER = 32


@dataclass(frozen=True)
class Seam:
    """A half-open monitor-to-monitor seam, represented as XFixes endpoints."""

    x1: int
    y1: int
    x2: int
    y2: int
    axis: str
    directions: int = 0

    @property
    def key(self) -> Tuple[int, int, int, int]:
        return self.x1, self.y1, self.x2, self.y2


def seams(monitors: Iterable[Rect]) -> List[Seam]:
    """Return each shared edge segment once; external edges are deliberately omitted."""
    displays = list(monitors)
    found: Dict[Tuple[int, int, int, int], Seam] = {}
    for index, first in enumerate(displays):
        for second in displays[index + 1:]:
            if first.x + first.width == second.x or second.x + second.width == first.x:
                start = max(first.y, second.y)
                end = min(first.y + first.height, second.y + second.height)
                if end - start > 1:
                    x = (first.x + first.width if first.x + first.width == second.x
                         else second.x + second.width)
                    item = Seam(x, start, x, end - 1, "x")
                    found[item.key] = item
            if first.y + first.height == second.y or second.y + second.height == first.y:
                start = max(first.x, second.x)
                end = min(first.x + first.width, second.x + second.width)
                if end - start > 1:
                    y = (first.y + first.height if first.y + first.height == second.y
                         else second.y + second.height)
                    item = Seam(start, y, end - 1, y, "y")
                    found[item.key] = item
    return list(found.values())


def armed_seams(monitors: Iterable[Rect], display_map: dict, models: Iterable) -> List[Seam]:
    """Return only internal stretches covered by an armed, display-scoped zone model."""
    displays = list(monitors)
    routes: Dict[Tuple[str, int], List[Tuple[int, int, int]]] = {}
    for model in models:
        if not getattr(model, "armed", True):
            continue
        display = getattr(model, "display", None)
        edge = getattr(model, "edge", None)
        rect = display_map.get(display) if isinstance(display, str) else None
        if not isinstance(rect, Rect) or edge not in ("left", "right", "top", "bottom"):
            continue
        spans = _zone_spans(model, rect, edge)
        if not spans:
            continue
        for span in spans:
            for other in displays:
                if other == rect:
                    continue
                if edge in ("left", "right"):
                    adjacent = other.x + other.width == rect.x if edge == "left" else other.x == rect.x + rect.width
                    if not adjacent:
                        continue
                    start, end = max(span[0], other.y), min(span[1], other.bottom)
                    if end > start:
                        x = rect.x if edge == "left" else rect.x + rect.width
                        route = (start, end, -1 if edge == "left" else 1)
                        routes.setdefault(("x", x), []).append(route)
                    else:
                        continue
                else:
                    adjacent = other.y + other.height == rect.y if edge == "top" else other.y == rect.y + rect.height
                    if not adjacent:
                        continue
                    start, end = max(span[0], other.x), min(span[1], other.right)
                    if end > start:
                        y = rect.y if edge == "top" else rect.y + rect.height
                        route = (start, end, -1 if edge == "top" else 1)
                        routes.setdefault(("y", y), []).append(route)
                    else:
                        continue
    found = []
    for (axis, coordinate), spans in routes.items():
        breaks = sorted({point for start, end, _direction in spans for point in (start, end + 1)})
        for start, stop in zip(breaks, breaks[1:]):
            blocked = {direction for low, high, direction in spans if low <= start and high >= stop - 1}
            if not blocked:
                continue
            directions = _allowed_directions(axis, blocked)
            if axis == "x":
                item = Seam(coordinate, start, coordinate, stop - 1, axis, directions)
            else:
                item = Seam(start, coordinate, stop - 1, coordinate, axis, directions)
            found.append(item)
    return found


def _allowed_directions(axis: str, blocked: set) -> int:
    if axis == "x":
        return (0 if 1 in blocked else BARRIER_POSITIVE_X) | (0 if -1 in blocked else BARRIER_NEGATIVE_X)
    return (0 if 1 in blocked else BARRIER_POSITIVE_Y) | (0 if -1 in blocked else BARRIER_NEGATIVE_Y)


def _zone_spans(model, rect: Rect, edge: str):
    low, high = (rect.y, rect.bottom) if edge in ("left", "right") else (rect.x, rect.right)
    if isinstance(model, PartEdge):
        size = high - low + 1
        return [(low + (part * size + 2) // 3,
                 low + ((part + 1) * size + 2) // 3 - 1)
                for part, name in enumerate(("start", "middle", "end")) if name in model.parts]
    if isinstance(model, CornerPush):
        if edge in ("left", "right"):
            if model.horizontal != edge:
                return []
            if model.vertical == "top":
                return [(low, min(high, low + CORNER_PX))]
            return [(max(low, high - CORNER_PX), high)]
        if model.vertical != edge:
            return []
        return [(low, min(high, low + CORNER_PX))] if model.horizontal == "left" else (
            [(max(low, high - CORNER_PX), high)])
    return [(low, high)]


class Controller:
    """Reconcile directional XFixes barriers for the sender's currently armed zones."""

    def __init__(self, backend) -> None:
        self._backend = backend
        self._barriers: Dict[int, Seam] = {}
        self._signature = None

    @property
    def active(self) -> bool:
        return bool(self._barriers)

    def configure(self, monitors: Iterable[Rect], resistance_px: int, enabled: bool = True,
                  display_map: dict = None, models: Iterable = ()) -> None:
        resistance = max(0.0, float(resistance_px))
        displays = list(monitors)
        wanted = armed_seams(displays, display_map or {}, models) if enabled and resistance > 0 else []
        # X protocol coordinates are signed 16-bit screen coordinates. Omit only unrepresentable
        # seams; a bad display arrangement must not prevent ordinary input capture from starting.
        wanted = [item for item in wanted if all(-32768 <= point <= 32767 for point in item.key)]
        signature = (tuple((item.key, item.directions) for item in wanted), resistance, bool(enabled))
        if signature == self._signature:
            return
        self._remove_all()
        self._signature = signature
        if not enabled or resistance <= 0:
            return
        try:
            for item in wanted:
                barrier = self._backend.create_barrier(item)
                if barrier is not None:
                    self._barriers[int(barrier)] = item
        except Exception:
            self._remove_all()
            self._signature = None
            raise

    def close(self) -> None:
        self._remove_all()
        self._signature = None

    def _remove_all(self) -> None:
        for barrier in list(self._barriers):
            try:
                self._backend.destroy_barrier(barrier)
            finally:
                self._barriers.pop(barrier, None)


def _patch_xfixes_query_version() -> None:
    try:
        import Xlib.ext.xfixes
    except Exception:
        return
    if getattr(Xlib.ext.xfixes, "_beamer_patched_v5", False):
        return

    def query_version(self, major_version=5, minor_version=0):
        return Xlib.ext.xfixes.QueryVersion(
            display=self.display,
            opcode=self.display.get_extension_major(Xlib.ext.xfixes.extname),
            major_version=major_version,
            minor_version=minor_version,
        )

    Xlib.ext.xfixes.query_version = query_version
    Xlib.ext.xfixes._beamer_patched_v5 = True


_patch_xfixes_query_version()


def _request_classes():
    # python-xlib is optional on macOS and Windows; keep its protocol types lazy like capture_x11's
    # connection itself.
    _patch_xfixes_query_version()
    from Xlib.protocol import rq

    class CreatePointerBarrier(rq.Request):
        _request = rq.Struct(rq.Card8("opcode"), rq.Opcode(_CREATE_POINTER_BARRIER), rq.RequestLength(),
                             rq.Card32("barrier"), rq.Card32("window"),
                             rq.Int16("x1"), rq.Int16("y1"), rq.Int16("x2"), rq.Int16("y2"),
                             rq.Card32("directions"), rq.Pad(2), rq.LengthOf("devices", 2),
                             rq.List("devices", rq.Card16))

    class DestroyPointerBarrier(rq.Request):
        _request = rq.Struct(rq.Card8("opcode"), rq.Opcode(_DESTROY_POINTER_BARRIER), rq.RequestLength(),
                             rq.Card32("barrier"))

    return CreatePointerBarrier, DestroyPointerBarrier


class XlibBackend:
    """The XFixes/XInput protocol requests needed by Controller, on Hooks' X connection."""

    def __init__(self, display, root) -> None:
        _patch_xfixes_query_version()
        self._create, self._destroy = _request_classes()
        self._display = display
        self._protocol = getattr(display, "display", display)
        self._root = root
        self._xfixes_opcode = self._protocol.get_extension_major("XFIXES")
        if hasattr(self._display, "xfixes_query_version"):
            try:
                self._display.xfixes_query_version()
            except Exception:
                pass

    def create_barrier(self, seam: Seam) -> int:
        barrier = self._protocol.allocate_resource_id()
        self._create(
            display=self._protocol, opcode=self._xfixes_opcode, barrier=barrier, window=self._root.id,
            x1=seam.x1, y1=seam.y1, x2=seam.x2, y2=seam.y2,
            directions=seam.directions, devices=[],
        )
        if hasattr(self._display, "flush"):
            self._display.flush()
        return barrier

    def destroy_barrier(self, barrier: int) -> None:
        self._destroy(display=self._protocol, opcode=self._xfixes_opcode, barrier=barrier)
        if hasattr(self._display, "flush"):
            self._display.flush()
