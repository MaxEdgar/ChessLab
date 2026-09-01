"""Visual theme: application-wide dark stylesheet and board color palettes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardPalette:
    light_square: str
    dark_square: str
    selected: str
    last_move: str
    legal_dot: str
    check: str
    arrow: str


BOARD_THEMES: dict[str, BoardPalette] = {
    "midnight": BoardPalette(
        light_square="#3a4250",
        dark_square="#252b35",
        selected="#5b7fb5aa",
        last_move="#d9a44680",
        legal_dot="#e8e8e880",
        check="#c0405080",
        arrow="#e74c3cc0",  # red arrow
    ),
    "walnut": BoardPalette(
        light_square="#e8c99b",
        dark_square="#8f5a34",
        selected="#6fa8dcaa",
        last_move="#f6f66980",
        legal_dot="#20202070",
        check="#e0405090",
        arrow="#e74c3cc0",  # red arrow
    ),
    "graphite": BoardPalette(
        light_square="#bfbfbf",
        dark_square="#5f5f5f",
        selected="#4a90d9aa",
        last_move="#e0c04680",
        legal_dot="#10101070",
        check="#d1394680",
        arrow="#e74c3cc0",  # red arrow
    ),
}

# Base surface colors for the application chrome (independent of board theme).
BG_APP = "#1b1f27"
BG_PANEL = "#20242e"
BG_PANEL_ALT = "#262b36"
BORDER = "#333a48"
TEXT_PRIMARY = "#e7e9ee"
TEXT_SECONDARY = "#9aa3b2"
ACCENT = "#4fa3d9"
ACCENT_DIM = "#3a7aa8"
GOOD = "#5cb85c"
WARN = "#e0a63e"
BAD = "#d9534f"

DARK_QSS = f"""
QWidget {{
    background-color: {BG_APP};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {BG_APP};
}}

QMenuBar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
    padding: 2px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background-color: {BG_PANEL_ALT};
}}
QMenu {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {ACCENT_DIM};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 6px;
}}

QToolBar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
    spacing: 4px;
    padding: 4px;
}}
QToolButton {{
    background: transparent;
    border-radius: 6px;
    padding: 6px;
    color: {TEXT_PRIMARY};
}}
QToolButton:hover {{
    background-color: {BG_PANEL_ALT};
}}
QToolButton:pressed {{
    background-color: {ACCENT_DIM};
}}
QToolButton:checked {{
    background-color: {ACCENT_DIM};
}}

QStatusBar {{
    background-color: {BG_PANEL};
    border-top: 1px solid {BORDER};
    color: {TEXT_SECONDARY};
}}

QDockWidget {{
    titlebar-close-icon: none;
    color: {TEXT_PRIMARY};
}}
QDockWidget::title {{
    background-color: {BG_PANEL};
    padding: 6px 8px;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
}}

QTreeWidget, QListWidget, QTableWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    alternate-background-color: {BG_PANEL_ALT};
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT_PRIMARY};
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background-color: {BG_PANEL_ALT};
    color: {TEXT_SECONDARY};
    padding: 4px;
    border: none;
    border-bottom: 1px solid {BORDER};
}}

QScrollBar:vertical {{
    background: {BG_APP};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT_DIM};
}}
QScrollBar:horizontal {{
    background: {BG_APP};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 20px;
}}

QPushButton {{
    background-color: {BG_PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 12px;
    color: {TEXT_PRIMARY};
}}
QPushButton:hover {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT_DIM};
}}
QPushButton:pressed {{
    background-color: {ACCENT};
}}
QPushButton:disabled {{
    color: {TEXT_SECONDARY};
    background-color: {BG_PANEL};
}}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {BG_PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 6px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_DIM};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
}}

QSlider::groove:horizontal {{
    background: {BORDER};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG_PANEL_ALT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}

QSplitter::handle {{
    background-color: {BORDER};
}}

QToolTip {{
    background-color: {BG_PANEL_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    padding: 4px;
}}
"""
