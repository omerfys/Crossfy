"""Run one Qt test module with a deterministic PC display cache."""

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("display_map", choices=("empty", "windows"))
    parser.add_argument("module", help="Discovery pattern, e.g. test_pages_win.py")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    app_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(app_dir))
    sys.path.insert(1, str(app_dir / "tests"))
    temp_dir = app_dir / ".test-tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(temp_dir)

    import kvm_bridge_win
    import display_map_fixture
    from core import return_edge

    def refresh(window):
        window._own_display_map = (
            {"0": return_edge.Rect(0, 0, 1920, 1080)}
            if args.display_map == "windows" else {}
        )

    with patch.object(kvm_bridge_win.WindowsApplication, "_refresh_own_displays", refresh):
        suite = unittest.defaultTestLoader.discover(str(app_dir / "tests"), pattern=args.module)
        result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
