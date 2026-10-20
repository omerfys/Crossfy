import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pages_win
import capture_portal
import inject_portal
import portal
from portal_fakes import FakeBus, FakeEi, vardict, wait_for
from core.tests.app_methods import load_methods
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
import widgets


class MemoryTokens:
    def read(self):
        return ""

    def write(self, _token):
        pass


class LinuxPermissionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_card_is_only_visible_on_linux_wayland(self):
        visible = pages_win.linux_permissions_visible
        self.assertTrue(visible("linux", True))
        self.assertFalse(visible("linux", False))
        self.assertFalse(visible("win32", True))
        self.assertFalse(visible("darwin", True))

    def test_portal_reports_each_row_state(self):
        state = pages_win.LinuxPermissionState()
        self.assertEqual(state.status("capture"), ("not_requested", ""))
        self.assertEqual(state.status("remote"), ("not_requested", ""))

        state.report("capture", "ready")
        state.report("remote", "refused", "The desktop refused remote control.")
        self.assertEqual(state.status("capture"), ("ready", ""))
        self.assertEqual(state.status("remote"), ("refused", "The desktop refused remote control."))

        state.report("capture", "unavailable", "InputCapture is missing.")
        self.assertEqual(state.status("capture"), ("unavailable", "InputCapture is missing."))

        state.report("remote", "unavailable", "The session closed.", retryable=True)
        self.assertTrue(state.can_ask_again("remote"))

    def test_ask_again_resets_the_row_and_starts_a_fresh_request(self):
        requests = []
        state = pages_win.LinuxPermissionState()
        for direction in ("capture", "remote"):
            state.bind_requester(direction, lambda key=direction: requests.append(key))
            state.report(direction, "refused", "The desktop refused the request.")
            self.assertTrue(state.ask_again(direction))
            self.assertEqual(state.status(direction), ("not_requested", ""))
        self.assertEqual(requests, ["capture", "remote"])

    def test_input_capture_requires_both_granted_capabilities(self):
        for version in (1, 2):
            with self.subTest(version=version):
                bus = FakeBus(versions={capture_portal.INTERFACE: version})
                if version == 2:
                    bus.returns["CreateSession2"] = (vardict({"session_handle": "/session/1"}),)
                    bus.answers["Start"] = (0, {"capabilities": capture_portal.CAP_KEYBOARD})
                else:
                    bus.answers["CreateSession"] = (0, {
                        "session_handle": "/session/1", "capabilities": capture_portal.CAP_KEYBOARD,
                    })
                bus.returns["ConnectToEIS"] = (99,)
                session = capture_portal._Session(lambda: bus, lambda _fd: object(), MemoryTokens(), lambda: False)
                session.check()

                with self.assertRaises(capture_portal.CaptureUnavailable):
                    session.open()

                self.assertEqual(bus.made("ConnectToEIS"), [])

    @unittest.skipIf(sys.platform == "win32", "the Wayland back ends select on pipes, which Windows cannot; they run only on Linux")
    def test_remote_desktop_refuses_partial_device_grants(self):
        state = pages_win.LinuxPermissionState()
        bus = FakeBus(versions={inject_portal.INTERFACE: 2, inject_portal.CLIPBOARD: 1})
        bus.answers["CreateSession"] = (0, {"session_handle": "/session/1"})
        bus.answers["Start"] = (0, {"devices": inject_portal.DEVICE_KEYBOARD})
        bus.returns["ConnectToEIS"] = (99,)
        remote = inject_portal.Remote(connect=lambda: bus, ei=lambda _fd: FakeEi(), tokens=MemoryTokens())
        inject_portal.on_permission = lambda status, detail, retryable=False: state.report(
            "remote", status, detail, retryable,
        )
        try:
            remote.start()
            wait_for(lambda: state.status("remote")[0] != "not_requested", what="the permission state")
            self.assertEqual(state.status("remote")[0], "refused")
            self.assertTrue(state.can_ask_again("remote"))
            self.assertEqual(bus.made("ConnectToEIS"), [])
        finally:
            remote.stop()
            inject_portal.on_permission = None

    @unittest.skipIf(sys.platform == "win32", "the Wayland back ends select on pipes, which Windows cannot; they run only on Linux")
    def test_capture_partial_grant_is_refused_and_retryable(self):
        state = pages_win.LinuxPermissionState()
        bus = FakeBus(versions={capture_portal.INTERFACE: 2})
        bus.returns["CreateSession2"] = (vardict({"session_handle": "/session/1"}),)
        bus.answers["Start"] = (0, {"capabilities": capture_portal.CAP_KEYBOARD})
        hooks = capture_portal.Hooks(lambda *_args: False, lambda *_args: False, lambda *_args: None,
                                     connect=lambda: bus, ei=lambda _fd: FakeEi(), tokens=MemoryTokens())
        hooks.on_permission = lambda status, detail, retryable=False: state.report(
            "capture", status, detail, retryable,
        )
        try:
            hooks.start()
            wait_for(lambda: state.status("capture")[0] != "not_requested", what="the partial InputCapture grant")
            self.assertEqual(state.status("capture")[0], "refused")
            self.assertTrue(state.can_ask_again("capture"))
        finally:
            hooks.stop()

    @unittest.skipIf(sys.platform == "win32", "the Wayland back ends select on pipes, which Windows cannot; they run only on Linux")
    def test_remote_ask_again_opens_a_fresh_portal_request(self):
        state = pages_win.LinuxPermissionState()
        buses = []
        def connect():
            bus = FakeBus(versions={inject_portal.INTERFACE: 2, inject_portal.CLIPBOARD: 1})
            bus.answers["CreateSession"] = (0, {"session_handle": f"/session/{len(buses) + 1}"})
            bus.answers["Start"] = (1, {}) if not buses else (
                0, {"devices": inject_portal.DEVICE_KEYBOARD | inject_portal.DEVICE_POINTER},
            )
            bus.returns["ConnectToEIS"] = (99,)
            buses.append(bus)
            return bus
        remote = inject_portal.Remote(connect=connect, ei=lambda _fd: FakeEi(), tokens=MemoryTokens())
        inject_portal.on_permission = lambda status, detail, retryable=False: state.report(
            "remote", status, detail, retryable,
        )
        state.bind_requester("remote", remote.request_again)
        try:
            remote.start()
            wait_for(lambda: state.status("remote")[0] == "refused", what="the permission refusal")
            self.assertTrue(state.ask_again("remote"))
            wait_for(lambda: state.status("remote")[0] == "ready", what="the fresh RemoteDesktop request")
            self.assertEqual([len(bus.made("Start")) for bus in buses], [1, 1])
        finally:
            remote.stop()
            inject_portal.on_permission = None

    @unittest.skipIf(sys.platform == "win32", "the Wayland back ends select on pipes, which Windows cannot; they run only on Linux")
    def test_capture_ask_again_opens_a_fresh_portal_request(self):
        state = pages_win.LinuxPermissionState()
        buses = []
        def connect():
            bus = FakeBus(versions={capture_portal.INTERFACE: 2})
            bus.returns["CreateSession2"] = (vardict({"session_handle": f"/session/{len(buses) + 1}"}),)
            bus.answers["Start"] = (1, {}) if not buses else (
                0, {"capabilities": capture_portal.CAP_KEYBOARD | capture_portal.CAP_POINTER},
            )
            bus.returns["ConnectToEIS"] = (99,)
            bus.answers["GetZones"] = (0, {"zones": []})
            buses.append(bus)
            return bus
        hooks = capture_portal.Hooks(lambda *_args: False, lambda *_args: False, lambda *_args: None,
                                     connect=connect, ei=lambda _fd: FakeEi(), tokens=MemoryTokens())
        hooks.on_permission = lambda status, detail, retryable=False: state.report(
            "capture", status, detail, retryable,
        )
        state.bind_requester("capture", hooks.request_again)
        try:
            hooks.start()
            wait_for(lambda: state.status("capture")[0] == "refused", what="the capture refusal")
            self.assertEqual(state.status("capture")[0], "refused")
            self.assertTrue(state.ask_again("capture"))
            wait_for(lambda: state.status("capture")[0] == "ready", what="the fresh InputCapture request")
            self.assertEqual([len(bus.made("Start")) for bus in buses], [1, 1])
        finally:
            hooks.stop()

    def test_permissions_widget_shows_states_and_retry_visibility(self):
        surface = self.permissions_surface("linux", True)
        surface._overview_page(QVBoxLayout(), None)
        module = surface.permissions_module
        self.assertIsNotNone(surface.permissions_module)
        for direction in ("capture", "remote"):
            status, detail, retry = surface.permission_rows[direction]
            self.assertEqual(status.text(), "Not requested")
            self.assertTrue(retry.isHidden())
            surface.permission_state.report(direction, "refused", "Access was refused.")
            self.assertEqual(status.text(), "Refused")
            self.assertEqual(detail.text(), "Access was refused.")
            self.assertFalse(retry.isHidden())
            surface.permission_state.report(direction, "unavailable", "Portal is unavailable.")
            self.assertEqual(status.text(), "Unavailable")
            self.assertTrue(retry.isHidden())
            surface.permission_state.report(direction, "unavailable", "Session closed.", retryable=True)
            self.assertFalse(retry.isHidden())
            surface.permission_state.report(direction, "ready")
            self.assertEqual(status.text(), "Ready")
            self.assertTrue(retry.isHidden())
            requests = []
            surface.permission_state.bind_requester(direction, lambda: requests.append(direction))
            surface.permission_state.report(direction, "refused", "Access was refused.")
            retry.click()
            self.assertEqual(requests, [direction])
            self.assertEqual(status.text(), "Not requested")
        module.deleteLater()

    def test_overview_omits_permissions_card_on_x11_and_windows(self):
        for platform_name, wayland in (("linux", False), ("win32", True)):
            surface = self.permissions_surface(platform_name, wayland)
            layout = QVBoxLayout()
            surface._overview_page(layout, None)
            self.assertIsNone(surface.permissions_module)

    def permissions_surface(self, platform_name, wayland):
        namespace = {
            "pages_win": pages_win,
            "widgets": widgets,
            "QVBoxLayout": QVBoxLayout,
            "QHBoxLayout": QHBoxLayout,
            "QPushButton": widgets.ActionButton,
            "QWidget": QWidget,
            "sys": SimpleNamespace(platform=platform_name),
            "platform_parts": SimpleNamespace(WAYLAND=wayland),
            "machines_win": SimpleNamespace(MachinesModule=lambda *_args, **_kwargs: QWidget(),
                                             PairingSheet=lambda *_args: QWidget()),
        }
        methods = ["_overview_page", "_permissions_module", "_on_permission", "_ask_permission_again"]
        klass = load_methods("win_app/kvm_bridge_win.py", "WindowsApplication", methods, namespace)
        surface = klass()
        surface.permission_state = pages_win.LinuxPermissionState() if pages_win.linux_permissions_visible(
            platform_name, wayland,
        ) else None
        if surface.permission_state is not None:
            surface.permission_state.on_change = surface._on_permission
        surface._set_peer_send = surface._set_peer_allow = surface._set_peer_in_use = lambda *_args: None
        surface._set_shortcut_cycle = lambda *_args: None
        surface._re_pair = lambda *_args: None
        surface._set_peer_left_out = surface._rename_peer = lambda *_args: None
        surface._remove_peer = surface._toggle_pairing_sheet = lambda *_args: None
        surface._show_code = surface._cancel_code = surface._pair_clicked = surface._pick_machine = lambda *_args: None
        surface._pair_phone = surface._start_nearby = surface._choose_nearby = lambda *_args: None
        surface._confirm_nearby = surface._cancel_nearby = lambda *_args: None
        surface._link_module = surface._input_module = surface._same_module = surface._name_module = lambda *_args: QWidget()
        surface._sign_in_module = surface._tray_module = surface._updates_module = lambda *_args: QWidget()
        surface._refresh_peers = lambda: None
        return surface

    def test_refusal_during_select_devices_is_retryable(self):
        state = pages_win.LinuxPermissionState()
        bus = FakeBus(versions={inject_portal.INTERFACE: 2, inject_portal.CLIPBOARD: 1})
        bus.answers["CreateSession"] = (0, {"session_handle": "/session/1"})
        bus.answers["SelectDevices"] = (1, {})
        remote = inject_portal.Remote(connect=lambda: bus, ei=lambda _fd: FakeEi(), tokens=MemoryTokens())
        inject_portal.on_permission = lambda status, detail, retryable=False: state.report(
            "remote", status, detail, retryable,
        )
        try:
            remote.start()
            wait_for(lambda: state.status("remote")[0] != "not_requested", what="the permission refusal")
            self.assertEqual(state.status("remote")[0], "refused")
            self.assertTrue(state.can_ask_again("remote"))
        finally:
            remote.stop()
            inject_portal.on_permission = None

    @unittest.skipIf(sys.platform == "win32", "the Wayland back ends select on pipes, which Windows cannot; they run only on Linux")
    def test_remote_desktop_closed_signal_can_be_asked_again(self):
        state = pages_win.LinuxPermissionState()
        bus = FakeBus(versions={inject_portal.INTERFACE: 2, inject_portal.CLIPBOARD: 1})
        bus.answers["CreateSession"] = (0, {"session_handle": "/session/1"})
        bus.answers["Start"] = (0, {"devices": inject_portal.DEVICE_KEYBOARD | inject_portal.DEVICE_POINTER})
        bus.returns["ConnectToEIS"] = (99,)
        remote = inject_portal.Remote(connect=lambda: bus, ei=lambda _fd: FakeEi(), tokens=MemoryTokens())
        inject_portal.on_permission = lambda status, detail, retryable=False: state.report(
            "remote", status, detail, retryable,
        )
        try:
            remote.start()
            wait_for(remote.ready.is_set, what="RemoteDesktop readiness")
            bus.emit("/session/1", portal.SESSION, "Closed", ())
            wait_for(lambda: state.status("remote")[0] == "unavailable", what="the closed session")
            self.assertTrue(state.can_ask_again("remote"))
        finally:
            remote.stop()
            inject_portal.on_permission = None

    @unittest.skipIf(sys.platform == "win32", "the Wayland back ends select on pipes, which Windows cannot; they run only on Linux")
    def test_input_capture_closed_signal_can_be_asked_again(self):
        state = pages_win.LinuxPermissionState()
        bus = FakeBus(versions={capture_portal.INTERFACE: 2})
        bus.returns["CreateSession2"] = (vardict({"session_handle": "/session/1"}),)
        bus.returns["ConnectToEIS"] = (99,)
        bus.answers["Start"] = (0, {"capabilities": capture_portal.CAP_KEYBOARD | capture_portal.CAP_POINTER})
        bus.answers["GetZones"] = (0, {"zones": []})
        hooks = capture_portal.Hooks(lambda *_args: False, lambda *_args: False, lambda *_args: None,
                                     connect=lambda: bus, ei=lambda _fd: FakeEi(), tokens=MemoryTokens())
        hooks.on_permission = lambda status, detail, retryable=False: state.report(
            "capture", status, detail, retryable,
        )
        try:
            hooks.start()
            wait_for(lambda: state.status("capture")[0] == "ready", what="InputCapture readiness")
            bus.emit("/session/1", portal.SESSION, "Closed", ())
            wait_for(lambda: state.status("capture")[0] == "unavailable", what="the closed session")
            self.assertTrue(state.can_ask_again("capture"))
        finally:
            hooks.stop()


if __name__ == "__main__":
    unittest.main()
