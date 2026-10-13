"""Tkinter presentation for the portable PC/KV260 capture controller.

The interface follows one operator path: choose host and camera, confirm one
frame, record, then inspect or retrieve the session. Capture behavior lives in
desktop.py and core.py; this module only owns layout and visual state.
"""

from __future__ import annotations

import base64
import math
import tkinter as tk
from tkinter import ttk
from typing import Any

from .camera_lab import (AUTO_MANUAL_CHOICES, POWER_LINE_CHOICES, RESOLUTION_PRESETS,
                         TUNING)
from .gates import NAMES, WORDS


FONT = "Microsoft YaHei UI"
BG = "#E7EEEF"
SURFACE = "#FFFFFF"
INK = "#14303A"
MUTED = "#3E5563"
LINE = "#D3E0E4"
ACCENT = "#0B6A78"
ACCENT_DARK = "#084E5A"
PREVIEW = "#0E242C"
PREVIEW_INK = "#F4FBFC"
PREVIEW_MUTED = "#D0E4E8"
GOOD = "#0F7A52"
WARN = "#8A6410"
BAD = "#9B2C2C"
CHIP = "#E4EEF0"
CHIP_LINE = "#D3E0E4"
DURATION_CHOICES = ("60 秒短检", "10 分钟关口", "手动停止")
# Measured on HHW001, MJPEG 640x480. Absolute 100 is the UVC value, nominally 10 ms.
EXPOSURE_PRESETS = {
    "看清画面": ("自动", "", "更亮，用来对镜头、看清眼前有什么。室内大约每秒 11 张，会慢一些。"),
    "看流畅": ("快门优先", "100", "大约每秒 30 张。室内会变暗，只用来看快不快，不适合当最后要的画面。"),
}
PRESET_ALIASES = {
    "看清场景": "看清画面",
    "尽量满帧": "看流畅",
    "快门 10ms": "看流畅",
    "手动 10ms": "自己设置",
    "自定义": "自己设置",
}
GATE_COLORS = {
    "pass": ("#E5F6EE", GOOD),
    "fail": ("#FDECEC", BAD),
    "pending": ("#F8F1DE", WARN),
}


def _styles(app: tk.Tk) -> None:
    app.configure(background=BG)
    app.option_add("*Font", (FONT, 10))
    app.option_add("*TCombobox*Listbox.font", (FONT, 10))
    style = ttk.Style(app)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=INK, font=(FONT, 10))
    style.configure("App.TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE, relief="flat", borderwidth=0)
    style.configure("CardBody.TFrame", background=SURFACE, relief="flat", borderwidth=0)
    style.configure("App.TLabel", background=BG, foreground=INK, font=(FONT, 10))
    style.configure("CardTitle.TLabel", background=SURFACE, foreground=INK,
                    font=(FONT, 12, "bold"))
    style.configure("Card.TLabel", background=SURFACE, foreground=INK, font=(FONT, 10))
    style.configure("Hint.TLabel", background=SURFACE, foreground=MUTED, font=(FONT, 9))
    style.configure("Field.TLabel", background=SURFACE, foreground=MUTED, font=(FONT, 9))
    style.configure("Footer.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 2, 2, 0))
    style.configure("TNotebook.Tab", background="#D7E3E6", foreground=MUTED,
                    padding=(14, 4), font=(FONT, 10), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", SURFACE), ("active", "#E3ECEE")],
              foreground=[("selected", ACCENT), ("active", INK)])
    style.configure("TEntry", fieldbackground=SURFACE, foreground=INK,
                    bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=(6, 2))
    style.map("TEntry", bordercolor=[("focus", ACCENT), ("disabled", LINE)])
    style.configure("TCombobox", fieldbackground=SURFACE, foreground=INK,
                    background=SURFACE, bordercolor=LINE, arrowcolor=MUTED, padding=(6, 2))
    style.map("TCombobox", bordercolor=[("focus", ACCENT), ("disabled", LINE)],
              fieldbackground=[("readonly", SURFACE), ("disabled", "#F3F6F7")],
              foreground=[("disabled", "#8AA0A8")])
    style.configure("Primary.TButton", background=ACCENT, foreground=SURFACE,
                    borderwidth=0, padding=(12, 4), font=(FONT, 10, "bold"),
                    focuscolor=PREVIEW_INK)
    style.map("Primary.TButton",
              background=[("disabled", "#B7CDD2"), ("active", ACCENT_DARK),
                          ("pressed", ACCENT_DARK)],
              foreground=[("disabled", "#F4F8F8"), ("active", SURFACE)])
    style.configure("Secondary.TButton", background="#E5F1F3", foreground=ACCENT_DARK,
                    borderwidth=0, padding=(11, 4), font=(FONT, 10),
                    focuscolor=ACCENT)
    style.map("Secondary.TButton",
              background=[("active", "#D3E7EA"), ("pressed", "#D3E7EA"),
                          ("disabled", "#F0F4F5")],
              foreground=[("disabled", "#8AA0A8")])
    style.configure("Quiet.TButton", background=SURFACE, foreground=INK,
                    bordercolor=LINE, borderwidth=1, padding=(8, 4), font=(FONT, 9),
                    focuscolor=ACCENT)
    style.map("Quiet.TButton",
              background=[("active", "#F3F7F8"), ("pressed", "#E7EEEF"),
                          ("disabled", SURFACE)],
              foreground=[("disabled", "#8AA0A8")])
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=INK, rowheight=26, borderwidth=0, font=(FONT, 9))
    style.configure("Treeview.Heading", background="#F3F7F8", foreground=MUTED,
                    font=(FONT, 9), relief="flat", padding=(6, 5))
    style.map("Treeview", background=[("selected", "#D7EBEE")],
              foreground=[("selected", INK)])
    style.configure("TScrollbar", background=BG, troughcolor=BG, borderwidth=0,
                    arrowcolor=MUTED)


def _card(parent: Any, *, padx: int = 14, pady: int = 10) -> ttk.Frame:
    return ttk.Frame(parent, style="Card.TFrame", padding=(padx, pady))


def _field(parent: Any, row: int, column: int, label: str, variable: tk.StringVar,
           *, span: int = 1, show: str = "", choices: tuple[str, ...] | None = None,
           readonly: bool = False) -> ttk.Entry | ttk.Combobox:
    ttk.Label(parent, text=label, style="Field.TLabel").grid(
        row=row * 2, column=column, columnspan=span, sticky="w", pady=(1, 0))
    if choices is None:
        widget: ttk.Entry | ttk.Combobox = ttk.Entry(parent, textvariable=variable, show=show)
    else:
        widget = ttk.Combobox(parent, textvariable=variable, values=choices,
                              state="readonly" if readonly else "normal")
    widget.grid(row=row * 2 + 1, column=column, columnspan=span,
                sticky="ew", padx=(0, 8) if span == 1 else 0)
    return widget


def _pill(parent: Any, text: str, *, variable: tk.StringVar | None = None) -> tk.Label:
    return tk.Label(parent, text=text, textvariable=variable, background=CHIP, foreground=MUTED,
                    font=(FONT, 9), padx=8, pady=3)


def preview_fit(src_w: int, src_h: int, box_w: int, box_h: int,
                max_zoom: int = 8) -> tuple[int, int, int, int]:
    """Largest integer zoom/subsample of the source that fits inside the box."""
    src_w, src_h = max(1, int(src_w)), max(1, int(src_h))
    box_w, box_h = max(1, int(box_w)), max(1, int(box_h))
    best: tuple[int, int, int, int] | None = None
    best_area = 0
    for subsample in range(1, 9):
        for zoom in range(1, max_zoom + 1):
            out_w = src_w * zoom // subsample
            out_h = src_h * zoom // subsample
            if out_w < 1 or out_h < 1 or out_w > box_w or out_h > box_h:
                continue
            area = out_w * out_h
            if area > best_area:
                best = (zoom, subsample, out_w, out_h)
                best_area = area
    if best is not None:
        return best
    subsample = 1
    while src_w // subsample > box_w or src_h // subsample > box_h:
        subsample += 1
        if subsample > max(src_w, src_h):
            return 1, subsample, 1, 1
    return 1, subsample, max(1, src_w // subsample), max(1, src_h // subsample)


def _scaled(image: tk.PhotoImage, zoom: int, subsample: int) -> tk.PhotoImage:
    scaled = image
    if zoom != 1:
        scaled = scaled.zoom(zoom, zoom)
    if subsample != 1:
        scaled = scaled.subsample(subsample, subsample)
    return scaled


def _empty_preview(canvas: tk.Canvas, width: int = 320, height: int = 180) -> None:
    canvas.delete("all")
    width = max(int(width), 2)
    height = max(int(height), 2)
    arm = max(16, min(36, width // 9))
    inset = max(14, min(28, width // 12))
    color = "#4E7C84"
    corners = (
        (inset, inset, 1, 1),
        (width - inset, inset, -1, 1),
        (inset, height - inset, 1, -1),
        (width - inset, height - inset, -1, -1),
    )
    for x, y, dx, dy in corners:
        canvas.create_line(x, y, x + dx * arm, y, fill=color, width=1)
        canvas.create_line(x, y, x, y + dy * arm, fill=color, width=1)
    canvas.create_text(width // 2, height // 2 - 12, text="尚无画面",
                       fill=PREVIEW_INK, font=(FONT, 15, "bold"))
    canvas.create_text(width // 2, height // 2 + 14,
                       text=getattr(canvas, "empty_message", "点「预览一帧」确认视场"),
                       fill=PREVIEW_MUTED, font=(FONT, 9))


def layout_preview(canvas: tk.Canvas, box: tuple[int, int] | None = None) -> None:
    """Draw the source frame edge to edge. The pane behind it stays the card color."""
    holder = canvas.master
    if box is None:
        box_w, box_h = holder.winfo_width(), holder.winfo_height()
    else:
        box_w, box_h = box
    if box_w < 20 or box_h < 20:
        return
    source = getattr(canvas, "source_image", None)
    if source is None:
        width = min(box_w, max(2, box_h * 4 // 3))
        height = min(box_h, max(2, width * 3 // 4))
        canvas.fitted_image = None
        canvas.configure(width=width, height=height, background=PREVIEW)
        canvas.place(relx=0.5, rely=0.5, anchor="center", width=width, height=height)
        _empty_preview(canvas, width, height)
        return
    zoom, subsample, _out_w, _out_h = preview_fit(
        source.width(), source.height(), box_w, box_h)
    fitted = _scaled(source, zoom, subsample)
    out_w, out_h = fitted.width(), fitted.height()
    canvas.fitted_image = fitted
    canvas.image = fitted
    canvas.configure(width=out_w, height=out_h, background=PREVIEW)
    canvas.place(relx=0.5, rely=0.5, anchor="center", width=out_w, height=out_h)
    canvas.delete("all")
    canvas.create_image(0, 0, image=fitted, anchor="nw")


def _preview_pane(parent: ttk.Frame, title: str, hint: str,
                  empty: str = "点「预览一帧」确认视场") -> tuple[tk.Canvas, tk.Label]:
    head = ttk.Frame(parent, style="CardBody.TFrame")
    head.pack(fill="x")
    ttk.Label(head, text=title, style="CardTitle.TLabel").pack(side="left")
    badge = _pill(head, "待预览")
    badge.pack(side="right")
    ttk.Label(parent, text=hint, style="Hint.TLabel", wraplength=280).pack(
        anchor="w", pady=(2, 8))
    holder = tk.Frame(parent, background=SURFACE, highlightthickness=0, borderwidth=0)
    holder.pack(fill="both", expand=True)
    canvas = tk.Canvas(holder, width=300, height=225, background=PREVIEW,
                       highlightthickness=0, borderwidth=0)
    canvas.source_image = None
    canvas.empty_message = empty
    canvas.place(relx=0.5, rely=0.5, anchor="center", width=300, height=225)
    _empty_preview(canvas, 300, 225)
    holder.bind("<Configure>", lambda _event: layout_preview(canvas))
    return canvas, badge


def build_ui(app: Any) -> None:
    _styles(app)
    app.title("Capture Studio · 数据集采集")
    app.geometry("1120x740")
    app.minsize(960, 650)

    app.output_var = tk.StringVar(value="captures")
    app.ffmpeg_var = tk.StringVar()
    app.ffprobe_var = tk.StringVar()
    app.pc_device = tk.StringVar()
    app.pc_scan_var = tk.StringVar(value="准备检测…")
    app.pc_current_var = tk.StringVar(value="当前设备：正在检测…")
    app.pc_width = tk.StringVar(value="1920")
    app.pc_height = tk.StringVar(value="1080")
    app.pc_fps = tk.StringVar(value="30")
    app.pc_codec = tk.StringVar(value="ffv1")
    app.board_url = tk.StringVar()
    app.board_token = tk.StringVar()
    app.board_device = tk.StringVar()
    app.board_scan_var = tk.StringVar(value="未连接")
    app.board_current_var = tk.StringVar(value="当前设备：未连接板端")
    app.board_width = tk.StringVar(value="1920")
    app.board_height = tk.StringVar(value="1080")
    app.board_fps = tk.StringVar(value="30")
    app.board_format = tk.StringVar(value="mjpeg")
    app.board_bitrate = tk.StringVar(value="20000")
    app.operator = tk.StringVar()
    app.notes = tk.StringVar()
    app.duration_var = tk.StringVar(value="60 秒短检")
    app.lens_var = tk.StringVar()
    app.light_var = tk.StringVar()
    app.distance_var = tk.StringVar()
    app.board_resolution = tk.StringVar(value="1920×1080")
    app.board_power_line = tk.StringVar(value="不改")
    app.board_wb = tk.StringVar(value="不改")
    app.board_focus = tk.StringVar(value="不改")
    for item in TUNING:
        if item.kind == "int":
            setattr(app, f"board_{item.name}", tk.StringVar())
    app.lab_auto_watch = tk.BooleanVar(value=True)
    app.lab_auto_preview = tk.BooleanVar(value=True)
    app.lab_board_var = tk.StringVar(value="开发板：还没连上")
    app.lab_camera_var = tk.StringVar(value="摄像头：还没认出")
    app.lab_step_var = tk.StringVar(value="第 1 步：把开发板网线插上。保存过密钥后，插上就会自动连。")
    app.lab_watch_var = tk.StringVar(value="正在等待开发板和摄像头")
    app.lab_camera_pick = tk.StringVar()
    app.lab_support_var = tk.StringVar(value="还没读取。留空的项目不会改摄像头自己的数值。")
    app.board_session_var = tk.StringVar(value="板端尚无活动会话")
    app.board_metrics_var = tk.StringVar(value="首次使用请填入地址和令牌")
    app.status_var = tk.StringVar(value="就绪 · 插上开发板和摄像头后会自动识别")
    app.remote_session = tk.StringVar()

    shell = ttk.Frame(app, style="App.TFrame", padding=(12, 4, 12, 2))
    shell.pack(fill="both", expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(2, weight=1)
    shell.rowconfigure(3, minsize=32)

    header = tk.Frame(shell, background=PREVIEW)
    header.grid(row=0, column=0, sticky="ew")
    title_row = tk.Frame(header, background=PREVIEW)
    title_row.pack(fill="x", padx=16, pady=(6, 5))
    tk.Label(title_row, text="数据集采集", background=PREVIEW, foreground=PREVIEW_INK,
             font=(FONT, 16, "bold")).pack(side="left")
    tk.Label(title_row, text="Capture Studio", background=PREVIEW, foreground="#9EC4CB",
             font=(FONT, 10)).pack(side="right")
    rule = tk.Frame(header, background=ACCENT, height=2)
    rule.pack_propagate(False)
    rule.pack(fill="x")

    common = _card(shell, padx=14, pady=6)
    common.grid(row=1, column=0, sticky="ew", pady=(4, 4))
    for index, weight in enumerate((5, 2, 3, 2)):
        common.columnconfigure(index, weight=weight)
    labels = ("数据目录", "采集人", "场景备注", "时长")
    for index, text in enumerate(labels):
        ttk.Label(common, text=text, style="Field.TLabel").grid(
            row=0, column=index, sticky="w", padx=(0, 8))
    path_row = ttk.Frame(common, style="CardBody.TFrame")
    path_row.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(2, 0))
    ttk.Entry(path_row, textvariable=app.output_var).pack(side="left", fill="x", expand=True)
    ttk.Button(path_row, text="选择", command=app._browse_output,
               style="Quiet.TButton").pack(side="left", padx=(6, 0))
    ttk.Entry(common, textvariable=app.operator).grid(
        row=1, column=1, sticky="ew", padx=(0, 10), pady=(2, 0))
    ttk.Entry(common, textvariable=app.notes).grid(
        row=1, column=2, sticky="ew", padx=(0, 10), pady=(2, 0))
    duration = ttk.Combobox(common, textvariable=app.duration_var, width=12,
                            values=DURATION_CHOICES, state="readonly")
    duration.grid(row=1, column=3, sticky="ew", pady=(2, 0))
    app.duration_var.trace_add("write", lambda *_: update_duration(app))

    notebook = ttk.Notebook(shell)
    notebook.grid(row=2, column=0, sticky="nsew")
    app.lab_tab = ttk.Frame(notebook, style="App.TFrame")
    app.pc_tab = ttk.Frame(notebook, style="App.TFrame")
    app.board_tab = ttk.Frame(notebook, style="App.TFrame")
    app.review_tab = ttk.Frame(notebook, style="App.TFrame")
    app.settings_tab = ttk.Frame(notebook, style="App.TFrame")
    notebook.add(app.lab_tab, text="  摄像头测试  ")
    notebook.add(app.pc_tab, text="  电脑采集  ")
    notebook.add(app.board_tab, text="  KV260 采集  ")
    notebook.add(app.review_tab, text="  会话与校验  ")
    notebook.add(app.settings_tab, text="  工具设置  ")

    _build_lab(app)
    _build_pc(app)
    _build_board(app)
    _build_review(app)
    _build_settings(app)

    footer = tk.Frame(shell, background=BG, height=32)
    app.footer = footer
    footer.grid(row=3, column=0, sticky="ew", pady=(4, 0))
    footer.pack_propagate(False)
    dot = tk.Canvas(footer, width=8, height=8, background=BG, highlightthickness=0)
    dot.create_oval(0, 0, 8, 8, fill=GOOD, outline=GOOD)
    dot.pack(side="left", padx=(4, 8), pady=12)
    app.status_label = ttk.Label(footer, textvariable=app.status_var, style="Footer.TLabel")
    app.status_label.pack(side="left", fill="x", expand=True, pady=5)
    ttk.Label(footer, text="本地优先", style="Footer.TLabel").pack(side="right", padx=(8, 2))
    app.protocol("WM_DELETE_WINDOW", app._close)
    update_duration(app)
    refresh_controls(app)


def _mode_body(tab: ttk.Frame) -> tuple[ttk.Frame, ttk.Frame]:
    body = ttk.Frame(tab, style="App.TFrame", padding=(0, 4, 0, 0))
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=5)
    body.columnconfigure(1, weight=4)
    body.rowconfigure(0, weight=1)
    left = _card(body, padx=12, pady=4)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    right = _card(body, padx=12, pady=4)
    right.grid(row=0, column=1, sticky="nsew")
    return left, right


def _scroll_form(parent: ttk.Frame) -> ttk.Frame:
    canvas = tk.Canvas(parent, background=BG, highlightthickness=0, borderwidth=0)
    scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    inner = ttk.Frame(canvas, style="Card.TFrame", padding=(12, 8))
    window = canvas.create_window((0, 0), window=inner, anchor="nw")

    def fit(_event: object = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(window, width=max(canvas.winfo_width(), 1))

    inner.bind("<Configure>", fit)
    canvas.bind("<Configure>", fit)

    def wheel(event: tk.Event) -> None:
        canvas.yview_scroll(int(-event.delta / 120), "units")

    canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", wheel))
    canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return inner


def _build_lab(app: Any) -> None:
    body = ttk.Frame(app.lab_tab, style="App.TFrame", padding=(0, 4, 0, 0))
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=6)
    body.columnconfigure(1, weight=4)
    body.rowconfigure(0, weight=1)
    left_host = ttk.Frame(body, style="App.TFrame")
    left_host.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    form = _scroll_form(left_host)
    form.columnconfigure(0, weight=1)
    form.columnconfigure(1, weight=1)
    ttk.Label(form, text="摄像头测试", style="CardTitle.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(form, text="插上开发板和摄像头后会自动认出。留空的数字表示不改。",
              style="Hint.TLabel", wraplength=460).grid(
                  row=1, column=0, columnspan=2, sticky="w", pady=(2, 2))
    ttk.Label(form, textvariable=app.lab_step_var, style="Card.TLabel",
              wraplength=460).grid(row=2, column=0, columnspan=2, sticky="w")
    ttk.Label(form, textvariable=app.lab_board_var, style="Card.TLabel",
              wraplength=460).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
    ttk.Label(form, textvariable=app.lab_camera_var, style="Card.TLabel",
              wraplength=460).grid(row=4, column=0, columnspan=2, sticky="w")
    ttk.Label(form, textvariable=app.lab_watch_var, style="Hint.TLabel").grid(
        row=5, column=0, columnspan=2, sticky="w", pady=(0, 4))
    watch = ttk.Frame(form, style="CardBody.TFrame")
    watch.grid(row=6, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(watch, text="插上后自动识别", variable=app.lab_auto_watch).pack(side="left")
    ttk.Checkbutton(watch, text="认出后自动看画面", variable=app.lab_auto_preview).pack(
        side="left", padx=(12, 0))
    ttk.Button(watch, text="马上识别", command=app._identify_now,
               style="Quiet.TButton").pack(side="left", padx=(12, 0))
    ttk.Button(watch, text="连接设置", command=app._configure_board,
               style="Quiet.TButton").pack(side="left", padx=(6, 0))

    ttk.Label(form, text="要测的摄像头", style="Field.TLabel").grid(
        row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
    app.lab_camera_box = ttk.Combobox(form, textvariable=app.lab_camera_pick, state="readonly")
    app.lab_camera_box.grid(row=8, column=0, columnspan=2, sticky="ew")
    ttk.Label(form, textvariable=app.pc_current_var, style="Hint.TLabel",
              wraplength=460).grid(row=9, column=0, columnspan=2, sticky="w", pady=(2, 0))
    ttk.Label(form, text="若上一行出现电脑摄像头，说明线插在电脑上。调参请插到开发板。",
              style="Hint.TLabel", wraplength=460).grid(
                  row=10, column=0, columnspan=2, sticky="w")

    picture = ttk.Frame(form, style="CardBody.TFrame")
    picture.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    for index in range(4):
        picture.columnconfigure(index, weight=1)
    ttk.Label(picture, text="分辨率", style="Field.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Combobox(picture, textvariable=app.board_resolution, state="readonly",
                 values=tuple(RESOLUTION_PRESETS) + ("自己填",)).grid(
                     row=1, column=0, sticky="ew", padx=(0, 8))
    for index, (label, variable) in enumerate(
            (("宽", app.board_width), ("高", app.board_height), ("帧率", app.board_fps)), 1):
        ttk.Label(picture, text=label, style="Field.TLabel").grid(row=0, column=index, sticky="w")
        ttk.Entry(picture, textvariable=variable, width=6).grid(
            row=1, column=index, sticky="ew", padx=(0, 8))
    ttk.Label(form, text="格式", style="Field.TLabel").grid(
        row=12, column=0, sticky="w", pady=(6, 0))
    ttk.Combobox(form, textvariable=app.board_format, state="readonly",
                 values=("mjpeg", "raw")).grid(row=13, column=0, sticky="ew", padx=(0, 8))
    ttk.Label(form, text="多数摄像头先用 mjpeg、640×480、30 帧。raw 文件更大。",
              style="Hint.TLabel", wraplength=460).grid(
                  row=14, column=0, columnspan=2, sticky="w")

    app.lab_entries = {}
    app.lab_range_vars = {}
    numbers = ttk.Frame(form, style="CardBody.TFrame")
    numbers.grid(row=15, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    numbers.columnconfigure(0, weight=1)
    numbers.columnconfigure(1, weight=1)
    ttk.Label(numbers, text="亮暗、颜色、对焦", style="Field.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w")
    integers = [item for item in TUNING if item.kind == "int" and item.name not in {
        "white_balance_temperature", "focus_absolute"}]
    for index, item in enumerate(integers):
        variable = getattr(app, f"board_{item.name}")
        app.lab_range_vars[item.name] = tk.StringVar(value=item.hint)
        grid_row = 1 + (index // 2) * 2
        column = index % 2
        ttk.Label(numbers, text=item.label, style="Field.TLabel").grid(
            row=grid_row, column=column, sticky="w", pady=(4, 0))
        entry = ttk.Entry(numbers, textvariable=variable)
        entry.grid(row=grid_row + 1, column=column, sticky="ew", padx=(0, 8))
        app.lab_entries[item.name] = entry
    specials = (
        ("灯光频率", app.board_power_line, POWER_LINE_CHOICES, "power_line_frequency"),
        ("白平衡", app.board_wb, AUTO_MANUAL_CHOICES, "white_balance_auto"),
        ("对焦", app.board_focus, AUTO_MANUAL_CHOICES, "focus_auto"),
    )
    combo_row = ttk.Frame(form, style="CardBody.TFrame")
    combo_row.grid(row=16, column=0, columnspan=2, sticky="ew", pady=(6, 0))
    for index, (label, variable, choices, name) in enumerate(specials):
        combo_row.columnconfigure(index, weight=1)
        ttk.Label(combo_row, text=label, style="Field.TLabel").grid(
            row=0, column=index, sticky="w")
        box = ttk.Combobox(combo_row, textvariable=variable, values=choices,
                           state="readonly", width=10)
        box.grid(row=1, column=index, sticky="ew", padx=(0, 8))
        app.lab_entries[name] = box
        app.lab_range_vars[name] = tk.StringVar(value=TUNING_HINT[name])
    pair = ttk.Frame(form, style="CardBody.TFrame")
    pair.grid(row=17, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    pair.columnconfigure(0, weight=1)
    pair.columnconfigure(1, weight=1)
    for index, name in enumerate(("white_balance_temperature", "focus_absolute")):
        item = next(entry for entry in TUNING if entry.name == name)
        variable = getattr(app, f"board_{item.name}")
        cell = ttk.Frame(pair, style="CardBody.TFrame")
        cell.grid(row=0, column=index, sticky="ew", padx=(0, 8))
        ttk.Label(cell, text=item.label, style="Field.TLabel").pack(anchor="w")
        entry = ttk.Entry(cell, textvariable=variable)
        entry.pack(fill="x")
        app.lab_entries[name] = entry
        app.lab_range_vars[name] = tk.StringVar(value=item.hint)
    ttk.Label(form, textvariable=app.lab_support_var, style="Hint.TLabel",
              wraplength=460).grid(row=18, column=0, columnspan=2, sticky="w", pady=(6, 0))
    tools = ttk.Frame(form, style="CardBody.TFrame")
    tools.grid(row=19, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    ttk.Button(tools, text="按这个参数看画面", command=app._apply_lab,
               style="Primary.TButton").pack(side="left", padx=(0, 6))
    ttk.Button(tools, text="读出这只能调什么", command=app._read_lab_controls,
               style="Secondary.TButton").pack(side="left", padx=(0, 6))
    ttk.Button(tools, text="填入当前数值", command=app._fill_lab_controls,
               style="Quiet.TButton").pack(side="left")
    more = ttk.Frame(form, style="CardBody.TFrame")
    more.grid(row=20, column=0, columnspan=2, sticky="ew", pady=(6, 0))
    ttk.Button(more, text="室内日光灯", command=app._lab_fluorescent,
               style="Secondary.TButton").pack(side="left", padx=(0, 6))
    ttk.Button(more, text="数字留空", command=app._clear_lab_tuning,
               style="Quiet.TButton").pack(side="left", padx=(0, 6))
    app.lab_short_button = ttk.Button(more, text="录 60 秒并检查", command=app._lab_short,
                                      style="Primary.TButton")
    app.lab_short_button.pack(side="left")
    ttk.Label(form, text="短检会停掉预览，录一分钟，再把文件取回并检查。",
              style="Hint.TLabel", wraplength=460).grid(
                  row=21, column=0, columnspan=2, sticky="w", pady=(6, 8))

    preview_parent = _card(body, padx=12, pady=4)
    preview_parent.grid(row=0, column=1, sticky="nsew")
    app.lab_preview_canvas, app.lab_badge = _preview_pane(
        preview_parent, "测试画面", "预览不写入数据集。开始短检前会先停掉预览。",
        empty="插上后会自动出现画面")
    app.lab_badge.configure(text="未连接")
    ttk.Button(preview_parent, text="大屏看画面", command=app._open_large_view,
               style="Secondary.TButton").pack(anchor="w", pady=(8, 0))
    app.lab_metrics_var = tk.StringVar(value="实际取流帧率：—")
    ttk.Label(preview_parent, textvariable=app.lab_metrics_var, style="Card.TLabel",
              wraplength=300).pack(anchor="w", pady=(8, 2))
    ttk.Label(preview_parent, textvariable=app.board_session_var, style="Card.TLabel",
              wraplength=300).pack(anchor="w")
    ttk.Label(preview_parent, textvariable=app.board_metrics_var, style="Hint.TLabel",
              wraplength=300).pack(anchor="w", pady=(2, 0))
    app.board_wb.trace_add("write", lambda *_: update_lab_dependents(app))
    app.board_focus.trace_add("write", lambda *_: update_lab_dependents(app))
    update_lab_dependents(app)


TUNING_HINT = {item.name: item.hint for item in TUNING}


def update_lab_dependents(app: Any) -> None:
    controls = getattr(app, "lab_controls", None) or []
    support = getattr(app, "lab_support", {}) or {}

    def usable(name: str, automatic: bool) -> str:
        missing = bool(controls) and support.get(name) is None
        return "disabled" if automatic or missing else "normal"

    temperature = app.lab_entries.get("white_balance_temperature")
    focus = app.lab_entries.get("focus_absolute")
    if temperature is not None:
        temperature.configure(state=usable("white_balance_temperature", app.board_wb.get() == "自动"))
    if focus is not None:
        focus.configure(state=usable("focus_absolute", app.board_focus.get() == "自动"))


def paint_lab_support(app: Any, controls: list[dict] | None, error: str = "") -> None:
    from .camera_lab import support_for
    if error:
        app.lab_support_var.set(error)
    elif not controls:
        app.lab_support_var.set("没有读到可调项目，仍可按常用范围手填。留空表示不改。")
    else:
        app.lab_support_var.set("已读出这只摄像头的项目。没有的项已停用。留空仍表示不改。")
    app.lab_controls = controls or []
    found = support_for(app.lab_controls) if controls else {}
    app.lab_support = found
    for name, widget in app.lab_entries.items():
        hint = app.lab_range_vars.get(name)
        if not controls:
            if str(widget.cget("state")) == "disabled" and name not in {
                    "white_balance_temperature", "focus_absolute"}:
                widget.configure(state="readonly" if name in {
                    "power_line_frequency", "white_balance_auto", "focus_auto"} else "normal")
            continue
        item = found.get(name)
        if item is None:
            widget.configure(state="disabled")
            if hint is not None:
                hint.set("这只摄像头没有这一项")
            continue
        kind = "readonly" if name in {
            "power_line_frequency", "white_balance_auto", "focus_auto"} else "normal"
        widget.configure(state=kind)
        if hint is not None and item.get("min") is not None and item.get("max") is not None:
            current = item.get("value")
            hint.set(f"当前 {current}，可填 {item['min']}–{item['max']}，留空不改")
    update_lab_dependents(app)


def _build_pc(app: Any) -> None:
    left, preview_parent = _mode_body(app.pc_tab)
    left.columnconfigure(0, weight=1)
    left.columnconfigure(1, weight=1)
    ttk.Label(left, text="电脑直连 USB 摄像头", style="CardTitle.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(left, text="先确认设备和画面，再开始保存采集文件。", style="Hint.TLabel").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(2, 2))
    ttk.Label(left, text="摄像头", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 1))
    ttk.Label(left, textvariable=app.pc_scan_var, style="Hint.TLabel").grid(
        row=2, column=1, sticky="e", pady=(4, 1))
    device_row = ttk.Frame(left, style="CardBody.TFrame")
    device_row.grid(row=3, column=0, columnspan=2, sticky="ew")
    app.pc_device_box = ttk.Combobox(device_row, textvariable=app.pc_device)
    app.pc_device_box.pack(side="left", fill="x", expand=True)
    ttk.Button(device_row, text="刷新设备", command=app._list_local_devices,
               style="Quiet.TButton").pack(side="left", padx=(6, 0))

    dimensions = ttk.Frame(left, style="CardBody.TFrame")
    dimensions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 0))
    for index, (label, variable) in enumerate((
        ("宽度", app.pc_width), ("高度", app.pc_height), ("帧率 FPS", app.pc_fps)
    )):
        dimensions.columnconfigure(index, weight=1)
        _field(dimensions, 0, index, label, variable)
    _field(left, 3, 0, "保存编码", app.pc_codec,
           choices=("ffv1", "copy", "mjpeg"), readonly=True)
    ttk.Label(left, text="FFV1 保存解码帧且占用空间较大；copy 仅适用于可直接封装的压缩流。",
              style="Hint.TLabel", wraplength=420).grid(
                  row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
    actions = ttk.Frame(left, style="CardBody.TFrame")
    actions.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    ttk.Button(actions, text="预览一帧", command=app._preview_local,
               style="Secondary.TButton").pack(side="left", padx=(0, 6))
    app.pc_start_button = ttk.Button(actions, text="开始采集", command=app._start_local,
                                     style="Primary.TButton")
    app.pc_start_button.pack(side="left", padx=(0, 6))
    app.pc_stop_button = ttk.Button(actions, text="停止并校验", command=app._stop_local,
                                    style="Quiet.TButton")
    app.pc_stop_button.pack(side="left")

    app.pc_preview_canvas, app.pc_badge = _preview_pane(
        preview_parent, "画面确认", "预览只取一帧，不会写入数据集。")
    ttk.Label(preview_parent, textvariable=app.pc_current_var,
              style="Card.TLabel", wraplength=300).pack(anchor="w", pady=(8, 2))
    app.pc_session_var = tk.StringVar(value="尚无采集会话")
    app.pc_metrics_var = tk.StringVar(value="预览后可开始录制")
    ttk.Label(preview_parent, textvariable=app.pc_session_var,
              style="Card.TLabel", wraplength=300).pack(anchor="w")
    ttk.Label(preview_parent, textvariable=app.pc_metrics_var,
              style="Hint.TLabel", wraplength=300).pack(anchor="w", pady=(2, 0))


def _build_board(app: Any) -> None:
    left, preview_parent = _mode_body(app.board_tab)
    left.columnconfigure(0, weight=1)
    left.columnconfigure(1, weight=1)
    ttk.Label(left, text="KV260 直连 USB 摄像头", style="CardTitle.TLabel").grid(
        row=0, column=0, sticky="w")
    ttk.Button(left, text="连接设置", command=app._configure_board,
               style="Quiet.TButton").grid(row=0, column=1, sticky="e")
    ttk.Label(left, text="板端保存视频；停止后校验并取回电脑。", style="Hint.TLabel").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
    _field(left, 1, 0, "KV260 地址", app.board_url)
    _field(left, 1, 1, "连接令牌", app.board_token, show="•")
    ttk.Label(left, text="板端视频设备", style="Field.TLabel").grid(
        row=4, column=0, sticky="w", pady=(2, 0))
    ttk.Label(left, textvariable=app.board_scan_var, style="Hint.TLabel").grid(
        row=4, column=1, sticky="e", pady=(2, 0))
    device_row = ttk.Frame(left, style="CardBody.TFrame")
    device_row.grid(row=5, column=0, columnspan=2, sticky="ew")
    app.board_device_box = ttk.Combobox(device_row, textvariable=app.board_device)
    app.board_device_box.pack(side="left", fill="x", expand=True)
    ttk.Button(device_row, text="刷新设备", command=app._list_board_devices,
               style="Quiet.TButton").pack(side="left", padx=(6, 0))
    dimensions = ttk.Frame(left, style="CardBody.TFrame")
    dimensions.grid(row=6, column=0, columnspan=2, sticky="ew")
    for index, (label, variable) in enumerate((
        ("宽度", app.board_width), ("高度", app.board_height), ("帧率 FPS", app.board_fps)
    )):
        dimensions.columnconfigure(index, weight=1)
        _field(dimensions, 0, index, label, variable)
    _field(left, 4, 0, "摄像头格式", app.board_format, choices=("mjpeg", "raw"), readonly=True)
    app.board_bitrate_entry = _field(left, 4, 1, "H.264 码率 kb/s", app.board_bitrate)
    app.board_preset = tk.StringVar(value="看清画面")
    app.board_preset_note = tk.StringVar(value=EXPOSURE_PRESETS["看清画面"][2])
    app.board_exposure_mode = tk.StringVar(value="自动")
    app.board_exposure_absolute = tk.StringVar(value="")
    ttk.Label(left, text="怎么拍", style="Field.TLabel").grid(
        row=10, column=0, columnspan=2, sticky="w", pady=(4, 0))
    preset_row = ttk.Frame(left, style="CardBody.TFrame")
    preset_row.grid(row=11, column=0, columnspan=2, sticky="ew")
    app.preset_buttons = {}
    for name in EXPOSURE_PRESETS:
        button = ttk.Button(preset_row, text=name,
                            command=lambda chosen=name: app.board_preset.set(chosen),
                            style="Secondary.TButton")
        button.pack(side="left", padx=(0, 6))
        app.preset_buttons[name] = button
    ttk.Button(preset_row, text="自己设置",
               command=lambda: app.board_preset.set("自己设置"),
               style="Quiet.TButton").pack(side="left")
    app.preset_buttons["自己设置"] = preset_row.winfo_children()[-1]
    ttk.Label(left, textvariable=app.board_preset_note, style="Hint.TLabel",
              wraplength=420, justify="left").grid(
                  row=12, column=0, columnspan=2, sticky="w", pady=(2, 0))
    exposure_row = ttk.Frame(left, style="CardBody.TFrame")
    app.exposure_row = exposure_row
    exposure_row.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(2, 0))
    ttk.Label(exposure_row, text="曝光", style="Field.TLabel").pack(side="left")
    app.board_exposure_mode_box = ttk.Combobox(
        exposure_row, textvariable=app.board_exposure_mode, width=8,
        values=("自动", "手动", "快门优先"), state="readonly")
    app.board_exposure_mode_box.pack(side="left", padx=(6, 8))
    ttk.Label(exposure_row, text="数字", style="Field.TLabel").pack(side="left")
    app.board_exposure_entry = ttk.Entry(exposure_row, textvariable=app.board_exposure_absolute,
                                         width=8)
    app.board_exposure_entry.pack(side="left", padx=(6, 0))
    tools = ttk.Frame(left, style="CardBody.TFrame")
    tools.grid(row=14, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    ttk.Button(tools, text="自动连接/查设备", command=app._connect_board,
               style="Quiet.TButton").pack(side="left", padx=(0, 6))
    ttk.Button(tools, text="预览一帧", command=app._preview_board,
               style="Secondary.TButton").pack(side="left", padx=(0, 6))
    app.board_live_button = ttk.Button(tools, text="实时预览", command=app._live_board,
                                      style="Secondary.TButton")
    app.board_live_button.pack(side="left")
    actions = ttk.Frame(left, style="CardBody.TFrame")
    actions.grid(row=15, column=0, columnspan=2, sticky="ew", pady=(2, 0))
    app.board_start_button = ttk.Button(actions, text="开始采集", command=app._start_board,
                                        style="Primary.TButton")
    app.board_start_button.pack(side="left", padx=(0, 6))
    app.board_stop_button = ttk.Button(actions, text="停止并取回", command=app._stop_board,
                                       style="Quiet.TButton")
    app.board_stop_button.pack(side="left")

    app.board_preview_canvas, app.board_badge = _preview_pane(
        preview_parent, "板端画面", "预览和采集用同一种拍法。开始采集会先停掉预览。")
    app.board_badge.configure(text="未连接")
    ttk.Button(preview_parent, text="大屏看画面", command=app._open_large_view,
               style="Secondary.TButton").pack(anchor="w", pady=(8, 0))
    app.board_live_metrics_var = tk.StringVar(value="实际取流帧率：— · 预览输出：—")
    ttk.Label(preview_parent, textvariable=app.board_live_metrics_var,
              style="Card.TLabel", wraplength=300).pack(anchor="w", pady=(8, 2))
    ttk.Label(preview_parent, textvariable=app.board_current_var,
              style="Card.TLabel", wraplength=300).pack(anchor="w", pady=(0, 2))
    ttk.Label(preview_parent, textvariable=app.board_session_var,
              style="Card.TLabel", wraplength=300).pack(anchor="w")
    ttk.Label(preview_parent, textvariable=app.board_metrics_var,
              style="Hint.TLabel", wraplength=300).pack(anchor="w", pady=(2, 0))
    app.board_format.trace_add("write", lambda *_: update_board_format(app))
    app.board_exposure_mode.trace_add("write", lambda *_: update_board_exposure(app))
    update_board_format(app)
    update_board_exposure(app)
    update_preset_hint(app)


def _build_review(app: Any) -> None:
    outer = ttk.Frame(app.review_tab, style="App.TFrame", padding=(0, 8, 0, 0))
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.columnconfigure(1, weight=1)
    outer.rowconfigure(0, weight=1)
    left = _card(outer, padx=14, pady=10)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    ttk.Label(left, text="取回板端会话", style="CardTitle.TLabel").pack(anchor="w")
    ttk.Label(left, text="网络中断后可按会话 ID 继续取回。", style="Hint.TLabel").pack(
        anchor="w", pady=(2, 8))
    ttk.Entry(left, textvariable=app.remote_session).pack(fill="x", pady=(0, 6))
    row = ttk.Frame(left, style="CardBody.TFrame")
    row.pack(anchor="w", pady=(0, 8))
    ttk.Button(row, text="板端", width=4, command=app._list_board_sessions,
               style="Quiet.TButton").pack(side="left")
    ttk.Button(row, text="本机", width=4, command=app._list_local_sessions,
               style="Quiet.TButton").pack(side="left", padx=(6, 0))
    ttk.Button(left, text="取回选中会话", command=app._fetch_board,
               style="Primary.TButton").pack(anchor="w", pady=(0, 8))
    app.session_tree = ttk.Treeview(left, columns=("created", "status", "ready"),
                                    show="headings", height=5, selectmode="browse")
    for key, label, width, anchor in (("created", "创建时间", 132, "w"),
                                      ("status", "状态", 72, "w"),
                                      ("ready", "入库", 72, "center")):
        app.session_tree.heading(key, text=label)
        app.session_tree.column(key, width=width, anchor=anchor)
    app.session_tree.pack(fill="both", expand=True)
    app.session_tree.bind("<<TreeviewSelect>>", lambda _event: select_session(app))

    right = _card(outer, padx=14, pady=10)
    right.grid(row=0, column=1, sticky="nsew")
    ttk.Label(right, text="校验与活动记录", style="CardTitle.TLabel").pack(anchor="w")
    ttk.Label(right, text="完整性、帧率、画面、收尾分开显示。四关都通过才可入库。",
              style="Hint.TLabel", wraplength=420).pack(anchor="w", pady=(2, 8))
    app.gates_var = tk.StringVar(value="校验后显示四关")
    gate_row = ttk.Frame(right, style="CardBody.TFrame")
    gate_row.pack(fill="x")
    app.gate_labels = {}
    for key in ("integrity", "frame_rate", "image", "closeout"):
        label = _pill(gate_row, NAMES[key])
        label.pack(side="left", padx=(0, 6), pady=(0, 6))
        app.gate_labels[key] = label
    verdict_row = ttk.Frame(right, style="CardBody.TFrame")
    verdict_row.pack(fill="x", pady=(0, 8))
    app.verdict_label = _pill(verdict_row, "", variable=app.gates_var)
    app.verdict_label.pack(side="right")
    ttk.Button(right, text="选择本地会话并校验", command=app._audit_chosen,
               style="Secondary.TButton").pack(anchor="w", pady=(0, 8))
    log_wrap = tk.Frame(right, background="#F4F8F8")
    log_wrap.pack(fill="both", expand=True)
    app.log_text = tk.Text(log_wrap, height=5, wrap="word", state="normal",
                           background="#F4F8F8", foreground=INK, relief="flat",
                           padx=10, pady=8, borderwidth=0, font=(FONT, 9),
                           insertbackground=INK)
    app.log_text.insert("end", "操作记录会显示在这里。\n")
    app.log_text.configure(state="disabled")
    app.log_text.pack(fill="both", expand=True)


def _build_settings(app: Any) -> None:
    card = _card(app.settings_tab, padx=14, pady=10)
    card.pack(fill="x", pady=(8, 0))
    card.columnconfigure(0, weight=1)
    ttk.Label(card, text="采集工具", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(card, text="便携包已内置 FFmpeg 和 FFprobe。只在需要替换版本时填写路径。",
              style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 2))
    _field(card, 1, 0, "FFmpeg 路径", app.ffmpeg_var)
    _field(card, 2, 0, "FFprobe 路径", app.ffprobe_var)
    ttk.Button(card, text="检查工具", command=app._check_tools,
               style="Secondary.TButton").grid(row=6, column=0, sticky="w", pady=(8, 0))
    tip = _card(app.settings_tab, padx=14, pady=10)
    tip.pack(fill="x", pady=(8, 0))
    tip.columnconfigure(0, weight=1)
    tip.columnconfigure(1, weight=1)
    tip.columnconfigure(2, weight=1)
    ttk.Label(tip, text="随会话保存", style="CardTitle.TLabel").grid(
        row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(tip, text="镜头、光照和距离写入每一次采集。换电脑后重新选择摄像头；连接令牌不保存。",
              style="Hint.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 2))
    _field(tip, 1, 0, "镜头", app.lens_var)
    _field(tip, 1, 1, "光照", app.light_var)
    _field(tip, 1, 2, "距离", app.distance_var)


def update_board_format(app: Any) -> None:
    app.board_bitrate_entry.configure(state="normal" if app.board_format.get() == "raw"
                                      else "disabled")


def update_duration(app: Any) -> None:
    manual = app.duration_var.get() == "手动停止"
    text = "开始采集" if manual else "限时采集"
    for button in (getattr(app, "pc_start_button", None), getattr(app, "board_start_button", None)):
        if button is not None:
            button.configure(text=text)


def paint_gates(app: Any, gates: dict | None) -> None:
    for key, label in app.gate_labels.items():
        if not gates or key not in gates:
            label.configure(text=NAMES[key], background=CHIP, foreground=MUTED)
            continue
        status = gates[key].get("status", "pending")
        background, foreground = GATE_COLORS.get(status, (CHIP, MUTED))
        label.configure(text=f"{NAMES[key]} {WORDS.get(status, status)}",
                        background=background, foreground=foreground)
    verdict = app.verdict_label
    if not gates:
        app.gates_var.set("校验后显示四关")
        verdict.configure(background=CHIP, foreground=MUTED)
    elif gates.get("dataset_ready"):
        app.gates_var.set("可入库")
        verdict.configure(background=GATE_COLORS["pass"][0], foreground=GOOD)
    else:
        app.gates_var.set("不可入库")
        verdict.configure(background=GATE_COLORS["fail"][0], foreground=BAD)


def update_preset_hint(app: Any) -> None:
    name = app.board_preset.get()
    if name == "自己设置":
        app.exposure_row.grid()
        app.board_preset_note.set("拿不准就点「看清画面」。自动最亮；要自己填时，数字 100 大约是快门 10 毫秒。")
    else:
        app.exposure_row.grid_remove()
        spec = EXPOSURE_PRESETS.get(name)
        app.board_preset_note.set(spec[2] if spec else "")
    for key, button in getattr(app, "preset_buttons", {}).items():
        selected = key == name
        if key == "自己设置":
            button.configure(style="Primary.TButton" if selected else "Quiet.TButton")
        else:
            button.configure(style="Primary.TButton" if selected else "Secondary.TButton")


def update_board_exposure(app: Any) -> None:
    app.board_exposure_entry.configure(state="disabled" if app.board_exposure_mode.get() == "自动"
                                       else "normal")


def set_badge(app: Any, mode: str, text: str, *, live: bool = False) -> None:
    labels = [app.pc_badge if mode == "pc" else app.board_badge]
    if mode == "board" and getattr(app, "lab_badge", None) is not None:
        labels.append(app.lab_badge)
    for label in labels:
        label.configure(text=text, background="#DBF0E7" if live else CHIP,
                        foreground=GOOD if live else MUTED)


def refresh_controls(app: Any) -> None:
    local_active = app.local_recorder is not None
    board_active = bool(app.board_session_id)
    pairs = ((app.pc_start_button, not local_active and bool(app.pc_device.get().strip())),
             (app.pc_stop_button, local_active),
             (app.board_start_button, not board_active and bool(app.board_device.get().strip())
              and bool(app.board_url.get().strip()) and bool(app.board_token.get().strip())),
             (app.board_stop_button, board_active))
    for button, enabled in pairs:
        button.state(["!disabled"] if enabled and not app.working else ["disabled"])


def open_large_preview(app: Any) -> "LargePreview":
    current = getattr(app, "large_preview", None)
    if current is not None:
        try:
            current.window.lift()
            return current
        except tk.TclError:
            app.large_preview = None
    view = LargePreview(app)
    app.large_preview = view
    source = getattr(app.board_preview_canvas, "source_image", None)
    if source is not None:
        view.show_source(source)
    return view


class LargePreview:
    """Full-window camera view. Wheel zoom and drag inspect small objects."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.source: tk.PhotoImage | None = None
        self.magnify = 1
        self.pan_x = 0
        self.pan_y = 0
        self._center_next = False
        self._drag: tuple[int, int, int, int] | None = None
        window = tk.Toplevel(app)
        window.title("大屏看画面")
        window.geometry("1280x800")
        window.minsize(800, 500)
        try:
            window.state("zoomed")
        except tk.TclError:
            pass
        self.window = window
        bar = tk.Frame(window, background=SURFACE)
        bar.pack(fill="x")
        tk.Label(bar, text="滚轮放大，按住拖动。Esc 关闭。画面按采集分辨率送来，不是先缩成小图再拉大。",
                 background=SURFACE, foreground=INK, font=(FONT, 10)).pack(side="left", padx=12, pady=8)
        tk.Button(bar, text="关闭", command=self.close).pack(side="right", padx=12, pady=6)
        self.canvas = tk.Canvas(window, background=PREVIEW, highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag_to)
        window.bind("<Escape>", lambda _event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        _empty_preview(self.canvas, 960, 540)

    def show_source(self, source: tk.PhotoImage) -> None:
        self.source = source
        self.redraw()

    def _wheel(self, event: tk.Event) -> None:
        if event.delta > 0:
            if self.magnify == 1:
                self._center_next = True
            self.magnify = min(4, self.magnify + 1)
        else:
            self.magnify = max(1, self.magnify - 1)
        if self.magnify == 1:
            self.pan_x = self.pan_y = 0
        self.redraw()

    def _press(self, event: tk.Event) -> None:
        self._drag = (event.x, event.y, self.pan_x, self.pan_y)

    def _drag_to(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        x0, y0, pan_x, pan_y = self._drag
        self.pan_x = pan_x + event.x - x0
        self.pan_y = pan_y + event.y - y0
        self.redraw()

    def redraw(self) -> None:
        source = self.source
        width = max(self.canvas.winfo_width(), 2)
        height = max(self.canvas.winfo_height(), 2)
        if source is None:
            _empty_preview(self.canvas, width, height)
            return
        zoom, subsample, _out_w, _out_h = preview_fit(
            source.width(), source.height(), width, height, max_zoom=6)
        zoom *= self.magnify
        divisor = math.gcd(zoom, subsample)
        fitted = _scaled(source, zoom // divisor, subsample // divisor)
        image_w, image_h = fitted.width(), fitted.height()
        if self._center_next:
            self.pan_x = (width - image_w) // 2
            self.pan_y = (height - image_h) // 2
            self._center_next = False
        if image_w > width:
            self.pan_x = min(0, max(width - image_w, self.pan_x))
        else:
            self.pan_x = (width - image_w) // 2
        if image_h > height:
            self.pan_y = min(0, max(height - image_h, self.pan_y))
        else:
            self.pan_y = (height - image_h) // 2
        self.canvas.fitted_image = fitted
        self.canvas.delete("all")
        self.canvas.create_image(self.pan_x, self.pan_y, image=fitted, anchor="nw")

    def close(self) -> None:
        if getattr(self.app, "large_preview", None) is self:
            self.app.large_preview = None
        self.window.destroy()


def show_preview(app: Any, body: bytes, mode: str) -> None:
    encoded = base64.b64encode(body).decode("ascii")
    canvases = [app.pc_preview_canvas if mode == "pc" else app.board_preview_canvas]
    if mode == "board" and getattr(app, "lab_preview_canvas", None) is not None:
        canvases.append(app.lab_preview_canvas)
    for canvas in canvases:
        canvas.source_image = tk.PhotoImage(data=encoded)
        canvas.update_idletasks()
        layout_preview(canvas)
    large = getattr(app, "large_preview", None)
    if mode == "board" and large is not None:
        large.show_source(canvases[0].source_image)
    set_badge(app, mode, "画面已确认")
    if mode == "board" and getattr(app, "lab_badge", None) is not None:
        app.lab_badge.configure(text="画面已确认", background="#DBF0E7", foreground=GOOD)


def populate_sessions(app: Any, sessions: list[dict[str, Any]]) -> None:
    tree = app.session_tree
    for item in tree.get_children():
        tree.delete(item)
    for item in sessions:
        session_id = item.get("session_id", "")
        ready = item.get("ready")
        if ready is None:
            ready = "可入库" if item.get("dataset_ready") else "—"
        tree.insert("", "end", iid=session_id,
                    values=(item.get("created_utc", "")[:19].replace("T", " "),
                            item.get("status", ""), ready))


def select_session(app: Any) -> None:
    selected = app.session_tree.selection()
    if selected:
        app.remote_session.set(selected[0])
