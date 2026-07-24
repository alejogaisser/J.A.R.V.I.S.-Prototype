"""Design tokens shared by the Mk II application shell and desktop pet."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase


class Palette:
    VOID = "#02070A"
    VOID_DEEP = "#010406"
    SURFACE = "#06141B"
    SURFACE_RAISED = "#0A1D26"
    SURFACE_HOVER = "#0D2631"
    LINE = "#123946"
    LINE_STRONG = "#1E6072"
    CYAN = "#27C8FF"
    CYAN_BRIGHT = "#69E8FF"
    CYAN_SOFT = "#A9F3FF"
    CYAN_MUTED = "#247EAE"
    TEXT = "#DDFBFF"
    TEXT_MEDIUM = "#7EB4BF"
    TEXT_DIM = "#497680"
    SUCCESS = "#63F6D0"
    WARNING = "#FFC66D"
    ERROR = "#FF405C"
    ERROR_SOFT = "#FF9AA9"


class Motion:
    MICRO = 150
    PANEL = 300
    MODE = 520
    CINEMATIC = 900
    FRAME_MS = 16


class Radius:
    SMALL = 8
    MEDIUM = 12
    LARGE = 18
    PILL = 999


def color(value: str, alpha: int = 255) -> QColor:
    result = QColor(value)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result


def _family(preferred: str, fallback: str) -> str:
    families = set(QFontDatabase.families())
    return preferred if preferred in families else fallback


def display_font(size: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    font = QFont(_family("Space Grotesk", "Segoe UI"), size, weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.3)
    return font


def body_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return QFont(_family("Inter", "Segoe UI"), size, weight)


def mono_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return QFont(_family("IBM Plex Mono", "Cascadia Mono"), size, weight)


def app_stylesheet() -> str:
    """Global stylesheet for native controls that do not paint themselves."""
    return f"""
        QToolTip {{
            color: {Palette.TEXT};
            background: {Palette.SURFACE_RAISED};
            border: 1px solid {Palette.LINE_STRONG};
            border-radius: 6px;
            padding: 6px 9px;
        }}
        QMenu {{
            color: {Palette.TEXT};
            background: {Palette.SURFACE};
            border: 1px solid {Palette.LINE_STRONG};
            padding: 6px;
        }}
        QMenu::item {{
            border-radius: 6px;
            padding: 8px 22px 8px 11px;
        }}
        QMenu::item:selected {{
            color: {Palette.CYAN_SOFT};
            background: {Palette.SURFACE_HOVER};
        }}
        QScrollBar:vertical {{
            width: 7px;
            margin: 2px;
            background: transparent;
        }}
        QScrollBar::handle:vertical {{
            min-height: 28px;
            border-radius: 3px;
            background: {Palette.LINE_STRONG};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{ height: 0; }}
    """
