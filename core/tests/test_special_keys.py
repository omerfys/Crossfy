import unittest

from core import special_keys


class SpecialKeyWireTests(unittest.TestCase):
    def test_hangul_and_hanja_names_survive_special_key_translation(self):
        for key in ("hangul", "hanja"):
            for own in ("macos", "windows", "linux"):
                for peer in ("macos", "windows", "linux"):
                    self.assertEqual(special_keys.wire_name(key, own, peer), key)

    def test_window_switcher_chord_rules(self):
        cases = (
            ("macos", "windows", "tab", {"cmd"}, (("cmd",), "alt")),
            ("macos", "windows", "tab", {"cmd", "shift"}, (("cmd",), "alt")),
            ("macos", "linux", "tab", {"cmd_r"}, (("cmd_r",), "alt")),
            ("windows", "macos", "tab", {"alt", "shift"}, (("alt",), "cmd")),
            ("linux", "macos", "tab", {"alt_r"}, (("alt_r",), "cmd")),
        )
        for own, peer, key, held, expected in cases:
            with self.subTest(own=own, peer=peer, held=held):
                self.assertEqual(special_keys.switcher_chord(own, peer, key, held), expected)

    def test_window_switcher_chord_ignores_other_keys_and_same_system_pairs(self):
        self.assertIsNone(special_keys.switcher_chord("macos", "windows", "c", {"cmd"}))
        self.assertIsNone(special_keys.switcher_chord("macos", "macos", "tab", {"cmd"}))
        self.assertIsNone(special_keys.switcher_chord("windows", "linux", "tab", {"alt"}))
        self.assertIsNone(special_keys.switcher_chord("windows", "macos", "tab", {"cmd"}))

    def test_ios_is_in_the_mac_family_for_switcher_pairs(self):
        self.assertIsNone(special_keys.switcher_chord("macos", "ios", "tab", {"cmd"}))
        self.assertEqual(special_keys.switcher_chord("windows", "ios", "tab", {"alt"}), (("alt",), "cmd"))
        self.assertEqual(special_keys.switcher_chord("ios", "windows", "tab", {"cmd"}), (("cmd",), "alt"))

    def test_switcher_hold_survives_repeated_and_shift_tab_until_the_source_releases(self):
        messages, held_as = special_keys.switcher_transitions("macos", "windows", {"cmd": "ctrl"})
        self.assertEqual(held_as, {"cmd": "alt"})
        self.assertEqual(special_keys.switcher_transitions("macos", "windows", {"cmd": "alt"}), ([], {}))
        shifted = {"cmd": "alt", "shift": "shift"}
        self.assertEqual(special_keys.switcher_transitions("macos", "windows", shifted), ([], {}))
        self.assertEqual(special_keys.release_key("cmd", {"cmd": "alt", "shift": "shift"}), "alt")
        self.assertEqual(special_keys.release_key("shift", {"shift": "shift"}), "shift")

    def test_release_key_waits_until_the_last_physical_key_with_that_wire_name(self):
        held = {"alt": "cmd", "alt_r": "cmd"}
        self.assertIsNone(special_keys.release_key("alt", held))
        self.assertEqual(special_keys.release_key("alt_r", {"alt_r": "cmd"}), "cmd")

    def test_switcher_transitions_move_cmd_to_alt_once_and_keep_it(self):
        messages, held_as = special_keys.switcher_transitions("macos", "windows", {"cmd": "ctrl"})
        self.assertEqual(messages, [{"type": "keyup", "data": {"key": "ctrl"}},
                                    {"type": "keydown", "data": {"key": "alt"}}])
        self.assertEqual(held_as, {"cmd": "alt"})
        self.assertEqual(special_keys.switcher_transitions("macos", "windows", {"cmd": "alt"}), ([], {}))

    def test_switcher_transitions_leave_a_key_another_physical_key_still_holds(self):
        messages, _ = special_keys.switcher_transitions("macos", "linux", {"cmd": "ctrl", "ctrl": "ctrl"})
        self.assertEqual(messages, [{"type": "keydown", "data": {"key": "alt"}}])

    def test_switcher_transitions_alt_tab_to_a_mac_becomes_cmd(self):
        messages, held_as = special_keys.switcher_transitions("windows", "macos", {"alt": "alt"})
        self.assertEqual(messages, [{"type": "keyup", "data": {"key": "alt"}},
                                    {"type": "keydown", "data": {"key": "cmd"}}])
        self.assertEqual(held_as["alt"], "cmd")

    def test_switcher_transitions_nothing_without_the_modifier_or_between_like_systems(self):
        self.assertEqual(special_keys.switcher_transitions("macos", "windows", {"shift": "shift"}), ([], {}))
        self.assertEqual(special_keys.switcher_transitions("windows", "linux", {"alt": "alt"}), ([], {}))

    def test_plain_mac_function_keys_keep_their_physical_names(self):
        for key in ("f4", "f5", "f6"):
            self.assertEqual(special_keys.wire_name(key, "macos", "windows"), key)
            self.assertEqual(special_keys.wire_name(key, "macos", "linux"), key)

    def test_search_key_from_windows_or_linux_opens_mac_spotlight(self):
        self.assertEqual(special_keys.wire_name("browser_search", "windows", "macos"), "spotlight")
        self.assertEqual(special_keys.wire_name("search", "linux", "macos"), "spotlight")

    def test_windows_search_and_dictation_shortcuts_become_mac_intents(self):
        self.assertEqual(special_keys.windows_shortcut_intent("s"), "spotlight")
        self.assertEqual(special_keys.windows_shortcut_intent("h"), "dictation")
        self.assertEqual(special_keys.windows_shortcut_intent("n"), "")

    def test_mac_f13_print_screen_maps_to_the_windows_print_screen_key(self):
        self.assertEqual(special_keys.wire_name("f13", "macos", "windows"), "print_screen")

    def test_same_platform_and_unmapped_keys_keep_their_physical_name(self):
        self.assertEqual(special_keys.wire_name("f4", "macos", "macos"), "f4")
        self.assertEqual(special_keys.wire_name("f6", "macos", "windows"), "f6")
        self.assertEqual(special_keys.wire_name("volume_up", "windows", "macos"), "volume_up")

    def test_media_keys_keep_their_names_across_both_wire_directions(self):
        keys = ("volume_up", "volume_down", "volume_mute", "media_play_pause", "media_next", "media_prev")
        for key in keys:
            self.assertEqual(special_keys.wire_name(key, "macos", "windows"), key)
            self.assertEqual(special_keys.wire_name(key, "windows", "macos"), key)
            self.assertEqual(special_keys.wire_name(key, "linux", "windows"), key)


if __name__ == "__main__":
    unittest.main()
