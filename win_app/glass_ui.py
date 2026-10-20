"""
Crossfy - Liquid Glass Design Studio
Hardware-accelerated translucent glassmorphic studio interface.
Zero outer margin, true translucent frosted glass (Windows 11 Acrylic),
modular architecture, and authentic live animated preview tiles.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

# Setup paths
ROOT_DIR = Path(__file__).resolve().parent.parent
WIN_APP_DIR = Path(__file__).resolve().parent

if str(WIN_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WIN_APP_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(1, str(ROOT_DIR))

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import app_config
from core import effects
from core.i18n import tr
import desktop_win
from edge_glow import EdgeGlow, PreviewLoop
from effect_overlay import EffectOverlay, logical_point
from effect_previews import EffectStill, SwitchStill, TileHover
import pages_win
import theme
import tokens
from ui.glass import GlassButton, GlassPanel, GlassPill, apply_windows_acrylic
from ui.liquid import LiquidSegmentedControl, LiquidSlider, LiquidToggle
from ui.radial import RadialPalettePicker
import widgets


def make_scroll_transparent(scroll: QScrollArea) -> None:
    """Ensures QScrollArea and its internal viewport are fully translucent."""
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("background: transparent; border: none;")
    vp = scroll.viewport()
    vp.setAutoFillBackground(False)
    vp.setStyleSheet("background: transparent; border: none;")
    vp.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


GLASS_STUDIO_STYLESHEET = """
QWidget {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Hanken Grotesk", sans-serif;
    color: #ffffff;
}

/* Translucent Main Glass Container */
QFrame#glassMainRoot {
    background: rgba(10, 16, 26, 0.30);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 18px;
}

/* Transparent background for all scroll containers, viewports and modules */
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget, QScrollArea QWidget#qt_scrollarea_viewport {
    background: transparent;
    border: none;
}
QFrame[vernier="module"], QWidget[vernier="sidebar"], QWidget[vernier="plain"], QWidget[vernier="rack"], QStackedWidget {
    background: transparent;
    border: none;
}

/* Custom Minimalist Glass Scrollbar */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 8px 3px 8px 0px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.22);
    min-height: 40px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0, 240, 255, 0.55);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    border: none;
    height: 0px;
}

/* Translucent Frosted Glass Preview Tiles */
QPushButton[vernier="tile"], QPushButton[vernier="tile-on"] {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 14px;
    padding: 2px;
}
QPushButton[vernier="tile"]:hover {
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.28);
}
QPushButton[vernier="tile-on"] {
    background: rgba(0, 240, 255, 0.10);
    border: 2px solid #00f0ff;
    border-radius: 14px;
}
QLabel[vernier="tile-name"] {
    color: #ffffff;
    font-size: 13px;
    font-weight: 700;
}
QLabel[vernier="eyebrow"] {
    color: rgba(0, 240, 255, 0.85);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
}
QLabel[vernier="preview-hint"] {
    color: rgba(255, 255, 255, 0.45);
    font-size: 11px;
}
"""


class GlassHeader(QFrame):
    """Draggable header bar. Window only moves when clicking and dragging the header."""

    def __init__(self, window: QWidget, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.window = window
        self._drag_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            if not self.window.isMaximized():
                self.window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()
        event.accept()


class GlassWindow(QWidget):
    """Liquid Glass Design Studio - Main Application Window"""

    def __init__(self, config_path: Optional[Path] = None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.config_path = config_path or app_config.default_config_path()
        try:
            self.config = app_config.load_config(self.config_path, unpairedok=True) if hasattr(app_config, "unpairedok") else app_config.load_config(self.config_path, unpaired_ok=True)
        except Exception:
            self.config = app_config.default_config()

        self._drag_pos = QPoint()
        self.effects: Optional[EffectOverlay] = None
        self.glow: Optional[EdgeGlow] = None
        # Load monitors
        try:
            self.monitors = desktop_win.monitors()
        except Exception:
            self.monitors = []

        # Interactive preview engine
        self.preview_loop = PreviewLoop(self)
        self.tile_hover = TileHover(self.preview_loop, self)
        self.effect_stills = {}
        self.switch_stills = {}

        self._init_ui()
        self._init_effects()
        self._init_tracker()

        # Hardware Acrylic Blur on Windows 11
        apply_windows_acrylic(int(self.winId()))

        # Start live preview loop
        self.preview_loop.run(True)

    def _init_ui(self):
        self.setWindowTitle("Crossfy Transition Studio")
        self.resize(1080, 790)

        # Center on primary monitor
        if self.monitors:
            primary = next((m for m in self.monitors if m.x == 0 and m.y == 0), self.monitors[0])
            self.move(primary.x + (primary.width - 1080) // 2, primary.y + (primary.height - 790) // 2)

        # Root layout with 0 margins: NO outer layer or border frame!
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Glass Root Container
        self.glass_box = QFrame(self)
        self.glass_box.setObjectName("glassMainRoot")

        box_layout = QVBoxLayout(self.glass_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(0)

        # 1. Custom Glass Header
        header = self._build_header()
        box_layout.addWidget(header)

        # 2. Main Content (Sidebar + Pages)
        content_row = QHBoxLayout()
        content_row.setContentsMargins(22, 14, 22, 22)
        content_row.setSpacing(22)

        # Glass Sidebar
        self.sidebar = self._build_sidebar()
        content_row.addWidget(self.sidebar)

        # Pages Stack
        self.pages = QStackedWidget()
        self.page_styles = self._build_styles_page()
        self.page_colours = self._build_colours_page()
        self.page_tuning = self._build_tuning_page()
        self.page_monitors = self._build_monitors_page()

        self.pages.addWidget(self.page_styles)
        self.pages.addWidget(self.page_colours)
        self.pages.addWidget(self.page_tuning)
        self.pages.addWidget(self.page_monitors)

        content_row.addWidget(self.pages, 1)
        box_layout.addLayout(content_row)

        root_layout.addWidget(self.glass_box)


    def _build_header(self) -> QWidget:
        header = GlassHeader(self)
        header.setFixedHeight(70)
        header.setStyleSheet("background: transparent; border-bottom: 1px solid rgba(255, 255, 255, 0.08);")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(26, 0, 22, 0)

        # Brand / Title
        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(10)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet("background: #00f0ff; border-radius: 5px;")
        brand_layout.addWidget(dot)

        title = QLabel("CROSSFY")
        title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: 800; letter-spacing: 2.2px;")
        brand_layout.addWidget(title)

        subtitle = QLabel("TRANSITION STUDIO")
        subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.45); font-size: 11px; font-weight: 600; letter-spacing: 1.5px;")
        brand_layout.addWidget(subtitle)

        hl.addLayout(brand_layout)
        hl.addStretch()

        # Monitor Status Pill (Autoscaled from ui.glass)
        self.mon_pill = GlassPill(f"{len(self.monitors)} Ekran Aktif  ·  Çoklu Monitör Modu")
        hl.addWidget(self.mon_pill)

        hl.addSpacing(16)

        # Glass Button (from ui.glass)
        self.btn_test = GlassButton("Canlı Efekti Test Et", height=36, radius=18.0, primary=True)
        self.btn_test.setFixedWidth(175)
        self.btn_test.clicked.connect(self.play_test_animation)
        hl.addWidget(self.btn_test)

        hl.addSpacing(16)

        # Window Controls (Min, Close)
        btn_min = GlassButton("—", height=32, radius=10.0, primary=False)
        btn_min.setFixedSize(32, 32)
        btn_min.clicked.connect(self.showMinimized)
        hl.addWidget(btn_min)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(32, 32)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.05);
                color: rgba(255, 255, 255, 0.85);
                border-radius: 10px;
                font-size: 11px;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-top: 1px solid rgba(255, 255, 255, 0.22);
            }
            QPushButton:hover {
                background: rgba(255, 50, 75, 0.85);
                border: 1px solid rgba(255, 70, 95, 0.90);
                color: white;
            }
        """)
        btn_close.clicked.connect(self.close)
        hl.addWidget(btn_close)

        return header

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setFixedWidth(205)
        sidebar.setStyleSheet("background: transparent;")

        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 10, 0, 0)
        sl.setSpacing(10)

        self.nav_buttons = []
        nav_items = [
            ("Geçiş Stilleri", 0),
            ("Renk Paletleri", 1),
            ("İnce Ayarlar", 2),
            ("Monitör Haritası", 3),
        ]

        for text, page_idx in nav_items:
            btn = QPushButton(text)
            btn.setFixedHeight(46)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._nav_style(page_idx == 0))
            btn.clicked.connect(lambda _, idx=page_idx: self._switch_nav(idx))
            sl.addWidget(btn)
            self.nav_buttons.append(btn)

        sl.addStretch()

        # Engine Status Card (from ui.glass)
        engine_card = GlassPanel(radius=14.0)
        el = QVBoxLayout(engine_card)
        el.setContentsMargins(14, 12, 14, 12)
        el.setSpacing(4)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        active_dot = QLabel("●")
        active_dot.setStyleSheet("color: #00f0ff; font-size: 8px;")
        status_row.addWidget(active_dot)

        active_title = QLabel("Geçiş Motoru")
        active_title.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 700;")
        status_row.addWidget(active_title)
        status_row.addStretch()

        badge_fps = QLabel("60 FPS")
        badge_fps.setStyleSheet("color: #00f0ff; font-size: 10px; font-weight: 700; background: rgba(0, 240, 255, 0.12); padding: 2px 6px; border-radius: 4px;")
        status_row.addWidget(badge_fps)
        el.addLayout(status_row)

        sub_desc = QLabel("Ekran sınırlarında anlık geçiş")
        sub_desc.setStyleSheet("color: rgba(255, 255, 255, 0.45); font-size: 11px;")
        el.addWidget(sub_desc)

        sl.addWidget(engine_card)
        return sidebar

    def _nav_style(self, active: bool) -> str:
        if active:
            return """
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 rgba(0, 240, 255, 0.18), 
                        stop:1 rgba(153, 51, 255, 0.08));
                    color: #00f0ff;
                    font-size: 14px;
                    font-weight: 700;
                    text-align: left;
                    padding-left: 18px;
                    border-radius: 12px;
                    border: 1px solid rgba(0, 240, 255, 0.40);
                    border-left: 4px solid #00f0ff;
                }
            """
        return """
            QPushButton {
                background: transparent;
                color: rgba(255, 255, 255, 0.65);
                font-size: 14px;
                font-weight: 500;
                text-align: left;
                padding-left: 18px;
                border-radius: 12px;
                border: 1px solid transparent;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.05);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.10);
            }
        """

    def _switch_nav(self, target_idx: int):
        self.pages.setCurrentIndex(target_idx)
        for i, btn in enumerate(self.nav_buttons):
            btn.setStyleSheet(self._nav_style(i == target_idx))

    # --- Page 1: Styles with Authentic Preview Tiles & Liquid Controls ---
    def _build_styles_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        make_scroll_transparent(scroll)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(10, 10, 16, 10)
        cl.setSpacing(18)

        # Title
        top_box = QVBoxLayout()
        top_box.setSpacing(4)
        h_lbl = QLabel("Ekran Geçiş Stilleri")
        h_lbl.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800;")
        top_box.addWidget(h_lbl)

        sub_lbl = QLabel("Kutuların üzerine fareyle gelerek canlı animasyonları izleyebilirsiniz. Seçtiğiniz stil ekran sınırlarında aktif olur.")
        sub_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.55); font-size: 13px;")
        top_box.addWidget(sub_lbl)
        cl.addLayout(top_box)

        # Liquid Controls Glass Card (from ui.glass & ui.liquid)
        opts_box = GlassPanel(radius=16.0)
        ol = QHBoxLayout(opts_box)
        ol.setContentsMargins(18, 12, 18, 12)
        ol.setSpacing(14)

        lbl1 = QLabel("Önizleme Yeri:")
        lbl1.setStyleSheet("color: rgba(255, 255, 255, 0.85); font-size: 13px; font-weight: 600;")
        ol.addWidget(lbl1)

        self.choice_place = LiquidSegmentedControl(
            [("edge", "Kenar (Edge)"), ("corner", "Köşe (Corner)")],
            current="edge",
            on_change=self._on_place_changed,
        )
        ol.addWidget(self.choice_place)

        ol.addSpacing(20)

        lbl2 = QLabel("Stil Türü:")
        lbl2.setStyleSheet("color: rgba(255, 255, 255, 0.85); font-size: 13px; font-weight: 600;")
        ol.addWidget(lbl2)

        self.choice_mode = LiquidSegmentedControl(
            [("crossing", "Geçiş (Crossing)"), ("switch", "Kısayol & İniş")],
            current="crossing",
            on_change=self._on_mode_changed,
        )
        ol.addWidget(self.choice_mode)

        ol.addStretch()
        cl.addWidget(opts_box)

        # Authentic EffectStill Preview Tiles
        colours = app_config.palette_colours(self.config.glow_colour)
        self.effect_stills = {}
        groups = []
        for title, items in pages_win.style_groups():
            tiles = [
                (style, tr(name), tr(detail), self.effect_stills.setdefault(style, EffectStill(style, colours)))
                for style, name, detail in items
            ]
            groups.append((tr(title), tiles))

        self.glow_style_choice = widgets.TileGroups(groups, self.config.glow_style, on_change=self._on_style_selected)
        cl.addWidget(self.glow_style_choice.view)

        # Switch arrival tiles
        self.switch_stills = {}
        switch_groups = []
        for title, items in pages_win.switch_groups():
            tiles = [
                (choice, tr(name), tr(detail), self.switch_stills.setdefault(choice, SwitchStill(choice, self.config.glow_style, colours)))
                for choice, name, detail in items
            ]
            switch_groups.append((tr(title), tiles))

        self.switch_style_choice = widgets.TileGroups(switch_groups, self.config.shortcut_arrival_style, on_change=self._on_switch_selected)
        self.switch_style_choice.view.setVisible(False)
        cl.addWidget(self.switch_style_choice.view)

        # Hover Animation Tracker
        for choices, pictures in ((self.glow_style_choice, self.effect_stills), (self.switch_style_choice, self.switch_stills)):
            for val, pic in pictures.items():
                self.tile_hover.track(choices.tile(val), pic)

        cl.addStretch()
        scroll.setWidget(container)
        return scroll

    def _on_style_selected(self, style_val: str):
        self.config.glow_style = style_val
        self._save_config()
        self._update_effects()
        for still in self.switch_stills.values():
            still.set_crossing_style(style_val)
        self.play_test_animation()

    def _on_switch_selected(self, switch_val: str):
        self.config.shortcut_arrival_style = switch_val
        self._save_config()
        self._update_effects()
        self.play_test_animation()

    def _on_place_changed(self, place_val: str):
        for still in self.effect_stills.values():
            still.set_place(place_val)

    def _on_mode_changed(self, mode_val: str):
        is_crossing = (mode_val == "crossing")
        self.glow_style_choice.view.setVisible(is_crossing)
        self.switch_style_choice.view.setVisible(not is_crossing)

    # --- Page 2: Palettes with Radial Picker & Swatches ---
    def _build_colours_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        make_scroll_transparent(scroll)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(10, 10, 16, 10)
        cl.setSpacing(18)

        # Title
        top_box = QVBoxLayout()
        top_box.setSpacing(4)
        h_lbl = QLabel("Renk Paletleri & Radyal Seçici")
        h_lbl.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800;")
        top_box.addWidget(h_lbl)

        sub_lbl = QLabel("Radyal kadrandan veya renk çubuklarından istediğiniz paleti seçin; tüm animasyonlar anında güncellenir.")
        sub_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.55); font-size: 13px;")
        top_box.addWidget(sub_lbl)
        cl.addLayout(top_box)

        # Radial Menu Dial Card (from ui.radial)
        radial_card = GlassPanel(radius=18.0)
        rcl = QHBoxLayout(radial_card)
        rcl.setContentsMargins(24, 18, 24, 18)
        rcl.setSpacing(26)

        # Radial Dial Component
        self.radial_picker = RadialPalettePicker(
            current=self.config.glow_colour,
            on_select=self._on_colour_selected,
        )
        rcl.addWidget(self.radial_picker)

        # Information Side Box
        info_col = QVBoxLayout()
        info_col.setSpacing(8)

        r_title = QLabel("Radyal Renk Kadranı")
        r_title.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 700;")
        info_col.addWidget(r_title)

        r_desc = QLabel("Çark üzerindeki renk dilimlerine tıklayarak canlı olarak renk temalarını değiştirebilirsiniz.")
        r_desc.setStyleSheet("color: rgba(255, 255, 255, 0.55); font-size: 12px; line-height: 1.4;")
        r_desc.setWordWrap(True)
        info_col.addWidget(r_desc)

        self.lbl_active_palette = QLabel(f"Aktif Palet: {self.config.glow_colour.capitalize()}")
        self.lbl_active_palette.setStyleSheet("color: #00f0ff; font-weight: 700; font-size: 14px; margin-top: 6px;")
        info_col.addWidget(self.lbl_active_palette)

        info_col.addStretch()
        rcl.addLayout(info_col)
        cl.addWidget(radial_card)

        # Authentic SwatchGroups
        swatch_groups_data = [
            (tr(title), [(val, tr(name), app_config.palette_colours(val)) for val, name in items])
            for title, items in pages_win.colour_groups()
        ]
        self.swatch_choice = widgets.SwatchGroups(
            swatch_groups_data,
            self.config.glow_colour,
            on_change=self._on_colour_selected,
        )
        cl.addWidget(self.swatch_choice.view)

        cl.addStretch()
        scroll.setWidget(container)
        return scroll

    def _on_colour_selected(self, colour_val: str):
        self.config.glow_colour = colour_val
        self._save_config()
        self._update_effects()

        # Update all 18 preview tiles
        colours = app_config.palette_colours(colour_val)
        for still in (*self.effect_stills.values(), *self.switch_stills.values()):
            still.set_palette(colours)

        # Update radial picker and title if called from swatch
        if hasattr(self, "radial_picker") and self.radial_picker.current != colour_val:
            self.radial_picker.current = colour_val
            self.radial_picker.update()

        if hasattr(self, "lbl_active_palette"):
            self.lbl_active_palette.setText(f"Aktif Palet: {colour_val.capitalize()}")

        self.play_test_animation()

    # --- Page 3: Tuning with Liquid Toggles & Liquid Controls ---
    def _build_tuning_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        make_scroll_transparent(scroll)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(10, 10, 16, 10)
        cl.setSpacing(18)

        # Title
        top_box = QVBoxLayout()
        top_box.setSpacing(4)
        h_lbl = QLabel("İnce Ayarlar ve Parametreler")
        h_lbl.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800;")
        top_box.addWidget(h_lbl)

        sub_lbl = QLabel("Animasyonun oynatma hızını, ekran kenarı derinliğini ve iniş halkası davranışını özelleştirin.")
        sub_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.55); font-size: 13px;")
        top_box.addWidget(sub_lbl)
        cl.addLayout(top_box)

        # 1. Liquid Toggles Card (from ui.liquid)
        toggles_card = GlassPanel(radius=16.0)
        tl = QVBoxLayout(toggles_card)
        tl.setContentsMargins(22, 16, 22, 16)
        tl.setSpacing(14)

        row1 = QHBoxLayout()
        lbl_t1 = QLabel("Ekranlar arası geçiş animasyonunu etkinleştir")
        lbl_t1.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 600;")
        row1.addWidget(lbl_t1)
        row1.addStretch()
        self.toggle_glow = LiquidToggle(checked=self.config.edge_glow, on_toggle=self._on_toggle_glow)
        row1.addWidget(self.toggle_glow)
        tl.addLayout(row1)

        row2 = QHBoxLayout()
        lbl_t2 = QLabel("İmlecin yeni ekrana indiği noktada iniş animasyonunu göster")
        lbl_t2.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 600;")
        row2.addWidget(lbl_t2)
        row2.addStretch()
        self.toggle_landing = LiquidToggle(checked=self.config.shortcut_arrival, on_toggle=self._on_toggle_landing)
        row2.addWidget(self.toggle_landing)
        tl.addLayout(row2)

        cl.addWidget(toggles_card)

        # 2. Length (Pace) Card with LiquidSegmentedControl
        len_card = GlassPanel(radius=16.0)
        ll = QVBoxLayout(len_card)
        ll.setContentsMargins(22, 16, 22, 16)
        ll.setSpacing(12)

        ll_head = QHBoxLayout()
        ll_title = QLabel("Animasyon Süresi (Playback Length)")
        ll_title.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: 700;")
        ll_head.addWidget(ll_title)
        ll_head.addStretch()
        ll.addLayout(ll_head)

        ll_desc = QLabel("Efektin ekranda kalma ve akış süresi: Seri, Doğal veya Akıcı & Uzun.")
        ll_desc.setStyleSheet("color: rgba(255, 255, 255, 0.5); font-size: 11px;")
        ll.addWidget(ll_desc)

        self.seg_length = LiquidSegmentedControl(
            [("snappy", "Hızlı (Snappy)"), ("normal", "Doğal (Normal)"), ("luxurious", "Akıcı & Uzun (Luxurious)")],
            current=self.config.effect_length,
            on_change=self._set_length,
        )
        ll.addWidget(self.seg_length)
        cl.addWidget(len_card)

        # 3. Size Card with LiquidSegmentedControl
        size_card = GlassPanel(radius=16.0)
        sl = QVBoxLayout(size_card)
        sl.setContentsMargins(22, 16, 22, 16)
        sl.setSpacing(12)

        sl_head = QHBoxLayout()
        sl_title = QLabel("Efekt Boyutu & Derinliği (Size)")
        sl_title.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: 700;")
        sl_head.addWidget(sl_title)
        sl_head.addStretch()
        sl.addLayout(sl_head)

        sl_desc = QLabel("Ekran kenarından içeriye doğru uzanan ışığın ve iniş halkasının çapı.")
        sl_desc.setStyleSheet("color: rgba(255, 255, 255, 0.5); font-size: 11px;")
        sl.addWidget(sl_desc)

        self.seg_size = LiquidSegmentedControl(
            [("fine", "İnce (Fine)"), ("medium", "Orta (Medium)"), ("broad", "Geniş (Broad)")],
            current=self.config.effect_size,
            on_change=self._set_size,
        )
        sl.addWidget(self.seg_size)
        cl.addWidget(size_card)

        # 4. Frame Rate Card with LiquidSegmentedControl
        fps_card = GlassPanel(radius=16.0)
        fl = QVBoxLayout(fps_card)
        fl.setContentsMargins(22, 16, 22, 16)
        fl.setSpacing(12)

        fl_title = QLabel("Yenileme Hızı (Frame Rate)")
        fl_title.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: 700;")
        fl.addWidget(fl_title)

        fps_items = [(v, tr(n)) for v, n, _ in effects.FRAME_RATES]
        self.choice_fps = LiquidSegmentedControl(
            fps_items,
            current=self.config.frame_rate,
            on_change=self._on_fps_changed,
        )
        fl.addWidget(self.choice_fps)
        cl.addWidget(fps_card)

        cl.addStretch()
        scroll.setWidget(container)
        return scroll

    def _on_toggle_glow(self, checked: bool):
        self.config.edge_glow = checked
        self._save_config()
        self._update_effects()

    def _on_toggle_landing(self, checked: bool):
        self.config.shortcut_arrival = checked
        self._save_config()
        self._update_effects()

    def _set_length(self, length_val: str):
        self.config.effect_length = length_val
        pace = effects.pace(length_val)
        self.config.effect_pace = pace
        self._save_config()
        self._update_effects()
        for still in (*self.effect_stills.values(), *self.switch_stills.values()):
            still.set_pace(pace)
        self.play_test_animation()

    def _set_size(self, size_val: str):
        self.config.effect_size = size_val
        fraction = effects.size_fraction(size_val)
        self.config.effect_size_fraction = fraction
        self._save_config()
        self._update_effects()
        for still in (*self.effect_stills.values(), *self.switch_stills.values()):
            still.set_effect_size(size_val, fraction)
        self.play_test_animation()

    def _on_fps_changed(self, fps_val: str):
        self.config.frame_rate = fps_val
        self._save_config()

    # --- Page 4: Interactive Panoramic Monitors Rig ---
    def _build_monitors_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        make_scroll_transparent(scroll)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(10, 10, 16, 10)
        cl.setSpacing(18)

        # Title
        top_box = QVBoxLayout()
        top_box.setSpacing(4)
        h_lbl = QLabel("Panoramik Monitör Yerleşimi")
        h_lbl.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800;")
        top_box.addWidget(h_lbl)

        sub_lbl = QLabel("Masanızdaki fiziksel ekran düzeni. Fareyi monitörleriniz arasında gezdirdikçe sınır geçiş animasyonları canlı oynatılır.")
        sub_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.55); font-size: 13px;")
        top_box.addWidget(sub_lbl)
        cl.addLayout(top_box)

        # 1. Panoramic Multi-Display Desk Rig (Horizontal Visual Layout)
        rig_panel = GlassPanel(radius=18.0)
        r_layout = QVBoxLayout(rig_panel)
        r_layout.setContentsMargins(22, 20, 22, 20)
        r_layout.setSpacing(16)

        rig_title_row = QHBoxLayout()
        rig_title_lbl = QLabel("Fiziksel Ekran Düzeni & Canlı İmleç Radarı")
        rig_title_lbl.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 700;")
        rig_title_row.addWidget(rig_title_lbl)
        rig_title_row.addStretch()

        live_tag = QLabel("● CANLI TAKİP")
        live_tag.setStyleSheet("color: #00f0ff; font-size: 10px; font-weight: 800; background: rgba(0, 240, 255, 0.12); padding: 3px 8px; border-radius: 6px;")
        rig_title_row.addWidget(live_tag)
        r_layout.addLayout(rig_title_row)

        # Sort monitors from left to right by their physical X coordinate
        sorted_monitors = sorted(self.monitors, key=lambda m: m.x)
        self.monitor_cards = []

        monitors_row = QHBoxLayout()
        monitors_row.setSpacing(10)

        for i, m in enumerate(sorted_monitors):
            # Monitor Display Glass Card
            m_card = QFrame()
            m_card.setFixedHeight(140)
            m_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            is_primary = (m.x == 0)
            pos_label = "Sol Ekran" if m.x < 0 else ("Orta Ekran (Birincil)" if is_primary else "Sağ Ekran")

            m_card.setStyleSheet("""
                QFrame {
                    background: rgba(14, 20, 32, 0.35);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 14px;
                }
                QLabel {
                    border: none;
                    background: transparent;
                }
            """)

            m_layout = QVBoxLayout(m_card)
            m_layout.setContentsMargins(14, 14, 14, 14)
            m_layout.setSpacing(6)

            # Bezel Top Header
            b_head = QHBoxLayout()
            b_num = QLabel(f"M{i+1}")
            b_num.setStyleSheet("color: #00f0ff; font-weight: 800; font-size: 12px; background: rgba(0, 240, 255, 0.12); padding: 2px 6px; border-radius: 4px;")
            b_head.addWidget(b_num)

            b_name = QLabel(pos_label)
            b_name.setStyleSheet("color: #ffffff; font-weight: 700; font-size: 13px;")
            b_head.addWidget(b_name)
            b_head.addStretch()
            m_layout.addLayout(b_head)

            m_layout.addStretch()

            # Center Radar Indicator
            radar_lbl = QLabel("● Hazır")
            radar_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.45); font-size: 12px; font-weight: 600;")
            radar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            m_layout.addWidget(radar_lbl)

            m_layout.addStretch()

            # Bottom Specs
            b_specs = QLabel(f"{m.width}x{m.height}  ·  X: {m.x}")
            b_specs.setStyleSheet("color: rgba(255, 255, 255, 0.40); font-size: 11px;")
            b_specs.setAlignment(Qt.AlignmentFlag.AlignCenter)
            m_layout.addWidget(b_specs)

            self.monitor_cards.append((m, m_card, radar_lbl))
            monitors_row.addWidget(m_card, 1)

            # Add Seam Transition Bridge between displays
            if i < len(sorted_monitors) - 1:
                seam_box = QFrame()
                seam_box.setFixedWidth(36)
                seam_box.setFixedHeight(140)
                seam_box.setStyleSheet("background: transparent; border: none;")
                sl = QVBoxLayout(seam_box)
                sl.setContentsMargins(0, 0, 0, 0)
                sl.addStretch()

                arrow_lbl = QLabel("◄ ►")
                arrow_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow_lbl.setStyleSheet("color: rgba(0, 240, 255, 0.70); font-weight: 800; font-size: 11px; background: rgba(0, 240, 255, 0.08); padding: 6px 2px; border-radius: 6px; border: 1px dashed rgba(0, 240, 255, 0.35);")
                sl.addWidget(arrow_lbl)
                sl.addStretch()
                monitors_row.addWidget(seam_box)

        r_layout.addLayout(monitors_row)
        cl.addWidget(rig_panel)

        # 2. Panoramic Specs Metrics (3 Glass Cards below)
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(14)

        total_width = sum(m.width for m in self.monitors) if self.monitors else 5760
        max_height = max((m.height for m in self.monitors), default=1080)

        for m_title, m_val, m_desc in [
            ("Panoramik Tuval", f"{total_width} x {max_height} px", f"{len(self.monitors)} Ekran Birleşik Çalışma Alanı"),
            ("Aktif Sınır Hatları", f"{max(0, len(self.monitors) - 1)} Geçiş Hattı", "Sol ↔ Orta ↔ Sağ Canlı Geçiş"),
            ("Donanım Performansı", "60 FPS · < 1 ms", "Piksel Düzeyinde GPU İvmesi"),
        ]:
            m_card = GlassPanel(radius=14.0)
            m_card.setFixedHeight(84)
            ml = QVBoxLayout(m_card)
            ml.setContentsMargins(16, 12, 16, 12)
            ml.setSpacing(3)

            t_lbl = QLabel(m_title)
            t_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.50); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;")
            ml.addWidget(t_lbl)

            v_lbl = QLabel(m_val)
            v_lbl.setStyleSheet("color: #00f0ff; font-size: 16px; font-weight: 800;")
            ml.addWidget(v_lbl)

            d_lbl = QLabel(m_desc)
            d_lbl.setStyleSheet("color: rgba(255, 255, 255, 0.40); font-size: 10px;")
            ml.addWidget(d_lbl)

            metrics_row.addWidget(m_card, 1)

        cl.addLayout(metrics_row)
        cl.addStretch()
        scroll.setWidget(container)
        return scroll

    # --- Real-Time Crossing Engine ---
    def _init_effects(self):
        try:
            self.effects = EffectOverlay()
            self.glow = EdgeGlow()
            self._update_effects()
        except Exception as e:
            print("Effects init error:", e)

    def _update_effects(self):
        cfg = self.config
        if self.effects is not None:
            self.effects.configure(
                cfg.glow_style,
                cfg.glow_colour,
                cfg.effect_length,
                cfg.effect_size,
                cfg.effect_pace,
                cfg.effect_size_fraction,
            )
        if self.glow is not None:
            self.glow.configure(
                cfg.glow_style,
                cfg.glow_colour,
                cfg.effect_length,
                cfg.effect_size,
                cfg.effect_pace,
                cfg.effect_size_fraction,
            )
    def _init_tracker(self):
        if len(self.monitors) < 2:
            return
        self._last_cursor_monitor = None
        self._tracker_timer = QTimer(self)
        self._tracker_timer.setInterval(16)  # ~60 FPS
        self._tracker_timer.timeout.connect(self._track_cursor)
        self._tracker_timer.start()

    def _track_cursor(self):
        if not self.config.edge_glow or self.effects is None:
            return
        try:
            x, y = desktop_win.cursor_position()
        except Exception:
            return

        curr_idx = None
        for i, m in enumerate(self.monitors):
            if m.x <= x < m.x + m.width and m.y <= y < m.y + m.height:
                curr_idx = i
                break
        if curr_idx is None:
            for i, m in enumerate(self.monitors):
                if m.x <= x <= m.x + m.width and m.y <= y <= m.y + m.height:
                    curr_idx = i
                    break

        if curr_idx is not None:
            if hasattr(self, "monitor_cards") and self.monitor_cards:
                for m, card, radar in self.monitor_cards:
                    is_here = (m == self.monitors[curr_idx])
                    if is_here:
                        card.setStyleSheet("""
                            QFrame {
                                background: rgba(0, 240, 255, 0.10);
                                border: 2px solid #00f0ff;
                                border-radius: 14px;
                            }
                            QLabel { border: none; background: transparent; }
                        """)
                        radar.setText("● İMLEÇ BU EKRANDA")
                        radar.setStyleSheet("color: #00f0ff; font-size: 11px; font-weight: 800;")
                    else:
                        card.setStyleSheet("""
                            QFrame {
                                background: rgba(14, 20, 32, 0.35);
                                border: 1px solid rgba(255, 255, 255, 0.10);
                                border-radius: 14px;
                            }
                            QLabel { border: none; background: transparent; }
                        """)
                        radar.setText("● Hazır")
                        radar.setStyleSheet("color: rgba(255, 255, 255, 0.45); font-size: 11px; font-weight: 600;")

            if self._last_cursor_monitor is not None and curr_idx != self._last_cursor_monitor:
                last_m = self.monitors[self._last_cursor_monitor]
                curr_m = self.monitors[curr_idx]

                if curr_m.x > last_m.x:
                    edge = "left"
                elif curr_m.x < last_m.x:
                    edge = "right"
                elif curr_m.y > last_m.y:
                    edge = "top"
                else:
                    edge = "bottom"
                lp = logical_point(x, y)
                if self.effects is not None:
                    self.effects.push(edge, 1.0, True, lp)
                    if self.config.glow_style not in ("glow", "beam"):
                        self.effects.arrive("edge", edge, lp)

            self._last_cursor_monitor = curr_idx

    def play_test_animation(self):
        try:
            x, y = desktop_win.cursor_position()
        except Exception:
            x, y = 500, 500

        self._update_effects()
        if self.effects is not None:
            lp = logical_point(x, y)
            self.effects.push("left", 1.0, True, lp)
            if self.config.glow_style not in ("glow", "beam"):
                self.effects.arrive("edge", "left", lp)
    def _save_config(self):
        try:
            app_config.save_config(self.config_path, self.config)
        except Exception as e:
            print("Config save error:", e)

def main():
    app = QApplication(sys.argv)
    theme.set_dark(True)
    theme.init_fonts()
    app.setFont(theme.font(theme.TYPE["body"]))
    app.setStyleSheet(GLASS_STUDIO_STYLESHEET)
    window = GlassWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
