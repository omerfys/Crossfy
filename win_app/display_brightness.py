"""Adjust built-in displays through WMI's brightness methods."""

import logging

LOGGER = logging.getLogger(__name__)
_WARNED_UNAVAILABLE = False


def _next_level(levels, current, direction):
    ordered = sorted(int(level) for level in levels)
    if direction > 0:
        return next((level for level in ordered if level > current), ordered[-1])
    return next((level for level in reversed(ordered) if level < current), ordered[0])


def adjust(steps: int, dispatch=None) -> bool:
    global _WARNED_UNAVAILABLE
    uninitialise_com = False
    try:
        if dispatch is None:
            import pythoncom

            pythoncom.CoInitialize()
            uninitialise_com = True
            from win32com.client import Dispatch

            dispatch = Dispatch
        service = dispatch("WbemScripting.SWbemLocator").ConnectServer(".", r"root\wmi")
        levels = service.ExecQuery("SELECT InstanceName, CurrentBrightness, Level FROM WmiMonitorBrightness")
        methods = {str(item.InstanceName): item for item in service.ExecQuery(
            "SELECT InstanceName FROM WmiMonitorBrightnessMethods"
        )}
        changed = False
        for screen in levels:
            method = methods.get(str(screen.InstanceName))
            if method is None:
                continue
            target = int(screen.CurrentBrightness)
            for _ in range(abs(int(steps))):
                target = _next_level(screen.Level, target, 1 if steps > 0 else -1)
            parameters = method.Methods_("WmiSetBrightness").InParameters.SpawnInstance_()
            parameters.Timeout = 0
            parameters.Brightness = target
            result = method.ExecMethod_("WmiSetBrightness", parameters)
            status = int(result.ReturnValue)
            if status != 0:
                raise OSError(f"WmiSetBrightness returned {status}")
            changed = True
    except Exception:
        LOGGER.exception("Windows display brightness failed")
        return False
    finally:
        if uninitialise_com:
            pythoncom.CoUninitialize()
    if not changed:
        if not _WARNED_UNAVAILABLE:
            LOGGER.info("No built-in display exposes WMI brightness control; external monitors are unchanged")
            _WARNED_UNAVAILABLE = True
        return False
    return True
