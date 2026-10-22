"""Model demo page. The desktop only draws frames and protocol results.

Inference stays on the board. The bundled street clip is a redistributable
aerial shot plus hand-placed marks (see assets/demo_clip/ATTRIBUTION.md).
Those marks are labeled demo data. A user video or camera still gets the
scripted overlay, also labeled demo data — the pixels are not classified here.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

from . import i18n, icons, motion
from .i18n import tr
from .inference import (JsonlRecorder, board_health, class_counts, demo_overlay, load_jsonl,
                        visible_detections)
from .product import STUDIO

_CLIP = Path(__file__).resolve().parent / "assets" / "demo_clip"
_FONTS = Path(__file__).resolve().parent / "assets" / "fonts"

# One blue, one amber, one green. Class colors are the same swatches the charts use.
_CLASS_COLORS = {
    "person": "#3DDC97", "car": "#E2B15A", "bus": "#6C97E8", "truck": "#F0A36A",
    "bicycle": "#C9A6FF", "drone": "#7ED0E0", "bird": "#FF8FA3",
}
_CLASS_ZH = {
    "person": "行人", "car": "汽车", "bus": "公交", "truck": "卡车",
    "bicycle": "自行车", "drone": "无人机", "bird": "鸟",
}
_PALETTE = ("#6C97E8", "#E2B15A", "#3DDC97", "#C9A6FF", "#F0A36A", "#7ED0E0", "#FF8FA3", "#9BB0C9")
_INK = QColor("#F4F7FB")
_MUTED = QColor("#93A4BA")
_LINE = QColor(150, 186, 255, 48)
_PANEL = QColor(12, 20, 36, 236)
_BG = QColor("#070B12")

_BADGE = {
    "demo": ("演示数据", "演示标注，不是识别结果"),
    "replay": ("回放数据", "录制的结果，不是实时识别"),
    "replay_demo": ("回放数据", "演示记录，不是实时识别"),
    "board": ("板端实时", "开发板上的模型输出"),
    "unconfigured": ("模型未接入", "通道已通，板端还没有模型输出"),
    "waiting": ("等待结果", "已连接，尚未收到这一帧的结果"),
    "offline": ("未连接", "连接开发板后使用板端画面"),
}

PREFS: dict[str, Any] = {"title": "", "customer": "", "logo": "", "logo_pos": "左上",
                        "min_score": 0.25, "follow": "small"}

_CLIP_FRAMES: list[QImage] | None = None
_CLIP_ROWS: list[dict[str, Any]] | None = None
_FONTS_READY = False


def _ensure_fonts() -> None:
    """Load bundled faces only after QApplication exists. Earlier calls segfault."""
    global _FONTS_READY
    if _FONTS_READY or QApplication.instance() is None or not _FONTS.is_dir():
        return
    for path in sorted(_FONTS.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))
    _FONTS_READY = True


def class_color(name: str) -> QColor:
    if name in _CLASS_COLORS:
        return QColor(_CLASS_COLORS[name])
    return QColor(_PALETTE[sum(name.encode("utf-8")) % len(_PALETTE)])


def class_label(name: str) -> str:
    if i18n.LANG == "en":
        return name
    return _CLASS_ZH.get(name, name)


def _ui_scale(widget: QWidget) -> float:
    window = widget.window() if widget is not None else None
    height = window.height() if window is not None and window.height() > 0 else 900
    return max(0.82, min(height / 900.0, 1.35))


def _font(px: float, weight: QFont.Weight = QFont.Weight.Medium, mono: bool = False) -> QFont:
    _ensure_fonts()
    font = QFont()
    if mono:
        font.setFamilies(["JetBrains Mono", "Noto Sans Mono", "Consolas", "monospace"])
    else:
        font.setFamilies(["Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei",
                          "Microsoft YaHei UI", "PingFang SC", "Noto Sans", "Segoe UI"])
    font.setPixelSize(max(1, int(round(px))))
    font.setWeight(weight)
    if mono:
        font.setStyleHint(QFont.StyleHint.Monospace)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def badge_copy(kind: str) -> tuple[str, str]:
    title, detail = _BADGE.get(kind, _BADGE["waiting"])
    return tr(title), tr(detail)


def _load_clip() -> tuple[list[QImage], list[dict[str, Any]]]:
    global _CLIP_FRAMES, _CLIP_ROWS
    if _CLIP_FRAMES is not None and _CLIP_ROWS is not None:
        return _CLIP_FRAMES, _CLIP_ROWS
    frames: list[QImage] = []
    folder = _CLIP / "frames"
    if folder.is_dir():
        for path in sorted(folder.glob("f_*.jpg")):
            image = QImage(str(path))
            if not image.isNull():
                frames.append(image)
    rows: list[dict[str, Any]] = []
    path = _CLIP / "demo.jsonl"
    if path.is_file():
        try:
            rows = load_jsonl(path)
        except (OSError, ValueError):
            rows = []
    _CLIP_FRAMES, _CLIP_ROWS = frames, rows
    return frames, rows


def clip_frame(frame_id: int) -> tuple[QImage, dict[str, Any]] | None:
    """Picture plus the hand-placed marks for one bundled frame. Not a detector."""
    frames, rows = _load_clip()
    if not frames or not rows:
        return None
    index = int(frame_id) % len(rows)
    image = frames[index % len(frames)]
    source = rows[index]
    result = dict(source)
    result["detections"] = [dict(item) for item in source.get("detections") or []]
    result["frame_id"] = int(frame_id)
    result["width"] = image.width()
    result["height"] = image.height()
    result["preview_only"] = True
    return image, result


@lru_cache(maxsize=64)
def _glyph(name: str, color: str, size: int) -> Any:
    from PySide6.QtGui import QPixmap
    renderer = QSvgRenderer(QByteArray(icons.svg_bytes(name, color, 1.75)))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QPixmap.fromImage(image)


def _panel(painter: QPainter, rect: QRectF, radius: float = 14) -> None:
    painter.setPen(QPen(_LINE, 1))
    painter.setBrush(_PANEL)
    painter.drawRoundedRect(rect, radius, radius)
    gloss = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + 28))
    gloss.setColorAt(0.0, QColor(255, 255, 255, 16))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gloss)
    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)


def _section(painter: QPainter, x: float, y: float, width: float, icon: str, title: str,
             accent: str) -> float:
    painter.drawPixmap(int(x), int(y + 1), _glyph(icon, accent, 16))
    painter.setPen(_INK)
    painter.setFont(_font(14, QFont.Weight.DemiBold))
    painter.drawText(QRectF(x + 22, y, width * 0.46, 18),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), title)
    metrics = painter.fontMetrics()
    text_w = metrics.horizontalAdvance(title)
    painter.setPen(QPen(QColor(accent), 1))
    painter.drawLine(QPointF(x + 28 + text_w, y + 9), QPointF(x + width, y + 9))
    return y + 24


def _fit(image: QImage, bounds: QRectF, cover: bool = False) -> QRectF:
    if image.isNull() or bounds.width() <= 1 or bounds.height() <= 1:
        return QRectF()
    contain = min(bounds.width() / image.width(), bounds.height() / image.height())
    scale = max(bounds.width() / image.width(), bounds.height() / image.height()) if cover else contain
    width, height = image.width() * scale, image.height() * scale
    return QRectF(bounds.x() + (bounds.width() - width) / 2,
                  bounds.y() + (bounds.height() - height) / 2, width, height)


def _brackets(painter: QPainter, rect: QRectF, color: QColor, alpha: float) -> None:
    if rect.width() < 2 or rect.height() < 2 or alpha <= 0.02:
        return
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, alpha)))
    arm = max(8.0, min(rect.width(), rect.height()) * 0.28)
    arm = min(arm, 22.0)
    pen = QPen(color)
    pen.setWidthF(max(1.6, min(2.4, min(rect.width(), rect.height()) * 0.06)))
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()

    def corner(px: float, py: float, dx: float, dy: float) -> None:
        path.moveTo(px, py + dy * arm)
        path.lineTo(px, py)
        path.lineTo(px + dx * arm, py)

    corner(rect.left(), rect.top(), 1, 1)
    corner(rect.right(), rect.top(), -1, 1)
    corner(rect.left(), rect.bottom(), 1, -1)
    corner(rect.right(), rect.bottom(), -1, -1)
    painter.drawPath(path)
    painter.restore()


def _label(painter: QPainter, rect: QRectF, det: dict[str, Any], color: QColor, alpha: float,
           bounds: QRectF, scale: float) -> None:
    text = f"{class_label(str(det['class']))}  {float(det['score']):.2f}"
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, alpha)))
    painter.setFont(_font(13 * scale, QFont.Weight.DemiBold, mono=True))
    metrics = painter.fontMetrics()
    box_h = metrics.height() + 6
    box_w = metrics.horizontalAdvance(text) + 18
    x = rect.left()
    y = rect.top() - box_h - 3
    if y < bounds.top() + 2:
        y = rect.top() + 3
    if x + box_w > bounds.right() - 2:
        x = max(bounds.left() + 2, bounds.right() - box_w - 2)
    box = QRectF(x, y, box_w, box_h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(6, 10, 18, 200))
    painter.drawRoundedRect(box, 4, 4)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(box.left(), box.top(), 3, box.height()), 1, 1)
    painter.setPen(_INK)
    painter.drawText(box.adjusted(8, 0, -4, 0),
                     int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
    painter.restore()


def _draw_zoom(painter: QPainter, dest: QRectF, image: QImage, det: dict[str, Any] | None,
               result: dict[str, Any] | None) -> None:
    painter.save()
    clip = QPainterPath()
    clip.addRoundedRect(dest, 8, 8)
    painter.setClipPath(clip)
    painter.fillRect(dest, QColor("#0B1220"))
    if image.isNull() or det is None or not result:
        painter.setPen(_MUTED)
        painter.setFont(_font(12))
        painter.drawText(dest, int(Qt.AlignmentFlag.AlignCenter), tr("无目标"))
        painter.restore()
        painter.setPen(QPen(_LINE, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(dest.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        return
    x, y, w, h = (float(v) for v in det["bbox"])
    rw, rh = max(1, int(result["width"])), max(1, int(result["height"]))
    pad = max(w, h, 24) * 0.9
    side = max(w, h) + pad * 2
    src = QRectF((x + w / 2) - side / 2, (y + h / 2) - side / 2, side, side)
    src = src.intersected(QRectF(0, 0, rw, rh))
    if not src.isEmpty():
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(dest, image, QRectF(src.x() / rw * image.width(), src.y() / rh * image.height(),
                                              src.width() / rw * image.width(), src.height() / rh * image.height()))
        sx, sy = dest.width() / src.width(), dest.height() / src.height()
        box = QRectF(dest.x() + (x - src.x()) * sx, dest.y() + (y - src.y()) * sy, w * sx, h * sy)
        _brackets(painter, box, class_color(str(det["class"])), 1.0)
    painter.restore()
    painter.setPen(QPen(_LINE, 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(dest.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)


def _chart(painter: QPainter, rect: QRectF, samples: list[float], color: QColor) -> None:
    plot = rect.adjusted(36, 4, -4, -16)
    painter.setPen(QPen(QColor(150, 186, 255, 28), 1))
    values = samples[-48:] or [0.0, 0.0]
    low, high = min(values), max(values)
    if high - low < 1e-3:
        low, high = low - 1, high + 1
    for step in range(3):
        y = plot.top() + plot.height() * step / 2
        painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        label = high - (high - low) * step / 2
        painter.setPen(_MUTED)
        painter.setFont(_font(10, mono=True))
        painter.drawText(QRectF(rect.left(), y - 7, 34, 14),
                         int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), f"{label:.0f}")
        painter.setPen(QPen(QColor(150, 186, 255, 28), 1))
    if len(values) >= 2:
        path = QPainterPath()
        fill = QPainterPath()
        for index, value in enumerate(values):
            px = plot.left() + index / (len(values) - 1) * plot.width()
            py = plot.bottom() - (value - low) / (high - low) * plot.height()
            if index == 0:
                path.moveTo(px, py)
                fill.moveTo(px, plot.bottom())
                fill.lineTo(px, py)
            else:
                path.lineTo(px, py)
                fill.lineTo(px, py)
        fill.lineTo(plot.right(), plot.bottom())
        fill.closeSubpath()
        shade = QLinearGradient(plot.topLeft(), plot.bottomLeft())
        shade.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 70))
        shade.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawPath(fill)
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.setPen(_MUTED)
    painter.setFont(_font(10))
    painter.drawText(QRectF(plot.left(), rect.bottom() - 14, 40, 14),
                     int(Qt.AlignmentFlag.AlignLeft), tr("较早"))
    painter.drawText(QRectF(plot.right() - 36, rect.bottom() - 14, 36, 14),
                     int(Qt.AlignmentFlag.AlignRight), tr("现在"))


def _ring(painter: QPainter, center: QPointF, radius: float, fraction: float, color: QColor) -> None:
    rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    pen = QPen(QColor(150, 186, 255, 36), 5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(rect, 225 * 16, -270 * 16)
    pen.setColor(color)
    painter.setPen(pen)
    span = max(0.0, min(1.0, fraction)) * -270 * 16
    painter.drawArc(rect, 225 * 16, int(span))


def _blank(width: int, height: int) -> QImage:
    image = QImage(max(2, width), max(2, height), QImage.Format.Format_RGB32)
    image.fill(QColor("#101820"))
    return image


class _State:
    def __init__(self) -> None:
        self.image = QImage()
        self.result: dict[str, Any] | None = None
        self.title = ""
        self.customer = ""
        self.logo = QImage()
        self.logo_pos = "左上"


class VideoStage(QWidget):
    def __init__(self, page: "ModelDemoPage") -> None:
        super().__init__()
        self.page = page
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def mousePressEvent(self, event: Any) -> None:
        result = self.page.state.result
        image = self.page.state.image
        if result is None or image.isNull():
            return
        rect = _fit(image, QRectF(self.rect()).adjusted(10, 10, -10, -10), cover=True)
        if not rect.contains(event.position()):
            return
        rw, rh = max(1, int(result["width"])), max(1, int(result["height"]))
        x = (event.position().x() - rect.x()) / rect.width() * rw
        y = (event.position().y() - rect.y()) / rect.height() * rh
        self.page.pin_at_image(x, y)

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), _BG)
        bounds = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        _panel(painter, bounds, 16)
        inner = bounds.adjusted(7, 7, -7, -7)
        image = self.page.state.image
        rect = _fit(image, inner, cover=True) if not image.isNull() else QRectF()
        if rect.isEmpty():
            painter.setPen(_MUTED)
            painter.setFont(_font(16))
            painter.drawText(inner, int(Qt.AlignmentFlag.AlignCenter), tr("等待画面"))
        else:
            clip = QPainterPath()
            clip.addRoundedRect(inner, 8, 8)
            painter.setClipPath(clip)
            painter.drawImage(rect, image)
            veil = QLinearGradient(inner.topLeft(), QPointF(inner.left(), inner.top() + 56))
            veil.setColorAt(0.0, QColor(5, 8, 14, 110))
            veil.setColorAt(1.0, QColor(5, 8, 14, 0))
            painter.fillRect(inner, veil)
            self._boxes(painter, rect)
            painter.setClipping(False)
        self._badge(painter, bounds)

    def _boxes(self, painter: QPainter, rect: QRectF) -> None:
        result = self.page.state.result
        if not result:
            return
        rw, rh = max(1, int(result["width"])), max(1, int(result["height"]))
        sx, sy = rect.width() / rw, rect.height() / rh
        scale = max(0.85, min(self.height() / 640, 1.6))
        for slot in self.page.slots.values():
            det = slot["det"]
            x, y, w, h = det["bbox"]
            box = QRectF(rect.x() + x * sx, rect.y() + y * sy, w * sx, h * sy)
            color = class_color(str(det["class"]))
            _brackets(painter, box, color, slot["alpha"])
            _label(painter, box, det, color, slot["alpha"], rect, scale)

    def _badge(self, painter: QPainter, bounds: QRectF) -> None:
        title, _detail = badge_copy(self.page.kind)
        painter.setFont(_font(12, QFont.Weight.DemiBold))
        pad = 12
        width = painter.fontMetrics().horizontalAdvance(title) + pad * 2
        height = painter.fontMetrics().height() + 8
        rect = QRectF(bounds.right() - width - 14, bounds.top() + 12, width, height)
        colors = {
            "demo": ("#3A2A12", "#F0C36A"), "replay": ("#1A2744", "#A9C4FF"),
            "replay_demo": ("#1A2744", "#A9C4FF"), "board": ("#12321F", "#7DDCB0"),
            "unconfigured": ("#3A2A12", "#F0C36A"),
        }
        fill, ink = colors.get(self.page.kind, ("#1A2230", "#C5D0E0"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(rect, height / 2, height / 2)
        painter.setPen(QColor(ink))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), title)


class HeaderBar(QWidget):
    def __init__(self, page: "ModelDemoPage") -> None:
        super().__init__()
        self.page = page
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> Any:
        from PySide6.QtCore import QSize
        return QSize(640, int(round(88 * _ui_scale(self))))

    def minimumSizeHint(self) -> Any:
        return self.sizeHint()

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _BG)
        rect = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        _panel(painter, rect, 14)
        accent = QLinearGradient(rect.topLeft(), QPointF(rect.left() + 220, rect.top()))
        accent.setColorAt(0.0, QColor("#6C97E8"))
        accent.setColorAt(1.0, QColor(108, 151, 232, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRect(QRectF(rect.left() + 14, rect.top() + 1, 180, 2))
        page = self.page
        state = page.state
        left = rect.left() + 16
        logo = state.logo
        block_top = rect.top() + max(10.0, (rect.height() - 64) / 2)
        if logo is not None and not logo.isNull() and state.logo_pos in ("左上", "左下"):
            lh = 40
            lw = lh * logo.width() / max(1, logo.height())
            painter.drawImage(QRectF(left, rect.top() + (rect.height() - lh) / 2, lw, lh), logo)
            left += lw + 14
        title = state.title or tr("模型展示")
        painter.setPen(_INK)
        painter.setFont(_font(30, QFont.Weight.DemiBold))
        painter.drawText(QRectF(left, block_top, rect.width() * 0.42, 36),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), title)
        _title, detail = badge_copy(page.kind)
        subtitle = detail
        if state.customer:
            subtitle = f"{state.customer}   ·   {detail}"
        painter.setPen(QColor("#D5DEEA"))
        painter.setFont(_font(15))
        painter.drawText(QRectF(left, block_top + 36, rect.width() * 0.46, 24),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), subtitle)
        if logo is not None and not logo.isNull() and state.logo_pos in ("右上", "右下"):
            lh = 36
            lw = lh * logo.width() / max(1, logo.height())
            painter.drawImage(QRectF(rect.right() - lw - 16, rect.top() + (rect.height() - lh) / 2, lw, lh), logo)
        self._status(painter, rect)

    def _status(self, painter: QPainter, rect: QRectF) -> None:
        page = self.page
        result = page.state.result or {}
        if page.kind == "board":
            model = str(result.get("model") or "—")
            backend = str(result.get("backend") or "—")
            board = tr("在线")
        elif page.kind in ("demo", "replay_demo"):
            model = tr("演示片段")
            backend = tr("演示数据")
            board = tr("演示")
        elif page.kind == "replay":
            model = tr("回放数据")
            backend = str(result.get("backend") or "—")
            board = "—"
        elif page.kind == "unconfigured":
            model = tr("模型未接入")
            backend = str(result.get("backend") or "—")
            board = tr("在线")
        else:
            model, backend, board = "—", "—", tr("未连接")
        clock = datetime.now().strftime("%H:%M:%S")
        chips = ((tr("板卡"), board), (tr("模型"), model), (tr("后端"), backend))
        base = rect.top() + max(12.0, (rect.height() - 48) / 2)
        painter.setFont(_font(24, QFont.Weight.Medium, mono=True))
        clock_w = painter.fontMetrics().horizontalAdvance(clock) + 4
        x = rect.right() - 18 - clock_w
        painter.setPen(_INK)
        painter.drawText(QRectF(x, base - 2, clock_w, 28),
                         int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), clock)
        painter.setFont(_font(12))
        painter.setPen(_MUTED)
        painter.drawText(QRectF(x, base + 26, clock_w, 16),
                         int(Qt.AlignmentFlag.AlignRight), tr("本地时间"))
        x -= 22
        value_font = _font(16, QFont.Weight.DemiBold)
        for caption, value in reversed(chips):
            painter.setFont(value_font)
            value_w = min(180, painter.fontMetrics().horizontalAdvance(value) + 10)
            block = max(104, value_w)
            x -= block
            painter.setPen(_MUTED)
            painter.setFont(_font(12, QFont.Weight.DemiBold))
            painter.drawText(QRectF(x, base, block - 10, 16),
                             int(Qt.AlignmentFlag.AlignLeft), caption)
            painter.setPen(_INK)
            painter.setFont(value_font)
            painter.drawText(QRectF(x, base + 18, block - 10, 24),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), value)
            x -= 6


class RailCanvas(QWidget):
    def __init__(self, page: "ModelDemoPage") -> None:
        super().__init__()
        self.page = page
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inner = QRectF(self.rect()).adjusted(14, 12, -14, -12)
        counts = class_counts(self.page.visible_detections())
        rows = list(counts.items()) or [(tr("无目标"), 0)]
        bars_h = 26 + 22 * min(6, len(rows))
        room = inner.height()
        if room < 340:
            kpi_h, gallery_h = 76.0, 0.0
            trend_h = max(80.0, room - kpi_h - bars_h - 16)
        else:
            kpi_h = 116.0 if room >= 500 else 104.0
            gallery_h = 132.0 if room >= 500 else 108.0
            trend_h = room - kpi_h - bars_h - gallery_h - 20
            if trend_h > 168:
                gallery_h += trend_h - 168
                trend_h = 168
            if trend_h < 96:
                gallery_h = max(84.0, gallery_h - (96 - trend_h))
                trend_h = room - kpi_h - bars_h - gallery_h - 20
        y = self._kpis(painter, inner, kpi_h)
        y = self._trend(painter, inner, y, trend_h)
        y = self._bars(painter, inner, y, rows, counts)
        if gallery_h >= 72 and y < inner.bottom() - 48:
            self._gallery(painter, inner, y)

    def _kpis(self, painter: QPainter, inner: QRectF, height: float) -> float:
        page = self.page
        gap = 8
        width = (inner.width() - gap * 2) / 3
        cards = (
            (tr("推理帧率"), f"{page.fps_value:0.1f}", "fps", "#6C97E8", "ui.activity"),
            (tr("时延"), f"{page.latency_value:0.1f}", "ms", "#E2B15A", "ui.gauge"),
            (tr("目标"), str(len(page.visible_detections())), "", "#3DDC97", "act.detect"),
        )
        for index, (caption, value, unit, color, icon) in enumerate(cards):
            box = QRectF(inner.left() + index * (width + gap), inner.top(), width, height)
            painter.setPen(QPen(QColor(color), 1))
            painter.setBrush(QColor(8, 14, 26, 180))
            painter.drawRoundedRect(box, 10, 10)
            painter.drawPixmap(int(box.left() + 10), int(box.top() + 8), _glyph(icon, color, 14))
            painter.setPen(_MUTED)
            painter.setFont(_font(12, QFont.Weight.DemiBold))
            painter.drawText(QRectF(box.left() + 28, box.top() + 6, box.width() - 34, 16),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), caption)
            painter.setPen(_INK)
            painter.setFont(_font(38 if height >= 100 else 28, QFont.Weight.Medium, mono=True))
            painter.drawText(QRectF(box.left() + 8, box.top() + 24, box.width() - 12, height - 46),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), value)
            if unit:
                painter.setPen(QColor(color))
                painter.setFont(_font(12, QFont.Weight.DemiBold, mono=True))
                painter.drawText(QRectF(box.left() + 10, box.bottom() - 22, box.width() - 16, 16),
                                 int(Qt.AlignmentFlag.AlignLeft), unit)
        return inner.top() + height + 12

    def _trend(self, painter: QPainter, inner: QRectF, y: float, height: float) -> float:
        y = _section(painter, inner.left(), y, inner.width(), "ui.activity", tr("时延走势"), "#E2B15A")
        _chart(painter, QRectF(inner.left(), y, inner.width(), max(48.0, height - 28)),
               self.page.latency_samples, QColor("#E2B15A"))
        return y + max(48.0, height - 28) + 6

    def _bars(self, painter: QPainter, inner: QRectF, y: float, rows: list, counts: dict) -> float:
        y = _section(painter, inner.left(), y, inner.width(), "act.detect", tr("类别统计"), "#6C97E8")
        peak = max([count for _, count in rows] + [1])
        painter.setFont(_font(12, QFont.Weight.DemiBold))
        for name, count in rows[:6]:
            color = class_color(str(name)) if name in counts else _MUTED
            label = class_label(str(name)) if name in counts else str(name)
            painter.setPen(_INK)
            painter.drawText(QRectF(inner.left(), y, 64, 18),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            track = QRectF(inner.left() + 68, y + 5, inner.width() - 104, 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(150, 186, 255, 28))
            painter.drawRoundedRect(track, 4, 4)
            fill = QRectF(track.left(), track.top(), track.width() * (count / peak if peak else 0), track.height())
            painter.setBrush(color)
            painter.drawRoundedRect(fill, 4, 4)
            painter.setPen(_INK)
            painter.setFont(_font(12, mono=True))
            painter.drawText(QRectF(track.right() + 6, y, 28, 18),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), str(count))
            y += 22
        return y + 6

    def _gallery(self, painter: QPainter, inner: QRectF, y: float) -> None:
        remain = inner.bottom() - y
        if remain < 56:
            return
        y = _section(painter, inner.left(), y, inner.width(), "ui.image", tr("小目标"), "#3DDC97")
        targets = _gallery_targets(self.page, 3)
        gap = 8
        cell_w = (inner.width() - gap * 2) / 3
        cell_h = max(36.0, inner.bottom() - y)
        cap_h = 20
        for index in range(3):
            cell = QRectF(inner.left() + index * (cell_w + gap), y, cell_w, cell_h)
            picture = cell.adjusted(0, 0, 0, -cap_h)
            det = targets[index] if index < len(targets) else None
            _draw_zoom(painter, picture, self.page.state.image, det, self.page.state.result)
            caption = tr("无目标")
            if det is not None:
                caption = f"{class_label(str(det['class']))}  {float(det['score']):.2f}"
            painter.setPen(_MUTED)
            painter.setFont(_font(11, QFont.Weight.DemiBold, mono=True))
            painter.drawText(QRectF(cell.left(), cell.bottom() - cap_h + 2, cell.width(), cap_h - 2),
                             int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter), caption)


class HealthStrip(QWidget):
    """Ring gauges. The page's strip owns the labels tests read; the showcase mirrors them."""

    def __init__(self, page: "ModelDemoPage", bind: bool = False) -> None:
        super().__init__()
        self.page = page
        self.bind = bind
        self.setMinimumHeight(118)
        self.setMaximumHeight(168)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 6)
        layout.setSpacing(0)
        self.caption = QLabel(tr("示意读数，不是板端"))
        self.caption.setObjectName("muted")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.caption)
        self.ring_host = QWidget()
        self.ring_host.setFixedHeight(78)
        self.ring_host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.ring_host)
        row = QHBoxLayout()
        self.rows: dict[str, QLabel] = {}
        for key, title in (("temp", "温度"), ("cpu", "CPU"), ("mem", "内存")):
            column = QVBoxLayout()
            column.setSpacing(0)
            value = QLabel("—")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setObjectName("kpiValue")
            name = QLabel(tr(title))
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setObjectName("muted")
            column.addWidget(value)
            column.addWidget(name)
            row.addLayout(column)
            self.rows[key] = value
        layout.addLayout(row)
        if bind:
            page.health_caption = self.caption
            page.health_rows = self.rows

    def apply_fonts(self) -> None:
        scale = _ui_scale(self)
        self.caption.setFont(_font(12 * scale))
        for label in self.rows.values():
            label.setFont(_font(20 * scale, QFont.Weight.DemiBold, mono=True))

    def sync(self) -> None:
        if self.bind:
            return
        self.caption.setText(self.page.health_caption.text())
        for key, label in self.rows.items():
            label.setText(self.page.health_rows[key].text())

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        values = self.page.meter_values
        colors = {"temp": "#F0A36A", "cpu": "#6C97E8", "mem": "#3DDC97"}
        host = self.ring_host.geometry()
        width = self.width() / 3
        center_y = host.center().y()
        radius = min(32.0, host.height() / 2 - 4)
        for index, key in enumerate(("temp", "cpu", "mem")):
            raw = values.get(key)
            fraction = 0.0 if raw is None else max(0.0, min(1.0, float(raw) / 100.0))
            _ring(painter, QPointF(width * index + width / 2, center_y), radius, fraction, QColor(colors[key]))


class TimelineBar(QWidget):
    def __init__(self, page: "ModelDemoPage") -> None:
        super().__init__()
        self.page = page
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> Any:
        from PySide6.QtCore import QSize
        return QSize(640, int(round(112 * min(_ui_scale(self), 1.15))))

    def minimumSizeHint(self) -> Any:
        return self.sizeHint()

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), _BG)
        rect = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        _panel(painter, rect, 14)
        y = _section(painter, rect.left() + 14, rect.top() + 10, rect.width() - 28,
                     "nav.sessions", tr("检测事件"), "#6C97E8")
        samples = self.page.count_samples[-60:]
        if len(samples) >= 2:
            plot = QRectF(rect.left() + 14, y, rect.width() - 28, max(28.0, rect.bottom() - y - 36))
            peak = max(samples) or 1
            painter.setPen(Qt.PenStyle.NoPen)
            span = plot.width() / len(samples)
            for index, value in enumerate(samples):
                bar_h = max(2.0, plot.height() * value / peak)
                painter.setBrush(QColor("#6C97E8"))
                painter.drawRoundedRect(QRectF(plot.left() + index * span, plot.bottom() - bar_h,
                                               max(1.0, span - 1), bar_h), 1, 1)
            y = plot.bottom() + 6
        x = rect.left() + 14
        painter.setFont(_font(12, QFont.Weight.DemiBold, mono=True))
        for stamp, name, score in self.page.events[-8:]:
            text = f"{stamp}  {class_label(name)}  {score:.2f}"
            width = painter.fontMetrics().horizontalAdvance(text) + 16
            if x + width > rect.right() - 10:
                break
            chip = QRectF(x, y, width, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(class_color(name)))
            painter.drawRoundedRect(QRectF(chip.left(), chip.top(), 3, chip.height()), 1, 1)
            painter.setBrush(QColor(8, 14, 26, 210))
            painter.drawRoundedRect(chip.adjusted(3, 0, 0, 0), 4, 4)
            painter.setPen(_INK)
            painter.drawText(chip.adjusted(8, 0, -4, 0), int(Qt.AlignmentFlag.AlignVCenter), text)
            x += width + 8


def _gallery_targets(page: "ModelDemoPage", limit: int) -> list[dict[str, Any]]:
    rows = page.visible_detections()
    if not rows:
        return []
    pinned = page.zoom_detection()
    ordered = sorted(rows, key=lambda det: float(det["bbox"][2]) * float(det["bbox"][3]))
    if pinned is not None:
        ordered = [pinned] + [det for det in ordered if det is not pinned and det.get("track_id") != pinned.get("track_id")]
    return ordered[:limit]


def _chrome_qss(scale: float) -> str:
    """Scoped to the demo page so combo/slider rules cannot stretch the shared footer."""
    body = int(round(13 * scale))
    small = int(round(12 * scale))
    root = "QWidget#demoRoot"
    return f"""
    {root} {{ background: #070B12; color: #E7EEF8; }}
    {root} QFrame#glass {{ background: #101826; border: 1px solid rgba(160, 190, 255, 0.18); border-radius: 14px; }}
    {root} QLabel#muted {{ color: #93A4BA; font-size: {small}px; background: transparent; }}
    {root} QLabel#kpiValue {{
        color: #F4F7FB; font-family: "JetBrains Mono"; font-size: {int(round(20 * scale))}px;
        font-weight: 650; background: transparent;
    }}
    {root} QLabel#body {{ color: #E7EEF8; font-size: {body}px; background: transparent; }}
    {root} QLineEdit, {root} QComboBox {{
        background: #0C1422; color: #E7EEF8; border: 1px solid rgba(160, 190, 255, 0.22);
        border-radius: 8px; padding: 4px 8px; min-height: 22px; font-size: {body}px;
    }}
    {root} QComboBox QAbstractItemView {{ background: #101826; color: #E7EEF8; selection-background-color: #24406E; }}
    {root} QPushButton#demoBtn, {root} QPushButton#demoChip {{
        background: #152033; color: #D5DDEC; border: 1px solid rgba(160, 190, 255, 0.18);
        border-radius: 8px; padding: 6px 12px; font-size: {body}px;
    }}
    {root} QPushButton#demoBtn:checked, {root} QPushButton#demoChip:checked {{
        background: #1B3E78; color: #FFFFFF; border-color: #6C97E8;
    }}
    {root} QPushButton#demoPrimary {{
        background: #2C6BED; color: #FFFFFF; border: none; border-radius: 8px;
        padding: 6px 14px; font-size: {body}px; font-weight: 650;
    }}
    {root} QSlider::groove:horizontal {{ height: 4px; background: #243044; border-radius: 2px; }}
    {root} QSlider::sub-page:horizontal {{ background: #6C97E8; border-radius: 2px; }}
    {root} QSlider::handle:horizontal {{
        width: 14px; height: 14px; margin: -6px 0; background: #F4F7FB; border-radius: 7px;
    }}
    """


class ModelDemoPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("demoRoot")
        self.state = _State()
        self.kind = "demo"
        self.source = "synthetic"
        self.follow = str(PREFS.get("follow") or "small")
        self.min_score = float(PREFS.get("min_score") or 0.25)
        self.disabled: set[str] = set()
        self.slots: dict[str, dict[str, Any]] = {}
        self.fps_samples: list[float] = []
        self.latency_samples: list[float] = []
        self.count_samples: list[int] = []
        self.events: list[tuple[str, str, float]] = []
        self.fps_value = 0.0
        self.latency_value = 0.0
        self._fps_target = 0.0
        self._latency_target = 0.0
        self._frame_id = -1
        self._last_noted: int | None = None
        self._arrivals: list[float] = []
        self._pinned: Any = None
        self._seen: list[str] = []
        self._recorder: JsonlRecorder | None = None
        self._recorded_id: int | None = None
        self._pump: _Pump | None = None
        self._replay: list[dict[str, Any]] = []
        self._replay_index = 0
        self._injected = False
        self._board_view: dict[str, Any] | None = None
        self._board_error = ""
        self._poll_stop: threading.Event | None = None
        self._poller: threading.Thread | None = None
        self._preview_seq = -1
        self._showcase: ShowcaseDialog | None = None
        self.ui_scale = 1.0
        self._active = False
        self.meter_values = {"temp": None, "cpu": None, "mem": None}
        _ensure_fonts()
        self._build()
        self._apply_prefs()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.step)
        self._restyle()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(10)
        self.header = HeaderBar(self)
        root.addWidget(self.header)
        body = QHBoxLayout()
        body.setSpacing(10)
        self.stage = VideoStage(self)
        self.rail = QFrame()
        self.rail.setObjectName("glass")
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(0)
        self.rail_canvas = RailCanvas(self)
        self.health = HealthStrip(self, bind=True)
        rail_layout.addWidget(self.rail_canvas, 1)
        rail_layout.addWidget(self.health)
        body.addWidget(self.stage, 1)
        body.addWidget(self.rail, 0)
        root.addLayout(body, 1)
        self.timeline = TimelineBar(self)
        root.addWidget(self.timeline)
        self.operator = self._operator()
        root.addWidget(self.operator)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

    def _operator(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("glass")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)
        sources = QHBoxLayout()
        sources.setSpacing(6)
        self.source_group = QButtonGroup(self)
        self.source_group.setExclusive(True)
        self.source_buttons = {}
        for key, text in (("synthetic", "演示片段"), ("video", "视频文件"), ("camera", "本机摄像头"),
                          ("replay", "回放"), ("board", "板端")):
            button = QPushButton(tr(text))
            button.setObjectName("demoBtn")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, name=key: self._choose_source(name))
            self.source_group.addButton(button)
            self.source_buttons[key] = button
            sources.addWidget(button)
        self.source_buttons["synthetic"].setChecked(True)
        sources.addStretch(1)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        sources.addLayout(self.chips)
        outer.addLayout(sources)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self._cap("置信度"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(self.min_score * 100)))
        self.slider.valueChanged.connect(self._score_changed)
        self.score_label = QLabel(f"{self.min_score:.2f}")
        self.score_label.setObjectName("body")
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.score_label)
        controls.addWidget(self._cap("跟随"))
        self.follow_box = QComboBox()
        for key, text in (("small", "最小目标"), ("score", "最高置信度"), ("pin", "点击选择")):
            self.follow_box.addItem(tr(text), key)
        self.follow_box.currentIndexChanged.connect(self._follow_changed)
        controls.addWidget(self.follow_box)
        self.record_button = QPushButton(tr("记录"))
        self.record_button.setObjectName("demoBtn")
        self.record_button.setCheckable(True)
        self.record_button.clicked.connect(self._toggle_record)
        controls.addWidget(self.record_button)
        full = QPushButton(tr("全屏演示"))
        full.setObjectName("demoPrimary")
        full.setIcon(icons.icon("act.fullscreen", 16, "onAccent"))
        full.setCursor(Qt.CursorShape.PointingHandCursor)
        full.clicked.connect(self.toggle_showcase)
        controls.addWidget(full)
        outer.addLayout(controls)
        setup = QHBoxLayout()
        setup.setSpacing(8)
        setup.addWidget(self._cap("展示标题"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(tr("模型展示"))
        self.title_edit.textChanged.connect(self._title_changed)
        setup.addWidget(self.title_edit, 1)
        setup.addWidget(self._cap("客户名称"))
        self.customer_edit = QLineEdit()
        self.customer_edit.textChanged.connect(self._customer_changed)
        setup.addWidget(self.customer_edit, 1)
        setup.addWidget(self._cap("Logo 位置"))
        self.logo_pos = QComboBox()
        for text in ("左上", "右上", "左下", "右下"):
            self.logo_pos.addItem(tr(text), text)
        self.logo_pos.currentIndexChanged.connect(self._logo_pos_changed)
        setup.addWidget(self.logo_pos)
        logo = QPushButton(tr("选择 Logo"))
        logo.setObjectName("demoBtn")
        logo.clicked.connect(self._choose_logo)
        setup.addWidget(logo)
        outer.addLayout(setup)
        self.chip_buttons: dict[str, QPushButton] = {}
        return bar

    def _cap(self, text: str) -> QLabel:
        label = QLabel(tr(text))
        label.setObjectName("muted")
        return label

    def _apply_prefs(self) -> None:
        self.state.title = str(PREFS.get("title") or "")
        self.state.customer = str(PREFS.get("customer") or "")
        self.state.logo_pos = str(PREFS.get("logo_pos") or "左上")
        self.title_edit.setText(self.state.title)
        self.customer_edit.setText(self.state.customer)
        index = self.logo_pos.findData(self.state.logo_pos)
        if index >= 0:
            self.logo_pos.setCurrentIndex(index)
        logo = str(PREFS.get("logo") or "")
        if logo and Path(logo).is_file():
            image = QImage(logo)
            if not image.isNull():
                self.state.logo = image
        index = self.follow_box.findData(self.follow)
        if index >= 0:
            self.follow_box.setCurrentIndex(index)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._restyle()

    def _restyle(self) -> None:
        height = max(1, self.height())
        self.ui_scale = max(0.82, min(height / 900.0, 1.35))
        rail = 460 if self.width() >= 1600 else 380 if self.width() >= 1200 else 300
        self.rail.setFixedWidth(rail)
        self.timeline.setVisible(height >= 820)
        self.header.updateGeometry()
        self.timeline.updateGeometry()
        self.setStyleSheet(_chrome_qss(self.ui_scale))
        self.health.apply_fonts()
        if self._showcase is not None:
            self._showcase.header.updateGeometry()
            self._showcase.timeline.updateGeometry()
            self._showcase.health.apply_fonts()

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            if not self.timer.isActive():
                self.timer.start(33)
            self.step()
        elif self._showcase is None or not self._showcase.isVisible():
            self.timer.stop()

    def shutdown(self) -> None:
        self.timer.stop()
        self._stop_pump()
        self._stop_poller()
        self._close_recorder()
        if self._showcase is not None:
            self._showcase.close()
            self._showcase = None

    def step(self, frame_id: int | None = None, now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        if self.source == "board" and not self._injected:
            self._step_board(moment)
        elif self.source == "replay":
            self._step_replay(moment)
        else:
            self._step_demo(frame_id, moment)
        self._animate()
        self._publish()

    def _step_demo(self, frame_id: int | None, now: float) -> None:
        self._frame_id = self._frame_id + 1 if frame_id is None else frame_id
        image = None
        if self._pump is not None:
            image = self._pump.latest()
            if self._pump.error and image is None:
                self.status.setText(tr("无法打开视频") if self.source == "video" else tr("无法打开摄像头"))
        if image is not None:
            result = demo_overlay(self._frame_id, image.width(), image.height())
            self.state.image = image
        else:
            bundled = clip_frame(self._frame_id) if self.source == "synthetic" else None
            if bundled is None:
                result = demo_overlay(self._frame_id, 1280, 720)
                self.state.image = _blank(int(result["width"]), int(result["height"]))
            else:
                self.state.image, result = bundled
        self.state.result = result
        self.kind = "demo"
        self._note(result, now)
        self._paint_health(_demo_meters(self._frame_id), preview=True)

    def _step_replay(self, now: float) -> None:
        if not self._replay:
            self.kind = "replay"
            self.state.result = None
            return
        result = self._replay[self._replay_index % len(self._replay)]
        self._replay_index += 1
        self.state.result = result
        bundled = clip_frame(int(result["frame_id"])) if result.get("preview_only") else None
        if bundled is not None and bundled[0].width() == int(result["width"]):
            self.state.image = bundled[0]
        else:
            self.state.image = _blank(int(result.get("width") or 1280), int(result.get("height") or 720))
        self.kind = "replay_demo" if result.get("preview_only") else "replay"
        self._note(result, now)
        self._paint_health({"cpu": None, "temp": None, "mem_used": None, "mem_total": None}, preview=False)

    def _step_board(self, now: float) -> None:
        with STUDIO.lock:
            preview = STUDIO.preview
            seq = STUDIO.preview_seq
            status = dict(STUDIO.board_status or {})
            connected = bool(STUDIO.connected)
        if preview and seq != self._preview_seq:
            image = QImage.fromData(preview)
            if not image.isNull():
                self.state.image = image
                self._preview_seq = seq
        view = self._board_view or {}
        result = view.get("result") if isinstance(view, dict) else None
        if isinstance(result, dict) and result.get("preview_only"):
            self.kind = "demo"
        elif isinstance(result, dict) and result.get("model") == "not-configured":
            self.kind = "unconfigured"
        elif isinstance(result, dict):
            self.kind = "board"
        elif not connected:
            self.kind = "offline"
        else:
            self.kind = "waiting"
        self.state.result = result if isinstance(result, dict) else None
        if isinstance(result, dict):
            self._note(result, now)
        self._paint_health(board_health(status), preview=False)
        if self._board_error and self.kind == "board":
            self.status.setText(self._board_error)

    def show_board_frame(self, image: QImage, result: dict[str, Any] | None,
                         health: dict[str, Any] | None = None, connected: bool = True) -> None:
        self.source = "board"
        self._injected = True
        self._stop_poller()
        self.state.image = image
        self.state.result = result
        if result and result.get("preview_only"):
            self.kind = "demo"
        elif result and result.get("model") == "not-configured":
            self.kind = "unconfigured"
        elif result:
            self.kind = "board"
        elif not connected:
            self.kind = "offline"
        else:
            self.kind = "waiting"
        if result:
            self._note(result, time.monotonic())
        self._paint_health(board_health(health or {}), preview=False)
        self._animate()
        self._publish()

    def _note(self, result: dict[str, Any], now: float) -> None:
        frame_id = int(result["frame_id"])
        if frame_id == self._last_noted:
            return
        self._last_noted = frame_id
        if self._arrivals and now < self._arrivals[-1]:
            self._arrivals.clear()
        self._arrivals.append(now)
        self._arrivals = [stamp for stamp in self._arrivals if 0.0 <= now - stamp <= 1.0]
        if len(self._arrivals) >= 2:
            span = self._arrivals[-1] - self._arrivals[0]
            if span > 0:
                self._fps_target = (len(self._arrivals) - 1) / span
        latency = float(result.get("latency_ms") or 0.0)
        self._latency_target = latency
        self.fps_samples.append(self._fps_target)
        self.latency_samples.append(latency)
        count = len(result.get("detections") or [])
        self.count_samples.append(count)
        del self.fps_samples[:-64]
        del self.latency_samples[:-64]
        del self.count_samples[:-64]
        stamp = datetime.now().strftime("%H:%M:%S")
        for det in result.get("detections") or []:
            self.events.append((stamp, str(det.get("class") or ""), float(det.get("score") or 0)))
        del self.events[:-24]
        for name in class_counts(result.get("detections") or []):
            if name not in self._seen:
                self._seen.append(name)
        if self._recorder is not None and frame_id != self._recorded_id:
            self._recorder.write(result)
            self._recorded_id = frame_id

    def _animate(self) -> None:
        visible = self.visible_detections()
        alive = set()
        for det in visible:
            key = _slot_key(det)
            alive.add(key)
            slot = self.slots.setdefault(key, {"alpha": 0.0, "det": det})
            slot["det"] = det
            if motion.reduced():
                slot["alpha"] = 1.0
            else:
                slot["alpha"] += (1.0 - slot["alpha"]) * 0.38
        for key in list(self.slots):
            if key in alive:
                continue
            if motion.reduced() or self.slots[key]["alpha"] <= 0.05:
                del self.slots[key]
            else:
                self.slots[key]["alpha"] -= 0.16
        if motion.reduced() or self.fps_value == 0 and self._fps_target:
            self.fps_value = self._fps_target
            self.latency_value = self._latency_target
        else:
            self.fps_value += (self._fps_target - self.fps_value) * 0.22
            self.latency_value += (self._latency_target - self.latency_value) * 0.22

    def visible_detections(self) -> list[dict[str, Any]]:
        return visible_detections(self.state.result, self.min_score, self.disabled)

    def zoom_detection(self) -> dict[str, Any] | None:
        rows = self.visible_detections()
        if not rows:
            return None
        if self._pinned is not None:
            for det in rows:
                if det.get("track_id") == self._pinned:
                    return det
        if self.follow == "score":
            return max(rows, key=lambda det: float(det["score"]))
        return min(rows, key=lambda det: float(det["bbox"][2]) * float(det["bbox"][3]))

    def pin_at_image(self, x: float, y: float) -> None:
        hits = []
        for det in self.visible_detections():
            bx, by, bw, bh = det["bbox"]
            if bx <= x <= bx + bw and by <= y <= by + bh:
                hits.append(det)
        if not hits:
            return
        chosen = min(hits, key=lambda det: float(det["bbox"][2]) * float(det["bbox"][3]))
        self._pinned = chosen.get("track_id")
        self.follow = "pin"
        index = self.follow_box.findData("pin")
        if index >= 0 and self.follow_box.currentIndex() != index:
            self.follow_box.setCurrentIndex(index)
        self._publish()

    def _publish(self) -> None:
        self._sync_chips()
        for widget in (self.header, self.stage, self.rail_canvas, self.health, self.timeline):
            widget.update()
        if self._showcase is not None and self._showcase.isVisible():
            self._showcase.health.sync()
            for widget in (self._showcase.header, self._showcase.stage, self._showcase.rail_canvas,
                           self._showcase.health, self._showcase.timeline):
                widget.update()

    def _sync_chips(self) -> None:
        if list(self.chip_buttons) == self._seen:
            return
        while self.chips.count():
            item = self.chips.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.chip_buttons = {}
        for name in self._seen:
            chip = QPushButton(class_label(name))
            chip.setObjectName("demoChip")
            chip.setCheckable(True)
            chip.setChecked(name not in self.disabled)
            chip.clicked.connect(lambda checked=False, label=name: self._chip(label, checked))
            self.chips.addWidget(chip)
            self.chip_buttons[name] = chip
        self.chips.addStretch(1)

    def _paint_health(self, health: dict[str, Any], preview: bool) -> None:
        self.health_caption.setText(tr("示意读数，不是板端") if preview else tr("板端状态"))
        temp = health.get("temp")
        cpu = health.get("cpu")
        used, total = health.get("mem_used"), health.get("mem_total")
        self.health_rows["temp"].setText("—" if temp is None else f"{temp:.0f} °C")
        self.health_rows["cpu"].setText("—" if cpu is None else f"{cpu:.0f}%")
        if used is None or not total:
            self.health_rows["mem"].setText("—")
            mem_pct = None
        else:
            mem_pct = used / total * 100
            self.health_rows["mem"].setText(f"{mem_pct:.0f}%")
        self.meter_values = {
            "temp": None if temp is None else float(temp),
            "cpu": None if cpu is None else float(cpu),
            "mem": None if mem_pct is None else float(mem_pct),
        }

    def _score_changed(self, value: int) -> None:
        self.min_score = value / 100
        PREFS["min_score"] = self.min_score
        self.score_label.setText(f"{self.min_score:.2f}")
        self.slots.clear()
        self._publish()

    def _follow_changed(self) -> None:
        self.follow = str(self.follow_box.currentData() or "small")
        PREFS["follow"] = self.follow
        self._publish()

    def _chip(self, name: str, checked: bool) -> None:
        if checked:
            self.disabled.discard(name)
        else:
            self.disabled.add(name)
        self.slots.clear()
        self._publish()

    def set_min_score(self, value: float) -> None:
        self.slider.setValue(int(round(value * 100)))

    def set_class_enabled(self, name: str, enabled: bool) -> None:
        self._chip(name, enabled)
        chip = self.chip_buttons.get(name)
        if chip is not None:
            chip.setChecked(enabled)

    def _choose_source(self, name: str) -> None:
        if name == "video":
            path, _ = QFileDialog.getOpenFileName(self, tr("选择视频"), "", "Video (*.mp4 *.mkv *.avi *.mov)")
            if not path:
                self._check_source()
                return
            self._open_pipe(_ffmpeg_file(path), 1280, 720, "video")
            return
        if name == "camera":
            command = _ffmpeg_camera()
            if command is None:
                self.status.setText(tr("无法打开摄像头"))
                self._check_source()
                return
            self._open_pipe(command, 1280, 720, "camera")
            return
        if name == "replay":
            path, _ = QFileDialog.getOpenFileName(self, tr("选择回放文件"), "", "JSONL (*.jsonl)")
            if not path:
                self._check_source()
                return
            self.load_replay(Path(path))
            return
        if name == "board":
            self._stop_pump()
            self.source = "board"
            self._injected = False
            self._ensure_poller()
            self._check_source()
            self._use_board_picture()
            return
        self._stop_pump()
        self._stop_poller()
        self.source = "synthetic"
        self._injected = False
        self._check_source()

    def _check_source(self) -> None:
        button = self.source_buttons.get(self.source)
        if button is not None:
            button.setChecked(True)

    def _open_pipe(self, command: list[str] | None, width: int, height: int, source: str) -> None:
        self._stop_pump()
        if not command:
            self.status.setText(tr("无法打开视频") if source == "video" else tr("无法打开摄像头"))
            self._check_source()
            return
        self._pump = _Pump(command, width, height)
        self.source = source
        self._injected = False
        self._stop_poller()
        self._check_source()
        self.status.setText("")

    def _use_board_picture(self) -> None:
        if not STUDIO.connected:
            self.status.setText(tr("未连接开发板"))
            return
        window = self.window()
        if STUDIO.live or STUDIO.busy or not hasattr(window, "payload"):
            return
        STUDIO.start_live(window.payload())

    def load_replay(self, path: Path) -> None:
        self._replay = load_jsonl(path)
        self._replay_index = 0
        self._stop_pump()
        self._stop_poller()
        self.source = "replay"
        self._injected = False
        self._check_source()
        self.status.setText(tr("回放数据"))
        self.step()

    def start_recording(self, path: Path) -> None:
        self._close_recorder()
        self._recorder = JsonlRecorder(path)
        self._recorded_id = None
        self.record_button.setChecked(True)
        self.record_button.setText(tr("停止记录"))
        self.status.setText(str(path))

    def stop_recording(self) -> int:
        count = self._recorder.count if self._recorder is not None else 0
        self._close_recorder()
        self.record_button.setChecked(False)
        self.record_button.setText(tr("记录"))
        return count

    def _toggle_record(self) -> None:
        if self._recorder is not None:
            count = self.stop_recording()
            self.status.setText(tr("结果已写入") + f"  {count}")
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("记录"), "model_demo.jsonl", "JSONL (*.jsonl)")
        if not path:
            self.record_button.setChecked(False)
            return
        self.start_recording(Path(path))

    def _close_recorder(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            self._recorder = None

    def _title_changed(self, text: str) -> None:
        self.state.title = text.strip()
        PREFS["title"] = self.state.title
        self.header.update()

    def _customer_changed(self, text: str) -> None:
        self.state.customer = text.strip()
        PREFS["customer"] = self.state.customer
        self.header.update()

    def _logo_pos_changed(self) -> None:
        self.state.logo_pos = str(self.logo_pos.currentData() or "左上")
        PREFS["logo_pos"] = self.state.logo_pos
        self.header.update()

    def _choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("选择 Logo"), "", "Image (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            return
        self.state.logo = image
        PREFS["logo"] = path
        self.header.update()

    def set_presentation(self, title: str = "", customer: str = "", logo_pos: str = "左上") -> None:
        self.title_edit.setText(title)
        self.customer_edit.setText(customer)
        index = self.logo_pos.findData(logo_pos)
        if index >= 0:
            self.logo_pos.setCurrentIndex(index)

    def toggle_showcase(self) -> None:
        if self._showcase is not None and self._showcase.isVisible():
            self._showcase.close()
            return
        self.open_showcase()

    def open_showcase(self) -> None:
        if self._showcase is None:
            self._showcase = ShowcaseDialog(self.window(), self)
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            self._showcase.resize(1920, 1080)
            self._showcase.show()
        else:
            self._showcase.showFullScreen()
        if not self.timer.isActive():
            self.timer.start(33)
        self._showcase.health.apply_fonts()
        self._publish()

    def showcase_open(self) -> bool:
        return self._showcase is not None and self._showcase.isVisible()

    def _on_showcase_closed(self) -> None:
        if not self._active:
            self.timer.stop()

    def _ensure_poller(self) -> None:
        if self._poller is not None and self._poller.is_alive():
            return
        self._poll_stop = threading.Event()
        self._poller = threading.Thread(target=self._poll, daemon=True)
        self._poller.start()

    def _poll(self) -> None:
        stop = self._poll_stop
        if stop is None:
            return
        while not stop.wait(0.12):
            client = STUDIO.client
            if client is None:
                self._board_error = ""
                self._board_view = None
                continue
            try:
                self._board_view = client.request("GET", "/infer", timeout=2)
                self._board_error = ""
            except (RuntimeError, OSError) as exc:
                self._board_error = str(exc)

    def _stop_poller(self) -> None:
        if self._poll_stop is not None:
            self._poll_stop.set()
        self._poller = None
        self._poll_stop = None

    def _stop_pump(self) -> None:
        if self._pump is not None:
            self._pump.close()
            self._pump = None


class ShowcaseDialog(QDialog):
    def __init__(self, parent: QWidget, page: ModelDemoPage) -> None:
        super().__init__(parent)
        self.page = page
        self.setWindowTitle(tr("模型展示"))
        self.setModal(False)
        self.header = HeaderBar(page)
        self.stage = VideoStage(page)
        self.rail_canvas = RailCanvas(page)
        self.health = HealthStrip(page, bind=False)
        self.timeline = TimelineBar(page)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)
        root.addWidget(self.header)
        body = QHBoxLayout()
        body.setSpacing(12)
        rail = QFrame()
        rail.setObjectName("showcaseRail")
        rail.setFixedWidth(460)
        rail.setStyleSheet(
            "QFrame#showcaseRail { background: #101826; border: 1px solid rgba(160, 190, 255, 0.18);"
            " border-radius: 14px; }"
            "QFrame#showcaseRail QLabel { color: #F4F7FB; background: transparent; font-family: 'JetBrains Mono'; }"
            "QFrame#showcaseRail QLabel#muted { color: #93A4BA; background: transparent;"
            " font-family: 'Noto Sans CJK SC', 'Microsoft YaHei UI'; }"
        )
        rail_box = QVBoxLayout(rail)
        rail_box.setContentsMargins(0, 0, 0, 0)
        rail_box.setSpacing(0)
        rail_box.addWidget(self.rail_canvas, 1)
        rail_box.addWidget(self.health)
        body.addWidget(self.stage, 1)
        body.addWidget(rail)
        root.addLayout(body, 1)
        root.addWidget(self.timeline)
        self.setStyleSheet("QDialog { background: #070B12; }")

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: Any) -> None:
        super().closeEvent(event)
        self.page._on_showcase_closed()


def _slot_key(det: dict[str, Any]) -> str:
    track = det.get("track_id")
    if track is not None:
        return f"id:{track}"
    box = tuple(round(float(part), 1) for part in det["bbox"])
    return f"{det['class']}:{box}"


def _demo_meters(frame_id: int) -> dict[str, Any]:
    """Placeholder meters for the no-board preview. Not a probe of a real board."""
    return {
        "cpu": 18 + 6 * math.sin(frame_id / 18.0),
        "temp": 46 + 2.4 * math.sin(frame_id / 22.0),
        "mem_used": int(1.35 * 1024 ** 3),
        "mem_total": int(4 * 1024 ** 3),
    }


class _Pump:
    """Latest RGB frame from an ffmpeg rawvideo pipe. Picture only — no detector."""

    def __init__(self, command: list[str], width: int, height: int) -> None:
        self.width, self.height = width, height
        self.frame: QImage | None = None
        self.error = ""
        self._lock = threading.Lock()
        self.proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        need = self.width * self.height * 3
        stream = self.proc.stdout
        if stream is None:
            return
        try:
            while True:
                buf = bytearray()
                while len(buf) < need:
                    chunk = stream.read(need - len(buf))
                    if not chunk:
                        err = b""
                        if self.proc.stderr is not None:
                            err = self.proc.stderr.read() or b""
                        self.error = err.decode("utf-8", "replace")[-240:] or "eof"
                        return
                    buf.extend(chunk)
                image = QImage(bytes(buf), self.width, self.height, self.width * 3, QImage.Format.Format_RGB888).copy()
                with self._lock:
                    self.frame = image
        except (OSError, ValueError) as exc:
            self.error = str(exc)

    def latest(self) -> QImage | None:
        with self._lock:
            return self.frame

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()


def _ffmpeg_file(path: str) -> list[str] | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1", "-i", path,
            "-an", "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x070B12",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]


def _ffmpeg_camera() -> list[str] | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    if os.name == "nt":
        return [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "dshow", "-i", "video=0",
                "-vf", "scale=1280:720", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "v4l2", "-i", "/dev/video0",
            "-vf", "scale=1280:720", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
