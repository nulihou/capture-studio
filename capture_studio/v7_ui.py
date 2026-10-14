"""v7 user-experience layer for the Qt window: wizard + auto-connect, templates, health check,
friendly errors, shortcuts/indicators/notifications, session review, serial terminal, PC
peripherals, dark mode.  Mixed into StudioWindow; capture/protocol logic stays in product.py."""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget,
)

from . import credstore, discovery, errors, health, i18n, icons, lan_scan, serial_term, session_review, templates, theme
from .i2c_hints import describe as i2c_describe
from .i18n import tr, tr_msg
from .product import STUDIO

SHORTCUTS = [
    ("Space", "开始 / 停止采集"), ("F", "大屏 / 全屏预览"), ("L", "实时预览开 / 关"), ("P", "预览一帧"),
    ("H", "采集前体检"), ("R", "刷新外设 / 会话"), ("Ctrl+1…6", "切换页面"), ("Ctrl+K", "连接向导"),
    ("?", "显示快捷键"), ("Esc", "关闭弹窗 / 退出大屏"),
]


def _lbl(text: str, name: str = "field") -> QLabel:
    widget = QLabel(tr(text))
    widget.setObjectName(name)
    return widget


def _btn(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(tr(text).replace("&", "&&"))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        button.setObjectName("primary")
    from .window import _decorate
    _decorate(button, text, primary)
    return button


class _Bridge(QObject):
    """Thread -> UI hand-off."""
    scan_done = Signal(object)
    test_done = Signal(list)
    serial_data = Signal(bytes)
    thumbs_done = Signal(dict)
    frames_done = Signal(list)


# ---------------------------------------------------------------------------------------- wizard
class Wizard(QDialog):
    """First-run / on-demand: find SSH hosts on the LAN, pick the board, credentials, auto-connect."""

    def __init__(self, parent: QWidget, scanner: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("连接向导"))
        self.setModal(True)
        self.setMinimumSize(560, 520)
        self.bridge = _Bridge()
        self.bridge.scan_done.connect(self._scan_finished)
        self.bridge.test_done.connect(self._test_finished)
        self._scanner = scanner
        self._cancel = threading.Event()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(10)
        self.step_title = _lbl("第 1 步 · 找到开发板", "title")
        layout.addWidget(self.step_title)
        self.steps = QStackedWidget()
        layout.addWidget(self.steps, 1)
        # step 1: scan
        one = QWidget()
        box = QVBoxLayout(one)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        rule = _lbl(discovery.RULE_TEXT + "不登录、不扫其他端口。", "meta")
        rule.setWordWrap(True)
        box.addWidget(rule)
        row = QHBoxLayout()
        self.scan_button = _btn("扫描局域网", True)
        self.scan_button.clicked.connect(self.start_scan)
        self.scan_note = _lbl("", "meta")
        row.addWidget(self.scan_button)
        row.addWidget(self.scan_note, 1)
        box.addLayout(row)
        self.hosts = QListWidget()
        self.hosts.itemDoubleClicked.connect(lambda _item: self.next_step())
        box.addWidget(self.hosts, 1)
        manual = QHBoxLayout()
        manual.addWidget(_lbl("或手动填写地址"))
        self.host = QLineEdit()
        self.host.setPlaceholderText("192.168.1.50")
        manual.addWidget(self.host, 1)
        self.test_button = _btn("测试这个 IP")
        self.test_button.clicked.connect(self.test_host)
        manual.addWidget(self.test_button)
        box.addLayout(manual)
        self.guide = _lbl("", "meta")
        self.guide.setWordWrap(True)
        self.guide.setVisible(False)
        box.addWidget(self.guide)
        self.steps.addWidget(one)
        # step 2: credentials
        two = QWidget()
        box = QVBoxLayout(two)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addWidget(_lbl("用户"))
        self.user = QLineEdit("ubuntu")
        box.addWidget(self.user)
        box.addWidget(_lbl("密码（仅新板第一次，用来安装密钥）"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        box.addWidget(self.password)
        self.remember = QCheckBox(tr("记住密码（保存在 Windows 凭据管理器，不写入文件）"))
        self.remember.setEnabled(credstore.available())
        box.addWidget(self.remember)
        box.addWidget(_lbl("之后的登录都用本机 SSH 密钥，一般不需要密码。", "meta"))
        box.addStretch(1)
        self.steps.addWidget(two)
        # step 3: finish
        three = QWidget()
        box = QVBoxLayout(three)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.summary = _lbl("", "fact")
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        self.auto = QCheckBox(tr("下次启动时自动连接并打开实时预览（可取消）"))
        self.auto.setChecked(True)
        box.addWidget(self.auto)
        box.addStretch(1)
        self.steps.addWidget(three)
        nav = QHBoxLayout()
        self.back = _btn("上一步")
        self.back.clicked.connect(self.prev_step)
        self.skip = _btn("跳过")
        self.skip.clicked.connect(self.reject)
        self.next = _btn("下一步", True)
        self.next.clicked.connect(self.next_step)
        nav.addWidget(self.skip)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        layout.addLayout(nav)
        settings = STUDIO.state()["settings"]
        self.host.setText(str(settings.get("host") or ""))
        self.user.setText(str(settings.get("user") or "ubuntu"))
        self._sync()

    def start_scan(self) -> None:
        self.scan_button.setEnabled(False)
        self.hosts.clear()
        self.scan_note.setText(tr("正在扫描…"))
        scanner = self._scanner

        def work() -> None:
            if scanner is not None:
                found = scanner()
            else:
                found = discovery.discover(cancel=self._cancel.is_set)
            if isinstance(found, list):
                found = {"found": found, "guidance": []}
            self.bridge.scan_done.emit(found)

        threading.Thread(target=work, daemon=True).start()

    def test_host(self) -> None:
        host = self.host.text().strip()
        if not host:
            self.scan_note.setText(tr("请选择或填写开发板地址"))
            return
        self.test_button.setEnabled(False)
        self.scan_note.setText(tr("正在测试…"))
        threading.Thread(target=lambda: self.bridge.test_done.emit(list(discovery.test_one(host))), daemon=True).start()

    def _test_finished(self, result: list) -> None:
        self.test_button.setEnabled(True)
        self.scan_note.setText(tr_msg(result[1]))

    def _scan_finished(self, result: Any) -> None:
        result = {"found": result, "guidance": []} if isinstance(result, list) else result
        found = [item if "kind" in item else discovery.classify(dict(item)) for item in result.get("found", [])]
        tips = result.get("guidance") or []
        self.guide.setText("\n".join(tr_msg(t) for t in tips))
        self.guide.setVisible(bool(tips))
        self.hosts.clear()
        self.scan_button.setEnabled(True)
        self.scan_note.setText(tr_msg(f"找到 {len(found)} 台可 SSH 的设备") if found else tr("没有找到，可以手动填写地址"))
        for item in found:
            row = QListWidgetItem(discovery.label_for(item, tr_msg))
            row.setIcon(icons.icon({"board": "dev.board", "pc": "nav.pc"}.get(item["kind"], "dev.net"), 16))
            row.setData(Qt.ItemDataRole.UserRole, item["host"])
            row.setToolTip(item.get("banner") or "")
            self.hosts.addItem(row)
        if found:
            self.hosts.setCurrentRow(0)

    def chosen_host(self) -> str:
        item = self.hosts.currentItem()
        if item is not None and not self.host.hasFocus() and self.host.text().strip() in ("", STUDIO.settings.get("host")):
            return str(item.data(Qt.ItemDataRole.UserRole))
        return self.host.text().strip() or (str(item.data(Qt.ItemDataRole.UserRole)) if item else "")

    def _sync(self) -> None:
        index = self.steps.currentIndex()
        self.step_title.setText(tr(["第 1 步 · 找到开发板", "第 2 步 · 登录方式", "第 3 步 · 完成"][index]))
        self.back.setEnabled(index > 0)
        self.next.setText(tr("连接" if index == 2 else "下一步"))
        if index == 2:
            self.summary.setText(f"{self.user.text().strip() or 'ubuntu'}@{self.chosen_host()}")

    def prev_step(self) -> None:
        self.steps.setCurrentIndex(max(0, self.steps.currentIndex() - 1))
        self._sync()

    def next_step(self) -> None:
        index = self.steps.currentIndex()
        if index == 0 and not self.chosen_host():
            self.scan_note.setText(tr("请选择或填写开发板地址"))
            return
        if index < 2:
            if index == 0:
                self.host.setText(self.chosen_host())
            self.steps.setCurrentIndex(index + 1)
            self._sync()
            return
        self.accept()

    def result_payload(self) -> dict[str, Any]:
        return {"host": self.host.text().strip() or self.chosen_host(), "user": self.user.text().strip() or "ubuntu",
                "password": self.password.text(), "remember": self.remember.isChecked() and bool(self.password.text()),
                "auto_connect": "1" if self.auto.isChecked() else "", "wizard_done": "1"}

    def reject(self) -> None:
        self._cancel.set()
        super().reject()


# ---------------------------------------------------------------------------------------- health
class HealthDialog(QDialog):
    def __init__(self, parent: QWidget, items: list[dict[str, str]], ask_start: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("采集前体检"))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(10)
        level = health.worst(items)
        head = {"ok": "一切就绪", "warn": "可以开始，但有几点建议", "fail": "建议先处理以下问题"}[level]
        layout.addWidget(_lbl(head, "title"))
        self.rows = []
        for item in items:
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(14, 10, 14, 10)
            box.setSpacing(2)
            role = {"ok": "ok", "warn": "warn", "fail": "error"}[item["level"]]
            glyph = {"ok": "st.ok", "warn": "st.warn", "fail": "st.fail"}[item["level"]]
            line = QHBoxLayout()
            line.setSpacing(8)
            mark = QLabel()
            mark.setObjectName("glyph")
            mark.setProperty("level", item["level"])
            mark.setPixmap(icons.pixmap(glyph, 16, role, self.devicePixelRatioF()))
            mark.setFixedSize(16, 18)
            mark.setAlignment(Qt.AlignmentFlag.AlignTop)
            line.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            title = QLabel(f"<b>{tr_msg(item['title'])}</b> · {tr_msg(item['detail'])}")
            title.setObjectName("field")
            title.setWordWrap(True)
            line.addWidget(title, 1)
            box.addLayout(line)
            if item.get("fix"):
                fix = QLabel("→ " + tr_msg(item["fix"]))
                fix.setObjectName("meta")
                fix.setWordWrap(True)
                box.addWidget(fix)
            layout.addWidget(card)
            self.rows.append(item)
        row = QHBoxLayout()
        row.addStretch(1)
        if ask_start:
            cancel = _btn("先不录")
            cancel.clicked.connect(self.reject)
            go = _btn("仍然开始" if level != "ok" else "开始采集", True)
            go.clicked.connect(self.accept)
            row.addWidget(cancel)
            row.addWidget(go)
        else:
            close = _btn("好", True)
            close.clicked.connect(self.accept)
            row.addWidget(close)
        layout.addLayout(row)


# ---------------------------------------------------------------------------------------- serial
class SerialTerminal(QDialog):
    def __init__(self, parent: QWidget, port: str, side: str, opener: Any = None) -> None:
        super().__init__(parent)
        self.port, self.side, self._opener = port, side, opener
        self.session: serial_term.Session | None = None
        self.received = bytearray()
        self.bridge = _Bridge()
        self.bridge.serial_data.connect(self._append)
        self.setWindowTitle(tr("串口终端") + f" · {port}")
        self.setMinimumSize(640, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(_lbl(f"{port}", "cardTitle"))
        top.addWidget(_lbl("开发板" if side == "board" else "电脑", "pill"))
        top.addStretch(1)
        top.addWidget(_lbl("波特率"))
        self.baud = QComboBox()
        for baud in serial_term.BAUDS:
            self.baud.addItem(str(baud), baud)
        self.baud.setCurrentIndex(serial_term.BAUDS.index(115200))
        top.addWidget(self.baud)
        self.hex_view = QCheckBox(tr("十六进制显示"))
        self.hex_view.toggled.connect(lambda _on: self._render())
        top.addWidget(self.hex_view)
        self.open_button = _btn("打开", True)
        self.open_button.clicked.connect(self.toggle)
        top.addWidget(self.open_button)
        layout.addLayout(top)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.view.setFont(mono)
        self.view.setPlaceholderText(tr("串口只在点“打开”后才会被占用。"))
        layout.addWidget(self.view, 1)
        send = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("要发送的内容（回车发送）"))
        self.input.returnPressed.connect(self.send)
        self.hex_send = QCheckBox(tr("按十六进制发送"))
        self.ending = QComboBox()
        for label, value in (("CRLF", "\r\n"), ("LF", "\n"), ("无", "")):
            self.ending.addItem(tr(label), value)
        clear = _btn("清空")
        clear.clicked.connect(self.clear)
        go = _btn("发送")
        go.clicked.connect(self.send)
        send.addWidget(self.input, 1)
        send.addWidget(self.hex_send)
        send.addWidget(self.ending)
        send.addWidget(clear)
        send.addWidget(go)
        layout.addLayout(send)
        self.note = _lbl("", "meta")
        layout.addWidget(self.note)

    def toggle(self) -> None:
        if self.session is not None:
            self.close_port()
            return
        baud = int(self.baud.currentData())
        try:
            if self._opener is not None:
                self.session = self._opener(self.port, baud)
            elif self.side == "board":
                self.session = serial_term.open_board(list(STUDIO.ssh_args), self.port, baud)
            else:
                self.session = serial_term.open_pc(self.port, baud)
            self.session.start(self.bridge.serial_data.emit)
        except Exception as exc:
            self.session = None
            self.note.setText(tr_msg(errors.friendly(str(exc))["title"]) + f" · {exc}")
            return
        self.open_button.setText(tr("关闭"))
        self.baud.setEnabled(False)
        self.note.setText(tr_msg(f"已打开 {self.port} @ {baud}"))

    def close_port(self) -> None:
        if self.session is not None:
            self.session.close()
        self.session = None
        self.open_button.setText(tr("打开"))
        self.baud.setEnabled(True)
        self.note.setText(tr("已关闭"))

    def send(self) -> None:
        if self.session is None:
            self.note.setText(tr("先打开串口"))
            return
        try:
            data = serial_term.parse_send(self.input.text(), self.hex_send.isChecked(), str(self.ending.currentData()))
        except ValueError as exc:
            self.note.setText(tr_msg(str(exc)))
            return
        self.session.write(data)
        self.input.clear()

    def _append(self, data: bytes) -> None:
        self.received += data
        del self.received[:-65536]
        self._render()

    def _render(self) -> None:
        if self.hex_view.isChecked():
            text = serial_term.hexdump(bytes(self.received))
        else:
            text = bytes(self.received).decode("utf-8", "replace")
        self.view.setPlainText(text)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def clear(self) -> None:
        self.received.clear()
        self._render()

    def done(self, result: int) -> None:
        self.close_port()
        super().done(result)


# ---------------------------------------------------------------------------------------- mixin
class V7Mixin:
    """Methods mixed into StudioWindow."""

    # ----- setup
    def _v7_init(self) -> None:
        self.bridge = _Bridge()
        self.bridge.thumbs_done.connect(self._thumbs_ready)
        self.bridge.frames_done.connect(self._frames_ready)
        self._was_recording = ""
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_tick)
        self._auto_left = 0
        self._auto_preview = False
        self._tray: QSystemTrayIcon | None = None
        self._play_frames: list[Path] = []
        self._play_index = 0
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._play_tick)
        self._thumbs: dict[str, str] = {}
        self._last_notified = ""
        self.notifications: list[str] = []
        self._shortcuts()
        hints = QApplication.styleHints()
        try:
            hints.colorSchemeChanged.connect(lambda _scheme: self._system_theme_changed())
        except AttributeError:
            pass

    def _shortcuts(self) -> None:
        def key(seq: str, slot: Any) -> None:
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda: None if self._typing() else slot())
        key("Space", self.toggle_capture)
        key("F", self.open_large)
        key("L", self.toggle_live)
        key("P", lambda: STUDIO.snap(self.payload(), "pc" if self.current_page == "pc" else "board"))
        key("H", lambda: self.show_health(False))
        key("R", self._refresh_shortcut)
        key("?", self.show_cheatsheet)
        key("Shift+/", self.show_cheatsheet)
        key("Ctrl+K", self.open_wizard)
        for index, page in enumerate(("lab", "pc", "board", "periph", "sessions", "settings"), 1):
            key(f"Ctrl+{index}", lambda name=page: self.show_page(name))

    def _typing(self) -> bool:
        focus = QApplication.focusWidget()
        return isinstance(focus, (QLineEdit, QPlainTextEdit)) or (isinstance(focus, QComboBox) and focus.isEditable())

    def _refresh_shortcut(self) -> None:
        if self.current_page == "periph":
            STUDIO.scan_peripherals()
            STUDIO.scan_pc_peripherals()
        elif self.current_page == "sessions":
            self._list_sessions(self.session_source or "local")

    # ----- builders used by window.py
    def _v7_nav_extras(self, layout: QVBoxLayout) -> None:
        wizard = QPushButton(tr("连接向导"))
        wizard.setObjectName("nav")
        wizard.setCursor(Qt.CursorShape.PointingHandCursor)
        wizard.clicked.connect(self.open_wizard)
        wizard.setIcon(icons.icon("act.wizard", 20, "muted", "active")); wizard.setIconSize(QSize(20, 20))
        wizard.setToolTip(tr("连接向导") + "  ·  Ctrl+K")
        layout.addWidget(wizard)
        keys = QPushButton(tr("快捷键"))
        keys.setObjectName("nav")
        keys.setCursor(Qt.CursorShape.PointingHandCursor)
        keys.clicked.connect(self.show_cheatsheet)
        keys.setIcon(icons.icon("act.keyboard", 20, "muted", "active")); keys.setIconSize(QSize(20, 20))
        keys.setToolTip(tr("显示快捷键") + "  ·  ?")
        layout.addWidget(keys)
        layout.addSpacing(10)

    def _theme_switch(self) -> QWidget:
        segment = QFrame()
        segment.setObjectName("segment")
        row = QHBoxLayout(segment)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        group = QButtonGroup(segment)
        group.setExclusive(True)
        current = str(STUDIO.settings.get("theme") or "跟随系统")
        self.theme_buttons: dict[str, QPushButton] = {}
        for value, text in (("跟随系统", "自动"), ("浅色", "浅色"), ("深色", "深色")):
            button = QPushButton(tr(text))
            button.setObjectName("lang")
            button.setCheckable(True)
            button.setChecked(current == value)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, v=value: self.set_theme(v))
            group.addButton(button)
            row.addWidget(button, 1)
            self.theme_buttons[value] = button
        return segment

    def _v7_stage_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("banner")
        box = QHBoxLayout(banner)
        box.setContentsMargins(14, 10, 10, 10)
        box.setSpacing(10)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.banner_title = QLabel()
        self.banner_title.setObjectName("fact")
        self.banner_text = QLabel()
        self.banner_text.setObjectName("meta")
        self.banner_text.setWordWrap(True)
        texts.addWidget(self.banner_title)
        texts.addWidget(self.banner_text)
        box.addLayout(texts, 1)
        self.banner_buttons: dict[str, QPushButton] = {}
        for key, text, slot in (("retry", "重试", self._banner_retry), ("details", "详情", self.show_error_details),
                                ("bundle", "复制诊断包", self.copy_bundle), ("connect_now", "立即连接", self._auto_now),
                                ("cancel", "取消", self._banner_cancel)):
            button = _btn(text, key in ("retry", "connect_now"))
            button.clicked.connect(slot)
            box.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            self.banner_buttons[key] = button
        banner.hide()
        self.banner = banner
        self._banner_kind = ""
        return banner

    def _v7_head_buttons(self, head: QHBoxLayout) -> None:
        check = QPushButton(tr("体检"))
        check.setObjectName("ghostLight")
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.setToolTip(tr("采集前体检") + "  ·  H")
        check.setIcon(icons.icon("act.health", 16, "normal", "active")); check.setIconSize(QSize(16, 16))
        check.clicked.connect(lambda: self.show_health(False))
        head.addWidget(check)
        self.health_button = check

    def _v7_template_button(self) -> QToolButton:
        button = QToolButton()
        button.setText(tr("模板"))
        button.setObjectName("templates")
        button.setIcon(icons.icon("act.template", 16, "normal", "active")); button.setIconSize(QSize(16, 16))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu = QMenu(button)
        menu.aboutToShow.connect(lambda: self._fill_template_menu(menu))
        button.setMenu(menu)
        self.template_button = button
        return button

    # ----- templates
    def _capture_mode(self) -> str:
        return "pc" if self.current_page == "pc" else "board"

    def _fill_template_menu(self, menu: QMenu) -> None:
        menu.clear()
        data = templates.load_all(STUDIO.templates_path())
        for name in data:
            action = menu.addAction("▶  " + name)
            action.triggered.connect(lambda _c=False, n=name: self.start_template(n))
        if data:
            menu.addSeparator()
        menu.addAction(tr("保存当前设置为模板…")).triggered.connect(lambda _c=False: self.save_template())
        if data:
            delete = menu.addMenu(tr("删除模板"))
            for name in data:
                delete.addAction(name).triggered.connect(lambda _c=False, n=name: templates.delete(STUDIO.templates_path(), n))

    def save_template(self, name: str | None = None, scene: str | None = None) -> None:
        if name is None:
            name, ok = QInputDialog.getText(self, tr("保存模板"), tr("模板名称"))
            if not ok or not name.strip():
                return
            scene, ok = QInputDialog.getText(self, tr("保存模板"), tr("场景（用于文件夹命名，可留空）"),
                                             text=str(STUDIO.settings.get("scene") or ""))
            if not ok:
                return
        data = dict(STUDIO.state()["settings"])
        data.update(self.payload())
        templates.save(STUDIO.templates_path(), name, templates.capture(data, scene or ""))
        with STUDIO.lock:
            STUDIO._log(f"已保存模板 {name}")

    def start_template(self, name: str) -> None:
        mode = self._capture_mode()
        data = templates.load_all(STUDIO.templates_path()).get(name)
        if data is None:
            return
        with STUDIO.lock:
            preview = templates.apply(dict(STUDIO.settings), data)
        merged = dict(STUDIO.state()["settings"])
        merged.update(preview)
        if not self._health_gate(mode, merged):
            return
        STUDIO.run_template(name, mode, start=True)

    # ----- capture with health gate
    def _health_items(self, mode: str, settings: dict[str, Any] | None = None) -> list[dict[str, str]]:
        state = STUDIO.state()
        settings = dict(settings or state["settings"])
        free = None
        try:
            import shutil
            path = STUDIO._output()
            probe = path if path.exists() else next((p for p in path.parents if p.exists()), path)
            free = float(shutil.disk_usage(probe).free)
        except OSError:
            pass
        link = None
        for item in state.get("peripherals") or []:
            if item["category"] == "net" and dict(item["props"]).get("状态") == "up":
                speed = dict(item["props"]).get("速率", "")
                if speed.split(" ")[0].isdigit():
                    link = float(speed.split(" ")[0])
                    break
        audit = None
        try:
            from .session_review import find_sessions
            last = next(iter(find_sessions(STUDIO._output(), limit=1)), None)
            if last is not None:
                audit = (json.loads((last / "session.json").read_text(encoding="utf-8")).get("audit")) or None
        except (OSError, ValueError):
            pass
        return health.check(settings, mode, free, state.get("board_status") or {}, str(state.get("camera_label") or ""),
                            link if mode == "board" else None, audit, state.get("board_info") or {}, self._size_history())

    def _size_history(self) -> list[dict[str, Any]]:
        """Summaries of up to 8 recent local sessions, cached 30 s; feeds the measured size estimate (v9)."""
        now = time.monotonic()
        cached = getattr(self, "_history_cache", None)
        if cached and now - cached[0] < 30:
            return cached[1]
        rows: list[dict[str, Any]] = []
        try:
            for path in session_review.find_sessions(STUDIO._output(), limit=8):
                rows.append(session_review.summarize(path))
        except OSError:
            pass
        self._history_cache = (now, rows)
        return rows

    def _health_gate(self, mode: str, settings: dict[str, Any] | None = None) -> bool:
        items = self._health_items(mode, settings)
        self.last_health = items
        if health.worst(items) == "ok":
            return True
        dialog = HealthDialog(self, items, ask_start=True)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def show_health(self, ask_start: bool = False) -> None:
        items = self._health_items(self._capture_mode())
        self.last_health = items
        self.health_dialog = HealthDialog(self, items, ask_start)
        self.health_dialog.exec()

    def start_capture(self, mode: str) -> None:
        if not self._health_gate(mode):
            return
        if mode == "lab":
            self.record_short()
        else:
            STUDIO.start_record(self.payload(), mode)

    def toggle_capture(self) -> None:
        state = STUDIO.state()
        if (state.get("recording") or {}).get("session_id"):
            STUDIO.stop_record()
            return
        if state.get("busy"):
            return
        mode = {"pc": "pc", "board": "board"}.get(self.current_page, "lab")
        if mode != "pc" and not state.get("connected"):
            self.open_wizard() if not state["settings"].get("host") else self.open_connect()
            return
        self.start_capture(mode)

    # ----- friendly errors
    def _banner_show(self, kind: str, title: str, text: str, buttons: tuple[str, ...]) -> None:
        self._banner_kind = kind
        self.banner_title.setText(title)
        self.banner_text.setText(text)
        for key, button in self.banner_buttons.items():
            button.setVisible(key in buttons)
        self.banner.show()

    def _banner_retry(self) -> None:
        STUDIO.retry()

    def _banner_cancel(self) -> None:
        if self._banner_kind == "auto":
            self.cancel_auto_connect()
        else:
            STUDIO.dismiss_error()
        self.banner.hide()
        self._banner_kind = ""

    def show_error_details(self) -> None:
        state = STUDIO.state()
        info = errors.friendly(state.get("last_error") or "")
        box = QMessageBox(self)
        box.setWindowTitle(tr("详情"))
        box.setText(tr_msg(info["title"]))
        box.setInformativeText(tr_msg(info["advice"]))
        box.setDetailedText(info["raw"])
        self.error_box = box
        box.exec()

    def copy_bundle(self, target: Path | None = None) -> Path:
        state = STUDIO.state()
        target = target or (Path(tempfile.gettempdir()) / time.strftime("capture_studio_diag_%Y%m%d_%H%M%S.zip"))
        path = errors.bundle(target, state)
        clipboard = QApplication.clipboard()
        from PySide6.QtCore import QMimeData, QUrl
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        mime.setText(str(path))
        clipboard.setMimeData(mime)
        with STUDIO.lock:
            STUDIO._log(f"诊断包已复制：{path.name}")
        return path

    # ----- wizard & auto-connect
    def open_wizard(self, scanner: Any = None) -> None:
        wizard = Wizard(self, scanner)
        self.wizard = wizard
        if wizard.exec() != QDialog.DialogCode.Accepted:
            STUDIO.update_settings({"wizard_done": "1"})
            return
        self._apply_wizard(wizard.result_payload())

    def _apply_wizard(self, result: dict[str, Any]) -> None:
        if result.get("remember"):
            credstore.save(result["user"], result["host"], result["password"])
        data = self.payload()
        data.update({k: result[k] for k in ("host", "user", "auto_connect", "wizard_done")})
        data["password"] = result.get("password") or credstore.load(result["user"], result["host"])
        self._auto_preview = True
        STUDIO.connect(data)

    def maybe_auto_connect(self, delay: int = 3) -> bool:
        settings = STUDIO.state()["settings"]
        if not settings.get("auto_connect") or not settings.get("host") or STUDIO.connected:
            return False
        self._auto_left = delay
        self._auto_tick(first=True)
        self._auto_timer.start(1000)
        return True

    def _auto_tick(self, first: bool = False) -> None:
        if not first:
            self._auto_left -= 1
        if self._auto_left <= 0:
            self._auto_timer.stop()
            self._auto_now()
            return
        host = STUDIO.settings.get("host")
        self._banner_show("auto", tr("自动连接"), tr_msg(f"{self._auto_left} 秒后连接 {host} 并打开实时预览"),
                          ("connect_now", "cancel"))

    def _auto_now(self) -> None:
        self._auto_timer.stop()
        self.banner.hide()
        self._banner_kind = ""
        settings = STUDIO.state()["settings"]
        data = self.payload()
        data["password"] = credstore.load(str(settings.get("user") or ""), str(settings.get("host") or ""))
        self._auto_preview = True
        STUDIO.connect(data)

    def cancel_auto_connect(self) -> None:
        self._auto_timer.stop()
        self._auto_preview = False
        with STUDIO.lock:
            STUDIO._log("已取消自动连接")

    # ----- per-refresh work
    def _v7_refresh(self, state: dict[str, Any]) -> None:
        recording = state.get("recording") or {}
        session = str(recording.get("session_id") or "")
        if session:
            left = recording.get("remaining")
            extra = f" {left}s" if left is not None else ""
            title = f"● {tr('录制中')}{extra} — Capture Studio"
        elif state.get("live"):
            title = f"◉ {tr('实时预览中')} — Capture Studio"
        else:
            title = "Capture Studio"
        if self.windowTitle() != title:
            self.setWindowTitle(title)
            self.setWindowIcon(_dot_icon("#FF3B30" if session else ("#34C759" if state.get("live") else "")))
        if self._was_recording and not session:
            self.notify(tr("采集完成"), tr_msg(f"会话 {self._was_recording} 已结束"))
        self._was_recording = session
        if self._auto_preview and state.get("connected") and not state.get("busy"):
            self._auto_preview = False
            if not state.get("live"):
                STUDIO.start_live(self.payload())
        error = str(state.get("last_error") or "")
        if error and self._banner_kind != "auto":
            info = errors.friendly(error)
            buttons = ("details", "bundle", "cancel") + (("retry",) if info["retry"] and state.get("can_retry") else ())
            if self._banner_kind != "error" or self.banner_text.text() != tr_msg(info["advice"]):
                self._banner_show("error", tr_msg(info["title"]), tr_msg(info["advice"]), buttons)
        elif not error and self._banner_kind == "error":
            self.banner.hide()
            self._banner_kind = ""
        est = health.estimate(dict(state.get("settings") or {}), self._capture_mode(), self._size_history())
        self.tiles["stream"].setToolTip(tr_msg(f"预计 {health.human(est['bytes'])} / {int(est['seconds'])} 秒 · {est['mbps']:.0f} Mb/s")
                                        + " · " + tr(est["label"]))
        self.size_estimate = est
        self._sync_review(state)

    def notify(self, title: str, text: str) -> None:
        self.notifications.append(f"{title}: {text}")
        if hasattr(self, "toast"):
            self.toast(f"{title} · {text}")  # v11: in-window toast (fades), tray balloon below stays
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(_dot_icon("#0071E3"), self)
            self._tray.show()
        self._tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 6000)

    def show_cheatsheet(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("快捷键"))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.addWidget(_lbl("快捷键", "title"))
        for keys, text in SHORTCUTS:
            row = QHBoxLayout()
            cap = QLabel(keys)
            cap.setObjectName("pill")
            cap.setMinimumWidth(96)
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(cap)
            row.addWidget(_lbl(text), 1)
            layout.addLayout(row)
        self.cheatsheet = dialog
        dialog.exec()

    # ----- theme
    def set_theme(self, choice: str) -> None:
        STUDIO.update_settings({"theme": choice})
        self._apply_theme(choice)

    def _system_theme_changed(self) -> None:
        if str(STUDIO.settings.get("theme") or "跟随系统") == "跟随系统":
            self._apply_theme("跟随系统")

    def _apply_theme(self, choice: str) -> None:
        dark = theme.resolve(choice)
        if dark == theme.DARK_MODE and getattr(self, "_theme_applied", False):
            return
        theme.DARK_MODE = dark
        self._theme_applied = True
        from .window import STYLE, _chevron_url
        QApplication.instance().setStyleSheet(theme.css(STYLE.replace("__CHEVRON__", _chevron_url())))
        self._rebuild()

    # ----- session review
    def _v7_sessions_extras(self, layout: QVBoxLayout) -> None:
        self.review_info = QLabel("")
        self.review_info.setObjectName("meta")
        self.review_info.setWordWrap(True)
        layout.addWidget(self.review_info)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.play_button = _btn("播放")
        self.play_button.clicked.connect(self.toggle_playback)
        folder = _btn("打开文件夹")
        folder.clicked.connect(self.open_session_folder)
        row.addWidget(self.play_button)
        row.addWidget(folder)
        layout.addLayout(row)
        self.sessions.setIconSize(QSize(64, 36))
        self.sessions.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sessions.setTextElideMode(Qt.TextElideMode.ElideMiddle)

    def _sync_review(self, state: dict[str, Any]) -> None:
        if not hasattr(self, "review_info"):
            return
        rows = state.get("sessions") or []
        missing = [r for r in rows if r.get("path") and r["path"] not in self._thumbs]
        if missing and not getattr(self, "_thumb_running", False):
            self._thumb_running = True
            paths = [r["path"] for r in missing][:12]

            def work() -> None:
                out: dict[str, str] = {}
                try:
                    ffmpeg = STUDIO._tool("ffmpeg")
                except Exception:
                    ffmpeg = None
                cache = Path(tempfile.gettempdir()) / "capture_studio_thumbs"
                for path in paths:
                    summary = session_review.summarize(Path(path))
                    thumb = session_review.ensure_thumbnail(ffmpeg, summary["media"][0], cache) if ffmpeg and summary["media"] else None
                    out[path] = str(thumb or "")
                self.bridge.thumbs_done.emit(out)

            threading.Thread(target=work, daemon=True).start()
        for index in range(self.sessions.count()):
            item = self.sessions.item(index)
            path = next((r.get("path") for r in rows if r.get("session_id") == item.data(Qt.ItemDataRole.UserRole)), None)
            thumb = self._thumbs.get(path or "", "")
            if thumb and item.data(Qt.ItemDataRole.UserRole + 1) != thumb:
                item.setIcon(QIcon(QPixmap(thumb)))
                item.setData(Qt.ItemDataRole.UserRole + 1, thumb)
        summary = self._selected_summary(rows)
        text = tr_msg(session_review.describe(summary)) if summary else ""
        if self.review_info.text() != text:
            self.review_info.setText(text)
        self.play_button.setEnabled(bool(summary and summary.get("media")))

    def _thumbs_ready(self, out: dict) -> None:
        self._thumbs.update(out)
        self._thumb_running = False

    def _selected_summary(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        rows = rows if rows is not None else STUDIO.state().get("sessions") or []
        row = next((r for r in rows if r.get("session_id") == self.session_id and r.get("path")), None)
        if row is None:
            return None
        cache = getattr(self, "_summary_cache", {})
        self._summary_cache = cache
        if row["path"] not in cache:
            cache[row["path"]] = session_review.summarize(Path(row["path"]))
        return cache[row["path"]]

    def open_session_folder(self) -> None:
        summary = self._selected_summary()
        if summary:
            import os
            os.startfile(summary["path"])  # Windows only

    def toggle_playback(self) -> None:
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.play_button.setText(tr("播放"))
            self.live_label.setText("")
            self.preview_seq = -2  # let the live/snapshot image repaint
            return
        summary = self._selected_summary()
        if not summary or not summary.get("media"):
            return
        self.play_button.setText(tr("正在准备…"))
        media = summary["media"][0]

        def work() -> None:
            try:
                ffmpeg = STUDIO._tool("ffmpeg")
            except Exception:
                self.bridge.frames_done.emit([])
                return
            out_dir = Path(tempfile.gettempdir()) / "capture_studio_play" / Path(summary["path"]).name
            self.bridge.frames_done.emit(session_review.extract_frames(ffmpeg, media, out_dir))

        threading.Thread(target=work, daemon=True).start()

    def _frames_ready(self, frames: list) -> None:
        self._play_frames = [Path(p) for p in frames]
        self._play_index = 0
        if not self._play_frames:
            self.play_button.setText(tr("播放"))
            with STUDIO.lock:
                STUDIO._log("无法播放：没有可用的画面（检查 ffmpeg）")
            return
        self.play_button.setText(tr("停止播放"))
        self._play_timer.start(200)  # frames were extracted at 5 fps

    def _play_tick(self) -> None:
        if not self._play_frames:
            self._play_timer.stop()
            return
        total = len(self._play_frames)
        position = self._play_index % total
        image = QImage(str(self._play_frames[position]))
        self._play_index += 1
        self.live_label.setText(playback_label(position, total))
        if not image.isNull():
            self.viewport.set_image(image) if hasattr(self.viewport, "set_image") else None
            self._image = image
            self.viewport.update()

    # ----- peripherals extras
    def _v7_periph_extras(self, head: QHBoxLayout) -> None:
        self.periph_source = QComboBox()
        self.periph_source.addItem(tr("开发板"), "board")
        self.periph_source.addItem(tr("电脑"), "pc")
        self.periph_source.currentIndexChanged.connect(self._periph_source_changed)
        head.insertWidget(2, self.periph_source)

    def _periph_source_changed(self, _index: int) -> None:
        if self.periph_source.currentData() == "pc" and not STUDIO.state().get("pc_peripherals"):
            STUDIO.scan_pc_peripherals()
        self._periph_seen = None
        self.refresh(STUDIO.state())

    def periph_source_items(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        self.periph_fallback = False
        if getattr(self, "periph_source", None) is not None and self.periph_source.currentData() == "pc":
            return list(state.get("pc_peripherals") or [])
        board = list(state.get("peripherals") or [])
        if not board and not state.get("connected") and state.get("pc_peripherals"):
            self.periph_fallback = True  # v9: board offline -> show this PC's real devices instead of an empty list
            return list(state.get("pc_peripherals") or [])
        return board

    def periph_detail_value(self, item: dict[str, Any], key: str, value: str) -> str:
        if item["category"] == "i2c" and key == "扫描结果":
            import re
            parts = re.findall(r"0x[0-9a-f]{2}(?: \(驱动占用\))?", value)
            return "; ".join(i2c_describe(part) for part in parts) if parts else value
        if item["category"] == "i2c" and key.startswith("0x"):
            hint = i2c_describe(key)
            return f"{value} · {hint[len(key) + 1:]}" if hint != key else value
        return value

    def open_terminal(self, opener: Any = None) -> None:
        current = self.periph_list.currentItem()
        item = self._periph_by_id(current.data(Qt.ItemDataRole.UserRole)) if current is not None else None
        if not item or item["category"] != "serial":
            with STUDIO.lock:
                STUDIO._log("请先在列表里选一个串口")
            return
        side = item.get("side") or "board"
        port = item.get("port") or dict(item["props"]).get("设备") or item["id"].split(":", 1)[1]
        self.terminal = SerialTerminal(self, port, side, opener)
        self.terminal.show()

    def export_inventory(self, folder: Path | None = None) -> Path:
        state = STUDIO.state()
        folder = folder or STUDIO._output()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        data = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "board": state.get("board_info") or {},
                "board_peripherals": [dict(i, props=[list(p) for p in i["props"]]) for i in state.get("peripherals") or []],
                "pc_peripherals": [dict(i, props=[list(p) for p in i["props"]]) for i in state.get("pc_peripherals") or []]}
        path = folder / f"hardware_inventory_{stamp}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        from .peripherals import as_text
        text = folder / f"hardware_inventory_{stamp}.txt"
        board = state.get("board_info") or {}
        head = [f"# {board.get('model', '')}  {board.get('os', '')}  {board.get('kernel', '')}".rstrip()]
        text.write_text("\n".join(head + ["", "## 开发板", as_text(state.get("peripherals") or []), "",
                                          "## 电脑", as_text(state.get("pc_peripherals") or [])]) + "\n", encoding="utf-8")
        with STUDIO.lock:
            STUDIO._log(f"已导出 {path.name}")
        return path

    # ----- PC custom mode
    def pc_custom_mode(self, values: tuple[str, str, str, str] | None = None) -> bool:
        if values is None:
            text, ok = QInputDialog.getText(self, tr("自定义模式"), tr("宽×高@帧率 格式，例如 1280x720@30 mjpeg"),
                                            text="1280x720@30 mjpeg")
            if not ok:
                return False
            import re
            match = re.match(r"^\s*(\d{2,5})\s*[x×*]\s*(\d{2,5})\s*@\s*(\d{1,3})\s*(mjpeg|raw)?\s*$", text, re.I)
            if not match:
                with STUDIO.lock:
                    STUDIO._log("格式不对，例如 1280x720@30 mjpeg")
                return False
            values = (match.group(1), match.group(2), match.group(3), (match.group(4) or "mjpeg").lower())
        width, height, fps, fmt = values
        data = self.payload()
        data.update({"width": width, "height": height, "fps": fps, "format": fmt})
        STUDIO.update_settings(data)
        with STUDIO.lock:
            STUDIO._log(f"已选用 {width}×{height} · {fps} fps · {fmt.upper()}")
        return True


def playback_label(position: int, total: int, fps: float = 5.0) -> str:
    """'回放 · 12/100 · 0:02 / 0:20' — frame counter plus elapsed time of the 5 fps preview frames (v9)."""
    def clock(seconds: float) -> str:
        seconds = int(seconds)
        return f"{seconds // 60}:{seconds % 60:02d}"
    current = position + 1
    return f"{tr('回放')} · {current}/{total} · {clock(position / fps)} / {clock(total / fps)}"


def _dot_icon(color: str) -> QIcon:
    """v10: the app icon, with a status badge (red = recording, green = live)."""
    from . import icons
    return icons.app_icon(color)
