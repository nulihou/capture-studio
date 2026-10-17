"""Desktop window for Capture Studio."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout,
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QCheckBox, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from . import i18n
from .i18n import tr, tr_msg, tr_opt
from .camera_lab import TUNING, support_for
from .camera_modes import PRESETS, mode_key, mode_label, mode_prefix, mode_view, saved_mode, sort_modes
from .product import STUDIO
from . import icons, motion, theme, updates
from . import __version__
from .v7_ui import V7Mixin

STYLE = """
* { font-family: "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"; }
QWidget { color: #1D1D1F; font-size: 13px; }
QWidget#app, QWidget#canvas { background: #F5F5F7; }
QWidget#nav { background: #FBFBFD; border-right: 1px solid #ECECF0; }
QWidget#side { background: transparent; }
QFrame#card { background: #FFFFFF; border: 1px solid #ECECF0; border-radius: 14px; }
QFrame#subtle { background: #F7F7F9; border: none; border-radius: 10px; }
QFrame#segment { background: #EDEDF0; border: none; border-radius: 8px; }
QLabel#brand { font-size: 15px; font-weight: 600; color: #1D1D1F; background: transparent; letter-spacing: -0.2px; }
QLabel#title { font-size: 24px; font-weight: 600; color: #1D1D1F; background: transparent; letter-spacing: -0.4px; }
QLabel#cardTitle { font-size: 14px; font-weight: 600; color: #1D1D1F; background: transparent; padding-bottom: 2px; }
QLabel#subTitle { font-size: 12px; font-weight: 600; color: #3A3A3C; background: transparent; }
QLabel#kpi { font-size: 20px; font-weight: 600; color: #1D1D1F; background: transparent; letter-spacing: -0.3px; }
QLabel#field { font-size: 12px; color: #6E6E73; background: transparent; }
QLabel#note, QLabel#status { color: #6E6E73; background: transparent; }
QLabel#log { color: #86868B; font-size: 12px; background: transparent; padding: 0 4px; }
QLabel#fact { font-size: 14px; font-weight: 600; color: #1D1D1F; background: transparent; }
QLabel#pill { background: #E8E8ED; color: #6E6E73; border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600; }
QLabel#pillOk { background: #E3F6E8; color: #1E8E3E; border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600; }
QLabel#pillInfo { background: #E8F1FC; color: #0066CC; border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600; }
QLabel#pillWarn { background: #FFF8E6; color: #B25000; border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600; }
QPushButton#lang { background: transparent; border: none; border-radius: 7px; padding: 4px 6px; color: #3A3A3C; font-size: 12px; font-weight: 500; min-height: 18px; }
QPushButton#lang:hover { background: rgba(255, 255, 255, 0.55); }
QPushButton#lang:checked { background: #FFFFFF; color: #1D1D1F; font-weight: 600; border: 1px solid rgba(0, 0, 0, 0.06); }
QFrame#tile { background: #FFFFFF; border: 1px solid #ECECF0; border-radius: 12px; }
QLabel#tileCaption { font-size: 11px; font-weight: 500; color: #86868B; background: transparent; letter-spacing: 0.2px; }
QLabel#tileValue { font-size: 14px; font-weight: 600; color: #1D1D1F; background: transparent; }
QLabel#meta { font-size: 12px; color: #6E6E73; background: transparent; }
QListWidget#activity { background: transparent; border: none; }
QListWidget#activity::item { padding: 5px 2px; border-radius: 0; color: #3A3A3C; border-bottom: 1px solid #F2F2F5; }
QListWidget#activity::item:selected, QListWidget#activity::item:hover { background: transparent; color: #3A3A3C; }
QProgressBar#meter { background: #E8E8ED; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar#meter::chunk { background: #0071E3; border-radius: 3px; }
QLabel#empty { font-size: 12px; color: #AEAEB2; background: transparent; }
QLabel#section { font-size: 11px; font-weight: 600; color: #86868B; background: transparent; padding-left: 10px; letter-spacing: 0.2px; }
QLineEdit, QComboBox {
    background: #F5F5F7;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 20px;
    selection-background-color: #0071E3;
    selection-color: #FFFFFF;
}
QLineEdit:hover, QComboBox:hover { background: #F0F0F3; border-color: #D2D2D7; }
QLineEdit:focus, QComboBox:focus { background: #FFFFFF; border: 1px solid #0071E3; }
QLineEdit:disabled, QComboBox:disabled { color: #AEAEB2; background: #F5F5F7; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow { image: url(__CHEVRON__); width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 10px;
    selection-background-color: #0071E3;
    selection-color: #FFFFFF;
    outline: none;
    padding: 6px;
}
QPushButton {
    background: #FFFFFF;
    color: #1D1D1F;
    border: 1px solid #DCDCE0;
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 20px;
    font-weight: 500;
}
QPushButton:hover { background: #F5F5F7; }
QPushButton:pressed { background: #E8E8ED; }
QPushButton:disabled { color: #AEAEB2; background: #F5F5F7; border-color: #ECECF0; }
QPushButton#link { background: transparent; border: none; color: #0066CC; padding: 2px 4px; min-height: 16px; font-weight: 500; }
QPushButton#link:hover { color: #0071E3; text-decoration: underline; }
QPushButton#link:disabled { color: #AEAEB2; }
QPushButton#primary { background: #0071E3; color: #FFFFFF; border: 1px solid #0071E3; font-weight: 600; }
QPushButton#primary:hover { background: #0077ED; border-color: #0077ED; }
QPushButton#primary:pressed { background: #006EDB; }
QPushButton#primary:disabled { background: #E8E8ED; border-color: #E8E8ED; color: #AEAEB2; }
QPushButton#nav {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #3A3A3C;
    text-align: left;
    padding: 7px 10px;
    min-height: 22px;
    font-weight: 500;
}
QPushButton#nav:hover { background: #EFEFF2; color: #1D1D1F; }
QPushButton#nav:checked { background: #E8E8ED; color: #1D1D1F; font-weight: 600; }
QPushButton#preset {
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 6px 8px;
    color: #3A3A3C;
    font-weight: 500;
}
QPushButton#preset:hover { color: #1D1D1F; background: rgba(255, 255, 255, 0.55); }
QPushButton#preset:checked { background: #FFFFFF; color: #1D1D1F; font-weight: 600; border: 1px solid rgba(0, 0, 0, 0.06); }
QPushButton#ghost { background: rgba(255, 255, 255, 0.10); color: #F5F5F7; border: 1px solid rgba(255, 255, 255, 0.18); border-radius: 15px; padding: 5px 14px; }
QPushButton#ghost:hover { background: rgba(255, 255, 255, 0.18); }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 8px 10px; border-radius: 8px; margin: 1px 0; }
QListWidget::item:selected { background: #E8F1FC; color: #0066CC; }
QListWidget::item:hover:!selected { background: #F5F5F7; }
QScrollArea#sideScroll, QScrollArea#sideScroll > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 0; }
QScrollBar::handle:vertical { background: rgba(0, 0, 0, 0.18); border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: rgba(0, 0, 0, 0.32); }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { height: 0; background: none; }
QToolTip { background: #1D1D1F; color: #FFFFFF; border: none; border-radius: 6px; padding: 5px 8px; }
QDialog { background: #FFFFFF; }
QFrame#banner { background: #FFF8E6; border: 1px solid #F5D9A0; border-radius: 12px; }
QPushButton#ghostLight { background: transparent; border: 1px solid #DCDCE0; border-radius: 11px; padding: 2px 12px; min-height: 16px; font-size: 12px; }
QPushButton#ghostLight:hover { background: #F5F5F7; }
QToolButton#templates { background: #FFFFFF; border: 1px solid #DCDCE0; border-radius: 8px; padding: 6px 12px; font-weight: 500; }
QToolButton#templates::menu-indicator { image: none; width: 0; }
QMenu { background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #0071E3; color: #FFFFFF; }
QPlainTextEdit { background: #F5F5F7; border: 1px solid #E5E5EA; border-radius: 9px; padding: 6px; }
QCheckBox { background: transparent; }
/* v10 detail polish */
QLabel#glyph { background: transparent; }
QPushButton:focus { border: 1px solid #0071E3; }
QPushButton#primary:focus { border: 1px solid #0058B0; }
QPushButton#nav:focus, QPushButton#lang:focus, QPushButton#preset:focus, QPushButton#link:focus { border: none; }
QPushButton#nav:pressed { background: #E5E5EA; }
QPushButton#nav:checked:hover { background: #E5E5EA; }
QComboBox:hover, QLineEdit:hover { border-color: #C7C7CC; }
QComboBox:focus, QLineEdit:focus { border-color: #0071E3; }
QListWidget { outline: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0 4px; }
QScrollBar::handle:horizontal { background: rgba(0, 0, 0, 0.18); border-radius: 4px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: rgba(0, 0, 0, 0.32); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QFrame#separator { background: #ECECF0; border: none; max-height: 1px; min-height: 1px; }
QLabel#keycap { color: #3A3A3C; background: #F2F2F5; border: 1px solid #DCDCE0; border-radius: 5px; padding: 1px 6px; font-size: 11px; font-weight: 600; }
QCheckBox#smallCheck { font-size: 12px; color: #6E6E73; spacing: 6px; }
QCheckBox#smallCheck::indicator { width: 13px; height: 13px; }
QLabel#toast { background: rgba(29, 29, 31, 0.92); color: #FFFFFF; border-radius: 12px; padding: 10px 18px; font-size: 13px; font-weight: 500; }
QLabel#tips { color: #86868B; font-size: 12px; background: transparent; }
QFrame#connectTip { background: #F7F7F9; border: 1px solid #ECECF0; border-radius: 10px; }
QLabel#connectTipTitle { font-size: 12px; font-weight: 600; color: #3A3A3C; background: transparent; }
QPushButton#tipDismiss { background: transparent; border: none; color: #86868B; font-size: 12px; padding: 2px 6px; }
QPushButton#tipDismiss:hover { color: #1D1D1F; }
"""


def _chevron_url() -> str:
    """v10: Lucide chevron, theme-coloured, with an @2x twin for HiDPI."""
    return icons.chevron_files(Path(os.environ.get("TEMP", ".")) / "capture_studio_icons", theme.color("#86868B"))


def _dpr(widget: QWidget | None = None) -> float:
    try:
        if widget is not None:
            return float(widget.devicePixelRatioF())
        screen = QApplication.primaryScreen()
        return float(screen.devicePixelRatio()) if screen else 1.0
    except Exception:
        return 1.0


PILL_KINDS = {  # kind -> (icon, background, foreground); light values, theme.css maps them for dark
    "neutral": ("st.dot", "#E8E8ED", "#6E6E73"), "ok": ("st.ok", "#E3F6E8", "#1E8E3E"),
    "info": ("st.info", "#E8F1FC", "#0066CC"), "warn": ("st.warn", "#FFF8E6", "#B25000"),
    "error": ("st.fail", "#FFECEB", "#D70015"), "rec": ("st.dot", "#FFECEB", "#D70015"),
    "live": ("st.dot", "#E3F6E8", "#1E8E3E"), "idle": ("st.dot", "#F2F2F5", "#8E8E93"),
}
FILLED_DOT = {"rec", "live", "neutral", "idle"}
_PILL_CACHE: dict[tuple, QPixmap] = {}


class _UpdateBridge(QObject):
    done = Signal(dict)


class UpdateDialog(QDialog):
    """v12: shows the new version's notes; Download opens the GitHub page in the browser (no self-replace)."""

    def __init__(self, parent: QWidget, result: dict) -> None:
        super().__init__(parent)
        self.result = result
        self.setWindowTitle(tr("检查更新"))
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        head = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(icons.pixmap("act.download", 24, "accent"))
        head.addWidget(badge)
        title = _label(tr_msg(f"有新版本 v{result.get('version', '')}"), "cardTitle")
        head.addWidget(title, 1)
        head.addWidget(Pill(tr_msg(f"当前 v{__version__}"), "neutral"))
        layout.addLayout(head)
        if result.get("asset_name"):
            layout.addWidget(_label(f"{result['asset_name']} · {_size(result.get('asset_size', 0))}", "meta"))
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(False)
        self.notes.setMarkdown(result.get("notes") or tr("没有更新说明"))
        layout.addWidget(self.notes, 1)
        layout.addWidget(_label("下载后解压到新文件夹即可，旧版本和设置不会被改动。", "meta"))
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.reject)
        self.download = QPushButton(tr("下载"))
        self.download.setObjectName("primary")
        _decorate(close, "关闭")
        _decorate(self.download, "下载", True)
        self.download.clicked.connect(self.open_download)
        row.addWidget(close)
        row.addWidget(self.download)
        layout.addLayout(row)

    def target_url(self) -> str:
        for url in (self.result.get("asset_url"), self.result.get("url"), updates.RELEASES):
            if url and updates.safe_url(url):
                return url
        return updates.RELEASES

    def open_download(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(self.target_url()))
        self.accept()


class Pill(QLabel):
    """v11 status pill: semantic Lucide icon + label, crisp at any DPR; colour changes cross-fade (200 ms)."""

    ICON = 12

    def __init__(self, text: str = "", kind: str = "neutral", size: str = "small") -> None:
        super().__init__(tr(text))
        self.kind = ""
        self.size_name = size
        self._fade = 0.0
        self._ghost: QPixmap | None = None
        self._anim: QVariantAnimation | None = None
        self.setObjectName("statusPill")
        self.set_state(kind, self.text(), animate=False)

    def _css(self) -> str:
        _icon, bg, fg = PILL_KINDS[self.kind]
        big = self.size_name == "large"
        return theme.css(f"QLabel {{ background: {bg}; color: {fg}; border-radius: {11 if big else 10}px; "
                         f"padding: {'3px 12px 3px 28px' if big else '2px 10px 2px 24px'}; "
                         f"font-size: {12 if big else 11}px; font-weight: 600; }}")

    def set_state(self, kind: str, text: str, animate: bool = True) -> None:
        kind = kind if kind in PILL_KINDS else "neutral"
        if kind == self.kind and text == self.text():
            return
        if animate and kind != self.kind and self.isVisible() and not motion.reduced() and self.width() > 0:
            self._ghost = self.grab()
            self._fade = 1.0
            anim = QVariantAnimation(self)
            anim.setDuration(motion.PILL_MS)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            anim.valueChanged.connect(self._on_fade)
            if self._anim is not None:
                self._anim.stop()
            self._anim = anim
            anim.start()
        elif motion.reduced() and self._anim is not None:
            self._anim.stop()
            self._ghost, self._fade = None, 0.0
        restyle = kind != self.kind
        self.kind = kind
        self.setText(text)
        if restyle:
            self.setStyleSheet(self._css())

    def refresh_theme(self) -> None:
        self.setStyleSheet(self._css())

    def _on_fade(self, value: Any) -> None:
        self._fade = float(value)
        if self._fade <= 0.001:
            self._ghost = None
        self.update()

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        name, _bg, fg = PILL_KINDS[self.kind]
        color = theme.color(fg)
        size = self.ICON
        left = 10 if self.size_name == "large" else 8
        top = (self.height() - size) / 2
        if self.kind in FILLED_DOT:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            r = 3.5 if self.kind in ("rec", "live") else 3.0
            painter.drawEllipse(QPointF(left + size / 2, self.height() / 2), r, r)
        else:
            key = (name, size, fg, _dpr(self), theme.DARK_MODE)
            if key not in _PILL_CACHE:  # paint runs every crossfade frame: rasterise each glyph once
                _PILL_CACHE[key] = icons.pixmap(name, size, fg, key[3])  # role_color maps once
            painter.drawPixmap(QPointF(left, top), _PILL_CACHE[key])
        if self._ghost is not None and self._fade > 0:
            painter.setOpacity(self._fade)
            painter.drawPixmap(0, 0, self._ghost)
        painter.end()


class Toast(QLabel):
    """v11 in-window toast: fades in, holds, fades out; instant under reduced motion. Never steals focus."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._anim: QPropertyAnimation | None = None

    def show_message(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 32)
        self.raise_()
        self.show()
        motion.fade_in(self, motion.TOAST_IN_MS)
        self._timer.start(motion.TOAST_HOLD_MS)

    def _fade_out(self) -> None:
        if motion.reduced():
            self.hide()
            return
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(motion.TOAST_OUT_MS)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(lambda: (self.hide(), self.setGraphicsEffect(None)))
        self._anim = anim
        anim.start()


class KeyTips(QWidget):
    """Shortcut rows (real bindings from v7_ui.SHORTCUTS); rows that don't fit are hidden, so it never forces height."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("side")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.setMinimumHeight(0)
        from .v7_ui import SHORTCUTS as KEYS
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)
        line = QFrame()
        line.setObjectName("separator")
        layout.addWidget(line)
        head = QHBoxLayout()
        head.setSpacing(6)
        glyph = QLabel()
        glyph.setObjectName("glyph")
        glyph.setPixmap(icons.pixmap("act.keyboard", 16, "muted", _dpr()))
        head.addWidget(glyph)
        head.addWidget(_label("快捷键", "tileCaption"), 1)
        self.rows: list[QWidget] = []
        header = QWidget()
        header.setObjectName("side")
        header.setLayout(head)
        layout.addWidget(header)
        self.rows.append(header)
        for key, text in KEYS[:6]:
            row = QWidget()
            row.setObjectName("side")
            box = QHBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(8)
            cap = _label(key, "keycap")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setMinimumWidth(44)
            box.addWidget(cap)
            box.addWidget(_label(text, "tips"), 1)
            layout.addWidget(row)
            self.rows.append(row)
        layout.addStretch(1)
        self.rows.insert(0, line)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        used = 8
        for row in self.rows:
            need = row.sizeHint().height() + 6
            row.setVisible(used + need <= self.height())
            used += need


class Dot(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.connected = False
        self.setFixedSize(8, 8)

    def set_connected(self, value: bool) -> None:
        self.connected = value
        self.update()

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#34C759" if self.connected else "#C7C7CC"))
        painter.drawEllipse(0, 0, 8, 8)


class Monitor(QWidget):
    """Full-bleed picture. Empty state is drawn, so it cannot disappear into the black."""

    def __init__(self) -> None:
        super().__init__()
        self.image = QImage()
        self.caption = ""
        self.empty_title = ""  # overrides "无画面" (e.g. PC page without a camera)
        self.setMinimumSize(520, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_image(self, image: QImage) -> None:
        self.image = image
        self.update()

    def set_empty_title(self, text: str) -> None:
        if text != self.empty_title:
            self.empty_title = text
            if self.image.isNull():
                self.update()

    def set_caption(self, text: str) -> None:
        if text != self.caption:
            self.caption = text
            if self.image.isNull():
                self.update()

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(), QColor("#0B0B0D"))
        if not self.image.isNull():
            pixmap = QPixmap.fromImage(self.image).scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation)
            painter.drawPixmap(
                (self.width() - pixmap.width()) // 2,
                (self.height() - pixmap.height()) // 2,
                pixmap)
            return
        cx, cy = self.width() / 2, self.height() / 2 - 44
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18))
        painter.drawRoundedRect(QRectF(cx - 26, cy - 26, 52, 52), 14, 14)
        glyph = icons.pixmap("st.empty", 24, "#8E8E93", _dpr(self))
        painter.drawPixmap(QPointF(cx - 12, cy - 12), glyph)
        painter.setPen(QColor("#F5F5F7"))
        title = QFont(self.font())
        title.setPixelSize(20)
        title.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title)
        painter.drawText(self.rect().adjusted(0, -16, 0, 0), Qt.AlignmentFlag.AlignCenter,
                         tr(self.empty_title or "无画面"))
        painter.setPen(QColor("#8E8E93"))
        detail = QFont(self.font())
        detail.setPixelSize(13)
        painter.setFont(detail)
        line = QRectF(0, self.height() / 2 + 10, self.width(), 28)
        painter.drawText(line, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.caption)
        if self.height() < 300 or self.empty_title:
            return
        steps = [tr("连接开发板"), tr("识别摄像头并预览"), tr("调整画面后开始采集")]
        step_font = QFont(self.font())
        step_font.setPixelSize(13)
        painter.setFont(step_font)
        metrics = painter.fontMetrics()
        width = max(metrics.horizontalAdvance(text) for text in steps) + 34
        left = (self.width() - width) / 2
        top = self.height() / 2 + 58
        for index, text in enumerate(steps):
            y = top + index * 30
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 28))
            painter.drawEllipse(QRectF(left, y, 20, 20))
            painter.setPen(QColor("#D1D1D6"))
            painter.drawText(QRectF(left, y, 20, 20), Qt.AlignmentFlag.AlignCenter, str(index + 1))
            painter.setPen(QColor("#AEAEB2"))
            painter.drawText(QRectF(left + 32, y, width, 20),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


def _viewfinder(size: int = 20) -> QPixmap:
    dpr = _dpr()
    pixmap = icons.app_pixmap(round(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def _lift(widget: QWidget, blur: int = 28, dy: int = 4, alpha: int = 18) -> QWidget:
    """Soft, diffuse elevation in the spirit of macOS cards."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, dy)
    shadow.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(shadow)
    return widget


class ElideLabel(QLabel):
    """Single-line label that ends with … instead of overflowing its column."""

    def __init__(self, text: str = "", name: str = "tileValue") -> None:
        super().__init__()
        self.setObjectName(name)
        self._full = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full(text)

    def set_full(self, text: str) -> None:
        if text != self._full:
            self._full = text
            self.setToolTip(text)
            self._elide()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(10, self.width())
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width))


BADGE = {
    "rec": "QLabel { background: #FFECEB; color: #D70015; border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 700; }",
    "live": "QLabel { background: #E3F6E8; color: #1E8E3E; border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 700; }",
    "idle": "QLabel { background: #F2F2F5; color: #8E8E93; border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600; }",
}


def _size(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.0f} {unit}" if unit in ("B", "KB") else f"{number:.1f} {unit}"
        number /= 1024
    return ""


def _rate(value: float) -> str:
    return _size(value) + "/s"


def _duration(seconds: int) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    if i18n.LANG == "en":
        return (f"{days}d " if days else "") + f"{hours}h {rest // 60}m"
    return (f"{days} 天 " if days else "") + f"{hours} 小时 {rest // 60} 分"


def session_row(summary: dict[str, Any]) -> str:
    """'10-14 09:31 · 1280×720 · 1:00 · 45.2 MB' from a session_review.summarize() dict (v9)."""
    import re as _re
    sid = str(summary.get("session_id") or "")
    found = _re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", sid)
    when = sid[:15]
    if found:
        from datetime import datetime, timezone
        stamp = datetime(*map(int, found.groups()), tzinfo=timezone.utc).astimezone()
        when = stamp.strftime("%m-%d %H:%M")
    parts = [when]
    if summary.get("width"):
        parts.append(f"{summary['width']}×{summary['height']}")
    if summary.get("duration"):
        seconds = int(float(summary["duration"]))
        parts.append(f"{seconds // 60}:{seconds % 60:02d}")
    if summary.get("size"):
        parts.append(_size(summary["size"]))
    return " · ".join(parts)


def _label(text: str, name: str = "field") -> QLabel:
    widget = QLabel(tr(text))
    widget.setObjectName(name)
    return widget


def _edit(text: str = "") -> QLineEdit:
    widget = QLineEdit(text)
    return widget


def _combo(options: list[str]) -> QComboBox:
    """Shows translated labels; the Chinese value the backend expects is kept as item data."""
    widget = QComboBox()
    # Size to the column, not to the longest (English) item, so the inspector never scrolls sideways.
    widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    widget.setMinimumContentsLength(4)
    for value in options:
        widget.addItem(tr_opt(value), value)
    return widget


def _button_text(text: str) -> str:
    """Qt treats '&' as a mnemonic marker; escape it so 'Save & Connect' renders literally."""
    return tr(text).replace("&", "&&")


SHORTCUTS = {"开始采集": "Space", "录 60 秒": "Space", "停止并取回": "Space", "停止并校验": "Space", "大屏": "F",
             "实时": "L", "停止实时": "L", "预览一帧": "P", "体检": "H", "刷新": "R"}


def _decorate(widget: QPushButton, text: str, primary: bool = False) -> None:
    """v10: leading 16 px icon for known actions plus a tooltip that names the keyboard shortcut."""
    name = icons.BUTTON_ICONS.get(text)
    if name:
        widget.setIcon(icons.icon(name, 16, "onAccent" if primary else "normal", "onAccent" if primary else "active"))
        widget.setIconSize(QSize(16, 16))
    widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # focus ring only for keyboard users, not after every click
    key = SHORTCUTS.get(text)
    widget.setToolTip(f"{tr(text)}  ·  {key}" if key else tr(text))


def _combo_value(widget: QComboBox) -> str:
    data = widget.currentData()
    return str(data) if data is not None else widget.currentText()


def _icon(kind: str) -> QIcon:
    """v10: sidebar glyphs from the shared Lucide set; muted at rest, full contrast on hover / checked."""
    return icons.icon(kind, 20, "muted", "active", selected="accent")


class FrameView(QGraphicsView):
    """Picture stage with wheel zoom and drag."""

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.scene().addItem(self.item)
        self._zoom = 1.0
        self._fit = QTransform()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#0B0B0D"))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def set_image(self, image: QImage) -> None:
        self.item.setPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.item.boundingRect())
        if self._zoom == 1.0:
            self._apply_fit()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if self._zoom == 1.0:
            self._apply_fit()

    def _apply_fit(self) -> None:
        self.resetTransform()
        rect = self.item.boundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._fit = self.transform()
        self._zoom = 1.0
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def wheelEvent(self, event: Any) -> None:
        if self.item.pixmap().isNull():
            return
        step = 0.25 if event.angleDelta().y() > 0 else -0.25
        target = min(4.0, max(1.0, self._zoom + step))
        self._zoom = target
        if target == 1.0:
            self._apply_fit()
        else:
            self.setTransform(self._fit)
            self.scale(target, target)
            self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        event.accept()

    def drawForeground(self, painter: QPainter, rect: Any) -> None:
        if not self.item.pixmap().isNull():
            return
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor("#f2f2f4"))
        painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, tr("无画面"))
        painter.restore()


class LargeView(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("大屏"))
        self.setModal(False)
        self.view = FrameView()
        self.seq = -1
        hint = QLabel(tr("滚轮放大    拖动平移    Esc 关闭"))
        close = QPushButton(tr("关闭"))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setObjectName("ghost")
        close.clicked.connect(self.close)
        bar = QHBoxLayout()
        bar.addWidget(hint)
        bar.addStretch(1)
        bar.addWidget(close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self.view, 1)
        layout.addLayout(bar)
        self.setStyleSheet(
            "QDialog { background: #0B0B0D; }"
            "QLabel { color: #8E8E93; background: transparent; font-size: 12px; }")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(int(screen.width() * 0.86), int(screen.height() * 0.86))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._pull)
        self.timer.start(120)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        if not self.timer.isActive():
            self.timer.start(120)

    def hideEvent(self, event: Any) -> None:
        # Bug fix: the hidden dialog kept decoding preview frames every 120 ms.
        self.timer.stop()
        super().hideEvent(event)

    def _pull(self) -> None:
        with STUDIO.lock:
            seq, data = STUDIO.preview_seq, STUDIO.preview
        if not data or seq == self.seq:
            return
        image = QImage.fromData(data)
        if image.isNull():
            return
        self.seq = seq
        self.view.set_image(image)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class ConnectDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("连接"))
        self.setModal(True)
        self.setMinimumWidth(460)
        self.fields: dict[str, QLineEdit] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(0)
        title = _label("连接开发板", "title")
        layout.addWidget(title)
        layout.addSpacing(8)
        self.tip = self._build_tip()
        layout.addWidget(self.tip)
        layout.addSpacing(4)
        for key, caption in (
            ("host", "地址"), ("user", "用户"), ("key", "Capture Studio SSH 密钥"),
            ("board_root", "板端目录"), ("serial", "摄像头序号"),
        ):
            edit = _edit()
            if key == "serial":
                edit.setPlaceholderText(tr("可留空"))
            self.fields[key] = edit
            layout.addSpacing(12)
            layout.addWidget(_label(caption))
            layout.addSpacing(6)
            if key == "key":
                row = QHBoxLayout()
                row.setSpacing(10)
                row.addWidget(edit, 1)
                choose = QPushButton(tr("选择"))
                choose.setCursor(Qt.CursorShape.PointingHandCursor)
                choose.clicked.connect(self._choose_key)
                row.addWidget(choose)
                layout.addLayout(row)
                self.choose = choose
            else:
                layout.addWidget(edit)
        self.password = _edit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(tr("仅新板第一次"))
        layout.addSpacing(12)
        layout.addWidget(_label("密码"))
        layout.addSpacing(6)
        layout.addWidget(self.password)
        row = QHBoxLayout()
        row.addStretch(1)
        self.find = QPushButton(_button_text("查找"))
        self.go = QPushButton(_button_text("保存并连接"))
        self.go.setObjectName("primary")
        for widget in (self.find, self.go):
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.find)
        row.addWidget(self.go)
        layout.addSpacing(24)
        layout.addLayout(row)
        self.go.clicked.connect(self.accept)
        self.find.clicked.connect(self._find)

    def _build_tip(self) -> QFrame:
        """Compact first-connect one-pager; dismissed state remembered in settings."""
        frame = QFrame()
        frame.setObjectName("connectTip")
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(4)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel(tr("首次连板"))
        title.setObjectName("connectTipTitle")
        head.addWidget(title, 1)
        dismiss = QPushButton(tr("不再显示"))
        dismiss.setObjectName("tipDismiss")
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.clicked.connect(self._dismiss_tip)
        head.addWidget(dismiss)
        box.addLayout(head)
        bullets = [
            "• " + tr("点“查找”扫描本机网段 /24、邻居表与 .local 的 SSH 应答"),
            "• " + tr("网线直连常出现 169.254：可扫邻居/.local，或给网卡设同网段静态 IP"),
            "• " + tr("也可直接填写开发板 IP 后连接"),
            "• " + tr("登录使用 Capture Studio SSH 密钥（磁盘文件仍为 id_ed25519_kv260）"),
        ]
        body = QLabel("\n".join(bullets))
        body.setObjectName("tips")
        body.setWordWrap(True)
        box.addWidget(body)
        return frame

    def _dismiss_tip(self) -> None:
        STUDIO.update_settings({"connect_tip_dismissed": "1"})
        self.tip.hide()

    def _choose_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Capture Studio SSH 密钥"))
        if path:
            self.fields["key"].setText(path)

    def _find(self) -> None:
        self.parent().discover(self.values())

    def values(self) -> dict[str, str]:
        return {key: widget.text().strip() for key, widget in self.fields.items()}

    def load(self, settings: dict[str, Any]) -> None:
        focused = QApplication.focusWidget()
        for key, widget in self.fields.items():
            if widget is focused:
                continue
            text = str(settings.get(key) or "")
            if widget.text() != text:
                widget.setText(text)
        dismissed = str(settings.get("connect_tip_dismissed") or "") in ("1", "True", "true")
        self.tip.setVisible(not dismissed)


class StudioWindow(V7Mixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("app")
        self.setWindowTitle("Capture Studio")
        self.resize(1360, 860)
        self.setMinimumSize(1100, 720)
        self.fields: dict[str, QWidget] = {}
        self.actions: list[QPushButton] = []
        self.presets: dict[str, QPushButton] = {}
        self._session_ids: list[str] = []
        self.session_id = ""
        self.preview_seq = -1
        self._image = QImage()
        self.dialog: ConnectDialog | None = None
        self.large: LargeView | None = None
        self.current_page = "lab"
        self.session_source = ""
        self._custom_mode = False
        self._disk_checked = 0.0
        self.live_button: QPushButton | None = None
        self._v7_init()
        self._build()
        self.refresh(STUDIO.state())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)

    def _action(self, text: str, slot: Any, primary: bool = False, needs: str = "") -> QPushButton:
        """needs: '' always | board | board_idle | idle | pc_cam | recording | controls | session | board_session."""
        widget = QPushButton(_button_text(text))
        widget.setProperty("needs", needs)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            widget.setObjectName("primary")
        _decorate(widget, text, primary)
        widget.clicked.connect(slot)
        self.actions.append(widget)
        return widget

    def _field(self, key: str, widget: QWidget) -> QWidget:
        self.fields[key] = widget
        return widget

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._nav())
        canvas = QWidget()
        canvas.setObjectName("canvas")
        column = QVBoxLayout(canvas)
        column.setContentsMargins(24, 24, 24, 24)
        column.setSpacing(16)
        column.addWidget(self._title_row())
        column.addWidget(self._overview())
        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._stage(), 1)
        body.addWidget(self._inspector())
        column.addLayout(body, 1)
        root.addWidget(canvas, 1)

    def _overview(self) -> QWidget:
        """Four compact status tiles: the at-a-glance summary of the rig."""
        row = QWidget()
        row.setObjectName("side")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.tiles: dict[str, ElideLabel] = {}
        for key, caption in (("board", "开发板"), ("camera", "摄像头"),
                             ("stream", "画面参数"), ("state", "状态")):
            tile = QFrame()
            tile.setObjectName("tile")
            box = QVBoxLayout(tile)
            box.setContentsMargins(16, 12, 16, 12)
            box.setSpacing(4)
            head = QHBoxLayout()
            head.setSpacing(6)
            glyph = QLabel()
            glyph.setObjectName("glyph")
            glyph.setPixmap(icons.pixmap({"board": "dev.board", "camera": "dev.video", "stream": "ui.image",
                                          "state": "ui.activity"}[key], 16, "muted", _dpr()))
            glyph.setFixedSize(16, 16)
            head.addWidget(glyph, 0, Qt.AlignmentFlag.AlignVCenter)
            head.addWidget(_label(caption, "tileCaption"), 1, Qt.AlignmentFlag.AlignVCenter)
            box.addLayout(head)
            value = ElideLabel("—")
            box.addWidget(value)
            self.tiles[key] = value
            layout.addWidget(tile, 1)
        return row

    def _live_button(self, button: QPushButton) -> QPushButton:
        self.live_button = button
        return button

    def _list_sessions(self, where: str) -> None:
        self.session_source = where
        STUDIO.list_sessions(where)

    def _fit_inspector(self) -> None:
        """Size the stacks to the visible page/tab only, so hidden content never forces a scrollbar."""
        page = self.stack.currentWidget()
        if page is None:
            return
        for index in range(self.stack.count()):
            widget = self.stack.widget(index)
            policy = QSizePolicy.Policy.Preferred if widget is page else QSizePolicy.Policy.Ignored
            widget.setSizePolicy(policy, policy)  # v9: hidden pages no longer widen the panel (clipping at 125 %)
        if hasattr(self, "lab_stack"):
            current = self.lab_stack.currentWidget()
            for index in range(self.lab_stack.count()):
                widget = self.lab_stack.widget(index)
                widget.setSizePolicy(QSizePolicy.Policy.Preferred,
                                     QSizePolicy.Policy.Preferred if widget is current else QSizePolicy.Policy.Ignored)
            self.lab_stack.updateGeometry()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if hasattr(self, "inspector"):
            width = 440 if self.width() >= 1800 else 400
            if self.inspector.width() != width:
                self.inspector.setFixedWidth(width)

    def _title_row(self) -> QWidget:
        row = QWidget()
        row.setObjectName("side")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(14)
        self.heading = _label("摄像头测试", "title")
        self.chip = Pill("未连接", "neutral", "large")
        self.status = _label("就绪", "status")
        layout.addWidget(self.heading)
        layout.addWidget(self.chip)
        layout.addStretch(1)
        layout.addWidget(self.status)
        return row

    def _nav(self) -> QWidget:
        nav = QWidget()
        nav.setObjectName("nav")
        nav.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nav.setFixedWidth(224)
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(14, 26, 14, 20)
        layout.setSpacing(2)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.setContentsMargins(10, 0, 0, 0)
        mark = QLabel()
        mark.setPixmap(_viewfinder())
        brand.addWidget(mark)
        brand.addWidget(_label("Capture Studio", "brand"))
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(28)
        layout.addWidget(_label("工作区", "section"))
        layout.addSpacing(6)
        self.pages = QButtonGroup(self)
        self.pages.setExclusive(True)
        self.page_buttons: dict[str, QPushButton] = {}
        for index, (key, text) in enumerate((
            ("lab", "测试"), ("pc", "电脑"), ("board", "开发板"), ("periph", "外设"),
            ("sessions", "会话"), ("settings", "设置"),
        )):
            button = QPushButton(tr(text))
            button.setObjectName("nav")
            button.setIcon(_icon(f"nav.{key}"))
            button.setIconSize(QSize(20, 20))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, name=key: self.show_page(name))
            self.pages.addButton(button, index)
            self.page_buttons[key] = button
            layout.addWidget(button)
        self.page_buttons["lab"].setChecked(True)
        layout.addStretch(1)
        self._v7_nav_extras(layout)
        layout.addWidget(_label("语言", "section"))
        layout.addSpacing(6)
        layout.addWidget(self._language_switch())
        layout.addSpacing(10)
        layout.addWidget(_label("外观", "section"))
        layout.addSpacing(6)
        layout.addWidget(self._theme_switch())
        return nav

    def _language_switch(self) -> QWidget:
        """Segmented 中文 / English control; switching rebuilds the window in place."""
        segment = QFrame()
        segment.setObjectName("segment")
        row = QHBoxLayout(segment)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        group = QButtonGroup(segment)
        group.setExclusive(True)
        for code, text in (("zh", "中文"), ("en", "English")):
            button = QPushButton(text)
            button.setObjectName("lang")
            button.setCheckable(True)
            button.setChecked(i18n.LANG == code)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=code: self.set_language(value))
            group.addButton(button)
            row.addWidget(button, 1)
        return segment

    def set_language(self, lang: str) -> None:
        if lang == i18n.LANG:
            return
        i18n.set_lang(lang)
        self._rebuild()

    def _rebuild(self) -> None:
        page = self.current_page
        tab = self.lab_stack.currentIndex() if hasattr(self, "lab_stack") else 0
        for window in (self.dialog, self.large):
            if window is not None:
                window.close()
                window.deleteLater()
        self.dialog = None
        self.large = None
        old = self.layout()
        if old is not None:
            QWidget().setLayout(old)  # hand the old tree to a throwaway parent so it is freed
        self.fields = {}
        self.actions = []
        self.presets = {}
        self._session_ids = []
        self.preview_seq = -1
        self.live_button = None
        self._disk_checked = 0.0
        for attribute in ("lab_stack", "lab_tabs", "mode_combos", "mode_captions", "_mode_items", "data_cards", "manual_mode"):
            if hasattr(self, attribute):
                delattr(self, attribute)
        self._build()
        self.show_page(page)
        self._show_tab(tab)
        self.refresh(STUDIO.state())

    def _stage(self) -> QWidget:
        self.stage = QFrame()
        self.stage.setObjectName("card")
        _lift(self.stage, 32, 6, 14)
        layout = QVBoxLayout(self.stage)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.setContentsMargins(6, 2, 4, 0)
        head.setSpacing(10)
        head.addWidget(_label("预览", "cardTitle"))
        self.badge = Pill("空闲", "idle")
        head.addWidget(self.badge)
        self.live_label = _label("", "meta")
        head.addStretch(1)
        self.stream_info = _label("", "meta")  # stream is already shown in the overview tile
        self.stream_info.hide()
        head.addWidget(self.live_label)
        self._v7_head_buttons(head)
        layout.addLayout(head)
        self.viewport = Monitor()
        layout.addWidget(self.viewport, 1)
        layout.addWidget(self._v7_stage_banner())
        # Compact activity feed under the picture (moved out of the side panel in v5).
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 0, 0, 0)
        bar.setSpacing(16)
        feed = QVBoxLayout()
        feed.setSpacing(2)
        feed.addWidget(_label("动态", "tileCaption"))
        self.activity = QLabel()
        self.activity.setObjectName("meta")
        self.activity.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.activity.setFixedHeight(self.activity.fontMetrics().lineSpacing() * 3 + 4)
        self.activity.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.activity.setText(tr("暂无动态"))
        feed.addWidget(self.activity)
        self._activity_lines: list[str] = []
        self.activity_empty = self.activity
        self.log = self.activity
        bar.addLayout(feed, 1)
        large = self._action("大屏", self.open_large)
        bar.addWidget(large, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(bar)
        return self.stage

    def _inspector(self) -> QWidget:
        inspector = QWidget()
        inspector.setObjectName("side")
        inspector.setFixedWidth(400)
        self.inspector = inspector
        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.footers: dict[str, QWidget] = {}
        self.stack = QStackedWidget()
        self.stack.setObjectName("side")
        self.stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.stack.addWidget(self._lab_page())
        self.stack.addWidget(self._pc_page())
        self.stack.addWidget(self._board_page())
        self.stack.addWidget(self._sessions_page())
        self.stack.addWidget(self._settings_page())
        self.stack.addWidget(self._periph_page())
        scroll = QScrollArea()
        scroll.setObjectName("sideScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("sideViewport")
        # Scoped selector: an unscoped rule here cascaded to every child and made cards/buttons see-through.
        scroll.viewport().setStyleSheet("QWidget#sideViewport { background: transparent; }")
        scroll.setWidget(self.stack)
        self.side_scroll = scroll  # safety net only; every page is laid out to fit at 1280x800
        layout.addWidget(scroll, 1)
        layout.addWidget(self._footer())
        return inspector

    def _footer(self) -> QWidget:
        """Pinned action bar: duration + the page's primary actions are always visible."""
        bar = QFrame()
        bar.setObjectName("card")
        _lift(bar)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self.duration_bar = QWidget()
        self.duration_bar.setObjectName("side")
        row = QHBoxLayout(self.duration_bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(_label("时长", "cardTitle"))
        row.addWidget(self._field("duration", _combo(["60 秒短检", "10 分钟关口", "手动停止"])), 1)
        row.addWidget(self._v7_template_button())
        self.template_button.setFixedHeight(self.fields["duration"].sizeHint().height())  # footer height unchanged from v6
        layout.addWidget(self.duration_bar)
        self.footer_stack = QStackedWidget()
        self.footer_stack.setObjectName("side")
        for name in ("lab", "pc", "board", "sessions", "settings", "periph"):
            self.footer_stack.addWidget(self.footers[name])
        layout.addWidget(self.footer_stack)
        return bar

    def _set_footer(self, page: str, *widgets: QWidget) -> None:
        holder = QWidget()
        holder.setObjectName("side")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        for widget in widgets:
            if len(widgets) >= 4 and isinstance(widget, QPushButton):
                widget.setIcon(QIcon())  # v10: four-up footers stay text-only so English labels never clip
            row.addWidget(widget, 1)
        self.footers[page] = holder

    def _card(self, title: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        if title:
            layout.addWidget(_label(title, "cardTitle"))
        return card, layout

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("side")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        card, layout = self._card()
        outer.addWidget(card)
        outer.addStretch(1)
        self._page_outer = outer
        return page, layout

    def _pair(self, left: QWidget, right: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(left, 1)
        row.addWidget(right, 1)
        return row

    def _tabs(self, names: list[str]) -> tuple[QFrame, QStackedWidget]:
        """Apple-style segmented tabs over a stacked card; only one group is on screen at a time."""
        segment = QFrame()
        segment.setObjectName("segment")
        row = QHBoxLayout(segment)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        stack = QStackedWidget()
        stack.setObjectName("side")
        group = QButtonGroup(segment)
        group.setExclusive(True)
        self.lab_tabs: list[QPushButton] = []
        for index, name in enumerate(names):
            button = QPushButton(tr(name))
            button.setObjectName("preset")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=index: self._show_tab(value))
            group.addButton(button)
            row.addWidget(button, 1)
            self.lab_tabs.append(button)
        self.lab_stack = stack
        return segment, stack

    def _show_tab(self, index: int) -> None:
        self.lab_stack.setCurrentIndex(index)
        self.lab_tabs[index].setChecked(True)
        self._fit_inspector()

    # ---- v6: capture modes ----------------------------------------------------------
    def _mode_row(self, kind: str) -> QWidget:
        """'Mode' dropdown filled from detection (or common presets) plus a detect button."""
        box = QWidget()
        box.setObjectName("side")
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        caption = _label("模式")
        column.addWidget(caption)
        row = QHBoxLayout()
        row.setSpacing(10)
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(8)
        combo.setMaxVisibleItems(10)
        combo.activated.connect(lambda index, which=kind: self._pick_mode(which, index))
        row.addWidget(combo, 1)
        row.addWidget(self._action("检测", lambda _checked=False, which=kind: STUDIO.detect_modes(which),
                                   needs="board" if kind == "board" else ""))
        column.addLayout(row)
        if not hasattr(self, "mode_combos"):
            self.mode_combos: dict[str, QComboBox] = {}
            self.mode_captions: dict[str, QLabel] = {}
            self._mode_items: dict[str, list[str]] = {}
        self.mode_combos[kind] = combo
        self.mode_captions[kind] = caption
        self._mode_items[kind] = []
        return box

    def _pick_mode(self, kind: str, index: int) -> None:
        key = str(self.mode_combos[kind].itemData(index) or "")
        if key == "custom" and kind == "pc":
            self.pc_custom_mode()
            return
        if key == "custom":
            self._custom_mode = True
            if hasattr(self, "manual_mode"):
                motion.reveal(self.manual_mode, True)
            self._fit_inspector()
            return
        self._custom_mode = False
        if hasattr(self, "manual_mode"):
            motion.reveal(self.manual_mode, False)
        width, height, fps, fmt = key.split("|")
        data = self.payload()
        prefix = mode_prefix(kind)  # v0.12.5: PC mode lives in pc_width/...; board keeps width/...
        data.update({prefix + "width": width, prefix + "height": height, prefix + "fps": fps, prefix + "format": fmt})
        STUDIO.update_settings(data)
        if kind == "pc":
            self._fit_inspector()
            return
        for name, value in (("width", width), ("height", height), ("fps", fps)):
            widget = self.fields.get(name)
            if isinstance(widget, QLineEdit):
                widget.setText(value)
        self._fit_inspector()

    def _sync_modes(self, kind: str, modes: list[dict[str, Any]], settings: dict[str, Any], note: str) -> None:
        combo = self.mode_combos.get(kind)
        if combo is None or combo.view().isVisible():
            return
        detected = bool(modes)
        listing = sort_modes(modes) if detected else sort_modes(PRESETS)
        items = [mode_key(mode) for mode in listing]
        allow_custom = True  # v7: PC gets a custom mode too (entered through a small dialog)
        if items != self._mode_items[kind]:
            self._mode_items[kind] = items
            combo.blockSignals(True)
            combo.clear()
            for mode in listing:
                combo.addItem(mode_label(mode), mode_key(mode))
            if allow_custom:
                combo.addItem(tr("自定义…"), "custom")
            combo.blockSignals(False)
        caption = (tr("模式") + " · " + (tr_msg(f"已检测到 {len(listing)} 种模式") if detected else tr("常用预设")))
        if self.mode_captions[kind].text() != caption:
            self.mode_captions[kind].setText(caption)
        combo.setToolTip(tr_msg(note) if note else "")
        current = saved_mode(settings, kind)
        key = mode_key(current) if current else ""
        if (kind == "board" and self._custom_mode) or key not in items:
            index = combo.findData("custom")
            if kind == "board" and hasattr(self, "manual_mode"):
                motion.reveal(self.manual_mode, True)
            if kind == "pc" and current:
                combo.setItemText(index, tr("自定义") + f" · {mode_label(current)}")
        else:
            index = combo.findData(key)
            if kind == "board" and hasattr(self, "manual_mode"):
                motion.reveal(self.manual_mode, False)
            if kind == "pc" and index >= 0:
                combo.setItemText(combo.findData("custom"), tr("自定义…"))
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)

    # ---- v6: data card (real paths, disk space, recent sessions) -----------------------
    def _data_card(self) -> QFrame:
        card, layout = self._card("数据")
        path = ElideLabel("", "meta")
        free = _label("", "meta")
        layout.addWidget(path)
        disk = QProgressBar()
        disk.setObjectName("meter")
        disk.setRange(0, 100)
        disk.setTextVisible(False)
        layout.addWidget(disk)
        layout.addWidget(free)
        layout.addLayout(self._buttons(
            self._action("打开文件夹", self.open_output),
            self._action("列出本机会话", lambda: self._list_sessions("local")),
        ))
        recent = QListWidget()
        recent.setObjectName("activity")
        recent.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        recent.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        recent.setMinimumHeight(28)
        recent.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(recent, 1)
        empty = _label("暂无会话", "empty")
        empty.hide()  # the empty state is shown inside the list so the card never spreads out
        if not hasattr(self, "data_cards"):
            self.data_cards: list[dict[str, Any]] = []
        self.data_cards.append({"path": path, "free": free, "recent": recent, "empty": empty, "rows": None, "disk": disk})
        return card

    def _output_path(self) -> Path:
        with STUDIO.lock:
            return STUDIO._output()

    def open_output(self) -> None:
        path = self._output_path()
        if not path.is_dir():
            with STUDIO.lock:
                STUDIO._log("数据目录尚不存在")
            return
        os.startfile(str(path))  # Windows only, like the rest of this window

    def _sync_data_cards(self, state: dict[str, Any]) -> None:
        if not getattr(self, "data_cards", None):
            return
        now = time.monotonic()
        if now - self._disk_checked >= 2.0:
            self._disk_checked = now
            path = self._output_path()
            probe = path
            while not probe.exists() and probe.parent != probe:
                probe = probe.parent
            used = None
            try:
                usage = shutil.disk_usage(probe)
                gigabytes = usage.free / 1024 ** 3
                total = usage.total / 1024 ** 3
                used = 100 * (1 - usage.free / usage.total) if usage.total else None
                free = (f"{gigabytes:.1f} GB free of {total:.0f} GB" if i18n.LANG == "en"
                        else f"剩余 {gigabytes:.1f} GB / 共 {total:.0f} GB")
            except (OSError, ZeroDivisionError):
                free = ""
            for card in self.data_cards:
                card["path"].set_full(str(path))
                card["free"].setText(free)
                card["disk"].setVisible(used is not None)
                if used is not None:
                    card["disk"].setValue(int(used))
        if state.get("sessions"):
            rows = [f"{item.get('session_id') or ''}  {tr_msg(str(item.get('status') or ''))}".rstrip()
                    for item in (state.get("sessions") or [])[:6]]
        else:
            rows = [session_row(item) for item in self._size_history()[:6]]  # v9: real local sessions
        for card in self.data_cards:
            if card["rows"] != rows:
                card["rows"] = rows
                card["recent"].clear()
                if rows:
                    card["recent"].addItems(rows)
                else:
                    placeholder = QListWidgetItem(tr("还没有本机会话，采集后会列在这里"))
                    placeholder.setForeground(QColor("#AEAEB2"))
                    placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                    card["recent"].addItem(placeholder)

    def _lab_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("side")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Connection: status already lives in the overview tiles, so this is just the two actions.
        link, link_layout = self._card()
        self.board_label = _label("未连接", "fact")  # kept for refresh(); shown in the tiles instead
        self.board_label.hide()
        self.camera_label = _label("未发现摄像头", "note")
        self.camera_label.hide()
        link_layout.addLayout(self._buttons(
            self._action("连接", self.open_connect),
            self._action("识别并预览", self.identify, True),
        ))
        layout.addWidget(link)

        segment, stack = self._tabs(["画面", "曝光", "图像"])
        layout.addWidget(segment)

        picture, picture_layout = self._card()
        self.board_device = _combo([])
        picture_layout.addWidget(_label("摄像头"))
        picture_layout.addWidget(self.board_device)
        width = self._field("width", _edit("640"))
        height = self._field("height", _edit("480"))
        fps = self._field("fps", _edit("30"))
        picture_layout.addWidget(self._mode_row("board"))
        self.manual_mode = QWidget()
        self.manual_mode.setObjectName("side")
        manual = QVBoxLayout(self.manual_mode)
        manual.setContentsMargins(0, 0, 0, 0)
        manual.addLayout(self._trio(
            (_label("宽"), width), (_label("高"), height), (_label("帧率"), fps),
            (_label("格式"), self._field("format", _combo(["mjpeg", "raw"])))))
        self.manual_mode.setVisible(False)
        picture_layout.addWidget(self.manual_mode)
        picture_layout.addLayout(self._buttons(self._action("应用并预览", self.apply_live, True, needs="board")))
        self.lab_tips = KeyTips()  # v10: keyboard cheat-sheet fills the tab's spare height, collapses when tight
        picture_layout.addWidget(self.lab_tips, 1)
        stack.addWidget(picture)

        expose, expose_layout = self._card()
        presets_box = QFrame()
        presets_box.setObjectName("segment")
        presets = QHBoxLayout(presets_box)
        presets.setContentsMargins(3, 3, 3, 3)
        presets.setSpacing(2)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for name in ("看清画面", "看流畅", "自己设置"):
            button = QPushButton(tr_opt(name))
            button.setObjectName("preset")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=name: self._set_preset(value))
            group.addButton(button)
            self.presets[name] = button
            self.actions.append(button)
            presets.addWidget(button)
        expose_layout.addWidget(presets_box)
        self.preset_note = _label("", "note")
        expose_layout.addWidget(self.preset_note)
        self.exposure_custom = QWidget()
        self.exposure_custom.setObjectName("side")
        custom = QHBoxLayout(self.exposure_custom)
        custom.setContentsMargins(0, 0, 0, 0)
        custom.setSpacing(10)
        mode = QVBoxLayout()
        mode.setSpacing(6)
        mode.addWidget(_label("曝光"))
        mode.addWidget(self._field("exposure_mode", _combo(["自动", "手动", "快门优先"])))
        number = QVBoxLayout()
        number.setSpacing(6)
        number.addWidget(_label("数字"))
        number.addWidget(self._field("exposure_absolute", _edit()))
        custom.addLayout(mode, 1)
        custom.addLayout(number, 1)
        expose_layout.addWidget(self.exposure_custom)
        expose_layout.addLayout(self._trio(
            (_label("灯光"), self._field("power", _combo(["不改", "关闭", "50 Hz", "60 Hz"]))),
            (_label("白平衡"), self._field("wb", _combo(["不改", "自动", "手动"]))),
            (_label("对焦"), self._field("focus", _combo(["不改", "自动", "手动"]))),
        ))
        expose_layout.addLayout(self._buttons(self._action("室内日光灯", self.fluorescent)))
        expose_layout.addStretch(1)
        stack.addWidget(expose)

        image, image_layout = self._card()
        ints = [item for item in TUNING if item.kind == "int"]
        for index in range(0, len(ints), 3):
            image_layout.addLayout(self._trio(*[
                (_label(item.label), self._field(item.name, _edit())) for item in ints[index:index + 3]
            ] + [(QLabel(), QWidget()) for _ in range(3 - len(ints[index:index + 3]))]))
        image_layout.addLayout(self._buttons(
            self._action("读取参数", lambda: STUDIO.read_controls(), needs="board"),
            self._action("填入当前", self.fill_current, needs="controls"),
            self._action("清空", self.clear_tuning),
        ))
        image_layout.addStretch(1)
        stack.addWidget(image)
        layout.addWidget(stack, 1)  # the active tab card reaches the footer: no grey gap

        self._set_footer("lab",
            self._action("录 60 秒", lambda: self.start_capture("lab"), True, needs="board_idle"),
            self._action("停止并取回", lambda: STUDIO.stop_record(), needs="recording"))
        return page

    def _pc_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("side")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        card, layout = self._card("电脑采集")
        self.pc_device = self._field("pc_device", _combo([]))
        layout.addWidget(_label("摄像头"))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.pc_device, 1)
        row.addWidget(self._action("刷新", STUDIO.scan_pc))
        layout.addLayout(row)
        self.pc_pick_label = Pill("", "info")  # v9: why this camera was chosen; pick another to override
        self.pc_pick_label.hide()
        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(0, 0, 0, 0)
        pick_row.addWidget(self.pc_pick_label)
        pick_row.addStretch(1)
        layout.addLayout(pick_row)
        layout.addWidget(self._mode_row("pc"))
        layout.addWidget(_label("编码"))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._field("codec", _combo(["ffv1", "copy", "mjpeg"])), 1)
        row.addWidget(self._action("预览一帧", lambda: STUDIO.snap(self.payload(), "pc"), needs="pc_cam"))
        layout.addLayout(row)
        outer.addWidget(card)
        outer.addWidget(self._data_card(), 1)
        self._set_footer("pc",
            self._action("开始采集", lambda: self.start_capture("pc"), True, needs="pc_cam"),
            self._action("停止并校验", lambda: STUDIO.stop_record(), needs="recording"))
        return page

    def _board_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("side")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        card, layout = self._board_info_card()  # one card: model, link, info, live status, actions
        self.board_live_buttons = (self._live_button(self._action("实时", self.toggle_live, needs="board")),
                                   self._action("预览", lambda: STUDIO.snap(self.payload(), "board"), needs="board"))
        layout.addLayout(self._buttons(*self.board_live_buttons))
        outer.addWidget(card)
        outer.addWidget(self._data_card(), 1)
        self._set_footer("board",
            self._action("开始采集", lambda: self.start_capture("board"), True, needs="board_idle"),
            self._action("停止并取回", lambda: STUDIO.stop_record(), needs="recording"))
        return page

    # ---- generic board info + live status (any SSH Linux board) -------------------
    INFO_ROWS = (("系统", "os"), ("内核", "kernel"), ("处理器", "cpu"), ("内存", "mem"),
                 ("存储", "disk"), ("网络", "net"), ("运行", "uptime"), ("FPGA", "fpga"))
    STATUS_ROWS = (("CPU", "cpu"), ("内存", "mem"), ("温度", "temp"), ("磁盘", "disk"),
                   ("GPU", "gpu"), ("NPU", "npu"), ("网速", "net"))

    def _board_info_card(self) -> tuple[QFrame, QVBoxLayout]:
        card, layout = self._card()
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_label("开发板", "cardTitle"))
        self.board_model = ElideLabel("", "fact")
        head.addWidget(self.board_model, 1)
        layout.addLayout(head)
        self.board_label_2 = ElideLabel(tr("未连接"), "meta")  # camera on the board (shown inside board_link)
        self.board_label_2.hide()
        self.board_link = ElideLabel("", "meta")  # host / user / device from the saved connection
        layout.addWidget(self.board_link)
        self.board_info_empty = _label("连接后显示型号、系统和实时资源", "empty")
        layout.addWidget(self.board_info_empty)
        layout.addWidget(self._board_quick())
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        self.info_cells: dict[str, tuple[QLabel, ElideLabel]] = {}
        for index, (title, key) in enumerate(self.INFO_ROWS):
            name, value = _label(title, "meta"), ElideLabel("", "field")
            row, col = divmod(index, 2)
            grid.addWidget(name, row, col * 2)
            grid.addWidget(value, row, col * 2 + 1)
            self.info_cells[key] = (name, value)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        meters = QGridLayout()
        meters.setHorizontalSpacing(16)
        meters.setVerticalSpacing(0)
        self.status_cells: dict[str, tuple[QWidget, QProgressBar, QLabel]] = {}
        for index, (title, key) in enumerate(self.STATUS_ROWS):
            cell = QWidget()
            box = QVBoxLayout(cell)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(1)
            top = QHBoxLayout()
            top.setSpacing(6)
            top.addWidget(_label(title, "meta"))
            top.addStretch(1)
            value = QLabel("")
            value.setObjectName("field")
            top.addWidget(value)
            box.addLayout(top)
            bar = QProgressBar()
            bar.setObjectName("meter")
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setMinimumWidth(24)
            box.addWidget(bar)
            row, col = divmod(index, 2)
            meters.addWidget(cell, row, col)
            self.status_cells[key] = (cell, bar, value)
        meters.setColumnStretch(0, 1)
        meters.setColumnStretch(1, 1)
        layout.addLayout(meters)
        self.status_wait = _label("等待实时状态…", "empty")
        layout.addWidget(self.status_wait)
        return card, layout

    def _board_quick(self) -> QFrame:
        """v9: shown while disconnected — saved connection, one-click connect/scan, and this PC's real devices."""
        box = QFrame()
        box.setObjectName("subtle")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_label("快速连接", "subTitle"))
        self.quick_saved = ElideLabel("", "meta")
        head.addWidget(self.quick_saved, 1)
        layout.addLayout(head)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.quick_connect = self._action("连接", self._quick_connect, True)
        buttons.addWidget(self.quick_connect, 1)
        buttons.addWidget(self._action("扫描局域网", self._quick_scan), 1)
        layout.addLayout(buttons)
        counts = QGridLayout()
        counts.setHorizontalSpacing(6)
        counts.setVerticalSpacing(0)
        self.quick_counts: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate((("camera", "摄像头"), ("serial", "串口"), ("usb", "USB 设备"), ("net", "网卡"))):
            value = _label("—", "fact")
            counts.addWidget(value, 0, index)
            counts.addWidget(_label(caption, "meta"), 1, index)
            counts.setColumnStretch(index, 1)
            self.quick_counts[key] = value
        layout.addLayout(counts)
        tail = QHBoxLayout()
        tail.setSpacing(6)
        self.quick_devices = ElideLabel("", "meta")
        self.quick_devices.setMinimumWidth(40)
        tail.addWidget(self.quick_devices, 1)
        more = QPushButton(tr("查看全部外设"))
        more.setObjectName("link")
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.clicked.connect(self._show_pc_peripherals)
        tail.addWidget(more)
        layout.addLayout(tail)
        self.board_quick = box
        return box

    def _quick_connect(self) -> None:
        if STUDIO.state()["settings"].get("host"):
            self._auto_now()
        else:
            self.open_wizard()

    def _quick_scan(self) -> None:
        self.open_wizard()
        wizard = getattr(self, "wizard", None)
        if wizard is not None and wizard.isVisible():
            wizard.start_scan()

    def _show_pc_peripherals(self) -> None:
        self.show_page("periph")
        if getattr(self, "periph_source", None) is not None:
            self.periph_source.setCurrentIndex(max(0, self.periph_source.findData("pc")))

    def _sync_pick(self, state: dict[str, Any]) -> None:
        from .camera_pick import REASONS
        label = getattr(self, "pc_pick_label", None)
        if label is None:
            return
        reason = str(state.get("pc_pick") or "")
        label.setVisible(bool(reason))
        if not reason:
            return
        text = tr(REASONS.get(reason, reason))
        label.set_state({"need_manual": "warn", "none": "neutral", "manual": "neutral"}.get(reason, "info"), text)

    def _sync_board_quick(self, state: dict[str, Any]) -> None:
        if not hasattr(self, "board_quick"):
            return
        connected = bool(state.get("connected"))
        self.board_quick.setVisible(not connected)
        self.board_link.setVisible(connected)
        self.board_info_empty.setVisible(False if not connected else self.board_info_empty.isVisible())
        for button in getattr(self, "board_live_buttons", ()):
            button.setVisible(connected)
        if connected:
            return
        settings = state.get("settings") or {}
        host = str(settings.get("host") or "")
        self.quick_saved.set_full((tr("已保存") + f" · {settings.get('user') or 'ubuntu'}@{host}") if host else tr("尚未保存开发板地址"))
        self.quick_connect.setText(_button_text("连接" if host else "连接向导"))
        items = list(state.get("pc_peripherals") or [])
        cameras = [r for r in (state.get("pc_devices") or []) if r]
        counts = {"camera": len(cameras) or sum(1 for i in items if i.get("category") == "video"),
                  "serial": sum(1 for i in items if i.get("category") == "serial"),
                  "usb": sum(1 for i in items if i.get("category") == "usb"),
                  "net": sum(1 for i in items if i.get("category") == "net")}
        scanned = bool(items) or bool(cameras)
        for key, label in self.quick_counts.items():
            text = str(counts[key]) if scanned else "—"
            if label.text() != text:
                label.setText(text)
        names = [str(r.get("label") if isinstance(r, dict) else r) for r in cameras][:2]
        names += [str(i.get("name") or "") for i in items if i.get("category") == "serial"][:2]
        if state.get("pc_periph_busy"):
            text = tr("正在扫描本机外设…")
        elif names:
            text = " · ".join(n for n in names if n)
        elif scanned:
            text = tr("未发现摄像头或串口")
        else:
            text = tr("点“查看全部外设”扫描这台电脑")
        self.quick_devices.set_full(text)

    def _sync_board_info(self, connected: bool, info: dict[str, Any], status: dict[str, Any]) -> None:
        info = info if connected else {}
        status = status if connected else {}
        self.board_model.set_full(str(info.get("model") or ""))
        self.board_info_empty.setVisible(not info)
        mem = _size(info.get("mem_total"))
        disk = (f"{_size(info.get('disk_free'))} / {_size(info.get('disk_total'))} " + tr("可用")) if info.get("disk_total") else ""
        fpga = ""
        if "fpga" in (info.get("capabilities") or []):
            fpga = " · ".join(str(part) for part in (info.get("fpga_state"), info.get("fpga_app")) if part)
        uptime = info.get("uptime_s")
        values = {
            "os": " · ".join(str(x) for x in (info.get("os"), info.get("l4t")) if x),
            "kernel": " · ".join(str(x) for x in (info.get("kernel"), info.get("arch")) if x),
            "cpu": " · ".join(x for x in (str(info.get("cpu") or ""),
                              (f"{info['cores']} " + tr("核")) if info.get("cores") else "") if x),
            "mem": mem,
            "disk": disk,
            "net": " · ".join(str(x) for x in (info.get("hostname"), info.get("ip")) if x),
            "uptime": _duration(uptime) if isinstance(uptime, int) else "",
            "fpga": fpga,
        }
        for key, (name, value) in self.info_cells.items():
            text = values.get(key, "")
            value.set_full(text)
            name.setVisible(bool(text))
            value.setVisible(bool(text))
        rows = {}
        if "cpu" in status:
            rows["cpu"] = (status["cpu"], f"{status['cpu']:.0f}%" + (f" · {status['load']}" if status.get("load") else ""))
        if status.get("mem_total"):
            rows["mem"] = (100 * status["mem_used"] / status["mem_total"], f"{status['mem_used'] / 2**30:.1f}/{status['mem_total'] / 2**30:.1f} GB")
        if "temp_max" in status:
            rows["temp"] = (min(100.0, status["temp_max"]), f"{status['temp_max']:.0f} °C")
        if status.get("disk_total"):
            rows["disk"] = (100 * status["disk_used"] / status["disk_total"], f"{100 * status['disk_used'] / status['disk_total']:.0f}%")
        if "gpu" in status:
            rows["gpu"] = (status["gpu"], f"{status['gpu']:.0f}%")
        if "npu" in status:
            rows["npu"] = (status["npu"], f"{status['npu']:.0f}%")
        if "rx_bps" in status:
            rows["net"] = (None, f"↓{_rate(status['rx_bps'])} ↑{_rate(status['tx_bps'])}")
        for key, (cell, bar, value) in self.status_cells.items():
            row = rows.get(key)
            cell.setVisible(row is not None)
            if row is None:
                continue
            percent, text = row
            bar.setVisible(percent is not None)
            if percent is not None:
                bar.setValue(int(max(0, min(100, percent))))
            if value.text() != text:
                value.setText(text)
        self.status_wait.setVisible(bool(info) and not rows)
        self.board_status_rows = sorted(rows)  # for tests

    def _sessions_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("side")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        card, layout = self._card("会话")
        outer.addWidget(card, 1)  # the list grows with the window instead of leaving a void
        layout.addLayout(self._buttons(
            self._action("板端", lambda: self._list_sessions("board"), needs="board"),
            self._action("本机", lambda: self._list_sessions("local")),
        ))
        self.sessions = QListWidget()
        self.sessions.setMinimumHeight(120)
        self.sessions.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sessions.currentItemChanged.connect(self._select_session)
        layout.addWidget(self.sessions, 1)
        self.gates = _label("", "fact")
        self.gates.setWordWrap(True)
        layout.addWidget(self.gates)
        self._v7_sessions_extras(layout)
        self._set_footer("sessions",
            self._action("取回", self.fetch_session, True, needs="board_session"),
            self._action("校验", self.audit_session, needs="session"))
        return page

    # ---- peripherals page (v6) -------------------------------------------------------
    PERIPH_COLORS = {"usb": "#0071E3", "video": "#AF52DE", "serial": "#FF9500", "i2c": "#34C759", "spi": "#30B0C7",
                     "net": "#5856D6", "storage": "#8E8E93", "audio": "#FF2D55", "gpio": "#A2845E",
                     "display": "#007AFF", "pci": "#FF3B30"}

    def _periph_icon(self, category: str) -> QIcon:
        cache = self.__dict__.setdefault("_periph_icons", {})
        if category not in cache:
            cache[category] = icons.tile_icon(icons.CATEGORY_ICONS.get(category, "dev.other"), 22,
                                              self.PERIPH_COLORS.get(category, "#8E8E93"))
        return cache[category]

    def _periph_page(self) -> QWidget:
        from .peripherals import CATEGORIES, CATEGORY_NAMES
        page = QWidget()
        page.setObjectName("side")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        card, layout = self._card()
        outer.addWidget(card, 1)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_label("外设", "cardTitle"))
        head.addStretch(1)
        self.periph_note = ElideLabel("", "meta")
        self._v7_periph_extras(head)
        head.addWidget(self._action("扫描 I2C", lambda: STUDIO.scan_peripherals(i2c=True), needs="board"))
        layout.addLayout(head)
        layout.addWidget(self.periph_note)  # v9: own row, never squeezed into "Connect a bo…"
        row = QHBoxLayout()
        row.setSpacing(8)
        self.periph_search = QLineEdit()
        self.periph_search.setPlaceholderText(tr("搜索名称、VID:PID、驱动…"))
        self.periph_search.setClearButtonEnabled(True)
        self.periph_search.textChanged.connect(lambda _text: self._render_periph())
        row.addWidget(self.periph_search, 1)
        self.periph_filter = QComboBox()
        self.periph_filter.addItem(tr("全部"), "")
        for category in CATEGORIES:
            self.periph_filter.addItem(self._periph_icon(category), tr(CATEGORY_NAMES[category]), category)
        self.periph_filter.setMaxVisibleItems(12)
        self.periph_filter.currentIndexChanged.connect(lambda _index: self._render_periph())
        row.addWidget(self.periph_filter)
        layout.addLayout(row)
        self.periph_list = QListWidget()
        self.periph_list.setIconSize(QSize(22, 22))
        self.periph_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.periph_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.periph_list.setMinimumHeight(90)
        self.periph_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.periph_list.currentItemChanged.connect(lambda current, _previous: self._show_periph(current))
        layout.addWidget(self.periph_list, 3)
        self.periph_title = ElideLabel("", "fact")
        layout.addWidget(self.periph_title)
        self.periph_detail = QListWidget()
        self.periph_detail.setObjectName("activity")
        self.periph_detail.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.periph_detail.setMinimumHeight(80)
        self.periph_detail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.periph_detail.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.periph_detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.periph_detail, 2)
        self._periph_items: list[dict[str, Any]] = []
        self._periph_seen: tuple[str, ...] | None = None
        self._set_footer("periph",
            self._action("刷新", lambda: STUDIO.scan_peripherals(), True, needs="board"),
            self._action("终端", self.open_terminal),
            self._action("复制", self.copy_periph),
            self._action("导出", self.export_periph))
        return page

    def _sync_periph(self, state: dict[str, Any]) -> None:
        items = self.periph_source_items(state)
        pc_side = getattr(self, "periph_source", None) is not None and self.periph_source.currentData() == "pc"
        note = str(state.get("periph_note") or "")
        if pc_side:
            note = "正在扫描外设…" if state.get("pc_periph_busy") else f"共 {len(items)} 项"
        elif state.get("periph_busy"):
            note = "正在扫描外设…"
        elif getattr(self, "periph_fallback", False):
            note = f"开发板未连接 · 显示这台电脑的 {len(items)} 项外设"
        elif not pc_side and not state.get("connected") and not items:
            note = "连接开发板后可扫描外设"
        self.periph_note.set_full(tr_msg(note))
        key = tuple(item["id"] + item["summary"] + str(len(item["props"])) for item in items)
        if key != self._periph_seen:
            self._periph_seen = key
            self._periph_items = list(items)
            self._render_periph()

    def _periph_visible(self) -> list[dict[str, Any]]:
        category = self.periph_filter.currentData() or ""
        needle = self.periph_search.text().strip().lower()
        out = []
        for item in self._periph_items:
            if category and item["category"] != category:
                continue
            if needle:
                hay = " ".join([item["name"], item["summary"], tr_msg(item["summary"])] +
                               [f"{k} {v}" for k, v in item["props"]]).lower()
                if needle not in hay:
                    continue
            out.append(item)
        return out

    def _render_periph(self) -> None:
        current = self.periph_list.currentItem()
        keep = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        self.periph_list.blockSignals(True)
        self.periph_list.clear()
        visible = self._periph_visible()
        for item in visible:
            row = QListWidgetItem(self._periph_icon(item["category"]), f"{item['name']}\n{tr_msg(item['summary'])}")
            row.setData(Qt.ItemDataRole.UserRole, item["id"])
            row.setToolTip(f"{item['name']}\n{tr_msg(item['summary'])}")
            self.periph_list.addItem(row)
        if not visible:
            empty = QListWidgetItem(tr("没有匹配的外设") if self._periph_items else tr("暂无外设信息"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.periph_list.addItem(empty)
        self.periph_list.blockSignals(False)
        target = 0
        for index in range(self.periph_list.count()):
            if self.periph_list.item(index).data(Qt.ItemDataRole.UserRole) == keep:
                target = index
        if visible:
            self.periph_list.setCurrentRow(target)
        self._show_periph(self.periph_list.currentItem() if visible else None)

    def _periph_by_id(self, ident: Any) -> dict[str, Any] | None:
        return next((item for item in self._periph_items if item["id"] == ident), None)

    def _show_periph(self, row: Any) -> None:
        item = self._periph_by_id(row.data(Qt.ItemDataRole.UserRole)) if row is not None else None
        self.periph_detail.clear()
        self.periph_title.set_full(item["name"] if item else "")
        if item is None:
            return
        for key, value in item["props"]:
            line = QListWidgetItem(f"{tr_msg(key)}:  {tr_msg(self.periph_detail_value(item, key, value))}")
            line.setToolTip(tr_msg(value))
            self.periph_detail.addItem(line)

    def _periph_text(self) -> str:
        from .peripherals import as_text
        return as_text(self._periph_visible(), tr_msg)

    def copy_periph(self) -> None:
        QApplication.clipboard().setText(self._periph_text())
        with STUDIO.lock:
            STUDIO._log("已复制外设清单")

    def export_periph(self) -> None:
        try:
            self.export_inventory()  # v7: board + PC peripherals + board info (JSON and text)
        except OSError as exc:
            with STUDIO.lock:
                STUDIO._log(str(exc))

    def _settings_page(self) -> QWidget:
        page, layout = self._page()
        layout.addWidget(_label("设置", "cardTitle"))
        output = self._field("output", _edit("captures"))
        choose = self._action("选择", self._choose_output)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(output, 1)
        row.addWidget(choose)
        head = QHBoxLayout()
        head.addWidget(_label("数据目录"))
        head.addStretch(1)
        self._motion_slot = head
        layout.addLayout(head)
        layout.addLayout(row)
        layout.addLayout(self._pair(
            self._stack_field("采集人", "operator"),
            self._stack_field("场景备注", "notes"),
        ))
        layout.addLayout(self._pair(
            self._stack_field("FFmpeg", "ffmpeg"),
            self._stack_field("FFprobe", "ffprobe"),
        ))
        layout.addLayout(self._trio(
            (_label("镜头"), self._field("lens", _edit())),
            (_label("光照"), self._field("lighting", _edit())),
            (_label("距离"), self._field("distance", _edit())),
        ))
        self.reduced_motion = QCheckBox(tr("减少动态效果"))
        self.reduced_motion.setToolTip(tr("关闭页面淡入、状态渐变和折叠动画（Windows 关闭动画时自动生效）"))
        self.reduced_motion.setChecked(bool(STUDIO.settings.get("reduced_motion")) or motion.system_reduced())
        self.reduced_motion.toggled.connect(self._set_reduced_motion)
        self.reduced_motion.setObjectName("smallCheck")
        self.reduced_motion.setMaximumHeight(18)
        self._motion_slot.addWidget(self.reduced_motion)  # same row as the folder label: no extra height
        # v12: update check (GitHub Releases, read-only; never replaces files)
        self.update_auto = QCheckBox(tr("启动时检查更新"))
        self.update_auto.setToolTip(tr("每天最多一次，在后台进行，不影响使用"))
        self.update_auto.setObjectName("smallCheck")
        self.update_auto.setMaximumHeight(18)
        self.update_auto.setChecked(str(STUDIO.settings.get("update_check", "1")) not in ("", "0", "False", "false"))
        self.update_auto.toggled.connect(lambda on: STUDIO.update_settings({"update_check": "1" if on else "0"}))
        self.update_pill = Pill(f"v{__version__}", "neutral")
        update_row = QHBoxLayout()
        update_row.setContentsMargins(0, 0, 0, 0)
        update_row.addWidget(self.update_auto)
        update_row.addStretch(1)
        self._motion_slot.addSpacing(8)
        self._motion_slot.addWidget(self.update_pill)  # status pill shares the folder row; the toggle row stays 18 px
        # v0.12.5: the SSH key note shares the update row, unwrapped. A word-wrapped label gave the page
        # height-for-width, so the side scroll area sized it at its preferred height (scrollbar at 1280x800).
        key_note = _label("SSH 密钥：id_ed25519_kv260", "tips")
        key_note.setToolTip(tr("界面显示「Capture Studio SSH 密钥」；磁盘文件名仍为 id_ed25519_kv260（兼容旧版）。"))
        update_row.addWidget(key_note)
        layout.addLayout(update_row)
        layout.setSpacing(max(6, layout.spacing() - 2))  # v12: make room for the update toggle without a scrollbar
        self._update_bridge = _UpdateBridge()
        self._update_bridge.done.connect(self._update_finished)
        self._update_result: dict[str, Any] = {}
        self._page_outer.insertWidget(1, self._data_card(), 1)
        self._page_outer.takeAt(2)  # drop the trailing stretch so the data card fills the column
        self._set_footer("settings",
            self._action("保存", self.save_settings, True),
            self._action("检查工具", self.check_tools),
            self._action("检查更新", lambda: self.check_updates(False)))
        return page

    # ------------------------------------------------------------------ v12 update check
    def check_updates(self, quiet: bool = False) -> None:
        if getattr(self, "_update_running", False):
            return
        self._update_running = True
        self._update_quiet = quiet
        self.update_pill.set_state("info", tr("正在检查更新…"))
        fetch = getattr(self, "_update_fetch", None)

        def work() -> None:
            try:
                result = updates.check(__version__, fetch) if fetch else updates.check(__version__)
            except Exception:  # never let a background check break the window
                result = {"state": "error", "message": "无法读取更新信息"}
            self._update_bridge.done.emit(result)

        threading.Thread(target=work, daemon=True).start()

    def _update_finished(self, result: dict) -> None:
        self._update_running = False
        self._update_result = result
        state = result.get("state")
        if state == "newer":
            self.update_pill.set_state("warn", tr_msg(f"有新版本 v{result['version']}"))
        elif state == "latest":
            self.update_pill.set_state("ok", tr_msg(f"已是最新 v{__version__}"))
        else:
            self.update_pill.set_state("error", tr("检查更新失败"))
            self.update_pill.setToolTip(tr_msg(result.get("message", "")))
        if state in ("newer", "latest"):
            STUDIO.update_settings({"update_checked_at": str(int(result.get("checked_at") or time.time()))})
        if getattr(self, "_update_quiet", False):
            if state == "newer":
                self.toast(tr_msg(f"有新版本 v{result['version']}，可在设置页下载"))
            return
        if state == "newer":
            UpdateDialog(self, result).exec()
        else:
            self.toast(tr_msg(f"已是最新 v{__version__}") if state == "latest" else tr_msg(result.get("message", "")))

    def _stack_field(self, caption: str, key: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(_label(caption))
        layout.addWidget(self._field(key, _edit()))
        return box

    def _trio(self, *columns: tuple[QLabel, QWidget]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        for caption, widget in columns:
            column = QVBoxLayout()
            column.setSpacing(6)
            column.addWidget(caption)
            column.addWidget(widget)
            row.addLayout(column, 1)
        return row

    def _buttons(self, *widgets: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(10)
        for widget in widgets:
            row.addWidget(widget)
        return row

    def show_page(self, name: str) -> None:
        titles = {
            "lab": "摄像头测试", "pc": "电脑采集", "board": "开发板采集",
            "sessions": "会话", "settings": "设置", "periph": "外设",
        }
        order = {"lab": 0, "pc": 1, "board": 2, "sessions": 3, "settings": 4, "periph": 5}
        changed = self.stack.currentIndex() != order[name]
        previous = getattr(self, "current_page", "")
        if changed and "pc" in (name, previous) and previous != name:
            # PC and board share one viewport: stop the board stream on the PC page and never
            # carry one source's last frame over to the other page.
            if name == "pc" and STUDIO.live:
                STUDIO.stop_live()
            STUDIO.clear_preview()
        self.stack.setCurrentIndex(order[name])
        if changed and self.isVisible():
            motion.fade_in(self.stack.currentWidget())  # v11: 180 ms fade; instant with reduced motion
        self.page_buttons[name].setChecked(True)
        self.current_page = name
        self.heading.setText(tr(titles[name]))
        self.duration_bar.setVisible(name in {"lab", "pc", "board"})
        self.footer_stack.setCurrentIndex(order[name])
        self._fit_inspector()
        # Paint source-specific cards/actions now; the periodic tick is not a navigation hook.
        self.refresh(STUDIO.state())

    def _set_reduced_motion(self, value: bool) -> None:
        motion.set_reduced(True if value else None)
        STUDIO.update_settings({"reduced_motion": bool(value)})

    def toast(self, text: str) -> None:
        if getattr(self, "_toast", None) is None:
            self._toast = Toast(self)
        self._toast.show_message(text)

    def payload(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QComboBox):
                data[key] = _combo_value(widget)
            elif isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()
        device = _combo_value(self.board_device).strip()
        if device:
            data["device"] = device
        return data

    def _set_widget(self, widget: QWidget, value: Any) -> None:
        if widget is QApplication.focusWidget():
            return
        text = "" if value is None else str(value)
        if isinstance(widget, QComboBox):
            index = widget.findData(text)
            if index < 0:
                index = widget.findText(text)
            if index >= 0 and widget.currentIndex() != index:
                widget.setCurrentIndex(index)
        elif isinstance(widget, QLineEdit) and widget.text() != text:
            widget.setText(text)

    def _sync_list(self, combo: QComboBox, values: list[Any], current: str) -> None:
        rows: list[tuple[str, str | None]] = []
        for item in values:
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("value") or "")
                value = str(item.get("value") or label)
                if label:
                    rows.append((label, value))
            elif item:
                rows.append((str(item), None))
        existing = [(combo.itemText(index), combo.itemData(index)) for index in range(combo.count())]
        if existing != rows:
            combo.blockSignals(True)
            combo.clear()
            for label, value in rows:
                if value is None:
                    combo.addItem(label)
                else:
                    combo.addItem(label, value)
            combo.blockSignals(False)
        if combo is QApplication.focusWidget():
            return
        if current:
            index = combo.findData(str(current))
            if index < 0:
                index = combo.findText(str(current))
            if index >= 0 and combo.currentIndex() != index:
                combo.setCurrentIndex(index)

    def refresh(self, state: dict[str, Any]) -> None:
        settings = state.get("settings") or {}
        for key, widget in self.fields.items():
            if key in settings:
                self._set_widget(widget, settings.get(key))
        preset = str(settings.get("preset") or "")
        for name, button in self.presets.items():
            button.setChecked(name == preset)
        notes = {"看清画面": "更亮", "看流畅": "室内会变暗"}
        self.preset_note.setText(tr(notes.get(preset, "")))
        motion.reveal(self.exposure_custom, preset == "自己设置")
        self.status.setText(tr_msg(str(state.get("status") or "就绪")))
        connected = bool(state.get("connected"))
        self.chip.set_state("ok" if connected else "neutral",
                            tr_msg(str(state.get("board_label") or "未连接")) if connected else tr("未连接"))
        self.board_label.setText(tr_msg(str(state.get("board_label") or "未连接")))
        self.camera_label.setText(tr_msg(str(state.get("camera_label") or "未发现摄像头")))
        self.board_label_2.set_full(
            tr_msg(str(state.get("camera_label") or "未发现摄像头")) if connected else tr("未连接"))
        recording = state.get("recording") or {}
        if recording.get("session_id"):
            extra = ""
            if recording.get("remaining") is not None:
                extra = f" · {recording['remaining']} " + ("s" if i18n.LANG == "en" else "秒")
            self.live_label.setText(f"{recording['session_id']}{extra}")
        elif getattr(self, "_play_timer", None) is not None and self._play_timer.isActive():
            pass  # v9: playback owns the counter; refresh no longer wipes it
        elif state.get("live") and self.current_page != "pc":
            self.live_label.setText(tr("实时"))
        else:
            self.live_label.setText("")
        self._sync_list(self.board_device, state.get("devices") or [],
                        str(state.get("device") or settings.get("device") or ""))
        pc = self.fields["pc_device"]
        if isinstance(pc, QComboBox):
            self._sync_list(pc, state.get("pc_devices") or [], str(settings.get("pc_device") or ""))
        self._sync_sessions(state.get("sessions") or [])
        self.gates.setText(tr_msg(str(state.get("gates") or "")))
        result_gates = (state.get('last_session') or {}).get('gates') or {}
        self.gates.setToolTip('\n'.join(f"{key}: {gate.get('detail', '')}" for key, gate in
                                      result_gates.items() if isinstance(gate, dict)))
        view = mode_view(settings, "pc" if self.current_page == "pc" else "board")
        width = view.get("width") or 640
        height = view.get("height") or 480
        fps = view.get("fps") or 30
        self.viewport.set_caption(f"{width} × {height} · {fps} fps")
        logs = state.get("logs") or []
        self._sync_activity([tr_msg(str(item)) for item in logs[-3:]][::-1])
        busy = bool(state.get("busy"))
        live = bool(state.get("live"))
        active = bool(recording.get("session_id"))
        completing = bool(state.get('completion'))
        available = not active and not completing and not state.get('start_uncertain')
        pc_view = self.current_page == "pc"
        pc_values = [str(item.get("value") if isinstance(item, dict) else item)
                     for item in (state.get("pc_devices") or [])]
        pc_device = str(settings.get("pc_device") or "")
        pc_cam = bool(pc_device) and pc_device in pc_values
        allowed = {
            "": True,
            "board": connected,
            "board_idle": connected and available,
            "idle": available,
            "pc_cam": available and pc_cam,
            "recording": active or completing,
            "controls": bool(state.get("controls")),
            "session": bool(self.session_id),
            "board_session": connected and bool(self.session_id),
        }
        for widget in self.actions:
            need = str(widget.property("needs") or "")
            enabled = not busy and allowed.get(need, True)
            if widget.isEnabled() != enabled:
                widget.setEnabled(enabled)
        if self.live_button is not None:
            text = _button_text("停止实时" if live else "实时")
            if self.live_button.text() != text:
                self.live_button.setText(text)
        mode = "rec" if active else ("live" if live else "idle")
        if pc_view:  # the board stream is not shown on the PC page
            mode = "rec" if active and recording.get("mode") == "pc" else "idle"
        word = {"rec": "录制中", "live": "实时预览中", "idle": "空闲"}[mode]
        if completing:
            word = '收尾待完成'
        if active and recording.get("remaining") is not None:
            word_text = f"{tr(word)} · {recording['remaining']} " + ("s" if i18n.LANG == "en" else "秒")
        else:
            word_text = tr(word)
        self.badge.set_state(mode, word_text)  # v11: icon pill; also shows the recording countdown again
        if pc_view:
            self.tiles["board"].set_full(tr("本机"))
            self.tiles["camera"].set_full(pc_device if pc_cam else tr("未检测到摄像头"))
        else:
            self.tiles["board"].set_full(
                tr_msg(str(state.get("board_label") or "未连接")) if connected else tr("未连接"))
            self.tiles["camera"].set_full(tr_msg(str(state.get("camera_label") or "未发现摄像头")))
        self.viewport.set_empty_title("本机未检测到摄像头" if pc_view and not pc_cam else "")
        stream = f"{width} × {height} · {fps} fps · {str(view.get('format') or '').upper()}"
        self.tiles["stream"].set_full(stream)
        self.tiles["state"].set_full(word_text)
        self.stream_info.setText(stream)
        note = str(state.get("modes_note") or "")
        if hasattr(self, "mode_combos"):
            self._sync_modes("board", state.get("board_modes") or [], settings, note)
            self._sync_modes("pc", state.get("pc_modes") or [], settings, note)
        self._sync_data_cards(state)
        self._v7_refresh(state)
        self._sync_periph(state)
        self._sync_board_info(connected, state.get("board_info") or {}, state.get("board_status") or {})
        self._sync_board_quick(state)
        self._sync_pick(state)
        host = str(settings.get("host") or "")
        link = " · ".join(part for part in (
            tr_msg(str(state.get("camera_label") or "")) if connected else "",
            f"{settings.get('user') or ''}@{host}" if host else "",
            str(state.get("device") or settings.get("device") or "")) if part)
        self.board_link.set_full(link or tr("尚未保存连接"))
        self._fit_inspector()
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.load(settings)
            self.dialog.find.setEnabled(not busy)
            self.dialog.go.setEnabled(not busy)
        self._paint_frame()

    def _sync_activity(self, lines: list[str]) -> None:
        if lines == self._activity_lines:
            return
        self._activity_lines = lines
        metrics = self.activity.fontMetrics()
        width = max(60, self.activity.width())
        shown = [metrics.elidedText(line, Qt.TextElideMode.ElideRight, width) for line in lines]
        self.activity.setToolTip("\n".join(lines))
        # Empty state sits at the top of the feed (v4 nit).
        self.activity.setText("\n".join(shown) if lines else tr("暂无动态"))

    def _sync_sessions(self, rows: list[dict[str, Any]]) -> None:
        # Bug fix: compare id *and* status, otherwise a status change was never shown.
        ids = [f"{item.get('session_id') or ''}\t{item.get('status') or ''}" for item in rows]
        if ids == self._session_ids:
            return
        self._session_ids = ids
        # Bug fix: clear() fired currentItemChanged(None) and wiped the selection before it could be restored.
        keep = self.session_id
        found = False
        self.sessions.blockSignals(True)
        self.sessions.clear()
        for item in rows:
            session_id = str(item.get("session_id") or "")
            status = str(item.get("status") or "")
            entry = QListWidgetItem(f"{session_id}  {tr_msg(status)}".rstrip())
            entry.setData(Qt.ItemDataRole.UserRole, session_id)
            self.sessions.addItem(entry)
            if keep and session_id == keep:
                self.sessions.setCurrentItem(entry)
                found = True
        self.sessions.blockSignals(False)
        self.session_id = keep if found else ""

    def _paint_frame(self) -> None:
        with STUDIO.lock:
            seq, data = STUDIO.preview_seq, STUDIO.preview
        if seq == self.preview_seq:
            return
        self.preview_seq = seq
        if not data:
            self._image = QImage()
            self.viewport.set_image(QImage())
            return
        image = QImage.fromData(data)
        if image.isNull():
            return
        self._image = image
        self.viewport.set_image(image)

    def _tick(self) -> None:
        self.refresh(STUDIO.state())

    def _choose_output(self) -> None:
        current = str(self.payload().get("output") or "")
        path = QFileDialog.getExistingDirectory(self, tr("数据目录"), current)
        if path:
            widget = self.fields["output"]
            if isinstance(widget, QLineEdit):
                widget.setText(path)

    def open_connect(self) -> None:
        if self.dialog is None:
            self.dialog = ConnectDialog(self)
            self.dialog.accepted.connect(self._connect)
        self.dialog.load(STUDIO.state()["settings"])
        self.dialog.password.clear()
        self.dialog.exec()

    def _connect(self) -> None:
        if self.dialog is None:
            return
        data = self.payload()
        data.update(self.dialog.values())
        data["password"] = self.dialog.password.text()
        self.dialog.password.clear()
        STUDIO.connect(data)

    def discover(self, values: dict[str, str]) -> None:
        data = self.payload()
        data.update(values)
        STUDIO.update_settings(data)
        STUDIO.discover()

    def identify(self) -> None:
        if not STUDIO.connected:
            self.open_connect()
            return
        STUDIO.start_live(self.payload())

    def apply_live(self) -> None:
        STUDIO.start_live(self.payload())

    def toggle_live(self) -> None:
        if STUDIO.live:
            STUDIO.stop_live()
            return
        STUDIO.start_live(self.payload())

    def _set_preset(self, name: str) -> None:
        data = self.payload()
        data["preset"] = name
        STUDIO.update_settings(data)

    def fill_current(self) -> None:
        with STUDIO.lock:  # controls are replaced by a worker thread
            controls = list(STUDIO.controls or [])
        found = support_for(controls)
        data = self.payload()
        filled = 0
        for item in TUNING:
            if item.kind != "int" or str(data.get(item.name) or "").strip():
                continue
            support = found.get(item.name) or {}
            if support.get("value") is None:
                continue
            data[item.name] = str(support["value"])
            filled += 1
        if filled:
            STUDIO.update_settings(data)
        with STUDIO.lock:
            STUDIO._log(f"已填入 {filled} 项" if filled else "先读取参数")

    def clear_tuning(self) -> None:
        data = self.payload()
        for item in TUNING:
            if item.kind == "int":
                data[item.name] = ""
        data["power"] = "不改"
        data["wb"] = "不改"
        data["focus"] = "不改"
        STUDIO.update_settings(data)

    def fluorescent(self) -> None:
        data = self.payload()
        data["preset"] = "看清画面"
        data["power"] = "50 Hz"
        data["wb"] = "自动"
        STUDIO.update_settings(data)

    def record_short(self) -> None:
        data = self.payload()
        data["duration"] = "60 秒短检"
        STUDIO.start_record(data, "board")

    def fetch_session(self) -> None:
        if self.session_id:
            STUDIO.fetch_session(self.session_id)

    def audit_session(self) -> None:
        if self.session_id:
            STUDIO.audit(self.session_id)

    def save_settings(self) -> None:
        STUDIO.update_settings(self.payload())
        with STUDIO.lock:
            STUDIO._log("已保存")

    def check_tools(self) -> None:
        try:
            STUDIO._tool("ffmpeg")
            STUDIO._tool("ffprobe")
        except FileNotFoundError as exc:
            message = str(exc)
        else:
            message = "采集工具已就绪"
        with STUDIO.lock:
            STUDIO._log(message)

    def _select_session(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self.session_id = "" if current is None else str(current.data(Qt.ItemDataRole.UserRole) or "")

    def open_large(self) -> None:
        if self.large is None:
            self.large = LargeView(self)
        self.large.show()
        self.large.raise_()
        self.large.activateWindow()
        if STUDIO.connected and not STUDIO.live and not STUDIO.busy and self.current_page != "pc":
            STUDIO.start_live(self.payload())

    def closeEvent(self, event: Any) -> None:
        state = STUDIO.state()
        if state.get("busy"):
            with STUDIO.lock:
                STUDIO.status = "请等待当前操作完成"
            event.ignore()
            return
        recording = state.get("recording") or {}
        if recording.get("mode") == "pc":
            with STUDIO.lock:
                STUDIO.status = "请先停止电脑采集"
            event.ignore()
            return
        STUDIO.update_settings(self.payload())
        STUDIO.close()
        event.accept()


def main() -> None:
    if os.name != "nt":
        raise SystemExit("桌面窗口目前只在 Windows 上打开")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # no UnicodeEncodeError on GBK consoles
        except (AttributeError, ValueError):
            pass
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    font = QFont("Segoe UI Variable Text")
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"])
    font.setPointSize(10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)  # v10: tabular figures so counters / sizes don't jitter
    except Exception:
        pass
    app.setFont(font)
    app.setWindowIcon(icons.app_icon())
    if STUDIO.settings.get("reduced_motion"):
        motion.set_reduced(True)
    theme.DARK_MODE = theme.resolve(str(STUDIO.settings.get("theme") or "跟随系统"))
    app.setStyleSheet(theme.css(STYLE.replace("__CHEVRON__", _chevron_url())))
    window = StudioWindow()
    window._theme_applied = True
    window.show()
    QTimer.singleShot(300, STUDIO.scan_pc_peripherals)  # v9: local USB/serial inventory fills the disconnected pages
    QTimer.singleShot(600, STUDIO.scan_pc)  # v9: PC cameras + automatic choice
    if updates.due(STUDIO.settings):
        QTimer.singleShot(3000, lambda: window.check_updates(True))  # v12: quiet, daily, background
    settings = STUDIO.state()["settings"]
    if not settings.get("wizard_done") and not settings.get("host"):
        QTimer.singleShot(400, window.open_wizard)  # first run
    else:
        window.maybe_auto_connect()
    app.exec()


if __name__ == "__main__":
    main()
