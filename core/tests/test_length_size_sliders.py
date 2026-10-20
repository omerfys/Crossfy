import base64
import unittest
from types import SimpleNamespace

from core import effects, settings_sync


class LengthSizeSliderTests(unittest.TestCase):
    def test_continuous_values_map_to_nearest_legacy_presets(self):
        self.assertEqual([effects.length_preset(value) for value in (0.5, 1.0, 2.0)],
                         ["short", "normal", "long"])
        self.assertEqual([effects.size_preset(value) for value in (0.03, 0.045, 0.06)],
                         ["small", "medium", "large"])
        self.assertEqual(effects.length_preset(0.25), "short")
        self.assertEqual(effects.size_preset(0.08), "large")

    def test_fractional_size_scales_against_short_edge_and_keeps_clamp(self):
        self.assertEqual(effects.edge_depth(1920, 1080, size_fraction=0.03), 32.4)
        self.assertEqual(effects.edge_depth(640, 480, size_fraction=0.02), 24)
        self.assertEqual(effects.edge_depth(3840, 2160, size_fraction=0.08), 144)

    def test_each_style_play_time_uses_shared_effect_timing_and_pace(self):
        self.assertEqual(effects.play_through_seconds("beam", 2.0), 1.2)
        self.assertEqual(effects.play_through_seconds("aperture", 0.5), 0.31)

    def test_switch_arrival_readout_uses_arrival_timing_when_there_is_no_departure(self):
        self.assertEqual(effects.play_through_seconds("locator", 1.0), 0.72)

    def test_shared_slider_readouts_use_core_timing_and_depth(self):
        self.assertEqual(effects.design_slider_readouts("beam", 2.0, 0.06, 1920, 1080),
                         ("1.2 s", "65 pt"))

    def test_preset_only_values_migrate_to_both_forms(self):
        pace, fraction, length, size = effects.design_values(
            length="long", size="small")
        self.assertEqual((pace, fraction, length, size), (2.0, 0.03, "long", "small"))

    def test_valid_continuous_values_take_precedence_and_invalid_values_fall_back(self):
        self.assertEqual(effects.design_values(1.35, 0.052, "normal", "medium"),
                         (1.35, 0.052, "normal", "medium"))
        self.assertEqual(effects.design_values(1.35, 0.052), (1.35, 0.052, "normal", "medium"))

    def test_a_preset_that_disagrees_with_its_slider_value_was_set_later_and_wins(self):
        self.assertEqual(effects.design_values(1.35, 0.052, "short", "small"),
                         (0.5, 0.03, "short", "small"))
        self.assertEqual(effects.design_values(99, 0.9, "short", "large"),
                         (0.5, 0.06, "short", "large"))

    def test_same_on_and_direct_design_sync_carry_both_forms(self):
        values = {
            "glow_style": "beam", "glow_colour": "signal", "effect_length": "normal",
            "effect_size": "medium", "effect_pace": 1.35, "effect_size_fraction": 0.052,
            "shortcut_arrival": True, "shortcut_arrival_style": "match",
        }
        state = {"set_at": 50, "by": base64.b64encode(bytes([1]) * 16).decode(), "values": values}
        message = settings_sync.message_data(True, 50, values, design_state=state)
        self.assertEqual(message["design"]["effect_pace"], 1.35)
        self.assertEqual(message["design"]["effect_size_fraction"], 0.052)
        received = settings_sync.read_design_state(
            {"on": True, "set_at": 50, "by": state["by"], "design_sync": state}, set(), now=50)
        self.assertEqual(received["values"]["effect_pace"], 1.35)
        self.assertEqual(received["values"]["effect_size_fraction"], 0.052)

    def test_152_shaped_state_uses_legacy_presets(self):
        peer = base64.b64encode(bytes([1]) * 16).decode()
        data = {"on": True, "set_at": 50, "by": peer,
                "design": {"effect_length": "long", "effect_size": "small"}}
        _on, _stamp, values = settings_sync.read(data, set(), now=50)
        self.assertEqual((values["effect_pace"], values["effect_size_fraction"],
                          values["effect_length"], values["effect_size"]),
                         (2.0, 0.03, "long", "small"))
        mac = settings_sync.apply_mac({"crossing": {"effect_length": "normal", "effect_size": "medium",
                                                       "methods": []}}, values)["crossing"]
        self.assertEqual((mac["effect_pace"], mac["effect_size_fraction"]), (2.0, 0.03))
        pc = SimpleNamespace(effect_length="normal", effect_size="medium", effect_pace=1.0,
                             effect_size_fraction=0.045, crossing_methods=[])
        settings_sync.apply_pc(pc, values)
        self.assertEqual((pc.effect_length, pc.effect_size, pc.effect_pace, pc.effect_size_fraction),
                         ("long", "small", 2.0, 0.03))

    def test_152_direct_design_state_fills_both_legacy_and_continuous_values(self):
        peer = base64.b64encode(bytes([1]) * 16).decode()
        state = {"on": True, "set_at": 50, "by": peer,
                 "design_sync": {"set_at": 50, "by": peer,
                                 "values": {"effect_length": "long"}}}
        values = settings_sync.read_design_state(state, set(), now=50)["values"]
        self.assertEqual((values["effect_pace"], values["effect_length"],
                          values["effect_size_fraction"], values["effect_size"]),
                         (2.0, "long", 0.045, "medium"))


if __name__ == "__main__":
    unittest.main()


class PresetOnlyApplyTests(unittest.TestCase):
    def test_a_preset_without_its_slider_value_replaces_the_held_one_on_both_apps(self):
        raw = settings_sync.apply_mac({"crossing": {"effect_pace": 1.0, "effect_size_fraction": 0.045}},
                                      {"effect_length": "long", "effect_size": "small"})
        self.assertEqual((raw["crossing"]["effect_pace"], raw["crossing"]["effect_size_fraction"]), (2.0, 0.03))
        config = SimpleNamespace(effect_pace=1.0, effect_size_fraction=0.045, effect_length="normal",
                                       effect_size="medium")
        settings_sync.apply_pc(config, {"effect_length": "short"})
        self.assertEqual((config.effect_pace, config.effect_length), (0.5, "short"))

    def test_a_followed_preset_replaces_the_followers_held_slider_value(self):
        current = {"effect_length": "short", "effect_pace": 0.5}
        state = {"set_at": 100, "by": "", "values": {"effect_length": "long"}}
        taken = settings_sync.followed_design(current, state, "p", "p", False, -1, "", force=True)
        self.assertEqual((taken["values"]["effect_length"], taken["values"]["effect_pace"]), ("long", 2.0))

