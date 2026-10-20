"""The rig's rc13 map (10-10-2026): the Mac saved to the left of this PC, the loan laptop paired on the
right with no tile of its own. The owner saw a vertical stack, tiny tiles and a mostly empty map."""

import unittest

import app_config
import test_crossing_page_parity as parity
from core import pairing, peerlist


class RigMapRc13(unittest.TestCase):
    setUp = parity.CrossingPageParityTests.setUp
    tearDown = parity.CrossingPageParityTests.tearDown
    _open_window = parity.CrossingPageParityTests._open_window
    _close_window = parity.CrossingPageParityTests._close_window
    _stop_patches = parity.CrossingPageParityTests._stop_patches

    def _rig(self, stacked=False):
        self._close_window()
        settings = app_config.migrate({"appearance": "dark", "name": "Desk PC", "peers": [], "check_updates": False})
        settings.update(name="Desk PC", check_updates=False)
        self.peers = []
        for index, (name, platform) in enumerate((("Studio Mac", "macos"), ("Loan laptop", "windows"))):
            entry = pairing.peer_entry(bytes([index + 7]) * 16, name, platform, 24820 + index,
                                       "A" * 43, f"192.168.1.{20 + index}", 1791321600 + index)
            entry["linked"] = True
            peerlist.add_peer(settings, entry)
            self.peers.append(entry)
        app_config.write_settings(self.path, settings)
        mac, acg = (entry["id"] for entry in self.peers)
        app_config.set_ways(self.path, mac, side="left", methods=["part", "corner"], parts=["start", "end"],
                            corner="bottom_right")
        app_config.set_ways(self.path, acg, side="" if stacked else "right",
                            methods=["edge"], parts=[], corner="")
        settings = app_config.load_settings(self.path)
        own = settings["machine_id"]
        settings["peers"][0]["side"] = "left"
        settings["peers"][1]["side"] = "" if stacked else "right"
        settings["layout"] = {own: {"x": -500, "y": 149, "w": 160, "h": 100, "name": "Desk PC"},
                              mac: {"x": -500 if stacked else -660,
                                    "y": 249 if stacked else 149, "w": 160, "h": 100, "name": "Studio Mac"}}
        settings["layout_by"] = own
        app_config.write_settings(self.path, settings)
        self._open_window()
        self.window.resize(1100, 760)
        parity.settle(self.window)
        return own, mac, acg

    def test_the_rig_arrangement_draws_as_saved(self):
        own, mac, acg = self._rig()
        canvas = self.window.atlas_canvas
        rects = {key: canvas.tile_rect(key) for key in (mac, own, acg)}
        self.assertEqual(set(canvas.tiles), {mac, own, acg})
        self.assertLess(rects[mac].right(), rects[own].left() + 1)
        self.assertLess(rects[own].right(), rects[acg].left() + 1,
                        f"tiles={ {key: (rect.x(), rect.y(), rect.width(), rect.height()) for key, rect in rects.items()} }")
        self.assertEqual(len({round(rect.y()) for rect in rects.values()}), 1)
        for key, rect in rects.items():
            for other in rects:
                if other != key:
                    self.assertFalse(rect.intersects(rects[other]))
        left = min(rect.left() for rect in rects.values())
        right = max(rect.right() for rect in rects.values())
        top = min(rect.top() for rect in rects.values())
        bottom = max(rect.bottom() for rect in rects.values())
        self.assertAlmostEqual((left+right)/2, canvas.width()/2, delta=1)
        self.assertAlmostEqual((top+bottom)/2, canvas.height()/2, delta=1)
        self.assertGreaterEqual(canvas._scale, 0.75)
        saved = app_config.load_settings(self.path)
        self.assertEqual(saved["layout"][acg]["x"], -340)
        self.assertEqual(next(peer["side"] for peer in saved["peers"] if peer["id"] == acg), "right")

    def test_stacked_rig_arrangement_does_not_overlap(self):
        own, mac, acg = self._rig(stacked=True)
        canvas = self.window.atlas_canvas
        rects = [canvas.tile_rect(peer) for peer in (own, mac, acg)]
        for index, rect in enumerate(rects):
            for other in rects[index+1:]:
                self.assertFalse(rect.intersects(other))


if __name__ == "__main__":
    unittest.main()
