"""Centralized visual theme for Jukebox UI.

Defines colors, spacing and font helpers so the application has a coherent,
modern look without spreading magic numbers across widgets.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication


# --- Color palette (dark theme) ---

WINDOW_BG = QColor(18, 18, 20)
PANEL_BG = QColor(28, 28, 32)
TEXT_PRIMARY = QColor(235, 235, 240)


# --- Layout metrics ---

SECTION_SPACING = 10
CONTROL_SPACING = 6


def apply_global_palette(app: QApplication) -> None:
    """Apply a dark palette to the QApplication while keeping it subtle.

    This intentionally keeps changes minimal to avoid fighting with the
    platform style; most detailed styling is still done per-widget.
    """
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, WINDOW_BG)
    palette.setColor(palette.ColorRole.Base, PANEL_BG)
    palette.setColor(palette.ColorRole.AlternateBase, PANEL_BG)
    palette.setColor(palette.ColorRole.Text, TEXT_PRIMARY)
    palette.setColor(palette.ColorRole.WindowText, TEXT_PRIMARY)
    palette.setColor(palette.ColorRole.ButtonText, TEXT_PRIMARY)
    palette.setColor(palette.ColorRole.ToolTipBase, PANEL_BG)
    palette.setColor(palette.ColorRole.ToolTipText, TEXT_PRIMARY)
    app.setPalette(palette)


@dataclass(frozen=True)
class VisualizerColors:
    background: QColor
    left_hand: QColor
    right_hand: QColor
    unknown: QColor
    cursor: QColor
    measure_line: QColor


@dataclass(frozen=True)
class PianoColors:
    white_key: QColor
    white_key_border: QColor
    black_key: QColor
    black_key_highlight: QColor
    active_key: QColor


@dataclass(frozen=True)
class LogColors:
    debug: str
    info: str
    warning: str
    error: str


@dataclass(frozen=True)
class Theme:
    """Central theme definition for the Jukebox UI."""

    # Base surfaces
    background_main: str
    background_panel: str
    background_panel_alt: str
    border_subtle: str

    # Text
    text_primary: str
    text_secondary: str
    text_muted: str

    # Accents
    accent_primary: str
    accent_secondary: str
    accent_success: str
    accent_warning: str
    accent_error: str

    # Domain-specific groups
    visualizer: VisualizerColors
    piano: PianoColors
    logs: LogColors

    # Global QSS snippet to style common widgets.
    qss: str


_theme_cache: Theme | None = None


def get_theme() -> Theme:
    """Return the cached dark-cyber theme instance (lazy-init)."""
    global _theme_cache
    if _theme_cache is None:
        _theme_cache = get_dark_cyber_theme()
    return _theme_cache

def get_dark_cyber_theme() -> Theme:
    """Return a dark, colorful theme: neutral dark base with clean, non-flashy accents."""
    # Base colors as hex strings (for QSS / HTML); pure black with neutral grays.
    background_main = "#121214"
    background_panel = "#1C1C20"
    background_panel_alt = "#222228"
    border_subtle = "#3C3C46"

    text_primary = "#EBEBF0"
    text_secondary = "#AAAAB4"
    text_muted = "#888896"

    # Accent colors: orange primary, teal secondary, standard green/red.
    accent_primary = "#EF6C4D"  # orange
    accent_secondary = "#22C1B5"  # teal
    accent_success = "#5EC96B"  # green
    accent_warning = "#E6A23C"  # amber
    accent_error = "#F56C6C"  # red

    visualizer = VisualizerColors(
        background=QColor(24, 24, 28),
        left_hand=QColor(96, 125, 139, 210),
        right_hand=QColor(240, 192, 64, 210),
        unknown=QColor(150, 150, 150, 160),
        cursor=QColor(255, 255, 255),
        measure_line=QColor(255, 255, 255, 40),
    )

    piano = PianoColors(
        white_key=QColor(200, 200, 210),
        white_key_border=QColor(140, 140, 155),
        black_key=QColor(30, 30, 38),
        black_key_highlight=QColor(80, 80, 100),
        active_key=QColor(160, 160, 170),
    )

    logs = LogColors(
        debug="#8888A0",
        info=text_secondary,
        warning=accent_warning,
        error=accent_error,
    )

    # Global stylesheet for common widgets; conservative so it plays well cross‑platform.
    qss = f"""
        QMainWindow, QDialog {{
            background-color: {background_main};
            color: {text_secondary};
        }}

        QWidget#CentralWidget {{
            background-color: {background_main};
        }}

        QGroupBox {{
            border: 1px solid {border_subtle};
            border-radius: 6px;
            margin-top: 10px;
            background-color: {background_panel};
        }}

        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 6px;
            color: {text_primary};
        }}

        QPushButton {{
            background-color: {background_panel_alt};
            color: {text_primary};
            border-radius: 4px;
            border: 1px solid {border_subtle};
            padding: 4px 10px;
        }}

        QPushButton:hover {{
            background-color: {border_subtle};
            color: {text_primary};
        }}

        QPushButton:pressed {{
            background-color: {accent_primary};
            color: #000000;
        }}

        QPushButton#PrimaryButton {{
            background-color: {accent_primary};
            color: #000000;
        }}

        QPushButton#PrimaryButton:hover {{
            background-color: {accent_secondary};
            color: {text_primary};
        }}

        QTabWidget::pane {{
            border-top: 1px solid {border_subtle};
        }}

        QTabBar::tab {{
            background-color: {background_panel};
            color: {text_muted};
            padding: 6px 14px;
        }}

        QTabBar::tab:selected {{
            background-color: {background_panel_alt};
            color: {text_primary};
            border-bottom: 3px solid {accent_primary};
        }}

        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: {background_panel_alt};
            border-radius: 3px;
            border: 1px solid {border_subtle};
            padding: 2px 6px;
            color: {text_primary};
        }}

        QSlider::groove:horizontal {{
            border: 1px solid {border_subtle};
            height: 6px;
            background: {background_panel_alt};
            border-radius: 3px;
        }}

        QSlider::sub-page:horizontal {{
            background: {accent_primary};
            border-radius: 3px;
        }}

        QSlider::handle:horizontal {{
            background: {accent_primary};
            width: 12px;
            margin: -4px 0;
            border-radius: 6px;
        }}

        QTextBrowser#LogOutput {{
            background-color: {background_panel_alt};
            border: 1px solid {border_subtle};
            color: {text_secondary};
        }}

        QTableView, QTableWidget {{
            gridline-color: {border_subtle};
            background-color: {background_panel};
            alternate-background-color: {background_panel_alt};
            color: {text_secondary};
        }}

        QHeaderView::section {{
            background-color: {background_panel_alt};
            color: {text_primary};
            border: 0px;
            border-bottom: 1px solid {border_subtle};
            padding: 4px 6px;
        }}

        QScrollBar:horizontal, QScrollBar:vertical {{
            background-color: {background_panel};
        }}
    """

    return Theme(
        background_main=background_main,
        background_panel=background_panel,
        background_panel_alt=background_panel_alt,
        border_subtle=border_subtle,
        text_primary=text_primary,
        text_secondary=text_secondary,
        text_muted=text_muted,
        accent_primary=accent_primary,
        accent_secondary=accent_secondary,
        accent_success=accent_success,
        accent_warning=accent_warning,
        accent_error=accent_error,
        visualizer=visualizer,
        piano=piano,
        logs=logs,
        qss=qss,
    )
