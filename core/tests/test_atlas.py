import copy
import math
import unittest

from core import settings_sync, ways
from core.tests.crossing_harness import per_screen_layout


class AtlasTests(unittest.TestCase):
    def test_taller_a_display_keeps_both_contacts_that_share_its_end_third(self):
        held = {"machine_id": "A", "peers": [{"id": "B", "port": 24820, "side": ""}], "zones": []}
        layout = {
            "A": {"x": 100, "y": 0, "w": 200, "h": 120, "displays": {
                "a1": {"x": 0, "y": 0, "w": 100, "h": 120},
                "a0": {"x": 100, "y": 0, "w": 100, "h": 100},
            }},
            "B": {"x": 0, "y": 0, "w": 100, "h": 200, "displays": {
                "b0": {"x": 0, "y": 0, "w": 100, "h": 100},
                "b1": {"x": 0, "y": 100, "w": 100, "h": 100},
            }},
        }

        result = ways.compile_layout(held, layout, now=10)

        routes = {(zone.get("display"), zone.get("target_display"), zone["kind"])
                  for zone in result["settings"]["zones"] if zone.get("side") == "left"}
        self.assertIn(("a1", "b1", "part"), routes)

    def test_per_screen_contact_zones_keep_only_the_shared_span(self):
        own, other = "own", "other"
        held = {"machine_id": own, "peers": [{"id": other, "port": 24820, "side": "right"}], "zones": []}
        layout = {
            own: {"x": 0, "y": 0, "w": 100, "h": 100,
                  "displays": {"source": {"x": 0, "y": 0, "w": 100, "h": 100}}},
            other: {"x": 100, "y": 0, "w": 100, "h": 125,
                    "displays": {"above": {"x": 0, "y": 0, "w": 100, "h": 25},
                                 "target": {"x": 0, "y": 25, "w": 100, "h": 100}}},
        }

        result = ways.compile_layout(held, layout, now=10)

        zone = next(zone for zone in result["settings"]["zones"] if zone.get("target_display") == "target")
        self.assertEqual(zone["contact_span"], [0.25, 1.0])
        self.assertEqual(zone["target_span"], [0.0, 0.75])

    def test_per_screen_aba_below_compiles_on_both_machines(self):
        def routes(result):
            return {(zone["kind"], zone.get("display"), zone.get("side"), zone.get("corner"),
                     zone.get("target_display"), zone.get("target_side"), tuple(zone.get("parts", ())))
                    for zone in result["settings"]["zones"]}

        cases = (
            ("equal displays", {}, "right", "left",
             {("edge", "0", "right", None, "0", "left", ()),
              ("corner", "0", "right", "bottom_right", "1", "left", ()),
              ("edge", "1", "left", None, "0", "right", ()),
              ("corner", "1", "left", "bottom_left", "1", "right", ())},
             {("edge", "0", "left", None, "0", "right", ()),
              ("edge", "0", "right", None, "1", "left", ()),
              ("corner", "1", "left", "top_left", "0", "right", ()),
              ("corner", "1", "right", "top_right", "1", "left", ())}),
            ("mixed logical display sizes", {"a_sizes": ((120, 100), (150, 100)),
                                             "b_sizes": ((100, 100), (130, 90))}, "right", "left",
             {("edge", "0", "right", None, "0", "left", ()),
              ("corner", "0", "right", "bottom_right", "1", "left", ()),
              ("edge", "1", "left", None, "0", "right", ()),
              ("part", "1", "bottom", None, "1", "top", ("start",))},
             {("edge", "0", "left", None, "0", "right", ()),
              ("edge", "0", "right", None, "1", "left", ()),
              ("corner", "1", "left", "top_left", "0", "right", ()),
              ("part", "1", "top", None, "1", "bottom", ("end",))}),
            ("B1 offset left", {"b1_x": 80}, "right", "left",
             {("edge", "0", "right", None, "0", "left", ()),
              ("part", "0", "bottom", None, "1", "top", ("end",)),
              ("edge", "1", "left", None, "0", "right", ())},
             {("edge", "0", "left", None, "0", "right", ()),
              ("edge", "0", "right", None, "1", "left", ()),
              ("part", "1", "top", None, "0", "bottom", ("start",))}),
            ("B1 offset right", {"b1_x": 120}, "right", "left",
             {("edge", "0", "right", None, "0", "left", ()),
              ("edge", "1", "left", None, "0", "right", ()),
              ("part", "1", "bottom", None, "1", "top", ("start",))},
             {("edge", "0", "left", None, "0", "right", ()),
              ("edge", "0", "right", None, "1", "left", ()),
              ("part", "1", "top", None, "1", "bottom", ("end",))}),
        )
        for label, kwargs, side_a, side_b, zones_a, zones_b in cases:
            with self.subTest(layout=label):
                tiles = per_screen_layout(A, B, **kwargs)
                settings_a = {"machine_id": A, "peers": [{"id": B, "port": 24820, "side": ""}], "zones": []}
                settings_b = {"machine_id": B, "peers": [{"id": A, "port": 24820, "side": ""}], "zones": []}
                from_a = ways.compile_layout(settings_a, tiles, now=10)
                from_b = ways.compile_layout(settings_b, tiles, now=10)

                self.assertTrue(from_a["accepted"])
                self.assertTrue(from_b["accepted"])
                self.assertEqual(from_a["settings"]["peers"][0]["side"], side_a)
                self.assertEqual(from_b["settings"]["peers"][0]["side"], side_b)
                self.assertEqual(routes(from_a), zones_a)
                self.assertEqual(routes(from_b), zones_b)

    def test_shifted_b1_keeps_the_machine_tile_scale_and_moves_only_its_display(self):
        for offset in (80, 120):
            with self.subTest(b1_offset=offset):
                tile = per_screen_layout(A, B, b1_x=offset)[B]
                frames = {frame["display"]: frame for frame in ways._display_frames(tile)}
                self.assertEqual((tile["x"], tile["w"]), (100, 100))
                self.assertEqual((frames["0"]["x"], frames["0"]["w"]), (100, 100))
                self.assertEqual((frames["1"]["x"], frames["1"]["w"]), (offset, 100))

    def test_per_screen_zones_include_both_aba_edges_and_b1_corner_routes(self):
        tiles = per_screen_layout(A, B)
        settings_a = {"machine_id": A, "peers": [{"id": B, "port": 24820, "side": ""}], "zones": []}
        settings_b = {"machine_id": B, "peers": [{"id": A, "port": 24820, "side": ""}], "zones": []}
        from_a = ways.compile_layout(settings_a, tiles, now=10)["settings"]["zones"]
        from_b = ways.compile_layout(settings_b, tiles, now=10)["settings"]["zones"]
        a_edges = {(zone.get("display"), zone.get("side"), zone.get("target_display"), zone.get("target_side"))
                   for zone in from_a if zone["kind"] == "edge"}
        b_edges = {(zone.get("display"), zone.get("side"), zone.get("target_display"), zone.get("target_side"))
                   for zone in from_b if zone["kind"] == "edge"}
        self.assertEqual(a_edges, {("0", "right", "0", "left"), ("1", "left", "0", "right")})
        self.assertEqual(b_edges, {("0", "left", "0", "right"), ("0", "right", "1", "left")})
        self.assertEqual({(zone.get("display"), zone.get("corner"), zone.get("target_display"), zone.get("target_side"))
                          for zone in from_a if zone["kind"] == "corner"},
                         {("0", "bottom_right", "1", "left"), ("1", "bottom_left", "1", "right")})
        self.assertEqual({(zone.get("display"), zone.get("corner"), zone.get("target_display"), zone.get("target_side"))
                          for zone in from_b if zone["kind"] == "corner"},
                         {("1", "top_left", "0", "right"), ("1", "top_right", "1", "left")})

    def test_layout_compile_edge_part_gap_and_corner(self):
        settings = self.settings(A)
        layout = self.picture(settings, A, self.tile(160, 0, 160, 100))
        result = ways.compile_layout(settings, layout, now=10)
        self.assertEqual(result["tiles"][A]["state"], "edge")
        self.assertEqual(settings["peers"][0]["side"], "")
        self.assertEqual(settings["zones"], [])
        self.assertEqual(result["settings"]["peers"][0]["side"], "right")
        self.assertEqual(ways.ways(result["settings"], A)["methods"], ["edge"])

        settings = self.settings(A)
        result = ways.compile_layout(settings, self.picture(settings, A, self.tile(160, 67, 160, 33)), now=10)
        self.assertEqual(result["tiles"][A]["state"], "part")
        self.assertEqual(ways.ways(result["settings"], A)["parts"], ["start", "middle", "end"])
        self.assertEqual(result["settings"]["zones"], [{"peer": A, "kind": "part", "parts": ["end"],
                                                         "side": "right", "contact_span": [0.67, 1.0],
                                                         "target_span": [0.0, 1.0]}])

        settings = self.settings(A)
        result = ways.compile_layout(settings, self.picture(settings, A, self.tile(160, 20, 160, 10)), now=10)
        self.assertEqual(result["tiles"][A]["state"], "gap")
        self.assertEqual(ways.has_way(result["settings"], A), False)

        settings = self.settings(A)
        result = ways.compile_layout(settings, self.picture(settings, A, self.tile(160, 100, 100, 100)), now=10)
        self.assertEqual(result["tiles"][A]["state"], "corner")
        self.assertEqual(ways.ways(result["settings"], A)["methods"], ["edge"])
        corner = next(zone for zone in result["settings"]["zones"] if zone["peer"] == A and zone["kind"] == "corner")
        self.assertEqual(corner["edge"], ways.corner_edge(corner["corner"], "right"))

    def test_two_peers_share_thirds_and_can_touch_elsewhere(self):
        settings = self.settings(A, B)
        layout = self.picture(settings, A, self.tile(160, 0, 160, 33), B, self.tile(160, 67, 160, 33))
        result = ways.compile_layout(settings, layout, now=10)
        self.assertEqual(ways.ways(result["settings"], A)["parts"], ["start", "middle", "end"])
        self.assertEqual(ways.ways(result["settings"], B)["parts"], ["start", "middle", "end"])
        self.assertEqual(result["settings"]["zones"], [
            {"peer": A, "kind": "part", "parts": ["start"], "side": "right",
             "contact_span": [0.0, 0.33], "target_span": [0.0, 1.0]},
            {"peer": B, "kind": "part", "parts": ["end"], "side": "right",
             "contact_span": [0.67, 1.0], "target_span": [0.0, 1.0]},
        ])
        self.assertEqual(result["tiles"][A]["state"], "part")
        self.assertEqual(result["tiles"][B]["state"], "part")

        settings = self.settings(A)
        settings = self.settings(A, B)
        result = ways.compile_layout(settings, self.picture(settings, A, self.tile(320, 0, 160, 100), B, self.tile(480, 0, 160, 100)), now=10)
        self.assertEqual(result["tiles"][B]["state"], "set-elsewhere")

        settings = self.settings(A)
        result = ways.compile_layout(settings, self.picture(settings, A, self.tile(160, 33, 160, 34)), now=10)
        self.assertEqual(result["tiles"][A]["thirds"], ["middle"])

        settings = self.settings(A)
        result = ways.compile_layout(settings, self.picture(settings, A, self.tile(160, 15, 160, 36)), now=10)
        self.assertEqual(result["tiles"][A]["thirds"], ["start", "middle"])

    def test_fourth_contact_on_one_side_is_refused(self):
        settings = self.settings(A, B, C, D)
        layout = self.picture(settings,
                              D, self.tile(160, 51, 160, 17), A, self.tile(160, 0, 160, 17),
                              B, self.tile(160, 17, 160, 17), C, self.tile(160, 34, 160, 17))
        result = ways.compile_layout(settings, layout, moved=A, now=10)
        self.assertFalse(result["accepted"])
        self.assertEqual(set(result["snap"]), {A})
        self.assertEqual(result["tiles"][A]["state"], "overlap")
        self.assertEqual(result["snap"][A], ways.snap_position(layout[A], settings["machine_id"],
                                                               {k: v for k, v in layout.items() if k != A}))

    def test_unplaced_picture_peer_derives_no_side_and_keeps_its_ways(self):
        settings = self.settings(A)
        settings["peers"][0]["side"] = "left"
        settings["zones"] = [{"peer": A, "kind": "edge"}, {"peer": A, "kind": "notch"}]
        result = ways.compile_layout(settings, self.picture(settings, A, self.tile(400, 0, 160, 100)), now=10)
        self.assertTrue(result["accepted"])
        compiled = result["settings"]
        self.assertEqual(compiled["peers"][0]["side"], "")
        self.assertEqual(ways.ways(compiled, A)["methods"], ["edge", "notch"])
        self.assertEqual(compiled["zones"], [])

    def test_place_beside_centres_the_tile_for_a_whole_edge_and_keeps_its_fields(self):
        layout = {"T": self.tile(0, 0, 160, 100), A: {**self.tile(700, 300, 160, 100), "name": "A"}}
        self.assertEqual(ways.place_beside(layout, "T", A, "right"), {**self.tile(160, 0, 160, 100), "name": "A"})
        self.assertEqual(ways.place_beside(layout, "T", A, "top"), {**self.tile(0, -100, 160, 100), "name": "A"})
        layout[B] = self.tile(160, 0, 160, 100)
        moved = ways.place_beside(layout, "T", A, "right")
        self.assertFalse(ways._overlaps(moved, layout[B]))
        self.assertEqual(moved["name"], "A")

    def test_overlap_refused_with_nearest_free_snap(self):
        near = ways.snap_position(self.tile(162, -50, 160, 100), "T",
                                  {"T": self.tile(0, 0, 160, 100)}, radius=12)
        self.assertEqual(near, self.tile(160, -50, 160, 100))
        occupied = {"T": self.tile(0, 0, 160, 100), A: self.tile(160, 0, 160, 100)}
        target = self.tile(160, 0, 160, 100)
        snapped = ways.snap_position(target, "T", occupied, radius=12)
        self.assertFalse(ways._overlaps(snapped, occupied["T"]))
        self.assertFalse(ways._overlaps(snapped, occupied[A]))
        settings = self.settings(A, B)
        layout = self.picture(settings, A, self.tile(300, 0, 160, 100), B, self.tile(300, 0, 160, 100))
        result = ways.compile_layout(settings, layout, moved=B, now=10)
        self.assertFalse(result["accepted"])
        self.assertEqual(set(result["snap"]), {B})
        self.assertEqual(result["snap"][B], ways.snap_position(layout[B], settings["machine_id"],
                                                               {k: v for k, v in layout.items() if k != B}))
        self.assertFalse(ways._overlaps(result["snap"][B], layout[settings["machine_id"]]))
        self.assertFalse(ways._overlaps(result["snap"][B], layout[A]))
        self.assertEqual(result["tiles"][B]["state"], "overlap")

    def test_snap_near_each_side_centre_uses_the_centred_position(self):
        own = self.tile(0, 0, 160, 100)
        layout = {"T": own}
        positions = {"left": (-80, 30), "right": (160, 30),
                     "top": (40, -40), "bottom": (40, 100)}

        for side, (x, y) in positions.items():
            with self.subTest(side=side):
                dropped = self.tile(x+3, y-3, 80, 40)
                self.assertEqual(ways.snap_position(dropped, "T", layout, radius=4),
                                 self.tile(x, y, 80, 40))

    def test_snap_supports_both_flush_alignments_on_each_side(self):
        own = self.tile(0, 0, 160, 100)
        layout = {"T": own}
        positions = ((160, 0), (160, 60), (-80, 0), (-80, 60),
                     (0, -40), (80, -40), (0, 100), (80, 100))

        for x, y in positions:
            with self.subTest(position=(x, y)):
                dropped = self.tile(x+3, y+3, 80, 40)
                self.assertEqual(ways.snap_position(dropped, "T", layout, radius=6),
                                 self.tile(x, y, 80, 40))

    def test_snap_keeps_existing_third_marks(self):
        own = self.tile(0, 0, 160, 100)
        layout = {"T": own}
        expected = self.tile(160, 13, 80, 40)
        dropped = self.tile(162, 14, 80, 40)

        self.assertEqual(ways.snap_position(dropped, "T", layout), expected)

    def test_snap_prefers_centred_candidate_when_a_third_mark_is_equally_near(self):
        own = self.tile(0, 0, 160, 120)
        layout = {"T": own}
        dropped = self.tile(160, 30, 160, 80)

        self.assertEqual(ways.snap_position(dropped, "T", layout), self.tile(160, 20, 160, 80))

    def test_centred_snap_radius_is_larger_than_other_candidates(self):
        own = self.tile(0, 0, 160, 100)
        layout = {"T": own}
        dropped = self.tile(160, 38, 80, 40)

        self.assertTrue(ways.within_snap_radius(dropped, self.tile(160, 30, 80, 40), "T", layout, 6))
        self.assertFalse(ways.within_snap_radius(dropped, self.tile(160, 13, 80, 40), "T", layout, 6))

    def test_snap_uses_nearest_free_candidate_when_centre_is_occupied(self):
        own = self.tile(0, 0, 160, 100)
        centred = self.tile(160, 40, 80, 20)
        layout = {"T": own, A: centred}
        dropped = dict(centred)

        snapped = ways.snap_position(dropped, "T", layout, radius=12)

        self.assertNotEqual(snapped, centred)
        self.assertFalse(ways._overlaps(snapped, own))
        self.assertFalse(ways._overlaps(snapped, layout[A]))
        self.assertEqual(snapped, ways.snap_position(dropped, "T", layout, radius=math.inf))

    def test_overlap_marks_only_the_involved_tiles_and_keeps_other_contacts(self):
        settings = self.settings(A, B, C)
        layout = self.picture(settings, A, self.tile(160, 0, 160, 100),
                              B, self.tile(400, 0, 160, 100), C, self.tile(400, 0, 160, 100))

        result = ways.compile_layout(settings, layout, capable={A, B, C}, now=10)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["tiles"][A]["state"], "edge")
        for peer, other in ((B, C), (C, B)):
            self.assertEqual(result["tiles"][peer]["state"], "overlap")
            self.assertEqual(result["tiles"][peer]["overlap_with"], other)
            self.assertEqual(result["tiles"][peer]["sentence_keys"], ["overlap"])

    def test_overlapping_tiles_keep_intent_but_generate_no_zones(self):
        settings = self.settings(A, B)
        for peer in (A, B):
            next(entry for entry in settings["peers"] if entry["id"] == peer)["side"] = "left"
        settings["zones"] = [{"peer": A, "kind": "edge"}, {"peer": B, "kind": "edge", "off": True}]
        layout = self.picture(settings, A, self.tile(-160, 0, 160, 100), B, self.tile(-160, 50, 160, 100))

        result = ways.compile_layout(settings, layout, now=10)

        self.assertEqual(result["tiles"][A]["state"], "overlap")
        self.assertEqual(result["tiles"][B]["state"], "overlap")
        self.assertEqual(ways.ways(result["settings"], A)["methods"], ["edge"])
        self.assertEqual(ways.ways(result["settings"], B)["methods"], [])
        self.assertEqual(result["settings"]["zones"], [])

    def test_rc7_shape_keeps_pc_crossing_and_names_the_overlapping_pair(self):
        own, pc, laptop, fedora = "own", "pc", "laptop", "fedora"
        settings = {"machine_id": own, "peers": [
            {"id": pc, "port": 24820, "side": "right", "name": "Studio PC"},
            {"id": laptop, "port": 24820, "side": "top", "name": "Laptop"},
            {"id": fedora, "port": 24820, "side": "", "name": "Test box"},
        ], "zones": [], "layout": {}}
        settings["peers"][0]["paired_with"] = [fedora]
        layout = {own: self.tile(332, 0, 160, 100), pc: self.tile(172, 17, 160, 100),
                  laptop: self.tile(359, -100, 160, 100), fedora: self.tile(359, -100, 160, 100)}

        result = ways.compile_layout(settings, layout, capable={own, pc, laptop, fedora}, now=10)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["tiles"][pc]["state"], "part")
        self.assertTrue(ways.has_way(result["settings"], pc))
        self.assertEqual(result["tiles"][laptop]["state"], "overlap")
        self.assertEqual(result["tiles"][laptop]["overlap_with"], fedora)
        self.assertEqual(result["layout"].keys(), {own, pc, laptop, fedora})

    def test_missing_own_tile_is_placed_before_compiling_contacts(self):
        settings = self.settings(A)
        own = settings["machine_id"]
        result = ways.compile_layout(settings, {A: self.tile(160, 0, 160, 100)}, now=10)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["layout"][own], self.tile(0, 0, 160, 100))
        self.assertEqual(result["tiles"][A]["state"], "edge")

    def test_compiling_active_peers_preserves_shelved_peer_intent_without_zones(self):
        settings = self.settings(A, B)
        next(peer for peer in settings["peers"] if peer["id"] == B)["left_out"] = True
        remembered = {"peer": B, "kind": "part", "parts": ["start"]}
        settings["zones"] = [dict(remembered)]
        result = ways.compile_layout(settings, self.picture(settings, A, self.tile(160, 0, 160, 100)), now=10)
        self.assertTrue(result["accepted"])
        self.assertFalse(any(zone["peer"] == B for zone in result["settings"]["zones"]))
        self.assertEqual(ways.ways(result["settings"], B)["parts"], ["start"])

    def test_derive_matches_legacy_mac_placement_examples(self):
        arrangements = [
            [("right", None)], [("left", None), ("right", None)],
            [("right", 2), ("right", 0)], [("right", None), ("top", None)],
        ]
        recorded = [
            ((179.0, 142.5, 120.0, 75.0), [(309.0, 148.5, 112.0, 63.0)]),
            ((240.0, 142.5, 120.0, 75.0), [(118.0, 148.5, 112.0, 63.0), (370.0, 148.5, 112.0, 63.0)]),
            ((207.0, 142.5, 120.0, 75.0), [(337.0, 183.0, 56.0, 31.5), (337.0, 145.5, 56.0, 31.5)]),
            ((179.0, 179.0, 120.0, 75.0), [(309.0, 185.0, 112.0, 63.0), (183.0, 106.0, 112.0, 63.0)]),
        ]
        from mac_app import pages
        self.assertIs(pages.diagram_layout, ways.diagram_layout)
        for machines in arrangements:
            with self.subTest(machines=machines):
                index = arrangements.index(machines)
                self.assertEqual(ways.diagram_layout(600, 360, machines), recorded[index])
                self.assertEqual(pages.diagram_layout(600, 360, machines), recorded[index])

    def test_saved_peer_tiles_are_authoritative_when_deriving_layout(self):
        settings = self.settings(A, B)
        settings["peers"][0]["paired_with"] = [C]
        settings["peers"][0]["side"] = "right"
        settings["layout"] = {settings["machine_id"]: self.tile(0, 0, 160, 100),
                               A: self.tile(172, 0, 160, 100),
                               B: self.tile(-172, 40, 160, 100),
                               C: {**self.tile(400, 0, 160, 100), "name": "Test box"}}

        layout = ways.derive_layout(settings)

        self.assertEqual(layout[A], settings["layout"][A])
        self.assertEqual(layout[B], settings["layout"][B])
        self.assertEqual(layout[C], settings["layout"][C])

    def test_missing_peer_avoids_saved_tiles_and_keeps_saved_metadata(self):
        settings = self.settings(A, B)
        own = settings["machine_id"]
        saved = {**self.tile(0, 100, 160, 100), "name": "Saved Mac",
                 "displays": {"main": {"x": 0, "y": 0, "w": 160, "h": 100}},
                 "display_offsets": {"main": {"x": 10, "y": 0}}}
        settings["peers"][0]["side"] = "bottom"
        settings["layout"] = {own: self.tile(0, 0, 160, 100), A: saved}

        layout = ways.derive_layout(settings, gap=0)

        self.assertEqual(layout[A], {**self.tile(0, 100, 160, 100), "displays": saved["displays"],
                                     "display_offsets": saved["display_offsets"], "name": "Saved Mac"})
        self.assertFalse(ways._overlaps(layout[B], layout[own]))
        self.assertFalse(ways._overlaps(layout[B], layout[A]))
        self.assertIsNotNone(ways._rect_contact(layout[own], layout[B]))

    def test_a_shelved_peers_kept_tile_never_blocks_an_active_peers_side(self):
        settings = self.settings(A, B)
        own = settings["machine_id"]
        settings["peers"][0].update(side="right", left_out=True)
        settings["peers"][1]["side"] = "right"
        settings["layout"] = {own: self.tile(0, 0, 160, 100), A: self.tile(160, 0, 160, 100)}

        layout = ways.derive_layout(settings, gap=0)

        self.assertEqual(layout[B], self.tile(160, 0, 160, 100))
        self.assertEqual(layout[A], self.tile(160, 0, 160, 100))

    def test_rc13_right_peer_fills_free_snap_beside_saved_left_peer(self):
        settings = self.settings(A, B)
        own = settings["machine_id"]
        settings["peers"][0]["side"] = "left"
        settings["peers"][1]["side"] = "right"
        settings["layout"] = {own: self.tile(-500, 149, 160, 100),
                               A: self.tile(-660, 149, 160, 100)}

        layout = ways.derive_layout(settings, gap=0)

        self.assertEqual(layout[B], self.tile(-340, 149, 160, 100))
        self.assertEqual(layout[A], settings["layout"][A])

    def test_layout_keeps_only_named_third_parties_listed_by_active_desktops(self):
        settings = self.settings(A, B)
        settings["peers"][0]["paired_with"] = [C, D]
        settings["layout"].update({
            A: self.tile(160, 0, 160, 100),
            B: self.tile(320, 0, 160, 100),
            C: {**self.tile(480, 0, 160, 100), "name": "Test box"},
            D: self.tile(640, 0, 160, 100),
        })

        layout = ways.derive_layout(settings)

        self.assertEqual(set(layout), {settings["machine_id"], A, B, C})
        self.assertEqual(layout[C]["name"], "Test box")

    def test_rc7_ghost_tiles_are_pruned_and_not_derived_or_fabricated(self):
        own, pc, laptop, phone, box, old_pc = "M", "PC", "LAPTOP", "PHONE", "BOX", "OLDPC"
        settings = {"machine_id": own, "peers": [
            {"id": pc, "port": 24820, "left_out": True, "paired_with": [phone, box]},
            {"id": laptop, "port": 24820, "paired_with": [old_pc]},
        ], "zones": [], "layout": {
            own: self.tile(0, 0, 160, 100), pc: {**self.tile(172, 0, 160, 100), "vouched_by": laptop},
            laptop: self.tile(344, 0, 160, 100),
            phone: {**self.tile(516, 0, 160, 100), "vouched_by": pc},
            box: {**self.tile(688, 0, 160, 100), "vouched_by": pc},
            old_pc: {**self.tile(860, 0, 160, 100), "vouched_by": laptop},
        }, "layout_set_at": 5, "layout_by": "before"}

        self.assertTrue(ways.prune_layout(settings, now=10))
        self.assertTrue({phone, box, old_pc}.isdisjoint(settings["layout"]))
        self.assertNotIn("vouched_by", settings["layout"][pc])
        self.assertFalse({phone, box, old_pc} & set(ways.derive_layout(settings)))
        incoming = {own: self.tile(0, 0, 160, 100), pc: self.tile(172, 0, 160, 100)}
        retained = ways.retain_held_peer_tiles(settings, incoming, settings["layout"])
        self.assertTrue({phone, box, old_pc}.isdisjoint(retained))
        received = {**incoming, **{ghost: self.tile(900, 0, 160, 100) for ghost in (phone, box, old_pc)}}
        retained = ways.retain_held_peer_tiles(settings, incoming, settings["layout"], received)
        self.assertEqual(set(retained), {own, pc, laptop})

    def test_named_third_party_tile_requires_a_live_non_shelved_peer(self):
        own, pc, box = "M", "PC", "BOX"
        settings = {"machine_id": own, "peers": [
            {"id": pc, "port": 24820, "paired_with": [box]},
        ], "zones": [], "layout": {
            own: self.tile(0, 0, 160, 100), pc: self.tile(172, 0, 160, 100),
            box: {**self.tile(344, 0, 160, 100), "name": "Test box"},
        }}

        self.assertIn(box, ways.derive_layout(settings))
        settings["peers"][0]["paired_with"] = []
        self.assertNotIn(box, ways.derive_layout(settings))
        settings["peers"][0]["paired_with"] = [box]
        settings["peers"][0]["in_use"] = False
        self.assertNotIn(box, ways.derive_layout(settings))
        settings["peers"][0]["in_use"] = True
        settings["peers"][0]["dormant"] = True
        self.assertNotIn(box, ways.derive_layout(settings))
        settings["peers"][0]["dormant"] = False
        settings["peers"][0]["left_out"] = True
        self.assertNotIn(box, ways.derive_layout(settings))

    def test_pruning_strips_vouch_metadata_without_restamping(self):
        settings = self.settings(A)
        own = settings["machine_id"]
        settings["layout"][own]["vouched_by"] = A
        settings["layout_set_at"] = 5

        self.assertTrue(ways.prune_layout(settings, now=10))
        self.assertNotIn("vouched_by", settings["layout"][own])
        self.assertEqual(settings["layout_set_at"], 5)
        self.assertNotIn("layout_by", settings)

    def test_compile_layout_drops_an_unvouched_stale_tile_before_contact_checks(self):
        settings = self.settings(A)
        layout = self.picture(settings, A, self.tile(160, 0, 160, 100),
                              D, self.tile(160, 0, 160, 100))

        result = ways.compile_layout(settings, layout, now=10)

        self.assertTrue(result["accepted"])
        self.assertNotIn(D, result["tiles"])
        self.assertNotIn(D, result["settings"]["layout"])

    def test_pruning_stamps_the_cleaned_shared_picture(self):
        settings = self.settings(A)
        own = settings["machine_id"]
        settings["peers"][0]["paired_with"] = [C]
        settings["layout"] = {own: self.tile(0, 0, 160, 100),
                               A: self.tile(160, 0, 160, 100),
                               C: {**self.tile(320, 0, 160, 100), "name": "Test box"},
                               D: self.tile(480, 0, 160, 100)}
        settings["layout_set_at"] = 5

        self.assertTrue(ways.prune_layout(settings, now=10))

        self.assertEqual(set(settings["layout"]), {own, A, C})
        self.assertGreater(settings["layout_set_at"], 5)
        self.assertEqual(settings["layout_by"], own)

    def test_named_third_party_tile_survives_while_its_direct_peer_lists_it(self):
        own, pc, laptop, box = "BQUFBQUFBQUFBQUFBQUFBQ", "BgYGBgYGBgYGBgYGBgYGBg", \
            "CAgICAgICAgICAgICAgICA", "BwcHBwcHBwcHBwcHBwcHBw"
        settings = {"machine_id": own, "peers": [
            {"id": pc, "port": 24820, "paired_with": [box]},
        ], "layout_set_at": 5, "layout": {
            own: self.tile(0, 0, 160, 100), pc: self.tile(172, 0, 160, 100),
            box: {**self.tile(344, 0, 160, 100), "name": "Test box"},
            laptop: {**self.tile(516, 0, 160, 100), "name": "Laptop"},
        }}

        ways.prune_layout(settings, now=10)

        self.assertEqual(set(settings["layout"]), {own, pc, box})

    def test_named_third_party_is_dropped_when_its_peer_no_longer_lists_it(self):
        own, mac, laptop, fedora = "BgYGBgYGBgYGBgYGBgYGBg", "BQUFBQUFBQUFBQUFBQUFBQ", \
            "CAgICAgICAgICAgICAgICA", "BwcHBwcHBwcHBwcHBwcHBw"
        settings = {"machine_id": own, "peers": [
            {"id": mac, "port": 24820, "paired_with": [laptop]},
            {"id": fedora, "port": 24820, "paired_with": [mac]},
        ], "layout": {ident: self.tile(index * 172, 0, 160, 100)
                       for index, ident in enumerate((own, mac, fedora, laptop))}}
        settings["layout"][laptop]["name"] = "Laptop"

        ways.prune_layout(settings, now=10)
        self.assertIn(laptop, settings["layout"])
        settings["peers"][0]["paired_with"] = []
        ways.prune_layout(settings, now=11)
        self.assertNotIn(laptop, settings["layout"])

    def test_received_layout_restores_missing_locally_held_peer_tiles(self):
        own, pc, fedora = "BQUFBQUFBQUFBQUFBQUFBQ", "BgYGBgYGBgYGBgYGBgYGBg", "BwcHBwcHBwcHBwcHBwcHBw"
        settings = {"machine_id": own, "peers": [
            {"id": pc, "port": 24820, "side": "right", "paired_with": [fedora]},
        ], "zones": [], "layout": {
            own: self.tile(0, 0, 160, 100), pc: self.tile(172, 0, 160, 100),
            fedora: {**self.tile(344, 0, 160, 100), "name": "Test box"},
        }}
        incoming = {own: self.tile(0, 0, 160, 100), pc: self.tile(172, 0, 160, 100)}

        merged = ways.retain_held_peer_tiles(settings, incoming, settings["layout"])

        self.assertEqual(merged[fedora], settings["layout"][fedora])

    def test_received_layout_places_a_missing_held_peer_by_its_default_side(self):
        own, peer = self.ident(50), self.ident(1)
        settings = {"machine_id": own, "peers": [
            {"id": peer, "port": 24820, "side": "right", "paired_with": []},
        ], "zones": [], "layout": {own: self.tile(0, 0, 160, 100)}}

        merged = ways.retain_held_peer_tiles(settings, {own: self.tile(0, 0, 160, 100)}, settings["layout"])

        # Flush, so it touches and keeps crossing; a 12 gap left it with no contact and no side.
        self.assertEqual(merged[peer], self.tile(160, 0, 160, 100))

    def test_received_layout_keeps_a_present_shelved_peer_tile_exactly(self):
        own, peer, shelf = self.ident(50), self.ident(1), self.ident(2)
        received = {shelf: {**self.tile(160, 0, 160, 100), "name": "Shelf"}}
        settings = {"machine_id": own, "peers": [
            {"id": peer, "port": 24820, "side": "right", "paired_with": []},
            {"id": shelf, "port": 24820, "side": "right", "left_out": True, "paired_with": []},
        ], "zones": [], "layout": {
            own: self.tile(0, 0, 160, 100), peer: self.tile(172, 0, 160, 100),
            shelf: self.tile(344, 0, 160, 100),
        }}

        merged = ways.retain_held_peer_tiles(
            settings, {own: self.tile(0, 0, 160, 100), peer: self.tile(160, 0, 160, 100)},
            settings["layout"], received)

        self.assertEqual(merged[shelf], received[shelf])

    def test_rc7_shared_picture_keeps_only_named_thirds_in_the_current_paired_list(self):
        own, peer, third = "M", "PC", "BOX"
        settings = {"machine_id": own, "peers": [
            {"id": peer, "port": 24820, "side": "left", "paired_with": [third]},
        ], "zones": [], "layout": {own: self.tile(0, 0, 100, 100)}}
        layout = {own: self.tile(0, 0, 100, 100), peer: self.tile(112, 0, 100, 100),
                  third: {**self.tile(224, 0, 100, 100), "name": "Test box"}}

        result = ways.compile_layout(settings, layout, capable={own, peer, third}, now=10)

        self.assertTrue(result["accepted"])
        self.assertIn(third, result["layout"])
        self.assertNotIn("vouched_by", result["layout"][third])
        result["settings"]["peers"][0]["paired_with"] = []
        ways.prune_layout(result["settings"], now=11)
        self.assertNotIn(third, result["settings"]["layout"])

    def test_arrangement_inverse_repositions_peer_from_new_side(self):
        settings = self.settings(A)
        layout = self.picture(settings, A, self.tile(160, 0, 160, 33))
        settings = ways.compile_layout(settings, layout, now=10)["settings"]
        settings["layout"][settings["machine_id"]]["x"] = 500
        changed = ways.arrangement(settings, A, "left", 20, self.ident(8), "this PC")
        self.assertTrue(changed[0])
        updated = settings["layout"]
        self.assertEqual(updated[A]["x"], 660)
        self.assertIsNotNone(ways._rect_contact(updated[settings["machine_id"]], updated[A]))

    def test_inverse_repositions_all_peers_on_old_and_new_sides_without_overlap(self):
        settings = self.settings(A, B, C)
        settings["peers"][0]["side"] = "right"
        settings["peers"][1]["side"] = "right"
        settings["peers"][2]["side"] = "top"
        layout = self.picture(settings, A, self.tile(172, 0, 160, 100), B, self.tile(172, 112, 160, 100),
                              C, self.tile(0, -112, 160, 100))
        settings["layout"] = layout
        settings["peers"][0]["side"] = "left"
        updated = ways.inverse_layout(settings, layout, peer=A)
        for one, tile in updated.items():
            for two, other in updated.items():
                if one < two:
                    self.assertFalse(ways._overlaps(tile, other), (one, two, tile, other))
        self.assertEqual(updated[B], layout[B])
        self.assertEqual(updated[C], layout[C])

    def test_set_elsewhere_only_when_a_peer_lacks_layout_capability(self):
        settings = self.settings(A, B)
        layout = self.picture(settings, A, self.tile(320, 0, 160, 100), B, self.tile(480, 0, 160, 100))
        result = ways.compile_layout(settings, layout, capable={A, B}, now=10)
        self.assertEqual(result["tiles"][A]["state"], "between")
        self.assertEqual(result["tiles"][B]["state"], "between")
        self.assertEqual(result["tiles"][A]["sentence_keys"], ["between"])
        self.assertEqual(ways.ATLAS_SENTENCES["between"], "Crosses between {first} and {second}.")
        self.assertEqual(ways.ATLAS_SENTENCES["set_elsewhere"], "Set on {first} or {second}.")

    def test_single_tile_model_has_no_second_contact_sentence(self):
        self.assertNotIn("second_contact", ways.ATLAS_SENTENCES)

    def test_compiled_layout_stamp_round_trips_as_base64_by(self):
        settings = self.settings(A)
        layout = self.picture(settings, A, self.tile(160, 0, 160, 100))
        result = ways.compile_layout(settings, layout, moved=A, now=10)
        self.assertEqual(result["settings"]["layout_by"], result["settings"]["machine_id"])
        state = {"set_at": result["settings"]["layout_set_at"],
                 "by": result["settings"]["layout_by"], "tiles": result["settings"]["layout"]}
        data = settings_sync.message_data(False, 5, by=self.ident(2), layout_state=state)
        self.assertEqual(settings_sync.read_layout_state(data, now=10), state)

    def test_layout_settings_sync_newest_clock_relay_and_capability(self):
        state = {"set_at": 10, "by": self.ident(1), "tiles": {A: self.tile(1, 2, 160, 100)}}
        data = settings_sync.message_data(False, 5, by=self.ident(2), layout_state=state)
        self.assertEqual(settings_sync.read_layout_state(data, now=10)["set_at"], 10)
        self.assertIsNone(settings_sync.read_layout_state(data, now=10 - settings_sync.DAY - 1))
        self.assertTrue(settings_sync.layout_arrived(state, 9, self.ident(2)))
        self.assertFalse(settings_sync.layout_arrived(state, 10, self.ident(2)))
        same_time_later_author = dict(state, by=self.ident(3))
        self.assertTrue(settings_sync.layout_arrived(same_time_later_author, 10, self.ident(2)))
        self.assertEqual(settings_sync.layout_recipients({A: {"settings", "layout"}, B: {"settings"}}), [A])
        self.assertNotIn("layout", settings_sync.for_capabilities(data, {"settings"}))
        self.assertIn("layout", settings_sync.for_capabilities(data, {"settings", "layout"}))

    def test_layout_state_carries_validated_display_rectangles(self):
        displays = {"panel-left": {"x": -1280, "y": 0, "w": 1280, "h": 800},
                    "panel-right": {"x": 0, "y": 0, "w": 1920, "h": 1080}}
        tiles = {A: dict(self.tile(0, 0, 160, 100), displays=displays)}
        state = {"set_at": 10, "by": self.ident(1), "tiles": tiles}
        data = settings_sync.message_data(False, 5, by=self.ident(2), layout_state=state)
        self.assertEqual(settings_sync.read_layout_state(data, now=10)["tiles"][A]["displays"], displays)
        malformed_tiles = {A: dict(self.tile(0, 0, 160, 100),
                                   displays={"panel-left": {"x": -1280, "y": 0, "w": 0, "h": 800}})}
        malformed = dict(state, tiles=malformed_tiles)
        self.assertIsNone(settings_sync.read_layout_state(
            settings_sync.message_data(False, 5, by=self.ident(2), layout_state=malformed), now=10))
        newer = settings_sync.for_capabilities(data, {"settings", "layout", "displays"})
        older = settings_sync.for_capabilities(data, {"settings", "layout"})
        self.assertIn("displays", newer["layout"]["tiles"][A])
        self.assertNotIn("displays", older["layout"]["tiles"][A])

    def test_layout_state_carries_the_machine_name_for_third_party_tiles(self):
        settings = self.settings(A)
        tiles = self.picture(settings, A, {**self.tile(160, 0, 160, 100), "name": "Test box"})
        data = settings_sync.message_data(False, 5, by=self.ident(2),
                    layout_state={"set_at": 5, "by": self.ident(2), "tiles": tiles})

        parsed = settings_sync.read_layout_state(data, now=10)

        self.assertEqual(parsed["tiles"][A]["name"], "Test box")

    def test_blank_optional_tile_name_is_dropped_without_rejecting_other_tiles(self):
        tiles = {A: {**self.tile(0, 0, 160, 100), "name": "  "},
                 B: self.tile(160, 0, 160, 100)}
        data = settings_sync.message_data(False, 5, by=self.ident(2),
                    layout_state={"set_at": 5, "by": self.ident(2), "tiles": tiles})

        parsed = settings_sync.read_layout_state(data, now=10)

        self.assertEqual(set(parsed["tiles"]), {A, B})
        self.assertNotIn("name", parsed["tiles"][A])

    def test_a_peer_between_two_displays_compiles_two_local_edges(self):
        settings = self.settings(A)
        layout = {
            settings["machine_id"]: {
                "x": 0, "y": 0, "w": 300, "h": 100,
                "displays": {
                    "panel-left": {"x": 0, "y": 0, "w": 100, "h": 100},
                    "panel-right": {"x": 200, "y": 0, "w": 100, "h": 100},
                },
            },
            A: self.tile(100, 0, 100, 100),
        }
        result = ways.compile_layout(settings, layout, now=10)
        zones = [zone for zone in result["settings"]["zones"] if zone["peer"] == A and zone["kind"] == "edge"]
        self.assertEqual([(zone["display"], zone["side"]) for zone in zones],
                         [("panel-left", "right"), ("panel-right", "left")])
        self.assertEqual(result["settings"]["peers"][0]["side"], "right")

    def test_rc6_saved_display_layout_keeps_the_mac_and_pc_edge_and_the_laptop_edge(self):
        own, pc, laptop, fedora = "BQUFBQUFBQUFBQUFBQUFBQ", "BgYGBgYGBgYGBgYGBgYGBg", \
            "CAgICAgICAgICAgICAgICA", "BwcHBwcHBwcHBwcHBwcHBw"
        settings = {"machine_id": own, "peers": [
            {"id": pc, "port": 24820, "side": "left", "name": "Studio PC"},
            {"id": laptop, "port": 24820, "side": "bottom", "name": "Laptop"},
        ], "zones": [
            {"peer": pc, "kind": "edge", "display": "0", "side": "left", "target_side": "right", "off": True},
            {"peer": pc, "kind": "part", "parts": ["middle", "end"], "display": "0", "side": "left", "target_side": "right"},
            {"peer": laptop, "kind": "edge", "display": "0", "side": "bottom", "target_side": "top", "off": True},
            {"peer": laptop, "kind": "part", "parts": ["middle", "end"], "display": "0", "side": "bottom", "target_side": "top"},
        ]}
        settings["peers"][0]["paired_with"] = [fedora]
        layout = {
            own: {"x": 332, "y": 0, "w": 160, "h": 100,
                  "displays": {"0": {"x": 0, "y": 0, "w": 1728, "h": 1117}}},
            pc: self.tile(172, 17, 160, 100),
            laptop: self.tile(359, 100, 160, 100),
            fedora: {**self.tile(359, -100, 160, 100), "name": "Test box"},
        }

        result = ways.compile_layout(settings, layout, capable={own, pc, laptop, fedora}, now=10)

        self.assertTrue(result["accepted"])
        self.assertIn(result["tiles"][pc]["state"], ("edge", "part"))
        self.assertIn(result["tiles"][laptop]["state"], ("edge", "part"))
        self.assertTrue(ways.has_way(result["settings"], pc))
        self.assertTrue(ways.has_way(result["settings"], laptop))
        self.assertEqual(result["layout"][fedora]["name"], "Test box")

    def test_shared_picture_accepts_named_third_party_in_current_paired_list(self):
        own, peer, third = "BQUFBQUFBQUFBQUFBQUFBQ", "BgYGBgYGBgYGBgYGBgYGBg", "BwcHBwcHBwcHBwcHBwcHBw"
        settings = {"machine_id": own, "peers": [{"id": peer, "port": 24820, "side": "left",
                                                    "paired_with": [third]}], "zones": []}
        layout = {
            own: self.tile(0, 0, 100, 100),
            peer: self.tile(112, 0, 100, 100),
            third: {**self.tile(224, 0, 100, 100), "name": "Test box"},
        }

        result = ways.compile_layout(settings, layout, capable={own, peer, third}, now=10)

        self.assertTrue(result["accepted"])
        self.assertIn(third, result["layout"])
        self.assertNotIn("vouched_by", result["layout"][third])

        saved = result["settings"]
        saved["layout"] = result["layout"]
        self.assertIn(third, ways.derive_layout(saved))
        saved["peers"] = []
        ways.prune_layout(saved, now=11)
        self.assertNotIn(third, saved["layout"])

    def test_new_layout_peers_are_placed_touching_the_local_machine(self):
        settings = self.settings(A)
        settings["peers"][0]["side"] = ""

        layout = ways.derive_layout(settings)

        self.assertIsNotNone(ways._rect_contact(layout[settings["machine_id"]], layout[A]))

    def test_reporting_a_display_change_updates_the_shared_layout_stamp_once(self):
        settings = self.settings(A)
        settings["layout"] = {settings["machine_id"]: self.tile(0, 0, 160, 100),
                               A: self.tile(172, 0, 160, 100)}
        displays = {"0": ways.return_edge.Rect(-100, 0, 100, 100),
                    "1": ways.return_edge.Rect(0, 0, 200, 100)}
        self.assertTrue(ways.refresh_displays(settings, displays, now=10))
        self.assertEqual(settings["layout"][settings["machine_id"]]["displays"],
                         {key: {"x": rect.x, "y": rect.y, "w": rect.width, "h": rect.height}
                          for key, rect in displays.items()})
        stamp = settings["layout_set_at"]
        self.assertFalse(ways.refresh_displays(settings, displays, now=11))
        self.assertEqual(settings["layout_set_at"], stamp)

    def test_split_display_offsets_move_one_panel_without_changing_its_reported_geometry(self):
        tile = {
            "x": 10, "y": 20, "w": 300, "h": 100,
            "displays": {
                "left": {"x": 0, "y": 0, "w": 100, "h": 100},
                "right": {"x": 100, "y": 0, "w": 200, "h": 100},
            },
            "display_offsets": {"right": {"x": 25, "y": -10}},
        }
        frames = {frame["display"]: frame for frame in ways._display_frames(tile)}
        self.assertEqual((frames["left"]["x"], frames["left"]["y"]), (10, 20))
        self.assertEqual((frames["right"]["x"], frames["right"]["y"]), (135, 10))
        self.assertEqual(tile["displays"]["right"], {"x": 100, "y": 0, "w": 200, "h": 100})

    def test_display_offsets_must_name_reported_displays_and_use_integer_offsets(self):
        valid = {"x": 0, "y": 0, "w": 300, "h": 100,
                 "displays": {"left": {"x": 0, "y": 0, "w": 100, "h": 100}},
                 "display_offsets": {"left": {"x": 1, "y": -2}}}
        self.assertTrue(ways._valid_tile_displays(valid))
        for offsets in ({"missing": {"x": 0, "y": 0}}, {"left": {"x": 0, "y": 0.5}}, []):
            self.assertFalse(ways._valid_tile_displays(dict(valid, display_offsets=offsets)))

    def test_design_sync_remains_optional_without_a_capability_gate(self):
        design = {"set_at": 10, "by": self.ident(1), "values": {"effect_length": "long"}}
        data = settings_sync.message_data(False, 5, design_state=design)
        filtered = settings_sync.for_capabilities(data, {"settings"})
        self.assertEqual(filtered["design_sync"], design)

    def test_layout_receiver_compiles_its_own_zones(self):
        settings = self.settings(A)
        tiles = self.picture(settings, A, self.tile(160, 0, 160, 100))
        received = {"set_at": 10, "by": self.ident(2), "tiles": tiles}
        data = settings_sync.message_data(False, 5, by=self.ident(2), layout_state=received)
        parsed = settings_sync.read_layout_state(data, now=10)
        self.assertEqual(parsed["tiles"], tiles)
        result = ways.compile_layout(settings, parsed["tiles"], now=10)
        self.assertTrue(result["accepted"])
        self.assertEqual(ways.ways(result["settings"], A)["methods"], ["edge"])

    def test_layout_receiver_preserves_split_display_offsets(self):
        settings = self.settings(A)
        tiles = self.picture(settings, A, self.tile(160, 0, 300, 100))
        tiles[A]["displays"] = {"left": {"x": 0, "y": 0, "w": 100, "h": 100},
                                 "right": {"x": 100, "y": 0, "w": 200, "h": 100}}
        tiles[A]["display_offsets"] = {"right": {"x": 24, "y": -8}}
        data = settings_sync.message_data(False, 5, layout_state={"set_at": 10, "by": self.ident(2), "tiles": tiles})
        parsed = settings_sync.read_layout_state(data, now=10)
        self.assertEqual(parsed["tiles"][A]["display_offsets"], tiles[A]["display_offsets"])
        old_peer = settings_sync.for_capabilities(data, {"settings", "layout"})
        self.assertNotIn("display_offsets", old_peer["layout"]["tiles"][A])
        malformed = copy.deepcopy(data)
        malformed["layout"]["tiles"][A]["display_offsets"]["ghost"] = {"x": 0, "y": 0}
        self.assertIsNone(settings_sync.read_layout_state(malformed, now=10))

    @staticmethod
    def tile(x, y, w, h):
        return {"x": x, "y": y, "w": w, "h": h}

    @staticmethod
    def ident(n):
        import base64
        return base64.urlsafe_b64encode(bytes([n]) * 16).decode().rstrip("=")

    def settings(self, *peers):
        own = self.ident(50)
        entries = [{"id": peer, "side": "", "side_set_at": 0, "side_by": "", "port": 24820,
                    "name": peer, "in_use": True} for peer in peers]
        return {"machine_id": own, "peers": entries, "zones": [], "layout": {own: self.tile(0, 0, 160, 100)}}

    def picture(self, settings, *items):
        layout = dict(settings["layout"])
        layout.update({items[i]: items[i + 1] for i in range(0, len(items), 2)})
        return layout


A = settings_id = "AQEBAQEBAQEBAQEBAQEBAQ"
B = "AgICAgICAgICAgICAgICAg"
C = "AwMDAwMDAwMDAwMDAwMDAw"
D = "BAQEBAQEBAQEBAQEBAQEBA"


if __name__ == "__main__":
    unittest.main()


class CrossingStretchTests(unittest.TestCase):
    own = {"x": 0, "y": 0, "w": 160, "h": 90}

    def test_whole_edge_and_no_thirds_light_the_whole_contact(self):
        contact = ("right", 0, 90)
        self.assertEqual(ways.crossing_stretches(contact, self.own, []), [contact])
        self.assertEqual(ways.crossing_stretches(contact, self.own, ["start", "middle", "end"]), [contact])

    def test_only_the_picked_thirds_light(self):
        self.assertEqual(ways.crossing_stretches(("right", 0, 90), self.own, ["start"]), [("right", 0, 30)])
        self.assertEqual(ways.crossing_stretches(("bottom", 0, 160), self.own, ["start", "end"]),
                         [("bottom", 0, 160 / 3), ("bottom", 320 / 3, 160)])

    def test_a_third_outside_the_contact_lights_nothing(self):
        self.assertEqual(ways.crossing_stretches(("right", 0, 30), self.own, ["end"]), [])

    def test_a_corner_is_untouched(self):
        contact = ("corner", "top_right", None)
        self.assertEqual(ways.crossing_stretches(contact, self.own, ["start"]), [contact])
