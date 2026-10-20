"""
Crossfy - Developer Entry Point
Directly launches the Liquid Glass Design Studio by default.
Use --classic or --kvm to launch the legacy KVM receiver.
"""
import sys
import os
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform == "win32":
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent
WIN_APP_DIR = ROOT_DIR / "win_app"

sys.path.insert(0, str(WIN_APP_DIR))
sys.path.insert(1, str(ROOT_DIR))

os.chdir(str(WIN_APP_DIR))

if __name__ == "__main__":
    if "--classic" in sys.argv or "--kvm" in sys.argv:
        import kvm_bridge_win
        kvm_bridge_win.main()
    else:
        import glass_ui
        glass_ui.main()
