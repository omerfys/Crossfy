"""Global shortcut session for Wayland desktops."""

import logging
import threading
from typing import Callable, Optional

import portal
from core.i18n import tr

LOGGER = logging.getLogger(__name__)

INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
SHORTCUT_ID = "send-input"
PREFERRED_TRIGGER = "LOGO+SHIFT+b"


class GlobalShortcut:
    def __init__(self, connect: Callable, on_activated: Callable[[], None], stopping: Callable[[], bool] = lambda: False) -> None:
        self._connect = connect
        self._on_activated = on_activated
        self._stopping = stopping
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._bus = None
        self._portal = None
        self._thread = None
        self.available: Optional[bool] = None
        self.refused = False
        self.trigger_description: Optional[str] = None
        self.session_handle: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="Beamer-global-shortcut", daemon=True)
        self._thread.start()

    def _is_stopping(self) -> bool:
        return self._stop.is_set() or self._stopping()

    def _set_trigger_description(self, shortcuts) -> None:
        for shortcut_id, details in shortcuts:
            if shortcut_id == SHORTCUT_ID:
                self.trigger_description = details.get("trigger_description")
                return

    def _run(self) -> None:
        try:
            bus = self._connect()
            with self._lock:
                self._bus = bus
            self._portal = portal.Portal(bus, self._is_stopping)
            version = self._portal.version(INTERFACE)
            self.available = version > 0
            if not self.available:
                LOGGER.info("The desktop does not provide the GlobalShortcuts portal")
                return
            results = self._portal.request(INTERFACE, "CreateSession", "a{sv}", lambda token: ({
                "handle_token": ("s", token),
                "session_handle_token": ("s", self._portal.token()),
            },))
            self.session_handle = results["session_handle"]
            try:
                bound = self._portal.request(INTERFACE, "BindShortcuts", "oa(sa{sv})sa{sv}", lambda token: (
                    self.session_handle,
                    [(SHORTCUT_ID, {
                        "description": ("s", tr("Send input to another machine")),
                        "preferred_trigger": ("s", PREFERRED_TRIGGER),
                    })],
                    "",
                    {"handle_token": ("s", token)},
                ))
            except portal.Refused:
                self.refused = True
                LOGGER.info("The desktop declined Beamer's global shortcut")
                return
            self._set_trigger_description(bound.get("shortcuts", []))
            while not self._is_stopping():
                for _path, interface, member, body in self._portal.signals(timeout=0.1):
                    if interface != INTERFACE or not body or body[0] != self.session_handle:
                        continue
                    if member == "Activated" and len(body) > 1 and body[1] == SHORTCUT_ID:
                        try:
                            self._on_activated()
                        except Exception:
                            LOGGER.exception("The global shortcut callback failed")
                    elif member == "ShortcutsChanged" and len(body) > 1:
                        self._set_trigger_description(body[1])
        except portal.Refused:
            self.refused = True
            LOGGER.info("The desktop declined Beamer's global shortcut")
        except Exception:
            if not self._is_stopping():
                LOGGER.exception("The global shortcut portal session failed")

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            bus = self._bus
        if self.session_handle is not None and self._portal is not None:
            try:
                self._portal.call(portal.SESSION, "Close", path=self.session_handle)
            except Exception:
                pass
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
