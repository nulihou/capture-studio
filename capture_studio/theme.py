"""Light / dark theme (v7): dark palette derived from the light stylesheet by an explicit colour map."""
from __future__ import annotations

import re

DARK = {
    "#1D1D1F": "#F5F5F7", "#F5F5F7": "#1C1C1E", "#FBFBFD": "#161618", "#E5E5EA": "#38383A", "#FFFFFF": "#2C2C2E",
    "#E8E8ED": "#3A3A3C", "#EDEDF0": "#2C2C2E", "#6E6E73": "#AEAEB2", "#86868B": "#98989D", "#3A3A3C": "#D1D1D6",
    "#F2F2F5": "#2C2C2E", "#AEAEB2": "#6E6E73", "#F0F0F3": "#323234", "#D2D2D7": "#48484A", "#EFEFF2": "#2C2C2E",
    "#E8F1FC": "#0A2A4A", "#0066CC": "#4DA3FF", "#E3F6E8": "#123A1F", "#1E8E3E": "#4CD964", "#FFECEB": "#4A1512",
    "#D70015": "#FF6961", "#FFF8E6": "#3A2E10", "#F5D9A0": "#6B5420", "#B25000": "#FFB340", "#48484A": "#C7C7CC", "#C7C7CC": "#48484A",
    "#ECECF0": "#323236", "#DCDCE0": "#48484A", "#F7F7F9": "#232325",
}
SPECIAL = [("QToolTip { background: #1D1D1F; color: #FFFFFF;", "QToolTip { background: #3A3A3C; color: #F5F5F7;"),
           ("rgba(255, 255, 255, 0.55)", "rgba(255, 255, 255, 0.10)"), ("rgba(0, 0, 0, 0.06)", "rgba(255, 255, 255, 0.08)"),
           ("rgba(0, 0, 0, 0.18)", "rgba(255, 255, 255, 0.22)"), ("rgba(0, 0, 0, 0.32)", "rgba(255, 255, 255, 0.36)")]
_HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
DARK_MODE = False


def color(value: str) -> str:
    return DARK.get(value.upper(), value) if DARK_MODE else value


def css(text: str, dark: bool | None = None) -> str:
    dark = DARK_MODE if dark is None else dark
    if not dark:
        return text
    tokens = {}
    for index, (light, dim) in enumerate(SPECIAL):
        token = f"@@S{index}@@"
        tokens[token] = dim
        text = text.replace(light, token)
    # QPushButton#primary / selection keep white text on blue: protect "color: #FFFFFF" pairs
    text = text.replace("color: #FFFFFF", "color: @@WHITE@@")
    text = _HEX.sub(lambda m: DARK.get(m.group(0).upper(), m.group(0)), text)
    for token, dim in tokens.items():
        text = text.replace(token, dim)
    return text.replace("@@WHITE@@", "#FFFFFF")


def system_dark() -> bool:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def resolve(choice: str) -> bool:
    """choice: '跟随系统' | '浅色' | '深色'."""
    if choice == "深色":
        return True
    if choice == "浅色":
        return False
    return system_dark()
