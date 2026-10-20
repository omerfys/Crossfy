"""Pure archive labels, including author names and human dates."""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pages_win


class SavedWaysLabelsTests(unittest.TestCase):
    def test_archive_reasons_and_day_first_date(self):
        stamp = time.mktime((2026, 10, 14, 12, 0, 0, 0, 0, -1))
        for reason, words in (("upgrade", "Before Beamer 1.5.5"),
                              ("older_version", "From an older Beamer"),
                              ("sync_off", "When Same ways went off"),
                              ("seeded", "When Same ways went on"),
                              ("edited", "Before you changed it"),
                              ("restored", "Before a restore")):
            with self.subTest(reason=reason):
                self.assertEqual(pages_win.saved_ways_label({"why": reason, "at": stamp}, {}),
                                 "14-10-2026 · " + words)

    def test_replaced_row_names_the_author(self):
        result = pages_win.saved_ways_label({"why": "replaced_by", "by": "own"},
                                           {"machine_id": "own", "name": "Studio PC"})
        self.assertTrue(result.endswith("Before Studio PC changed it"))


if __name__ == "__main__":
    unittest.main()
