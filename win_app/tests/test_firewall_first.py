import sys
import unittest
from types import SimpleNamespace
from unittest import mock


@unittest.skipUnless(sys.platform == "win32", "the app module needs Windows")
class RulesBeforeListeningTests(unittest.TestCase):
    """A listener Windows has no rule for makes it ask, and Allow there opens every network."""

    def owner(self, events):
        import kvm_bridge_win

        owner = SimpleNamespace(
            update_checker=SimpleNamespace(start=lambda: None),
            _firewall_target=lambda: ("C:\\Beamer\\Beamer.exe", 24820),
            bridge=SimpleNamespace(rules_ready=SimpleNamespace(emit=lambda: events.append("listen"))),
            _listen=lambda: events.append("listen"),
        )
        owner._rules_then_listen = lambda: kvm_bridge_win.WindowsApplication._rules_then_listen(owner)
        return kvm_bridge_win, owner

    def status(self, allowed=False, blocked=False, error=""):
        return SimpleNamespace(allowed=allowed, blocked=blocked, error=error)

    def test_missing_rules_are_added_before_anything_listens(self):
        events = []
        module, owner = self.owner(events)
        with mock.patch.object(module.firewall_win, "status", return_value=self.status()), \
                mock.patch.object(module.firewall_win, "repair", side_effect=lambda *a: events.append("rules")):
            owner._rules_then_listen()
        self.assertEqual(events, ["rules", "listen"])

    def test_an_existing_rule_or_a_block_is_left_alone(self):
        for existing in (self.status(allowed=True), self.status(blocked=True), self.status(error="no PowerShell")):
            events = []
            module, owner = self.owner(events)
            with self.subTest(existing=existing), \
                    mock.patch.object(module.firewall_win, "status", return_value=existing), \
                    mock.patch.object(module.firewall_win, "repair", side_effect=lambda *a: events.append("rules")):
                owner._rules_then_listen()
            self.assertEqual(events, ["listen"])

    def test_a_failure_still_listens(self):
        events = []
        module, owner = self.owner(events)
        with mock.patch.object(module.firewall_win, "status", side_effect=OSError("denied")):
            owner._rules_then_listen()
        self.assertEqual(events, ["listen"])

    def test_without_elevation_it_listens_at_once(self):
        events = []
        module, owner = self.owner(events)
        with mock.patch.object(module.firewall_win, "is_elevated", return_value=False):
            module.WindowsApplication.start(owner)
        self.assertEqual(events, ["listen"])


@unittest.skipUnless(sys.platform == "win32", "the app module needs Windows")
class FromSourceTests(unittest.TestCase):
    """29-09-2026: the test suite on the rig replaced the installed Beamer's rules with
    python.exe's, and the Mac's link timed out until Beamer restarted."""

    def run_both(self, frozen):
        import kvm_bridge_win as module

        events = []
        owner = SimpleNamespace(
            update_checker=SimpleNamespace(start=lambda: None),
            _firewall_target=lambda: ("C:\\Beamer\\Beamer.exe", 24820),
            bridge=SimpleNamespace(rules_ready=SimpleNamespace(emit=lambda: None)),
            _listen=lambda: None,
            _firewall_advice=SimpleNamespace(action="repair", rule_profiles=("Private",)),
            _run_firewall=lambda job, working: job("C:\\Beamer\\Beamer.exe", 24820),
        )
        owner._rules_then_listen = lambda: module.WindowsApplication._rules_then_listen(owner)

        class Inline:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                self.target()

        missing = SimpleNamespace(allowed=False, blocked=False, error="")
        with mock.patch.object(module.sys, "frozen", frozen, create=True), \
                mock.patch.object(module.threading, "Thread", Inline), \
                mock.patch.object(module.firewall_win, "is_elevated", return_value=True), \
                mock.patch.object(module.firewall_win, "status", return_value=missing), \
                mock.patch.object(module.firewall_win, "repair", side_effect=lambda *a: events.append("repair")):
            module.WindowsApplication.start(owner)
            module.WindowsApplication._firewall_action(owner)
        return events

    def test_the_built_exe_writes_its_rules_at_start_and_on_fix(self):
        self.assertEqual(self.run_both(frozen=True), ["repair", "repair"])

    def test_from_source_neither_path_touches_the_firewall(self):
        self.assertEqual(self.run_both(frozen=False), [])


if __name__ == "__main__":
    unittest.main()
