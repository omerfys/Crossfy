"""Desktop identity for Linux-specific guidance and portal compatibility."""

import os


def desktop(environ=None) -> str:
    environ = os.environ if environ is None else environ
    value = environ.get("XDG_CURRENT_DESKTOP") or environ.get("XDG_SESSION_DESKTOP", "")
    names = {name.strip().lower() for name in value.split(":")}
    if names & {"kde", "plasma"}:
        return "kde"
    if "gnome" in names:
        return "gnome"
    return ""
