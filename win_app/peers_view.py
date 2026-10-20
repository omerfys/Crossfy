"""What each paired machine's row on Overview says: a tone, a state word and one sentence.

Pure, so every state a link can be in is tested against a word. The booleans decide the broad
state; the link's own `kind` picks the flavour of a fault, and its status sentence (which already
names the machine, WIRE.md section 2) is the detail. The words are the Mac's, row for row.
"""

from __future__ import annotations

from dataclasses import dataclass

from core import peerlist, protocol
from core.i18n import matches_translation, N_, tr

PLATFORM_NAMES = {"macos": N_("Mac"), "windows": N_("Windows"), "linux": N_("Linux"),
                  "ios": N_("iPhone"), "android": N_("Android")}

REFUSED_KINDS = ("unauthenticated", "wrong_id", "different", "unreadable", "forgotten")
VERSION_KINDS = ("older", "newer", "not_beamer")
UNREACHABLE_KINDS = ("unreachable", "timeout")
QUIET_KINDS = ("connected", "removed", "off")


@dataclass(frozen=True)
class PeerState:
    tone: str
    word: str
    detail: str


def platform_name(entry: dict) -> str:
    return tr(PLATFORM_NAMES.get(entry.get("platform"), N_("Other")))


def address_line(entry: dict, hide: bool) -> str:
    host, port = entry.get("host") or "", entry.get("port")
    if not host or not isinstance(port, int) or isinstance(port, bool) or port <= 0:
        return tr("No address")
    return tr("{address} · port {port}").format(address="•••" if hide else host, port=port)


def describe(entry: dict, label: str, *, up: bool, driving: bool, input_there: bool, kind: str, status: str,
             waking: bool) -> PeerState:
    """`up`: a link to this machine is live, either way round. `driving`: its input is on this PC.
    `input_there`: this PC's input is on it. `kind` and `status`: what the link this PC dials to it
    last reported."""
    reason = peerlist.dormant_reason(entry)
    if reason:
        return PeerState("amber", tr("Needs re-pair"), reason)
    if entry.get("in_use", True) is not True:
        return PeerState("amber", tr("NOT IN USE"), tr("{name} is not in use on this PC.").format(name=label))
    if driving:
        return PeerState("signal", tr("Driving this PC"),
                         tr("{name}'s keyboard and pointer are on this PC. Push the pointer back through the edge it arrived by to send them home.").format(name=label))
    if input_there:
        return PeerState("signal", tr("Input here"),
                         tr("This PC's keyboard and pointer are on {name}. Do the same again to bring them home.").format(name=label))
    if not protocol.linkable(entry):
        return PeerState("amber", tr("Pair again"),
                         tr("{name} was paired on Beamer 1.4. Pair the two again to link them on 1.5.0.").format(name=label))
    if up:
        return PeerState("signal", tr("Linked"), tr("Connected to {name}.").format(name=label))
    if waking:
        return PeerState("amber", tr("Waiting"), tr("Waking {name}…").format(name=label))
    if not entry.get("send"):
        return PeerState("amber", tr("Waiting"), tr("Waiting for {name} to connect.").format(name=label))
    if not status or kind in QUIET_KINDS:
        return PeerState("amber", tr("Waiting"), tr("Looking for {name}. It connects on its own once Beamer is open there.").format(name=label))
    if kind in REFUSED_KINDS:
        return PeerState("fault", tr("Refused"), status)
    if kind in VERSION_KINDS or (kind == "closed" and matches_translation(
            status, "Update Beamer on {name} to 1.5.0; if it is up to date, pair the two again",
            "Update Beamer on {name}: it is older than this one")):
        return PeerState("fault", tr("Version"), status)
    if kind in UNREACHABLE_KINDS:
        return PeerState("fault", tr("Unreachable"), status)
    if kind == "refused":
        return PeerState("fault", tr("Not listening"), status)
    return PeerState("fault", tr("Dropped"), tr("{status}. Beamer keeps trying to reconnect.").format(status=status.rstrip(".")))
