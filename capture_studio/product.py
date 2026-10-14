"""Local product UI for Capture Studio.

The window is a browser page. Capture, SSH, and the board agent stay in the
existing Python modules.
"""
from __future__ import annotations

import json
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import socket
import subprocess

from .textcodec import safe_decode
from . import board_probe, peripherals, pc_peripherals, templates as capture_templates
from .camera_modes import apply_mode, choose_mode, list_dshow_modes, mode_label, saved_mode, sort_modes
import sys
import threading
import time
from typing import Any
from urllib.parse import urlparse

from .camera_lab import TUNING, camera_sentence, choice_label, has_image_tuning, read_tuning, slow_usb_warning
from .connect_kv260 import open_connection
from .core import (CaptureOptions, ProcessRecorder, SESSION_ID, audit_session,
                   local_ffmpeg_command, load_json, new_session, resolve_tool, update_session)
from .camera_pick import REASONS, camera_id, pick_camera
from .desktop import BoardClient, app_root, list_dshow_cameras
from .desktop_ui import EXPOSURE_PRESETS
from .gates import format_gates, preflight_dshow
from .portable_connect import FRESH_BOARD, connection_settings

WEB = Path(__file__).resolve().parent / "web"
EXPOSURE_LABELS = {"自动": 0, "手动": 1, "快门优先": 2}
DURATIONS = {"60 秒短检": 60, "10 分钟关口": 650, "手动停止": None}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Studio:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status = "就绪"
        self.busy = False
        self.logs: list[str] = []
        self.settings = self._load()
        self.client: BoardClient | None = None
        self.tunnel: subprocess.Popen[bytes] | None = None
        self.connected = False
        self.device = ""
        self.devices: list[str] = []
        self.cameras: list[dict[str, Any]] = []
        self.board_label = "未连接"
        self.camera_label = "未发现摄像头"
        self.sync_note = ""
        self.preview = b""
        self.preview_seq = 0
        self.live = False
        self._live_stop: threading.Event | None = None
        self.pc_devices: list[Any] = []
        self.pc_pick = ""  # v9: why the current PC camera was chosen (camera_pick.REASONS key)
        self.board_modes: list[dict[str, Any]] = []
        self.pc_modes: list[dict[str, Any]] = []
        self.modes_note = ""
        self.board_info: dict[str, Any] = {}
        self.board_status: dict[str, Any] = {}
        self.monitor: Any = None
        self.last_error = ""
        self._retry: tuple[str, Any] | None = None
        self.pc_peripherals: list[dict[str, Any]] = []
        self.pc_periph_busy = False
        self.ssh_args: list[str] = []
        self.peripherals: list[dict[str, Any]] = []
        self.periph_note = ""
        self.periph_busy = False
        self._hotplug = ""
        self._periph_at = 0.0
        self.controls: list[dict[str, Any]] = []
        self.recording: dict[str, Any] | None = None
        self.output_once: Path | None = None  # v9: template folder for one recording; settings keep the base
        self.local_recorder: ProcessRecorder | None = None
        self.sessions: list[dict[str, Any]] = []
        self.gates = ""
        self.metrics = ""

    def _settings_path(self) -> Path:
        return app_root() / "studio_settings.json"

    def _load(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "output": "captures", "ffmpeg": "", "ffprobe": "",
            "operator": "", "notes": "", "duration": "60 秒短检",
            "lens": "", "lighting": "", "distance": "",
            "width": 640, "height": 480, "fps": 30, "format": "mjpeg",
            "bitrate": 20000, "codec": "ffv1", "preset": "看清画面",
            "exposure_mode": "自动", "exposure_absolute": "",
            "power": "不改", "wb": "不改", "focus": "不改",
            "device": "", "pc_device": "", "pc_device_id": "",
            "auto_connect": "", "wizard_done": "", "theme": "跟随系统", "scene": "",
        }
        for item in TUNING:
            if item.kind == "int":
                defaults[item.name] = ""
        path = self._settings_path()
        if path.is_file():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    defaults.update({key: saved[key] for key in defaults if key in saved})
            except (OSError, ValueError):
                pass
        link = connection_settings()
        defaults["host"] = link.get("host", "")
        defaults["user"] = link.get("user", "ubuntu")
        defaults["key"] = link.get("key", "")
        defaults["board_root"] = link.get("board_root", FRESH_BOARD["board_root"])
        defaults["serial"] = link.get("serial", "")
        return defaults

    def _save(self) -> None:
        path = self._settings_path()
        path.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        link = {name: str(self.settings.get(name) or "") for name in
                ("host", "user", "key", "board_root", "serial")}
        (app_root() / "board_connection.json").write_text(
            json.dumps(link, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _log(self, message: str) -> None:
        self.logs.append(message)
        del self.logs[:-40]
        self.status = message

    def _output(self) -> Path:
        value = Path(str(self.settings.get("output") or "captures"))
        return (value if value.is_absolute() else app_root() / value).resolve()

    def _capture_root(self) -> Path:
        return self.output_once or self._output()

    def _tool(self, name: str) -> Path:
        return resolve_tool(name, str(self.settings.get(name) or ""), app_root())

    def state(self) -> dict[str, Any]:
        with self.lock:
            recording = dict(self.recording or {})
            if recording.get("started") and recording.get("seconds"):
                left = int(recording["seconds"] - (time.monotonic() - recording["started"]))
                recording["remaining"] = max(0, left)
            return {
                "status": self.status,
                "busy": self.busy,
                "logs": list(self.logs),
                "settings": dict(self.settings),
                "connected": self.connected,
                "device": self.device,
                "devices": list(self.devices),
                "cameras": self.cameras,
                "board_label": self.board_label,
                "camera_label": self.camera_label,
                "sync_note": self.sync_note,
                "live": self.live,
                "preview_seq": self.preview_seq,
                "pc_devices": list(self.pc_devices),
                "pc_pick": self.pc_pick,
                "controls": self.controls,
                "recording": recording,
                "sessions": self.sessions,
                "gates": self.gates,
                "metrics": self.metrics,
                "board_modes": list(self.board_modes),
                "pc_modes": list(self.pc_modes),
                "modes_note": self.modes_note,
                "board_info": dict(self.board_info),
                "board_status": dict(self.board_status),
                "peripherals": list(self.peripherals),
                "pc_peripherals": list(self.pc_peripherals),
                "pc_periph_busy": self.pc_periph_busy,
                "last_error": self.last_error,
                "can_retry": self._retry is not None,
                "periph_note": self.periph_note,
                "periph_busy": self.periph_busy,
            }

    def update_settings(self, payload: dict[str, Any]) -> None:
        with self.lock:
            chosen = str(payload.get("pc_device") or "")
            if chosen and chosen != str(self.settings.get("pc_device") or ""):
                # a different camera picked in the list = manual override; remember its VID:PID for next time
                self.pc_pick = "manual"
                payload = dict(payload)
                payload["pc_device_id"] = next((str(r.get("id") or "") for r in self.pc_devices
                                                if isinstance(r, dict) and r.get("value") == chosen), "")
            for key in self.settings:
                if key in payload and key != "password":
                    self.settings[key] = payload[key]
            self._save()

    def _work(self, label: str, func: Any) -> None:
        with self.lock:
            if self.busy:
                self._log("有操作正在进行")
                return
            self.busy = True
            self.status = label
            self.last_error = ""
            self._retry = None

        def run() -> None:
            try:
                func()
            except Exception as exc:
                with self.lock:
                    self._log(str(exc))
                    self.last_error = str(exc) or type(exc).__name__
                    self._retry = (label, func)
            finally:
                with self.lock:
                    self.busy = False

        threading.Thread(target=run, daemon=True).start()

    def discover(self) -> None:
        def work() -> None:
            from .board_discover import find_board
            host, note = find_board()
            with self.lock:
                if host:
                    self.settings["host"] = host
                    self._save()
                self._log(note or (host or "未找到开发板"))

        self._work("正在查找", work)

    def connect(self, payload: dict[str, Any]) -> None:
        self.update_settings(payload)
        password = str(payload.get("password") or "")

        def work() -> None:
            key = Path(str(self.settings.get("key") or ""))
            if not key.is_file():
                from .board_discover import ensure_ssh_key
                key = ensure_ssh_key(Path.home())
                with self.lock:
                    self.settings["key"] = str(key)
                    self._save()
            port = _free_port()
            args = Namespace(
                host=str(self.settings.get("host") or ""),
                user=str(self.settings.get("user") or "ubuntu"),
                ssh_key=key,
                board_root=str(self.settings.get("board_root") or FRESH_BOARD["board_root"]),
                local_port=port,
                device=None,
                camera_serial=str(self.settings.get("serial") or ""),
                password=password,
            )
            if not args.host:
                raise RuntimeError("填写开发板地址，或先查找")
            connection = open_connection(args)
            info = connection["client"].request("GET", "/devices")
            cameras = info.get("device_info") or []
            device = str(connection.get("device") or "")
            chosen = next((item for item in cameras if item.get("device") == device), None)
            board = info.get("board") or {}
            with self.lock:
                if self.tunnel is not None:
                    self.tunnel.terminate()
                self.client = connection["client"]
                self.tunnel = connection["tunnel"]
                self.connected = True
                self.device = device
                self.settings["device"] = device
                if cameras:
                    self.devices = [{"label": choice_label(item), "value": str(item.get("device") or "")}
                                    for item in cameras]
                else:
                    self.devices = [{"label": path, "value": path} for path in connection.get("devices") or []]
                self.cameras = cameras
                self.board_label = board.get("model") or board.get("hostname") or args.host
                self.camera_label = camera_sentence(chosen) if chosen else (
                    connection.get("selection_note") or "请选择摄像头")
                self.sync_note = connection.get("sync_note") or connection.get("selection_note") or ""
                self._log(self.sync_note or f"已连接 {self.camera_label}")
            self._detect_board_modes()  # automatic; never fails the connection
            self._probe_board(args.user, args.host, key)  # board-agnostic info + live status

        self._work("正在连接", work)

    # ---- board info / live status (v6, any SSH Linux board) -------------------------
    def _ssh_args(self, user: str, host: str, key: Path) -> list[str]:
        ssh = shutil.which("ssh")
        if not ssh:
            raise RuntimeError("OpenSSH 不可用")
        return [ssh, "-i", str(key), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", f"{user}@{host}"]

    def _probe_board(self, user: str, host: str, key: Path) -> None:
        """Never fails the connection: every probe is optional."""
        try:
            ssh_args = self._ssh_args(user, host, key)
            info = board_probe.probe_info(ssh_args)
        except Exception as exc:
            with self.lock:
                self.board_info = {}
                self._log(f"未能读取开发板信息：{exc}")
            return
        with self.lock:
            self.board_info = info
            self.ssh_args = ssh_args
            if info.get("model"):
                self.board_label = str(info["model"])
        self._start_monitor(ssh_args)
        self.scan_peripherals()  # automatic on connect

    def _start_monitor(self, ssh_args: list[str], factory: Any = None) -> None:
        self._stop_monitor()

        def update(status: dict[str, Any]) -> None:
            rescan = False
            with self.lock:
                if self.monitor is not monitor:
                    return
                self.board_status = status
                sig = str(status.get("hotplug") or "")
                if sig and self._hotplug and sig != self._hotplug:
                    rescan = True
                if sig:
                    self._hotplug = sig
            if rescan:
                self.scan_peripherals(reason="hotplug")

        monitor = (factory or board_probe.StatusMonitor)(ssh_args, update, 2.0)
        with self.lock:
            self.monitor = monitor
            self.board_status = {}
        monitor.start()

    def _stop_monitor(self) -> None:
        with self.lock:
            monitor, self.monitor = self.monitor, None
            self._hotplug = ""
        if monitor is not None:
            monitor.stop()

    # ---- v7: retry / pc peripherals / templates ---------------------------------------
    def retry(self) -> None:
        with self.lock:
            job = self._retry
        if job is not None:
            self._work(*job)

    def dismiss_error(self) -> None:
        with self.lock:
            self.last_error = ""
            self._retry = None

    def scan_pc_peripherals(self, runner: Any = None) -> None:
        with self.lock:
            if self.pc_periph_busy:
                return
            self.pc_periph_busy = True

        def work() -> None:
            try:
                items = (runner or pc_peripherals.scan)()
            except Exception as exc:
                items = []
                with self.lock:
                    self._log(f"电脑外设扫描失败：{exc}")
            with self.lock:
                self.pc_peripherals = items
                self.pc_periph_busy = False

        threading.Thread(target=work, daemon=True).start()

    def templates_path(self) -> Path:
        return app_root() / "capture_templates.json"

    def run_template(self, name: str, mode: str, start: bool = True) -> dict[str, Any]:
        data = capture_templates.load_all(self.templates_path())
        if name not in data:
            raise KeyError(name)
        with self.lock:
            payload = capture_templates.apply(dict(self.settings), data[name])
        payload["_output_once"] = payload.pop("output")
        if start:
            self.start_record(payload, mode)
        else:
            payload.pop("_output_once", None)
            self.update_settings(payload)
        with self.lock:
            self._log(f"已套用模板 {name}")
        return payload

    # ---- peripherals (v6) ------------------------------------------------------------
    def scan_peripherals(self, i2c: bool = False, reason: str = "", runner: Any = None) -> None:
        """Read-only discovery over SSH on its own thread; never blocks capture operations."""
        with self.lock:
            if self.periph_busy or not self.ssh_args:
                if not self.ssh_args:
                    self.periph_note = "连接开发板后可扫描外设"
                return
            self.periph_busy = True
            ssh_args = list(self.ssh_args)
            old = list(self.peripherals)

        def work() -> None:
            try:
                items = (runner or peripherals.scan)(ssh_args, i2c)
            except Exception as exc:
                with self.lock:
                    self.periph_note = f"外设扫描失败：{exc}"
                    self.periph_busy = False
                return
            added, removed = peripherals.diff(old, items) if old else ([], [])
            with self.lock:
                self.peripherals = items
                self.periph_busy = False
                self._periph_at = time.monotonic()
                self.periph_note = f"共 {len(items)} 项"
                for name in added:
                    self._log(f"新接入：{name}")
                for name in removed:
                    self._log(f"已移除：{name}")

        threading.Thread(target=work, daemon=True).start()

    def export_peripherals(self) -> Path:
        with self.lock:
            items = list(self.peripherals)
            info = dict(self.board_info)
            folder = self._output()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / time.strftime("peripherals_%Y%m%d_%H%M%S.json")
        payload = {"board": info, "peripherals": [dict(item, props=[list(p) for p in item["props"]]) for item in items]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with self.lock:
            self._log(f"已导出 {path.name}")
        return path

    # ---- capture mode detection (v6) ----------------------------------------------
    def _adopt_modes(self, kind: str, modes: list[dict[str, Any]], note: str) -> None:
        """Store detected modes; keep the saved mode if supported, else pick a sensible default."""
        modes = sort_modes(modes)
        with self.lock:
            setattr(self, f"{kind}_modes", modes)
            self.modes_note = note
            chosen = choose_mode(modes, saved_mode(self.settings))
            if chosen is not None and chosen != saved_mode(self.settings):
                apply_mode(self.settings, chosen)
                self._save()
                self._log(f"已选用 {mode_label(chosen)}")
            elif modes:
                self._log(f"已检测到 {len(modes)} 种模式")
            else:
                self._log(note or "未检测到模式，显示常用预设")

    def _detect_board_modes(self) -> None:
        with self.lock:
            client = self.client
            device = str(self.settings.get("device") or self.device)
        if client is None or not device:
            self._adopt_modes("board", [], "未检测到模式，显示常用预设")
            return
        try:
            from urllib.parse import quote
            payload = client.request("GET", "/formats?device=" + quote(device))
            modes = list(payload.get("modes") or [])
            note = str(payload.get("error") or "")
        except Exception as exc:  # old board agent (404), timeout, ...: fall back to presets
            modes, note = [], "开发板未提供模式检测，显示常用预设"
            with self.lock:
                self._log(str(exc))
        self._adopt_modes("board", modes, note if not modes else "")

    def _detect_pc_modes(self, ffmpeg: Path, device: str) -> None:
        if not device:
            self._adopt_modes("pc", [], "未检测到模式，显示常用预设")
            return
        try:
            modes = list_dshow_modes(ffmpeg, device)
        except Exception as exc:
            modes = []
            with self.lock:
                self._log(str(exc))
        self._adopt_modes("pc", modes, "" if modes else "未检测到模式，显示常用预设")

    def detect_modes(self, kind: str) -> None:
        def work() -> None:
            if kind == "board":
                self._detect_board_modes()
                return
            ffmpeg = self._tool("ffmpeg")
            with self.lock:
                device = str(self.settings.get("pc_device") or (self.pc_devices[0] if self.pc_devices else ""))
            self._detect_pc_modes(ffmpeg, device)

        self._work("正在检测模式", work)

    def scan_pc(self) -> None:
        def work() -> None:
            ffmpeg = self._tool("ffmpeg")
            cameras = list_dshow_cameras(ffmpeg)
            names = [item["value"] for item in cameras]
            with self.lock:
                self.pc_devices = [{"label": item["label"], "value": item["value"], "id": camera_id(item)}
                                   for item in cameras]
                self._log(f"本机摄像头 {len(cameras)} 台" if cameras else "未检测到摄像头")
                if len({item["name"] for item in cameras}) < len(cameras):
                    self._log("有同名摄像头，已用设备路径分开")
                device, reason = pick_camera(cameras, str(self.settings.get("pc_device") or ""),
                                             str(self.settings.get("pc_device_id") or ""))
                self.settings["pc_device"] = device
                if device:
                    self.settings["pc_device_id"] = next((r["id"] for r in self.pc_devices if r["value"] == device), "")
                self.pc_pick = reason
                if reason in ("vidpid", "sole_uvc", "need_manual"):
                    self._log(REASONS[reason])
            if device:
                self._detect_pc_modes(ffmpeg, device)  # automatic after listing cameras

        self._work("正在列出本机摄像头", work)

    def _options(self, mode: str) -> CaptureOptions:
        settings = self.settings
        preset = str(settings.get("preset") or "看清画面")
        if preset in EXPOSURE_PRESETS:
            mode_label, absolute, _note = EXPOSURE_PRESETS[preset]
        else:
            mode_label = str(settings.get("exposure_mode") or "自动")
            absolute = str(settings.get("exposure_absolute") or "")
        exposure_mode = EXPOSURE_LABELS.get(mode_label, 0)
        exposure_absolute = int(absolute) if exposure_mode and str(absolute).isdigit() else None
        tuning: dict[str, Any] = {}
        for item in TUNING:
            if item.kind == "int":
                text = str(settings.get(item.name) or "")
            elif item.name == "white_balance_auto":
                text = str(settings.get("wb") or "不改")
            elif item.name == "focus_auto":
                text = str(settings.get("focus") or "不改")
            else:
                text = str(settings.get("power") or "不改")
            tuning[item.name] = read_tuning(item.kind, text, item.label, item.low, item.high)
        if tuning.get("white_balance_auto") == 1:
            tuning["white_balance_temperature"] = None
        if tuning.get("focus_auto") == 1:
            tuning["focus_absolute"] = None
        device = str(settings.get("device") or self.device) if mode == "kv260_usb" else str(settings.get("pc_device") or "")
        if mode == "kv260_usb" and not re.fullmatch(r"/dev/video[0-9]+", device):
            raise RuntimeError("请先在列表里选择一只开发板上的摄像头。")
        if mode == "pc_usb" and not device:
            raise RuntimeError("请先在列表里选择一只电脑上的摄像头。")
        source_format = str(settings.get("format") or "mjpeg")
        info = next((item for item in self.cameras if item.get("device") == device), {})
        duration = DURATIONS.get(str(settings.get("duration") or ""), 60)
        options = CaptureOptions(
            device=device,
            width=int(settings.get("width") or 640),
            height=int(settings.get("height") or 480),
            fps=int(settings.get("fps") or 30),
            source_format=source_format if mode == "kv260_usb" else "auto",
            codec="copy" if mode == "kv260_usb" and source_format == "mjpeg"
            else ("h264" if mode == "kv260_usb" else str(settings.get("codec") or "ffv1")),
            bitrate_kbps=int(settings.get("bitrate") or 20000),
            operator=str(settings.get("operator") or ""),
            notes=str(settings.get("notes") or ""),
            lens=str(settings.get("lens") or ""),
            lighting=str(settings.get("lighting") or ""),
            distance=str(settings.get("distance") or ""),
            planned_seconds=duration,
            exposure_mode=exposure_mode,
            exposure_absolute=exposure_absolute,
            camera_serial=str(info.get("serial") or ""),
            usb_speed=str(info.get("speed") or ""),
            **tuning,
        )
        options.validate(mode)
        return options

    def _remember_frame(self, body: bytes) -> None:
        with self.lock:
            self.preview = body
            self.preview_seq += 1

    def start_live(self, payload: dict[str, Any]) -> None:
        self.update_settings(payload)

        def work() -> None:
            self.stop_live(remote=True, wait=True)
            with self.lock:
                client = self.client
            if client is None:
                raise RuntimeError("尚未连接开发板")
            options = self._options("kv260_usb")
            warning = slow_usb_warning(options.usb_speed, options.width, options.height)
            client.request("POST", "/live/start", options.__dict__)
            stop = threading.Event()
            with self.lock:
                self._live_stop = stop
                self.live = True
                if warning:
                    self._log(warning)
                else:
                    self._log("实时预览")

            def pump() -> None:
                from urllib.request import Request, urlopen
                from .live_preview import read_png
                request = Request(client.base_url + "/live/stream",
                                  headers={"Authorization": "Bearer " + client.token})
                try:
                    with urlopen(request, timeout=10) as stream:
                        while not stop.is_set():
                            self._remember_frame(read_png(stream))
                except Exception as exc:
                    if not stop.is_set():
                        with self.lock:
                            self._log(str(exc))
                            self.live = False

            threading.Thread(target=pump, daemon=True).start()

        self._work("正在打开画面", work)

    def stop_live(self, remote: bool = True, wait: bool = False) -> None:
        with self.lock:
            stop = self._live_stop
            client = self.client
            self._live_stop = None
            self.live = False
        if stop is not None:
            stop.set()
        if remote and client is not None:
            def work() -> None:
                try:
                    client.request("POST", "/live/stop", {}, timeout=10)
                except RuntimeError:
                    pass
            if wait:
                work()
            else:
                threading.Thread(target=work, daemon=True).start()

    def snap(self, payload: dict[str, Any], mode: str) -> None:
        self.update_settings(payload)

        def work() -> None:
            if mode == "pc":
                options = self._options("pc_usb")
                ffmpeg = self._tool("ffmpeg")
                root = self._output()
                root.mkdir(parents=True, exist_ok=True)
                target = root / ".capture_preview.png"
                command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "dshow",
                           "-video_size", f"{options.width}x{options.height}",
                           "-framerate", str(options.fps), "-i", f"video={options.device}",
                           "-frames:v", "1", str(target)]
                result = subprocess.run(command, capture_output=True, timeout=25)
                if result.returncode != 0 or not target.is_file():
                    raise RuntimeError(safe_decode(result.stderr)[-400:])
                self._remember_frame(target.read_bytes())
                target.unlink(missing_ok=True)
            else:
                with self.lock:
                    client = self.client
                if client is None:
                    raise RuntimeError("尚未连接开发板")
                options = self._options("kv260_usb")
                self._remember_frame(client.snapshot(options))
            with self.lock:
                self._log("画面已更新")

        self._work("正在取画面", work)

    def read_controls(self) -> None:
        def work() -> None:
            with self.lock:
                client = self.client
                device = str(self.settings.get("device") or self.device)
            if client is None or not device:
                raise RuntimeError("先连接开发板上的摄像头")
            from urllib.parse import quote
            payload = client.request("GET", "/controls?device=" + quote(device))
            with self.lock:
                self.controls = payload.get("controls") or []
                self._log("已读取参数" if self.controls else "未读到可调项")

        self._work("正在读取参数", work)

    def start_record(self, payload: dict[str, Any], mode: str) -> None:
        payload = dict(payload)
        once = payload.pop("_output_once", None)
        with self.lock:
            if once:
                value = Path(str(once))
                self.output_once = (value if value.is_absolute() else app_root() / value).resolve()
            else:
                self.output_once = None
        self.update_settings(payload)

        def work() -> None:
            self.stop_live(remote=False, wait=True)
            if mode == "pc":
                options = self._options("pc_usb")
                ffmpeg = self._tool("ffmpeg")
                root = self._capture_root()
                root.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(root).free < 100_000_000:
                    raise RuntimeError("磁盘剩余空间不足 100 MB")
                preflight = preflight_dshow(ffmpeg, options)
                session = new_session(root, "pc_usb", options)
                update_session(session, image_preflight=preflight, exposure_applied="not_applied")
                recorder = ProcessRecorder(session, local_ffmpeg_command(ffmpeg, options, session), "ffmpeg")
                recorder.start()
                with self.lock:
                    self.local_recorder = recorder
                    self.recording = {"mode": "pc", "session_id": session.name,
                                      "seconds": options.planned_seconds, "started": time.monotonic()}
                    self._log(f"电脑采集中 {session.name}")
                self._arm(session.name, options.planned_seconds)
                return
            with self.lock:
                client = self.client
            if client is None:
                raise RuntimeError("尚未连接开发板")
            options = self._options("kv260_usb")
            if has_image_tuning(options):
                with self.lock:
                    self._log("已修改图像参数，使用通用采集")
            value = client.request("POST", "/start", options.__dict__, timeout=60)
            with self.lock:
                self.recording = {"mode": "board", "session_id": value["session_id"],
                                  "seconds": options.planned_seconds, "started": time.monotonic()}
                self._log(f"采集中 {value['session_id']}")
            self._arm(value["session_id"], options.planned_seconds)

        self._work("正在开始采集", work)

    def _arm(self, session_id: str, seconds: int | None) -> None:
        if not seconds:
            return

        def wait() -> None:
            time.sleep(seconds)
            for _ in range(30):
                with self.lock:
                    current = (self.recording or {}).get("session_id")
                    busy = self.busy
                if current != session_id:
                    return
                if not busy:
                    self.stop_record()
                    return
                time.sleep(1)

        threading.Thread(target=wait, daemon=True).start()

    def stop_record(self) -> None:
        def work() -> None:
            with self.lock:
                recording = dict(self.recording or {})
                recorder = self.local_recorder
                client = self.client
            if recording.get("mode") == "pc" and recorder is not None:
                manifest = recorder.stop()
                audit = None
                if manifest.get("status") == "recorded":
                    audit = audit_session(recorder.session, self._tool("ffprobe"))
                with self.lock:
                    self.local_recorder = None
                    self.recording = None
                    self.gates = format_gates(audit) if isinstance(audit, dict) else ""
                    self._log(f"电脑采集结束 {manifest.get('status', '')}")
                return
            if client is None:
                raise RuntimeError("尚未连接开发板")
            manifest = client.request("POST", "/stop", {}, timeout=3600)
            session = client.download_session(manifest["session_id"], self._capture_root())
            audit = audit_session(session, self._tool("ffprobe"))
            with self.lock:
                self.recording = None
                self.gates = format_gates(audit) if isinstance(audit, dict) else ""
                self._log(f"已取回 {session.name}")

        self._work("正在停止并取回", work)

    def list_sessions(self, where: str) -> None:
        def work() -> None:
            rows: list[dict[str, Any]] = []
            if where == "board":
                with self.lock:
                    client = self.client
                if client is None:
                    raise RuntimeError("尚未连接开发板")
                rows = client.request("GET", "/sessions").get("sessions") or []
            else:
                from .session_review import find_sessions
                root = self._output()
                base = root.parent if root.parent.name and SESSION_ID.fullmatch(root.name) is None and \
                    capture_templates.re.match(r"^\d{8}(_|$)", root.name) else root
                for path in find_sessions(base, limit=40):
                    if not SESSION_ID.fullmatch(path.name):
                        continue
                    item = load_json(path / "session.json")
                    rows.append({"session_id": item.get("session_id", path.name),
                                 "created_utc": item.get("created_utc", ""),
                                 "status": item.get("status", ""), "path": str(path)})
            with self.lock:
                self.sessions = rows
                self._log(f"会话 {len(rows)} 个")

        self._work("正在列出会话", work)

    def fetch_session(self, session_id: str) -> None:
        def work() -> None:
            with self.lock:
                client = self.client
            if client is None:
                raise RuntimeError("尚未连接开发板")
            session = client.download_session(session_id, self._output())
            with self.lock:
                self._log(f"已取回 {session.name}")

        self._work("正在取回", work)

    def session_path(self, session_id: str) -> Path:
        """Session folder in the output root, or in a template sub-folder next to it (v7)."""
        root = self._output()
        direct = root / session_id
        if direct.is_dir():
            return direct
        from .session_review import find_sessions
        for base in (root, root.parent):
            for path in find_sessions(base, limit=400):
                if path.name == session_id:
                    return path
        return direct

    def audit(self, session_id: str) -> None:
        def work() -> None:
            session = self.session_path(session_id)
            result = audit_session(session, self._tool("ffprobe"))
            with self.lock:
                self.gates = format_gates(result) if isinstance(result, dict) else ""
                self._log(f"已校验 {session_id}")

        self._work("正在校验", work)

    def close(self) -> None:
        self._stop_monitor()
        self.stop_live(remote=True, wait=False)
        with self.lock:
            tunnel = self.tunnel
            self.tunnel = None
        if tunnel is not None:
            tunnel.terminate()


STUDIO = Studio()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0") or 0)
        if size > 100_000:
            raise ValueError("request too large")
        if size <= 0:
            return {}
        value = json.loads(self.rfile.read(size).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self._json(200, STUDIO.state())
            return
        if path == "/preview.png":
            with STUDIO.lock:
                body = STUDIO.preview
            if not body:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB / relative).resolve()
        if WEB not in target.parents and target != WEB:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        kind = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}.get(
                    target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read()
        except (ValueError, UnicodeError) as exc:
            self._json(400, {"error": str(exc)})
            return
        routes = {
            "/api/settings": lambda: STUDIO.update_settings(payload),
            "/api/discover": STUDIO.discover,
            "/api/connect": lambda: STUDIO.connect(payload),
            "/api/pc/devices": STUDIO.scan_pc,
            "/api/preview/live": lambda: STUDIO.start_live(payload),
            "/api/preview/stop": lambda: STUDIO.stop_live(),
            "/api/preview/snap": lambda: STUDIO.snap(payload, str(payload.get("mode") or "board")),
            "/api/controls": STUDIO.read_controls,
            "/api/record/start": lambda: STUDIO.start_record(payload, str(payload.get("mode") or "board")),
            "/api/record/stop": STUDIO.stop_record,
            "/api/sessions": lambda: STUDIO.list_sessions(str(payload.get("where") or "local")),
            "/api/sessions/fetch": lambda: STUDIO.fetch_session(str(payload.get("session_id") or "")),
            "/api/sessions/audit": lambda: STUDIO.audit(str(payload.get("session_id") or "")),
        }
        action = routes.get(path)
        if action is None:
            self._json(404, {"error": "unknown"})
            return
        action()
        self._json(200, STUDIO.state())


def main() -> None:
    from .window import main as run_window
    run_window()


if __name__ == "__main__":
    main()
