"""Capture events pass through the Qt shell to the real sender, without a desktop."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture_win
import kvm_bridge_win
import platform_parts
import sender
from core import protocol
from links_rig import B, Rig


class Keymap:
    def keysym(self, keycode, mods, group):
        return ord("a") if keycode == 38 else 0

    def text(self, keysym):
        return chr(keysym) if keysym else None

    def core_mods(self, mods):
        return mods


def shell(rig, capture):
    return SimpleNamespace(sender=rig.sender, _trigger=capture.Trigger())


def check_linux_key(capture, session, code, name, us):
    rig = Rig()
    assert rig.sender.set_redirecting(True)
    application = shell(rig, capture)
    hooks = capture.Hooks(
        lambda *args: kvm_bridge_win.WindowsApplication._on_hook_key(application, *args),
        lambda *_: False,
        lambda *_: None,
    )
    if session == "x11":
        hooks._connection = SimpleNamespace(keymap=Keymap())

        def feed(down):
            hooks._key(code + 8, down, 0, 0, True)
    else:
        hooks._keymap = Keymap()
        device = object()

        def feed(down):
            hooks._key_event(code, down, device)

    feed(True)
    feed(False)
    expected = {"key": name}
    if us is not None:
        expected["us"] = us
    assert rig.sent(B, protocol.MSG_KEYDOWN) == [{"type": protocol.MSG_KEYDOWN, "data": expected}]
    assert rig.sent(B, protocol.MSG_KEYUP) == [{"type": protocol.MSG_KEYUP, "data": expected}]


class CaptureSenderTests(unittest.TestCase):
    def check_backend(self, session):
        capture = platform_parts.load("linux", {"XDG_SESSION_TYPE": session}).capture
        with mock.patch.object(kvm_bridge_win, "capture_win", capture), mock.patch.object(sender, "OWN_PLATFORM", "linux"):
            for code, name, us in ((30, "a", "a"), (28, "enter", None), (42, "shift", None)):
                with self.subTest(key=name):
                    check_linux_key(capture, session, code, name, us)

    def test_x11_capture_key_press_and_release_reach_sender(self):
        self.check_backend("x11")

    def test_wayland_capture_key_press_and_release_reach_sender(self):
        self.check_backend("wayland")

    def test_windows_dead_key_and_composed_text_still_reach_sender(self):
        rig = Rig()
        rig.links.caps_of[B] = frozenset({"text"})
        assert rig.sender.set_redirecting(True)
        application = shell(rig, capture_win)
        callback = kvm_bridge_win.WindowsApplication._on_hook_key
        with mock.patch.object(kvm_bridge_win, "capture_win", capture_win):
            assert callback(application, capture_win.DeadKey("^"), True, 0xDD)
            assert rig.sent(B, protocol.MSG_KEYDOWN) == []
            assert rig.sent(B, protocol.MSG_TEXT) == []
            assert callback(application, capture_win.TextInput("^x"), True, 0x58)
            assert rig.sent(B, protocol.MSG_TEXT) == [{"type": protocol.MSG_TEXT, "data": {"text": "^x"}}]
