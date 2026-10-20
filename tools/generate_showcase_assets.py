"""
Generate high-resolution showcase assets for Crossfy README documentation.
"""
import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
WIN_APP_DIR = ROOT_DIR / "win_app"

sys.path.insert(0, str(WIN_APP_DIR))
sys.path.insert(1, str(ROOT_DIR))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt, QSize
import glass_ui

app = QApplication.instance() or QApplication(sys.argv)
theme = glass_ui.theme
theme.set_dark(True)
theme.init_fonts()
app.setFont(theme.font(theme.TYPE["body"]))
app.setStyleSheet(glass_ui.GLASS_STUDIO_STYLESHEET)

out_dir = ROOT_DIR / "docs" / "assets"
out_dir.mkdir(parents=True, exist_ok=True)

win = glass_ui.GlassWindow()
win.resize(1080, 780)
win.show()

# Force layout and paint
app.processEvents()

# 1. Hero Studio (Styles Page)
win.pages.setCurrentIndex(0)
app.processEvents()
img_hero = win.grab()
img_hero.save(str(out_dir / "1-hero-studio.png"))
print("Saved 1-hero-studio.png")

# 2. Radial Palette Picker Page
win.pages.setCurrentIndex(1)
app.processEvents()
img_palettes = win.grab()
img_palettes.save(str(out_dir / "3-radial-palette-picker.png"))
print("Saved 3-radial-palette-picker.png")

# 3. Tuning Page
win.pages.setCurrentIndex(2)
app.processEvents()
img_tuning = win.grab()
img_tuning.save(str(out_dir / "2-glow-beam-effects.png"))
print("Saved 2-glow-beam-effects.png")

# 4. Panoramic Monitors Rig Page
win.pages.setCurrentIndex(3)
app.processEvents()
img_monitors = win.grab()
img_monitors.save(str(out_dir / "4-panoramic-monitor-rig.png"))
print("Saved 4-panoramic-monitor-rig.png")

print("All showcase assets generated successfully!")
