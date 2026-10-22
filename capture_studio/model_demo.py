"""Model demo page. The desktop only draws frames and protocol results.

Inference stays on the board. Synthetic, video, and camera sources exist so the
page can be previewed with no board; their boxes come from ``demo_overlay``
and are always labeled as demo data.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from . import icons, motion
from .i18n import tr
from .inference import (JsonlRecorder, board_health, class_counts, demo_overlay, load_jsonl,
                        visible_detections)
from .product import STUDIO

SCENE_W, SCENE_H = 1920, 1080

# Curated, restrained class colors. Unknown names hash into the same list.
_CLASS_COLORS = {
    "person": "#8FB4FF", "car": "#E4C27A", "bicycle": "#7DDCB0", "drone": "#D7A6FF", "bird": "#FF9AAE",
}
_PALETTE = ("#8FB4FF", "#E4C27A", "#7DDCB0", "#D7A6FF", "#FF9AAE", "#7ED0E0", "#F0A36A", "#C6D48A")

_BADGE = {
    "demo": ("演示数据", "脚本框，不是识别结果"),
    "replay": ("回放数据", "录制的结果，不是实时识别"),
    "replay_demo": ("回放数据", "演示记录，不是实时识别"),
    "board": ("板端实时", "开发板上的模型输出"),
    "unconfigured": ("模型未接入", "通道已通，板端还没有模型输出"),
    "waiting": ("等待结果", "已连接，尚未收到这一帧的结果"),
    "offline": ("未连接", "连接开发板后使用板端画面"),
}

_BUILDINGS = (
    (0.03, 0.07, 0.16), (0.11, 0.05, 0.24), (0.18, 0.09, 0.18), (0.30, 0.04, 0.12),
    (0.78, 0.06, 0.20), (0.86, 0.08, 0.14), (0.94, 0.05, 0.22),
)
_STARS = (
    (0.08, 0.08), (0.16, 0.14), (0.22, 0.05), (0.41, 0.09), (0.57, 0.06),
    (0.63, 0.13), (0.81, 0.07), (0.90, 0.11), (0.48, 0.16),
)

# In-memory presentation so a language rebuild keeps what the operator typed.
PREFS: dict[str, Any] = {"title": "", "customer": "", "logo": "", "logo_pos": "左上",
                        "min_score": 0.25, "follow": "small"}


def class_color(name: str) -> QColor:
    if name in _CLASS_COLORS:
        return QColor(_CLASS_COLORS[name])
    return QColor(_PALETTE[sum(name.encode("utf-8")) % len(_PALETTE)])


def _font(px: float, weight: QFont.Weight = QFont.Weight.Medium) -> QFont:
    font = QFont()
    font.setFamilies(["Inter", "Source Sans 3", "WenQuanYi Micro Hei", "Segoe UI", "sans-serif"])
    font.setPixelSize(max(1, int(round(px))))
    font.setWeight(weight)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def badge_copy(kind: str) -> tuple[str, str]:
    title, detail = _BADGE.get(kind, _BADGE["waiting"])
    return tr(title), tr(detail)


def paint_scene(result: dict[str, Any]) -> QImage:
    """Illustrated backdrop for scripted boxes. Positions come from the result, not from a detector."""
    width, height = int(result["width"]), int(result["height"])
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(0, 0, 0, height)
    sky.setColorAt(0.0, QColor("#050910"))
    sky.setColorAt(0.42, QColor("#0E2038"))
    sky.setColorAt(0.62, QColor("#1A4A72"))
    sky.setColorAt(0.68, QColor("#101820"))
    sky.setColorAt(1.0, QColor("#080C11"))
    painter.fillRect(image.rect(), sky)
    glow = QLinearGradient(0, height * 0.56, 0, height * 0.72)
    glow.setColorAt(0.0, QColor(90, 150, 210, 0))
    glow.setColorAt(0.45, QColor(140, 186, 230, 54))
    glow.setColorAt(1.0, QColor(90, 150, 210, 0))
    painter.fillRect(QRectF(0, height * 0.56, width, height * 0.16), glow)
    painter.setPen(Qt.PenStyle.NoPen)
    for nx, ny in _STARS:
        painter.setBrush(QColor(220, 230, 245, 90))
        painter.drawEllipse(QPointF(nx * width, ny * height), 1.4, 1.4)
    horizon = height * 0.66
    painter.setBrush(QColor("#0C1624"))
    for nx, nw, nh in _BUILDINGS:
        rect = QRectF(nx * width, horizon - nh * height, nw * width, nh * height)
        painter.drawRect(rect)
        painter.setBrush(QColor(150, 190, 230, 28))
        win = max(3.0, width * 0.004)
        gap = win * 1.7
        y = rect.top() + gap
        while y < rect.bottom() - gap:
            x = rect.left() + gap
            while x < rect.right() - gap:
                painter.drawRect(QRectF(x, y, win, win * 1.35))
                x += gap
            y += gap
        painter.setBrush(QColor("#0C1624"))
    painter.setPen(QPen(QColor(180, 200, 220, 40), 1))
    painter.drawLine(QPointF(0, horizon), QPointF(width, horizon))
    painter.setPen(Qt.PenStyle.NoPen)
    for det in result.get("detections") or []:
        _paint_prop(painter, det, width, height)
    vignette = QRadialGradient(width * 0.5, height * 0.45, width * 0.72)
    vignette.setColorAt(0.55, QColor(0, 0, 0, 0))
    vignette.setColorAt(1.0, QColor(0, 0, 0, 90))
    painter.fillRect(image.rect(), vignette)
    painter.end()
    return image


def _paint_prop(painter: QPainter, det: dict[str, Any], width: int, height: int) -> None:
    x, y, w, h = det["bbox"]
    color = class_color(str(det["class"]))
    painter.setBrush(QColor(0, 0, 0, 50))
    painter.drawEllipse(QRectF(x + w * 0.1, y + h * 0.86, w * 0.8, max(4.0, h * 0.16)))
    name = str(det["class"])
    body = QColor(color)
    body.setAlpha(210)
    painter.setBrush(body)
    if name == "person":
        painter.drawEllipse(QRectF(x + w * 0.22, y, w * 0.56, w * 0.56))
        painter.drawRoundedRect(QRectF(x + w * 0.18, y + w * 0.48, w * 0.64, h - w * 0.48), w * 0.2, w * 0.2)
    elif name == "car":
        painter.drawRoundedRect(QRectF(x, y + h * 0.38, w, h * 0.52), h * 0.16, h * 0.16)
        roof = QColor(color)
        roof.setAlpha(160)
        painter.setBrush(roof)
        painter.drawRoundedRect(QRectF(x + w * 0.18, y + h * 0.08, w * 0.52, h * 0.38), h * 0.12, h * 0.12)
        painter.setBrush(QColor("#0B1018"))
        painter.drawEllipse(QRectF(x + w * 0.12, y + h * 0.62, h * 0.34, h * 0.34))
        painter.drawEllipse(QRectF(x + w * 0.68, y + h * 0.62, h * 0.34, h * 0.34))
    elif name == "bicycle":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(color, max(2.0, h * 0.06))
        painter.setPen(pen)
        painter.drawEllipse(QRectF(x, y + h * 0.35, h * 0.55, h * 0.55))
        painter.drawEllipse(QRectF(x + w - h * 0.55, y + h * 0.35, h * 0.55, h * 0.55))
        painter.drawLine(QPointF(x + h * 0.28, y + h * 0.62), QPointF(x + w * 0.55, y + h * 0.62))
        painter.drawLine(QPointF(x + w * 0.42, y + h * 0.2), QPointF(x + w * 0.7, y + h * 0.62))
        painter.setPen(Qt.PenStyle.NoPen)
    elif name == "drone":
        painter.drawRoundedRect(QRectF(x + w * 0.28, y + h * 0.32, w * 0.44, h * 0.36), 6, 6)
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 140))
        for cx, cy in ((0.12, 0.18), (0.72, 0.18), (0.12, 0.62), (0.72, 0.62)):
            painter.drawEllipse(QRectF(x + w * cx, y + h * cy, w * 0.2, h * 0.22))
    else:
        painter.drawEllipse(QRectF(x, y + h * 0.25, w, h * 0.55))
        wing = QColor(color)
        wing.setAlpha(150)
        painter.setBrush(wing)
        path = QPainterPath()
        path.moveTo(x + w * 0.2, y + h * 0.5)
        path.lineTo(x - w * 0.15, y + h * 0.15)
        path.lineTo(x + w * 0.35, y + h * 0.42)
        painter.drawPath(path)


def _fit(image: QImage, bounds: QRectF) -> QRectF:
    if image.isNull() or bounds.width() <= 1 or bounds.height() <= 1:
        return QRectF()
    scale = min(bounds.width() / image.width(), bounds.height() / image.height())
    width, height = image.width() * scale, image.height() * scale
    return QRectF(bounds.x() + (bounds.width() - width) / 2,
                  bounds.y() + (bounds.height() - height) / 2, width, height)


def _brackets(painter: QPainter, rect: QRectF, color: QColor, alpha: float) -> None:
    if rect.width() < 2 or rect.height() < 2 or alpha <= 0.02:
        return
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, alpha)))
    arm = max(6.0, min(rect.width(), rect.height()) * 0.34)
    arm = min(arm, rect.width() * 0.48, rect.height() * 0.48, 26.0)
    pen = QPen(color)
    pen.setWidthF(max(1.5, min(2.6, min(rect.width(), rect.height()) * 0.08)))
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
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
    text = f"{det['class']}  {float(det['score']):.2f}"
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, alpha)))
    painter.setFont(_font(12 * scale, QFont.Weight.DemiBold))
    metrics = painter.fontMetrics()
    text_w = metrics.horizontalAdvance(text)
    box_h = metrics.height() + 6
    box_w = text_w + 22
    x = rect.left()
    y = rect.top() - box_h - 4
    if y < bounds.top() + 2:
        y = min(rect.bottom() + 4, rect.top() + 4)
    if x + box_w > bounds.right() - 2:
        x = max(bounds.left() + 2, bounds.right() - box_w - 2)
    box = QRectF(x, y, box_w, box_h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(8, 12, 20, 188))
    painter.drawRoundedRect(box, 6, 6)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(x + 7, y + box_h / 2 - 4, 3, 8), 1, 1)
    painter.setPen(QColor("#F7F9FC"))
    painter.drawText(box.adjusted(16, 0, -4, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
    painter.restore()


def _draw_zoom(painter: QPainter, dest: QRectF, image: QImage, det: dict[str, Any] | None,
               result: dict[str, Any] | None, scale: float) -> None:
    painter.save()
    clip = QPainterPath()
    clip.addRoundedRect(dest, 12, 12)
    painter.setClipPath(clip)
    painter.fillRect(dest, QColor("#0B1220"))
    if image.isNull() or det is None or not result:
        painter.setPen(QColor("#8EA0B8"))
        painter.setFont(_font(13 * scale))
        painter.drawText(dest, int(Qt.AlignmentFlag.AlignCenter), tr("无目标"))
        painter.restore()
        return
    x, y, w, h = det["bbox"]
    rw, rh = max(1, int(result["width"])), max(1, int(result["height"]))
    pad = max(w, h, 28) * 0.85
    side = max(w, h) + pad * 2
    src = QRectF((x + w / 2) - side / 2, (y + h / 2) - side / 2, side, side)
    src = src.intersected(QRectF(0, 0, rw, rh))
    if src.isEmpty():
        painter.restore()
        return
    # Map result space onto the image, which may be a different resolution.
    ix = src.x() / rw * image.width()
    iy = src.y() / rh * image.height()
    iw = src.width() / rw * image.width()
    ih = src.height() / rh * image.height()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(dest, image, QRectF(ix, iy, iw, ih))
    shade = QLinearGradient(dest.topLeft(), dest.bottomLeft())
    shade.setColorAt(0.0, QColor(0, 0, 0, 70))
    shade.setColorAt(0.25, QColor(0, 0, 0, 0))
    painter.fillRect(dest, shade)
    sx = dest.width() / src.width()
    sy = dest.height() / src.height()
    box = QRectF(dest.x() + (x - src.x()) * sx, dest.y() + (y - src.y()) * sy, w * sx, h * sy)
    _brackets(painter, box, class_color(str(det["class"])), 1.0)
    painter.restore()
    painter.setPen(QPen(QColor(255, 255, 255, 36), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(dest.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)


class Sparkline(QWidget):
    def __init__(self, color: str) -> None:
        super().__init__()
        self.color = QColor(color)
        self.samples: list[float] = []
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event: Any) -> None:
        if len(self.samples) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        values = self.samples[-48:]
        low, high = min(values), max(values)
        if high - low < 1e-3:
            low, high = low - 1, high + 1
        width, height = self.width(), self.height()

        def point(index: int, value: float) -> QPointF:
            x = 1 + index / (len(values) - 1) * (width - 2)
            y = height - 3 - (value - low) / (high - low) * (height - 8)
            return QPointF(x, y)

        line = QPainterPath()
        line.moveTo(point(0, values[0]))
        for index in range(1, len(values)):
            line.lineTo(point(index, values[index]))
        fill = QPainterPath(line)
        fill.lineTo(point(len(values) - 1, low))
        fill.lineTo(point(0, low))
        fill.closeSubpath()
        fade = QLinearGradient(0, 0, 0, height)
        top = QColor(self.color)
        top.setAlpha(70)
        fade.setColorAt(0.0, top)
        fade.setColorAt(1.0, QColor(self.color.red(), self.color.green(), self.color.blue(), 0))
        painter.fillPath(fill, fade)
        pen = QPen(self.color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(line)


class Stage(QWidget):
    """Video, boxes, title and (in showcase) the readout strip."""

    def __init__(self, page: "ModelDemoPage", showcase: bool = False) -> None:
        super().__init__(page if not showcase else None)
        self.page = page
        self.showcase = showcase
        self._image_rect = QRectF()
        self.setMinimumSize(360, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._image_rect.isNull():
            return super().mousePressEvent(event)
        pos = event.position()
        if not self._image_rect.contains(pos):
            return
        result = self.page.state.result
        image = self.page.state.image
        if result is None or image.isNull():
            return
        rx = (pos.x() - self._image_rect.x()) / self._image_rect.width() * result["width"]
        ry = (pos.y() - self._image_rect.y()) / self._image_rect.height() * result["height"]
        self.page.pin_at_image(rx, ry)

    def paintEvent(self, _event: Any) -> None:
        page = self.page
        state = page.state
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale = max(0.78, min(self.height() / 900.0, 2.1))
        painter.fillRect(self.rect(), QColor("#070B12"))
        glow = QRadialGradient(self.width() * 0.5, self.height() * 0.08, self.width() * 0.7)
        glow.setColorAt(0.0, QColor(40, 78, 140, 70))
        glow.setColorAt(1.0, QColor(7, 11, 18, 0))
        painter.fillRect(self.rect(), glow)
        margin = 22 * scale if self.showcase else 8
        bottom_reserve = 168 * scale if self.showcase else 8
        bounds = QRectF(margin, margin, self.width() - margin * 2, self.height() - margin - bottom_reserve)
        rect = _fit(state.image, bounds)
        self._image_rect = rect
        if not state.image.isNull() and not rect.isNull():
            clip = QPainterPath()
            clip.addRoundedRect(rect, 14, 14)
            painter.setClipPath(clip)
            painter.drawImage(rect, state.image)
            top = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + rect.height() * 0.28))
            top.setColorAt(0.0, QColor(5, 8, 14, 150))
            top.setColorAt(1.0, QColor(5, 8, 14, 0))
            painter.fillRect(rect, top)
            if self.showcase:
                foot = QLinearGradient(QPointF(rect.left(), rect.bottom() - 80), rect.bottomLeft())
                foot.setColorAt(0.0, QColor(5, 8, 14, 0))
                foot.setColorAt(1.0, QColor(5, 8, 14, 120))
                painter.fillRect(rect, foot)
            painter.setClipping(False)
            self._boxes(painter, rect, scale)
        else:
            painter.setPen(QColor("#9AABC2"))
            painter.setFont(_font(16 * scale))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), tr("等待画面"))
        self._chrome(painter, scale)
        if self.showcase:
            self._hud(painter, scale)

    def _boxes(self, painter: QPainter, rect: QRectF, scale: float) -> None:
        result = self.page.state.result
        if not result:
            return
        rw, rh = max(1, int(result["width"])), max(1, int(result["height"]))
        sx, sy = rect.width() / rw, rect.height() / rh
        for key, slot in self.page.slots.items():
            det = slot["det"]
            x, y, w, h = det["bbox"]
            box = QRectF(rect.x() + x * sx, rect.y() + y * sy, w * sx, h * sy)
            color = class_color(str(det["class"]))
            _brackets(painter, box, color, slot["alpha"])
            _label(painter, box, det, color, slot["alpha"], rect, scale)

    def _chrome(self, painter: QPainter, scale: float) -> None:
        state = self.page.state
        title = state.title or tr("模型展示")
        left = 28 * scale
        top = 22 * scale
        badge = self._badge_box(painter, scale)
        logo = state.logo
        if logo is not None and not logo.isNull():
            lh = 42 * scale
            lw = lh * logo.width() / max(1, logo.height())
            right_edge = badge["x"] - 12 * scale
            positions = {
                "左上": (left, top),
                "右上": (right_edge - lw, top),
                "左下": (left, self.height() - top - lh - (150 * scale if self.showcase else 0)),
                "右下": (self.width() - left - lw, self.height() - top - lh - (150 * scale if self.showcase else 0)),
            }
            lx, ly = positions.get(state.logo_pos, positions["左上"])
            painter.drawImage(QRectF(lx, ly, lw, lh), logo)
            if state.logo_pos == "左上":
                left = lx + lw + 14 * scale
        title_width = max(160 * scale, badge["x"] - left - 18 * scale)
        painter.setPen(QColor("#F4F7FB"))
        painter.setFont(_font(28 * scale, QFont.Weight.DemiBold))
        painter.drawText(QRectF(left, top - 4, title_width, 36 * scale),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), title)
        cursor = top + 34 * scale
        if state.customer:
            painter.setPen(QColor("#A9B6C9"))
            painter.setFont(_font(14 * scale))
            painter.drawText(QRectF(left, cursor, title_width, 22 * scale),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), state.customer)
            cursor += 22 * scale
        if badge["detail"]:
            painter.setPen(QColor("#D5DEEA"))
            painter.setFont(_font(13 * scale))
            painter.drawText(QRectF(left, cursor, title_width, 20 * scale),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), badge["detail"])
        self._draw_badge(painter, badge)

    def _badge_box(self, painter: QPainter, scale: float) -> dict[str, Any]:
        title, detail = badge_copy(self.page.kind)
        painter.setFont(_font(12 * scale, QFont.Weight.DemiBold))
        metrics = painter.fontMetrics()
        pad = 12 * scale
        pill_w = metrics.horizontalAdvance(title) + pad * 2
        pill_h = metrics.height() + 8
        colors = {
            "demo": ("#3A2A12", "#F0C36A"),
            "replay": ("#1A2744", "#A9C4FF"),
            "replay_demo": ("#1A2744", "#A9C4FF"),
            "board": ("#12321F", "#7DDCB0"),
            "unconfigured": ("#3A2A12", "#F0C36A"),
            "waiting": ("#1A2230", "#C5D0E0"),
            "offline": ("#1A2230", "#C5D0E0"),
        }
        fill, ink = colors.get(self.page.kind, colors["waiting"])
        return {
            "title": title, "detail": detail, "scale": scale,
            "x": self.width() - pill_w - 24 * scale, "y": 24 * scale,
            "w": pill_w, "h": pill_h, "fill": fill, "ink": ink,
        }

    def _draw_badge(self, painter: QPainter, badge: dict[str, Any]) -> None:
        rect = QRectF(badge["x"], badge["y"], badge["w"], badge["h"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(badge["fill"]))
        painter.drawRoundedRect(rect, badge["h"] / 2, badge["h"] / 2)
        painter.setPen(QColor(badge["ink"]))
        painter.setFont(_font(12 * badge["scale"], QFont.Weight.DemiBold))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), badge["title"])

    def _hud(self, painter: QPainter, scale: float) -> None:
        page = self.page
        cards = (
            (tr("推理帧率"), f"{page.fps_value:0.1f}", "fps", "#8FB4FF", page.fps_samples),
            (tr("时延"), f"{page.latency_value:0.1f}", "ms", "#E4C27A", page.latency_samples),
            (tr("目标"), str(len(page.visible_detections())), "", "#7DDCB0", []),
        )
        gap = 12 * scale
        card_w, card_h = 196 * scale, 96 * scale
        x = 28 * scale
        y = self.height() - card_h - 28 * scale
        for caption, value, unit, color, samples in cards:
            rect = QRectF(x, y, card_w, card_h)
            painter.setPen(QPen(QColor(160, 190, 255, 40), 1))
            painter.setBrush(QColor(12, 18, 32, 210))
            painter.drawRoundedRect(rect, 14, 14)
            painter.setPen(QColor("#93A4BA"))
            painter.setFont(_font(11 * scale, QFont.Weight.Medium))
            painter.drawText(rect.adjusted(14, 8, -10, 0), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), caption)
            painter.setPen(QColor("#F4F7FB"))
            painter.setFont(_font(30 * scale, QFont.Weight.DemiBold))
            painter.drawText(rect.adjusted(14, 26, -10, 0), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), value)
            if unit:
                painter.setFont(_font(12 * scale))
                painter.setPen(QColor(color))
                painter.drawText(rect.adjusted(14, 62, -10, -8), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), unit)
            if len(samples) >= 2:
                self._mini_spark(painter, QRectF(rect.right() - 78 * scale, rect.top() + 36 * scale, 64 * scale, 40 * scale),
                                 samples, QColor(color))
            x += card_w + gap
        zoom = QRectF(self.width() - 280 * scale - 28 * scale, y, 280 * scale, card_h)
        det = page.zoom_detection()
        _draw_zoom(painter, zoom, page.state.image, det, page.state.result, scale)
        painter.setPen(QColor("#8EA0B8"))
        painter.setFont(_font(11 * scale))
        caption = tr("局部放大")
        if det is not None:
            caption = f"{tr('局部放大')}  ·  {det['class']}"
        painter.drawText(QRectF(zoom.x(), zoom.y() - 18 * scale, zoom.width(), 16 * scale),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), caption)
        painter.setPen(QColor(255, 255, 255, 80))
        painter.drawText(QRectF(0, self.height() - 22 * scale, self.width(), 16 * scale),
                         int(Qt.AlignmentFlag.AlignCenter), tr("Esc 退出"))

    def _mini_spark(self, painter: QPainter, rect: QRectF, samples: list[float], color: QColor) -> None:
        values = samples[-32:]
        low, high = min(values), max(values)
        if high - low < 1e-3:
            low, high = low - 1, high + 1
        path = QPainterPath()
        for index, value in enumerate(values):
            px = rect.x() + index / (len(values) - 1) * rect.width()
            py = rect.bottom() - (value - low) / (high - low) * rect.height()
            if index == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(path)


class ZoomCard(QWidget):
    def __init__(self, page: "ModelDemoPage") -> None:
        super().__init__()
        self.page = page
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        det = self.page.zoom_detection()
        margin = QRectF(0, 18, self.width(), self.height() - 18)
        _draw_zoom(painter, margin.adjusted(0, 0, -1, -1), self.page.state.image, det, self.page.state.result, self.page.ui_scale)
        painter.setPen(QColor("#93A4BA"))
        painter.setFont(_font(11 * self.page.ui_scale, QFont.Weight.DemiBold))
        text = tr("局部放大")
        if det is not None:
            text = f"{tr('局部放大')}  ·  {det['class']}  {float(det['score']):.2f}"
        painter.drawText(QRectF(0, 0, self.width(), 16), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)


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


def _chrome_qss(scale: float) -> str:
    """Styles for the demo page only.

    Every selector is anchored to ``#demoRoot``. Qt applies a widget stylesheet
    more broadly than the widget subtree, and an unscoped ``QComboBox`` rule
    was stretching the shared footer on the other pages.
    """
    kpi = int(round(32 * scale))
    body = int(round(13 * scale))
    small = int(round(11 * scale))
    root = "QWidget#demoRoot"
    return f"""
    {root} {{ background: #070B12; color: #E7EEF8; }}
    {root} QFrame#glass {{ background: #101826; border: 1px solid rgba(160, 190, 255, 0.16); border-radius: 16px; }}
    {root} QLabel#muted {{ color: #93A4BA; font-size: {small}px; background: transparent; }}
    {root} QLabel#kpi {{ color: #F4F7FB; font-size: {kpi}px; font-weight: 650; background: transparent; }}
    {root} QLabel#body {{ color: #E7EEF8; font-size: {body}px; background: transparent; }}
    {root} QLineEdit, {root} QComboBox {{
        background: #0C1422; color: #E7EEF8; border: 1px solid rgba(160, 190, 255, 0.20);
        border-radius: 8px; padding: 4px 8px; min-height: 20px; font-size: {body}px;
    }}
    {root} QComboBox QAbstractItemView {{ background: #101826; color: #E7EEF8; selection-background-color: #24406E; }}
    {root} QPushButton#demoBtn, {root} QPushButton#demoChip {{
        background: #152033; color: #D5DDEC; border: 1px solid rgba(160, 190, 255, 0.16);
        border-radius: 8px; padding: 6px 10px; font-size: {body}px;
    }}
    {root} QPushButton#demoBtn:checked, {root} QPushButton#demoChip:checked {{
        background: #1B3E78; color: #FFFFFF; border-color: #6C97E8;
    }}
    {root} QPushButton#demoPrimary {{
        background: #2C6BED; color: #FFFFFF; border: none; border-radius: 8px;
        padding: 6px 14px; font-size: {body}px; font-weight: 600;
    }}
    {root} QSlider::groove:horizontal {{ height: 4px; background: #243044; border-radius: 2px; }}
    {root} QSlider::sub-page:horizontal {{ background: #6C97E8; border-radius: 2px; }}
    {root} QSlider::handle:horizontal {{
        width: 14px; height: 14px; margin: -6px 0; background: #F4F7FB; border-radius: 7px;
    }}
    """


class _State:
    def __init__(self) -> None:
        self.image = QImage()
        self.result: dict[str, Any] | None = None
        self.title = ""
        self.customer = ""
        self.logo = QImage()
        self.logo_pos = "左上"


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
        self._build()
        self._apply_prefs()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.step)
        self._restyle()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)
        body = QHBoxLayout()
        body.setSpacing(12)
        self.stage = Stage(self, showcase=False)
        self.rail = self._rail()
        body.addWidget(self.stage, 1)
        body.addWidget(self.rail, 0)
        root.addLayout(body, 1)
        self.operator = self._operator()
        root.addWidget(self.operator)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

    def _rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("glass")
        rail.setFixedWidth(300)
        self.rail_frame = rail
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        self.fps_caption, self.fps_label, self.fps_spark = self._kpi(layout, "推理帧率", "fps", "#8FB4FF")
        self.lat_caption, self.lat_label, self.lat_spark = self._kpi(layout, "时延", "ms", "#E4C27A")
        self.count_caption = QLabel(tr("目标"))
        self.count_caption.setObjectName("muted")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("kpi")
        layout.addWidget(self.count_caption)
        layout.addWidget(self.count_label)
        self.count_box = QVBoxLayout()
        self.count_box.setSpacing(2)
        layout.addLayout(self.count_box)
        self.count_rows: dict[str, QLabel] = {}
        self.zoom = ZoomCard(self)
        layout.addWidget(self.zoom, 1)
        self.health_caption = QLabel(tr("示意读数，不是板端"))
        self.health_caption.setObjectName("muted")
        layout.addWidget(self.health_caption)
        self.health_rows = {}
        for key, caption in (("temp", "温度"), ("cpu", "CPU"), ("mem", "内存")):
            row = QHBoxLayout()
            name = QLabel(tr(caption))
            name.setObjectName("body")
            value = QLabel("—")
            value.setObjectName("body")
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(name)
            row.addWidget(value, 1)
            layout.addLayout(row)
            self.health_rows[key] = value
        return rail

    def _kpi(self, layout: QVBoxLayout, caption: str, unit: str, color: str):
        cap = QLabel(tr(caption))
        cap.setObjectName("muted")
        value = QLabel("—")
        value.setObjectName("kpi")
        unit_label = QLabel(unit)
        unit_label.setObjectName("muted")
        layout.addWidget(cap)
        row = QHBoxLayout()
        row.addWidget(value, 1)
        row.addWidget(unit_label, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(row)
        spark = Sparkline(color)
        layout.addWidget(spark)
        return cap, value, spark

    def _operator(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("glass")
        self.operator_frame = bar
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)
        sources = QHBoxLayout()
        sources.setSpacing(6)
        self.source_group = QButtonGroup(self)
        self.source_group.setExclusive(True)
        self.source_buttons = {}
        for key, text in (("synthetic", "合成场景"), ("video", "视频文件"), ("camera", "本机摄像头"),
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
        outer.addLayout(sources)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self._cap("置信度"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(self.min_score * 100)))
        self.slider.valueChanged.connect(self._score_changed)
        self.score_label = QLabel("0.25")
        self.score_label.setObjectName("body")
        self.score_label.setMinimumWidth(36)
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
        self.customer_edit.setPlaceholderText(tr("客户名称"))
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
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        outer.addLayout(self.chips)
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
        self.ui_scale = max(0.82, min(height / 900.0, 2.0))
        compact = height < 860
        rail = 320 if self.width() >= 1500 else 280 if self.width() >= 1180 else 248
        self.rail_frame.setFixedWidth(rail)
        rail_layout = self.rail_frame.layout()
        gap = 6 if compact else 10
        margin = 10 if compact else 14
        rail_layout.setSpacing(gap)
        rail_layout.setContentsMargins(margin, margin, margin, margin)
        self.fps_spark.setVisible(not compact)
        self.lat_spark.setVisible(not compact)
        self.zoom.setMinimumHeight(96 if compact else 150)
        bar = self.operator.layout()
        bar.setSpacing(4 if compact else 8)
        bar.setContentsMargins(10, 6, 10, 6) if compact else bar.setContentsMargins(12, 10, 12, 10)
        self.setStyleSheet(_chrome_qss(self.ui_scale))
        for label in (self.fps_label, self.lat_label, self.count_label):
            label.setFont(_font((26 if compact else 32) * self.ui_scale, QFont.Weight.DemiBold))

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
            result = demo_overlay(self._frame_id, SCENE_W, SCENE_H)
            self.state.image = paint_scene(result)
        self.state.result = result
        self.kind = "demo"
        self._note(result, now)
        health = _demo_meters(self._frame_id)
        self._paint_health(health, preview=True)

    def _step_replay(self, now: float) -> None:
        if not self._replay:
            self.kind = "replay"
            self.state.result = None
            return
        result = self._replay[self._replay_index % len(self._replay)]
        self._replay_index += 1
        self.state.result = result
        self.state.image = paint_scene(result)
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
        """Test hook: one board frame without a network poll."""
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
        del self.fps_samples[:-48]
        del self.latency_samples[:-48]
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
        self.stage.update()
        self.zoom.update()

    def _publish(self) -> None:
        self.fps_label.setText(f"{self.fps_value:0.1f}")
        self.lat_label.setText(f"{self.latency_value:0.1f}")
        rows = self.visible_detections()
        counts = class_counts(rows)
        self.count_label.setText(str(len(rows)))
        self._sync_count_rows(counts)
        self._sync_chips()
        self.fps_spark.samples = list(self.fps_samples)
        self.lat_spark.samples = list(self.latency_samples)
        self.fps_spark.update()
        self.lat_spark.update()
        self.stage.update()
        self.zoom.update()
        if self._showcase is not None and self._showcase.isVisible():
            self._showcase.stage.update()

    def _sync_count_rows(self, counts: dict[str, int]) -> None:
        if list(self.count_rows) != list(counts):
            while self.count_box.count():
                item = self.count_box.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.count_rows = {}
            for name in counts:
                label = QLabel()
                label.setObjectName("body")
                self.count_box.addWidget(label)
                self.count_rows[name] = label
        for name, label in self.count_rows.items():
            label.setText(f"{name}   {counts.get(name, 0)}")

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
            chip = QPushButton(name)
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
        else:
            self.health_rows["mem"].setText(f"{used / total * 100:.0f}%")

    def _score_changed(self, value: int) -> None:
        self.min_score = value / 100
        PREFS["min_score"] = self.min_score
        self.score_label.setText(f"{self.min_score:.2f}")
        self.slots.clear()
        self._publish()

    def _follow_changed(self) -> None:
        self.follow = str(self.follow_box.currentData() or "small")
        PREFS["follow"] = self.follow
        self.zoom.update()

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
        self.stage.update()

    def _customer_changed(self, text: str) -> None:
        self.state.customer = text.strip()
        PREFS["customer"] = self.state.customer
        self.stage.update()

    def _logo_pos_changed(self) -> None:
        self.state.logo_pos = str(self.logo_pos.currentData() or "左上")
        PREFS["logo_pos"] = self.state.logo_pos
        self.stage.update()

    def _choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("选择 Logo"), "", "Image (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            return
        self.state.logo = image
        PREFS["logo"] = path
        self.stage.update()

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
        self._showcase.stage.page = self
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            self._showcase.resize(1920, 1080)
            self._showcase.show()
        else:
            self._showcase.showFullScreen()
        if not self.timer.isActive():
            self.timer.start(33)
        self._showcase.stage.update()

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
        self.stage = Stage(page, showcase=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stage)
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


def _ffmpeg_file(path: str) -> list[str] | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1", "-i", path,
            "-an", "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x070B12",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]


def _ffmpeg_camera() -> list[str] | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    if os.name == "nt":
        return [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "dshow", "-i", "video=0",
                "-an", "-vf", "scale=1280:720", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    device = "/dev/video0"
    if not Path(device).exists():
        return None
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "v4l2", "-i", device,
            "-an", "-vf", "scale=1280:720", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]

