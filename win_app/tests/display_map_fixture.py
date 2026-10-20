"""Display fixtures shared by the matrix runner and cache-specific tests."""

import kvm_bridge_win


refresh_own_displays = kvm_bridge_win.WindowsApplication._refresh_own_displays


def display_fields(window):
    return {"display": "0"} if window._own_displays() else {}
