"""v10: one consistent line-icon set (Lucide, ISC) rendered crisply at any devicePixelRatio, theme-aware.

SVGs are vendored in assets/icons (see ATTRIBUTION.md / LICENSE). Nothing is fetched at runtime.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import theme

SIZES = (16, 20, 24)
DPRS = (1.0, 1.25, 1.5, 2.0)
STROKE = {12: 2.1, 14: 2.0, 16: 1.9, 18: 1.8, 20: 1.75, 22: 1.7, 24: 1.6}  # optical: thinner strokes as icons grow

# role -> light-theme colour; theme.color() maps it to dark. Accent text stays white on blue.
ROLES = {"normal": "#48484A", "muted": "#86868B", "active": "#1D1D1F", "accent": "#0071E3", "disabled": "#C7C7CC",
         "onAccent": "#FFFFFF", "ok": "#1E8E3E", "warn": "#B25000", "error": "#D70015", "info": "#0066CC"}

ICONS = {'nav.lab': 'aperture', 'nav.pc': 'monitor', 'nav.board': 'circuit-board', 'nav.periph': 'cable', 'nav.sessions': 'history', 'nav.settings': 'settings', 'dev.usb': 'usb', 'dev.video': 'camera', 'dev.serial': 'terminal', 'dev.i2c': 'waypoints', 'dev.spi': 'binary', 'dev.net': 'network', 'dev.storage': 'hard-drive', 'dev.audio': 'audio-lines', 'dev.gpio': 'git-branch-plus', 'dev.display': 'monitor-smartphone', 'dev.pci': 'microchip', 'dev.board': 'circuit-board', 'dev.cpu': 'cpu', 'dev.memory': 'memory-stick', 'dev.temp': 'thermometer', 'dev.other': 'plug-zap', 'act.connect': 'link', 'act.disconnect': 'unplug', 'act.scan': 'radar', 'act.detect': 'scan-search', 'act.preview': 'scan', 'act.apply': 'circle-play', 'act.record': 'circle-dot', 'act.stop': 'square', 'act.live': 'video', 'act.live_stop': 'video-off', 'act.refresh': 'refresh-cw', 'act.terminal': 'terminal', 'act.copy': 'copy', 'act.export': 'upload', 'act.download': 'download', 'act.folder': 'folder-open', 'act.list': 'list', 'act.health': 'stethoscope', 'act.search': 'search', 'act.check': 'clipboard-check', 'act.close': 'x', 'act.next': 'chevron-right', 'act.back': 'chevron-left', 'act.fullscreen': 'maximize-2', 'act.keyboard': 'keyboard', 'act.save': 'save', 'act.clear': 'trash-2', 'act.wizard': 'wand-sparkles', 'act.send': 'send', 'act.play': 'play', 'act.pause': 'pause', 'act.ok': 'check', 'act.skip': 'arrow-right', 'act.fill': 'rotate-ccw', 'act.params': 'sliders-horizontal', 'act.template': 'layers', 'act.lang': 'languages', 'st.ok': 'circle-check', 'st.info': 'info', 'st.warn': 'triangle-alert', 'st.error': 'circle-alert', 'st.fail': 'circle-x', 'st.dot': 'circle', 'st.idle': 'clock', 'st.empty': 'camera-off', 'ui.chevron': 'chevron-down', 'ui.light': 'sun', 'ui.dark': 'moon', 'ui.auto': 'sun-moon', 'ui.gauge': 'gauge', 'ui.image': 'image', 'ui.file': 'file-text', 'ui.activity': 'activity'}

# Chinese source text of a button -> semantic icon (buttons are created from source text before tr()).
BUTTON_ICONS = {
    "连接": "act.connect", "保存并连接": "act.connect", "扫描局域网": "act.scan", "识别并预览": "act.detect", "检测": "act.detect",
    "应用并预览": "act.apply", "预览一帧": "act.preview", "预览": "act.preview", "开始采集": "act.record", "录 60 秒": "act.record",
    "仍然开始": "act.record", "停止并取回": "act.stop", "停止并校验": "act.stop", "实时": "act.live", "停止实时": "act.live_stop",
    "刷新": "act.refresh", "终端": "act.terminal", "复制": "act.copy", "导出": "act.export", "取回": "act.download",
    "打开文件夹": "act.folder", "打开": "act.folder", "列出本机会话": "act.list", "体检": "act.health", "查找": "act.search",
    "校验": "act.check", "检查工具": "act.check", "关闭": "act.close", "下一步": "act.next", "上一步": "act.back", "大屏": "act.fullscreen",
    "快捷键": "act.keyboard", "保存": "act.save", "清空": "act.clear", "连接向导": "act.wizard", "发送": "act.send", "播放": "act.play",
    "好": "act.ok", "跳过": "act.skip", "先不录": "act.skip", "填入当前": "act.fill", "读取参数": "act.params", "扫描 I2C": "act.scan",
    "查看全部外设": "act.next", "选择": "act.folder", "板端": "dev.board", "本机": "nav.pc",
}

CATEGORY_ICONS = {"usb": "dev.usb", "video": "dev.video", "serial": "dev.serial", "i2c": "dev.i2c", "spi": "dev.spi",
                  "net": "dev.net", "storage": "dev.storage", "audio": "dev.audio", "gpio": "dev.gpio",
                  "display": "dev.display", "pci": "dev.pci"}


def icon_dir() -> Path:
    # frozen builds bundle the folder next to this module (build_portable --add-data), so one rule serves both
    return Path(__file__).resolve().parent / "assets" / "icons"


def file_for(name: str) -> Path:
    return icon_dir() / f"{ICONS.get(name, name)}.svg"


def role_color(role: str) -> str:
    value = ROLES.get(role, role)
    return value if role == "onAccent" else theme.color(value)


@lru_cache(maxsize=512)
def svg_bytes(name: str, color: str, stroke: float) -> bytes:
    text = file_for(name).read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = text.replace("currentColor", color)
    text = re.sub(r'stroke-width="[0-9.]+"', f'stroke-width="{stroke:g}"', text)
    return text.encode("utf-8")


def stroke_for(size: int) -> float:
    return STROKE.get(size, 1.75)


def pixmap(name: str, size: int = 20, role: str = "normal", dpr: float = 1.0):
    """Crisp pixmap: rasterised at size*dpr device pixels, tagged with dpr so Qt draws it 1:1."""
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    px = max(1, round(size * dpr))
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg_bytes(name, role_color(role), stroke_for(size))))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(dpr)
    return result


def icon(name: str, size: int = 20, role: str = "normal", active: str = "active", selected: str = ""):
    """QIcon with Normal/Active(hover)/Selected(checked)/Disabled modes at every supported DPR."""
    from PySide6.QtGui import QIcon
    result = QIcon()
    modes = ((QIcon.Mode.Normal, role), (QIcon.Mode.Active, active or role),
             (QIcon.Mode.Selected, selected or active or role),
             (QIcon.Mode.Disabled, "disabled" if role != "onAccent" else "onAccent"))
    for mode, which in modes:
        for dpr in DPRS:
            result.addPixmap(pixmap(name, size, which, dpr), mode, QIcon.State.Off)
        if selected:
            for dpr in DPRS:
                result.addPixmap(pixmap(name, size, selected, dpr), mode, QIcon.State.On)
    return result


def tile(name: str, size: int, background: str, dpr: float = 1.0):
    """Device-type badge: white glyph on a rounded colour tile (iOS settings style)."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    px = max(1, round(size * dpr))
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(QRectF(0, 0, px, px), px * 0.26, px * 0.26)
    glyph = pixmap(name, 16 if size >= 22 else 14, "onAccent", dpr)
    glyph.setDevicePixelRatio(1.0)
    offset = (px - glyph.width()) / 2
    painter.drawPixmap(int(round(offset)), int(round(offset)), glyph)
    painter.end()
    out = QPixmap.fromImage(image)
    out.setDevicePixelRatio(dpr)
    return out


def tile_icon(name: str, size: int, background: str):
    from PySide6.QtGui import QIcon
    result = QIcon()
    for dpr in DPRS:
        result.addPixmap(tile(name, size, background, dpr))
    return result


def app_pixmap(px: int, badge: str = ""):
    """App icon: white aperture glyph on an Apple-blue squircle with a soft vertical gradient."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    inset = px * 0.04
    rect = QRectF(inset, inset, px - 2 * inset, px - 2 * inset)
    gradient = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.bottom()))
    gradient.setColorAt(0, QColor("#2E8BFF"))
    gradient.setColorAt(1, QColor("#0062D1"))
    path = QPainterPath()
    path.addRoundedRect(rect, px * 0.225, px * 0.225)
    painter.fillPath(path, gradient)
    glyph_px = round(px * 0.6)
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer
    stroke = 2.0 if px <= 20 else (1.8 if px <= 32 else 1.6)
    renderer = QSvgRenderer(QByteArray(svg_bytes("nav.lab", "#FFFFFF", stroke)))
    offset = (px - glyph_px) / 2
    renderer.render(painter, QRectF(offset, offset, glyph_px, glyph_px))
    if badge:
        r = px * 0.17
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(px - r * 1.05, r * 1.05), r * 1.25, r * 1.25)
        painter.setBrush(QColor(badge))
        painter.drawEllipse(QPointF(px - r * 1.05, r * 1.05), r, r)
    painter.end()
    return QPixmap.fromImage(image)


def app_icon(badge: str = ""):
    from PySide6.QtGui import QIcon
    result = QIcon()
    for px in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        result.addPixmap(app_pixmap(px, badge))
    return result


def chevron_files(folder: Path, color: str) -> str:
    """Combo-box arrow for QSS; writes name.png and name@2x.png so HiDPI picks the sharp one."""
    folder.mkdir(parents=True, exist_ok=True)
    tag = color.strip("#")
    path = folder / f"cs_chevron_{tag}.png"
    for dpr, target in ((1.0, path), (2.0, folder / f"cs_chevron_{tag}@2x.png")):
        image = pixmap("ui.chevron", 12, color, dpr).toImage()
        image.setDevicePixelRatio(1.0)
        image.save(str(target))
    return path.as_posix()


def referenced() -> set[str]:
    return set(ICONS) | set(BUTTON_ICONS.values()) | set(CATEGORY_ICONS.values())
