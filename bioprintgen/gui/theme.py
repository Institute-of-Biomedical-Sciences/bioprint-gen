"""Compact flat themes (dark + light) with a single accent.

Colour names are module-level so widgets can use `theme.BG` etc. directly.
`set_theme()` rebinds them, so after switching, any view that re-creates its
items picks up the new palette.
"""
from __future__ import annotations

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

DARK = dict(
    ACCENT="#4c9aff", ACCENT_DIM="#3b7fd6",
    BG="#1b1e24", BG_ELEV="#232730", BG_INPUT="#2b303b", BORDER="#343a46",
    TEXT="#e6e9ef", TEXT_DIM="#9aa3b2",
    TEXT_OFF="#5a626f", BG_OFF="#212530", BORDER_OFF="#2b303a",
    TRAVEL="#4a5060", EXTRUDE="#4c9aff", PERIM="#ffb454", SELECT="#ff5f8f",
    GRID="#262b34",
    TOOL_EXTRUDE={1: "#4c9aff", 2: "#4ecb8d", 3: "#c78bff"},
    TOOL_PERIM={1: "#ffb454", 2: "#2f9e6b", 3: "#9a5fd0"},
)

LIGHT = dict(
    ACCENT="#2563eb", ACCENT_DIM="#1d4ed8",
    BG="#f4f5f7", BG_ELEV="#ffffff", BG_INPUT="#ffffff", BORDER="#cfd4dc",
    TEXT="#1b1e24", TEXT_DIM="#5b6472",
    TEXT_OFF="#a9b0ba", BG_OFF="#f0f1f4", BORDER_OFF="#e2e5ea",
    TRAVEL="#aab2be", EXTRUDE="#2563eb", PERIM="#d97706", SELECT="#e11d48",
    GRID="#e6e8ec",
    TOOL_EXTRUDE={1: "#2563eb", 2: "#15803d", 3: "#7c3aed"},
    TOOL_PERIM={1: "#d97706", 2: "#0f766e", 3: "#a21caf"},
)

THEMES = {"dark": DARK, "light": LIGHT}
_current = "dark"

# -- bound by set_theme() (defaults so imports work before apply_theme) --
ACCENT = ACCENT_DIM = BG = BG_ELEV = BG_INPUT = BORDER = ""
TEXT = TEXT_DIM = TRAVEL = EXTRUDE = PERIM = SELECT = GRID = ""
TEXT_OFF = BG_OFF = BORDER_OFF = ""
TOOL_EXTRUDE: dict = {}
TOOL_PERIM: dict = {}


def set_theme(name: str) -> None:
    """Rebind the module-level colour names to the chosen palette."""
    global _current
    pal = THEMES.get(name, DARK)
    _current = name if name in THEMES else "dark"
    globals().update(pal)


def current_theme() -> str:
    return _current


set_theme("dark")


def tool_extrude_color(extruder: int) -> str:
    return TOOL_EXTRUDE.get(extruder, EXTRUDE)


def tool_perim_color(extruder: int) -> str:
    return TOOL_PERIM.get(extruder, PERIM)


def build_qss() -> str:
    return f"""
* {{ font-family: "Segoe UI", "Inter", "SF Pro Text", Arial; font-size: 12px; color: {TEXT}; }}
QMainWindow, QWidget {{ background: {BG}; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {BG_ELEV}; padding: 6px 10px; border: none;
    text-transform: uppercase; letter-spacing: 1px; color: {TEXT_DIM}; }}
QToolBar {{ background: {BG_ELEV}; border: none; padding: 4px; spacing: 4px; }}
QToolBar QToolButton, QPushButton {{ background: {BG_INPUT}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 6px 12px; }}
QToolBar QToolButton:hover, QPushButton:hover {{ border-color: {ACCENT}; }}
QToolBar QToolButton:pressed, QPushButton:pressed {{ background: {ACCENT_DIM}; color: white; }}
QToolBar QToolButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_DIM}; }}
QPushButton#section {{ background: {BG_ELEV}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 10px; text-align: left; font-weight: 600; color: {TEXT_DIM};
    text-transform: uppercase; letter-spacing: 1px; font-size: 10px; }}
QPushButton#section:hover {{ border-color: {ACCENT}; color: {TEXT}; }}
QPushButton#section:checked {{ color: {TEXT}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding-top: 8px;
    background: {BG_ELEV}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px;
    color: {TEXT_DIM}; text-transform: uppercase; letter-spacing: 1px; font-size: 10px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {BG_INPUT};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px; min-height: 18px; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {BG_INPUT}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {BORDER}; background: {BG_INPUT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QLabel#hint {{ color: {TEXT_DIM}; font-size: 11px; }}
QLabel#stat {{ color: {TEXT_DIM}; }}
QPlainTextEdit, QTextBrowser {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 6px;
    font-family: "JetBrains Mono", "Consolas", monospace; font-size: 12px;
    selection-background-color: {ACCENT_DIM}; }}
QTextBrowser {{ font-family: "Segoe UI", "Inter", Arial; font-size: 13px; }}
QTableWidget {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 6px;
    gridline-color: {BORDER}; }}
QHeaderView::section {{ background: {BG_ELEV}; color: {TEXT_DIM}; border: none;
    padding: 4px; font-size: 11px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollArea {{ border: none; }}
QStatusBar {{ background: {BG_ELEV}; color: {TEXT_DIM}; }}
QToolTip {{ background: {BG_INPUT}; color: {TEXT}; border: 1px solid {ACCENT}; padding: 4px; }}
QMenu {{ background: {BG_ELEV}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; color: white; }}

/* --- disabled: settings that don't apply to the current selection --- */
QLabel:disabled, QCheckBox:disabled {{ color: {TEXT_OFF}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QPlainTextEdit:disabled, QTableWidget:disabled {{
    background: {BG_OFF}; border-color: {BORDER_OFF}; color: {TEXT_OFF}; }}
QCheckBox::indicator:disabled {{ background: {BG_OFF}; border-color: {BORDER_OFF}; }}
QPushButton:disabled, QToolButton:disabled {{
    background: {BG_OFF}; border-color: {BORDER_OFF}; color: {TEXT_OFF}; }}
QHeaderView::section:disabled {{ color: {TEXT_OFF}; }}
"""


def apply_theme(app: QApplication, name: str = "dark") -> None:
    set_theme(name)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.Base, QColor(BG_INPUT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(BG_INPUT))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    app.setPalette(pal)
    app.setStyleSheet(build_qss())
