"""Cross-platform names for system keys whose physical key differs by OS."""

from core import keytable, protocol


def wire_name(physical: str, own_platform: str, peer_platform: str):
    """Return a safe target intent, the unchanged key name, or None when no target exists."""
    if own_platform == peer_platform:
        return physical
    if own_platform == "macos":
        if physical == "f13" and peer_platform == "windows":
            return "print_screen"
    if peer_platform == "macos" and physical in ("browser_search", "search"):
        return "spotlight"
    return physical


def windows_shortcut_intent(key: str):
    """The Windows system shortcuts that have safe macOS equivalents."""
    return {"s": "spotlight", "h": "dictation", "n": ""}.get(key.lower())


def switcher_chord(own_platform: str, peer_platform: str, key: str, held_modifiers):
    """The physical modifier(s) to retarget for a cross-system window switcher chord."""
    if key != "tab":
        return None
    own_mac, peer_mac = keytable.is_mac(own_platform), keytable.is_mac(peer_platform)
    if own_mac == peer_mac:
        return None
    sources, target = (("cmd", "cmd_r"), "alt") if own_mac else (("alt", "alt_r"), "cmd")
    held = tuple(name for name in sources if name in held_modifiers)
    return (held, target) if held else None


def release_key(physical: str, sent: dict):
    """Return the wire name to release, unless another physical key still holds it."""
    name = sent.get(physical)
    if name is None or any(key != physical and held == name for key, held in sent.items()):
        return None
    return name


def switcher_transitions(own_platform: str, peer_platform: str, sent: dict):
    """For a Tab going down towards `peer_platform`: the key messages that first move a held Cmd
    (from a Mac) or Alt (to a Mac) onto the receiver's window-switcher modifier, and the names those
    physical keys are held as from then on, so their release lets go of the right key. `sent` maps
    each physical key held towards that peer to the name it was sent as."""
    decision = switcher_chord(own_platform, peer_platform, "tab", sent)
    if decision is None:
        return [], {}
    sources, target = decision
    if all(sent.get(source) == target for source in sources):
        return [], {}
    old_names = {sent[source] for source in sources if source in sent}
    other_names = {name for physical, name in sent.items() if physical not in sources}
    messages = [{"type": protocol.MSG_KEYUP, "data": {"key": name}} for name in sorted(old_names - other_names)]
    if target not in other_names:
        messages.append({"type": protocol.MSG_KEYDOWN, "data": {"key": target}})
    return messages, {source: target for source in sources}
