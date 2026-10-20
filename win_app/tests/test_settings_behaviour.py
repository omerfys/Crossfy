"""Windows settings decisions with in-memory configuration and no Qt window."""

from core.tests.settings_behaviour import SettingsBehaviourTests as _SettingsBehaviourTests
from types import SimpleNamespace


class WindowsSettingsBehaviourTests(_SettingsBehaviourTests):
    platform = "win"

    def setUp(self):
        super().setUp()
        self.app.parts_choice = SimpleNamespace(view=SimpleNamespace(refresh_metrics=lambda: None))


del _SettingsBehaviourTests
