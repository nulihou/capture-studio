"""Portable Windows desktop controller for PC and board USB acquisition."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .camera_lab import (RESOLUTION_PRESETS, TUNING, arrival_message, board_sentence,
                         camera_sentence, choice_label, choose_camera, has_image_tuning,
                         path_from_choice, read_tuning, slow_usb_warning)
from .core import (CaptureOptions, ProcessRecorder, SESSION_ID, audit_session,
                   local_ffmpeg_command, load_json, new_session, resolve_tool, sha256,
                   update_session)
from .gates import format_gates, gate_lines, preflight_dshow
from .desktop_ui import (EXPOSURE_PRESETS, PRESET_ALIASES, build_ui, paint_gates,
                         paint_lab_support, populate_sessions, refresh_controls, set_badge,
                         show_preview, update_board_exposure, update_preset_hint)


def app_root() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


class BoardClient:
    def live_frame(self) -> bytes:
        request = Request(self.base_url + '/live/frame', headers={'Authorization': 'Bearer '+self.token})
        from .live_preview import PREVIEW_PNG_LIMIT
        with urlopen(request, timeout=5) as response:
            if response.headers.get_content_type() != 'image/png':
                raise RuntimeError('preview response is not PNG')
            body = response.read(PREVIEW_PNG_LIMIT + 1)
            if len(body) > PREVIEW_PNG_LIMIT:
                raise RuntimeError('preview frame exceeds limit')
            return body

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path:
            raise ValueError("Board URL must be http(s)://host:port")
        if not token.strip():
            raise ValueError("Board token is required")
        self.token = token.strip()

    def request(self, method: str, endpoint: str, payload: dict[str, Any] | None = None,
                *, timeout: int = 15) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(self.base_url + endpoint, data=data, method=method,
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", str(exc))
            except (ValueError, UnicodeError):
                detail = str(exc)
            raise RuntimeError(f"Board returned {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach board: {exc.reason}") from exc

    def download_session(self, session_id: str, output_root: Path) -> Path:
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid board session ID")
        manifest = self.request("GET", f"/sessions/{session_id}")
        if manifest.get("status") not in ("recorded", "audited", "needs_review"):
            raise RuntimeError("board session must be stopped before download")
        session = output_root.expanduser().resolve() / session_id
        session.mkdir(parents=True, exist_ok=True)
        items = manifest.get("files", [])
        if not isinstance(items, list) or not items:
            raise RuntimeError("board session has no recorded files")
        for item in items:
            relative = item["path"]
            if not re.fullmatch(r"segments/part_[0-9]{5}\.mkv", relative):
                raise ValueError("board manifest contains an unsafe file path")
            target = session / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file() and sha256(target) == item["sha256"]:
                continue
            partial = target.with_name(target.name + ".part")
            request = Request(self.base_url + f"/sessions/{session_id}/files/{quote(relative, safe='/')}",
                              headers={"Authorization": "Bearer " + self.token})
            try:
                with urlopen(request, timeout=120) as response, partial.open("wb") as handle:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        handle.write(block)
            except (HTTPError, URLError, OSError) as exc:
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"download failed for {relative}: {exc}") from exc
            if partial.stat().st_size != item["size"] or sha256(partial) != item["sha256"]:
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"checksum mismatch for {relative}")
            partial.replace(target)
        (session / "session.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
        try:
            log_request = Request(self.base_url + f"/sessions/{session_id}/files/capture.log",
                                  headers={"Authorization": "Bearer " + self.token})
            with urlopen(log_request, timeout=30) as response:
                (session / "capture.log").write_bytes(response.read())
        except (HTTPError, URLError):
            pass
        return session

    def snapshot(self, options: CaptureOptions) -> bytes:
        request = Request(self.base_url + "/snapshot", data=json.dumps(options.__dict__).encode("utf-8"),
                          method="POST", headers={"Authorization": "Bearer " + self.token,
                                                  "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=35) as response:
                if response.headers.get_content_type() != "image/png":
                    raise RuntimeError("board did not return a PNG preview")
                return response.read(6 * 1024 * 1024)
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", str(exc))
            except (ValueError, UnicodeError):
                detail = str(exc)
            raise RuntimeError(f"board preview failed: {detail}") from exc


_DSHOW_NAME = re.compile(r'\]\s+"([^"]+)"(?:\s+\(([^)]+)\))?\s*$')
_DSHOW_ALT = re.compile(r'Alternative name "([^"]+)"')
_DSHOW_VID = re.compile(r"vid_([0-9a-fA-F]{4})&pid_([0-9a-fA-F]{4})", re.I)


def parse_dshow_devices(stderr: str) -> list[str]:
    names: list[str] = []
    for item in parse_dshow_cameras(stderr):
        if item["name"] not in names:
            names.append(item["name"])
    return names


def parse_dshow_cameras(stderr: str) -> list[dict[str, str]]:
    """Video devices with the DirectShow name ffmpeg records, plus VID:PID when advertised."""
    cameras: list[dict[str, str]] = []
    pending: dict[str, str] | None = None
    in_video = False
    for line in stderr.splitlines():
        if "DirectShow video devices" in line:
            in_video = True
            continue
        if "DirectShow audio devices" in line:
            in_video = False
            pending = None
            continue
        alternative = _DSHOW_ALT.search(line)
        if alternative and pending is not None:
            pending["alternative"] = alternative.group(1)
            found = _DSHOW_VID.search(alternative.group(1))
            if found:
                pending["vid"], pending["pid"] = found.group(1).lower(), found.group(2).lower()
            continue
        match = _DSHOW_NAME.search(line)
        if match and (match.group(2) == "video" or
                      (in_video and match.group(2) not in ("audio", "none"))):
            pending = {"name": match.group(1), "vid": "", "pid": "", "alternative": ""}
            cameras.append(pending)
    names = [item["name"] for item in cameras]
    for item in cameras:
        ident = f"{item['vid']}:{item['pid']}" if item["vid"] else ""
        item["label"] = f"{item['name']} · {ident}" if ident else item["name"]
        duplicated = names.count(item["name"]) > 1 and bool(item["alternative"])
        item["value"] = item["alternative"] if duplicated else item["name"]
    return cameras


def decode_dshow_text(data: bytes) -> str:
    """FFmpeg on Chinese Windows writes DirectShow names in the system code page."""
    import locale
    encodings: list[str] = []
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gbk"):
        if encoding and encoding.lower() not in {item.lower() for item in encodings}:
            encodings.append(encoding)
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def list_dshow_devices(ffmpeg: Path) -> list[str]:
    return [item["name"] for item in list_dshow_cameras(ffmpeg)]


def list_dshow_cameras(ffmpeg: Path) -> list[dict[str, str]]:
    result = subprocess.run([str(ffmpeg), "-hide_banner", "-list_devices", "true", "-f", "dshow",
                             "-i", "dummy"], capture_output=True, timeout=15)
    return parse_dshow_cameras(decode_dshow_text(result.stderr or b""))


class CaptureDesktop(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.root_dir = app_root()
        self.settings_path = self.root_dir / "capture_settings.json"
        self.local_recorder: ProcessRecorder | None = None
        self.board_session_id: str | None = None
        self.current_session: Path | None = None
        self.working = False
        self.results: queue.Queue[tuple[Callable[[Any], None], Any, str | None]] = queue.Queue()
        self._local_exit_reported = False
        self._pc_devices: list[str] = []
        self._pc_scan_state = "scanning"
        self._board_devices: list[str] = []
        self._board_connected = False
        self._board_device_error: str | None = None
        self._ssh_tunnel = None
        self._auto_stop = None
        self._preset_guard = False
        self._preview_after_connect = False
        self._resolution_guard = False
        self._choice_guard = False
        self._watch_busy = False
        self._quiet_errors = False
        self._next_connect = 0.0
        self._board_infos: list[dict[str, Any]] = []
        self._board_facts: dict[str, Any] = {}
        self._watch_generation = 0
        self.lab_support: dict[str, Any] = {}
        self.lab_controls: list[dict[str, Any]] = []
        self._build()
        self.pc_device.trace_add("write", lambda *_: self._update_pc_device_display())
        self.board_device.trace_add("write", lambda *_: self._update_board_device_display())
        self.board_url.trace_add("write", lambda *_: self._board_connection_changed())
        self.board_token.trace_add("write", lambda *_: self._board_connection_changed())
        self.board_preset.trace_add("write", lambda *_: self._on_exposure_preset())
        self.board_exposure_mode.trace_add("write", lambda *_: self._mark_custom_preset())
        self.board_exposure_absolute.trace_add("write", lambda *_: self._mark_custom_preset())
        self.board_resolution.trace_add("write", lambda *_: self._on_resolution_preset())
        self.board_width.trace_add("write", lambda *_: self._mark_custom_resolution())
        self.board_height.trace_add("write", lambda *_: self._mark_custom_resolution())
        self.lab_camera_pick.trace_add("write", lambda *_: self._on_lab_choice())
        self.board_live_metrics_var.trace_add(
            "write", lambda *_: self.lab_metrics_var.set(self.board_live_metrics_var.get()))
        self._load_settings()
        self._sync_resolution_preset()
        self._refresh_lab_identity()
        self._poll_after_id = self.after(100, self._poll)
        self._scan_after_id = self.after(250, self._list_local_devices)
        self._watch_after_id = self.after(4000, self._watch_tick)

    def _build(self) -> None:
        build_ui(self)

    def _browse_output(self) -> None:
        chosen = filedialog.askdirectory(title="选择数据集目录")
        if chosen:
            self.output_var.set(chosen)

    def _check_tools(self) -> None:
        try:
            paths = [str(self._tool("ffmpeg", self.ffmpeg_var)),
                     str(self._tool("ffprobe", self.ffprobe_var))]
        except FileNotFoundError as exc:
            messagebox.showerror("缺少工具", str(exc))
            return
        self._log("采集工具已就绪：" + "；".join(paths))

    def _output_root(self) -> Path:
        value = Path(self.output_var.get().strip())
        return (value if value.is_absolute() else self.root_dir / value).resolve()

    def _tool(self, name: str, configured: tk.StringVar) -> Path:
        return resolve_tool(name, configured.get().strip(), self.root_dir)

    def _client(self) -> BoardClient:
        return BoardClient(self.board_url.get().strip(), self.board_token.get())

    def _safe_client(self) -> BoardClient | None:
        try:
            return self._client()
        except ValueError as exc:
            messagebox.showerror("开发板连接设置", str(exc))
            return None

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.status_var.set(message if len(message) <= 110 else message[:107] + "…")

    def _run(self, description: str, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        if self.working:
            self._log("另一项操作尚未完成")
            return
        self.working = True
        self._log(description)
        refresh_controls(self)

        def worker() -> None:
            try:
                result = work()
                self.results.put((done, result, None))
            except Exception as exc:
                self.results.put((done, None, str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _complete(self, done: Callable[[Any], None], result: Any, error: str | None) -> None:
        self.working = False
        quiet = self._quiet_errors
        self._quiet_errors = False
        if error:
            if quiet:
                self._log("自动连接未成功：" + error)
                self.lab_watch_var.set("未连接")
            else:
                self._log("失败：" + error)
                messagebox.showerror("操作失败", error)
        else:
            done(result)
        refresh_controls(self)

    def _update_pc_device_display(self) -> None:
        name = self.pc_device.get().strip()
        if name and self.local_recorder is not None:
            label = f"当前设备：{name}（录制中）"
        elif name in self._pc_devices:
            label = f"当前设备：{name}"
        elif name:
            label = f"手动指定：{name}（尚未验证）"
        elif self._pc_scan_state == "scanning":
            label = "当前设备：正在检测…"
        elif self._pc_scan_state == "error":
            label = "当前设备：检测失败，请检查工具设置并重试"
        elif self._pc_devices:
            label = "当前设备：未选择，请从列表选择"
        else:
            label = "当前设备：未检测到摄像头，请检查 USB 连接和驱动"
        self.pc_current_var.set(label)
        refresh_controls(self)

    def _apply_local_devices(self, names: list[str], error: str | None = None) -> None:
        self._pc_devices = names
        self.pc_device_box.configure(values=names)
        self._pc_scan_state = "error" if error else "ready"
        if self.local_recorder is None:
            selected = self.pc_device.get().strip()
            if selected not in names:
                self.pc_device.set(names[0] if len(names) == 1 else "")
        self.pc_scan_var.set("检测失败" if error else
                             (f"已找到 {len(names)} 台" if names else "未检测到"))
        self._update_pc_device_display()
        if error:
            self._log("电脑摄像头检测失败：" + error)
        else:
            self._log("电脑摄像头：" + ("；".join(names) if names else
                                   "未检测到；请检查 USB 连接、驱动，或刷新设备"))

    def _list_local_devices(self) -> None:
        if self.working:
            self._scan_after_id = self.after(300, self._list_local_devices)
            return
        self._pc_scan_state = "scanning"
        self.pc_scan_var.set("正在检测…")
        self._update_pc_device_display()
        try:
            ffmpeg = self._tool("ffmpeg", self.ffmpeg_var)
        except FileNotFoundError as exc:
            self._apply_local_devices([], str(exc))
            return

        def work() -> tuple[list[str], str | None]:
            try:
                return list_dshow_devices(ffmpeg), None
            except Exception as exc:
                return [], str(exc)

        self._run("正在查询电脑摄像头…", work,
                  lambda result: self._apply_local_devices(*result))

    def _planned_seconds(self) -> int | None:
        table = {"60 秒短检": 60, "10 分钟关口": 650, "手动停止": None}
        label = self.duration_var.get()
        if label not in table:
            raise ValueError("时长请选择短检、10 分钟关口或手动停止")
        return table[label]

    def _scene(self) -> dict[str, Any]:
        return {"operator": self.operator.get().strip(), "notes": self.notes.get().strip(),
                "lens": self.lens_var.get().strip(), "lighting": self.light_var.get().strip(),
                "distance": self.distance_var.get().strip(),
                "planned_seconds": self._planned_seconds()}

    def _pc_options(self) -> CaptureOptions:
        options = CaptureOptions(device=self.pc_device.get().strip(), width=int(self.pc_width.get()),
                                 height=int(self.pc_height.get()), fps=int(self.pc_fps.get()),
                                 codec=self.pc_codec.get(), **self._scene())
        options.validate("pc_usb")
        return options

    def _on_exposure_preset(self) -> None:
        if self._preset_guard:
            return
        name = PRESET_ALIASES.get(self.board_preset.get(), self.board_preset.get())
        if name != self.board_preset.get():
            self._preset_guard = True
            try:
                self.board_preset.set(name)
            finally:
                self._preset_guard = False
        if name == "自己设置":
            update_preset_hint(self)
            return
        if name not in EXPOSURE_PRESETS:
            return
        self._apply_exposure_preset(name)

    def _apply_exposure_preset(self, name: str, *, restart: bool = True, announce: bool = True) -> None:
        mode, absolute, note = EXPOSURE_PRESETS[name]
        self._preset_guard = True
        try:
            self.board_preset.set(name)
            self.board_exposure_mode.set(mode)
            self.board_exposure_absolute.set(absolute)
        finally:
            self._preset_guard = False
        update_board_exposure(self)
        update_preset_hint(self)
        recording = self.board_session_id is not None or (
            self.local_recorder is not None and self.local_recorder.status()["running"])
        if not announce:
            return
        if recording:
            self._log(note + " 这次已经在拍了，要等下次才换。")
            return
        self._log(note)
        if restart and getattr(self, "_live_stop_event", None) is not None:
            self._reopen_live_board()

    def _mark_custom_preset(self) -> None:
        if self._preset_guard:
            return
        current = EXPOSURE_PRESETS.get(self.board_preset.get())
        if current is None:
            return
        mode, absolute, _note = current
        if (self.board_exposure_mode.get() != mode or
                self.board_exposure_absolute.get() != absolute):
            self._preset_guard = True
            try:
                self.board_preset.set("自己设置")
            finally:
                self._preset_guard = False
            update_preset_hint(self)

    def _on_resolution_preset(self) -> None:
        if self._resolution_guard:
            return
        size = RESOLUTION_PRESETS.get(self.board_resolution.get())
        if size is None:
            return
        self._resolution_guard = True
        try:
            self.board_width.set(str(size[0]))
            self.board_height.set(str(size[1]))
        finally:
            self._resolution_guard = False

    def _mark_custom_resolution(self) -> None:
        if self._resolution_guard:
            return
        current = RESOLUTION_PRESETS.get(self.board_resolution.get())
        if current is None:
            return
        if (self.board_width.get() != str(current[0]) or
                self.board_height.get() != str(current[1])):
            self._resolution_guard = True
            try:
                self.board_resolution.set("自己填")
            finally:
                self._resolution_guard = False

    def _sync_resolution_preset(self) -> None:
        pair = (self.board_width.get(), self.board_height.get())
        for name, size in RESOLUTION_PRESETS.items():
            if pair == (str(size[0]), str(size[1])):
                self._resolution_guard = True
                try:
                    self.board_resolution.set(name)
                finally:
                    self._resolution_guard = False
                return

    def _on_lab_choice(self) -> None:
        if self._choice_guard:
            return
        path = path_from_choice(self.lab_camera_pick.get())
        if path and path != self.board_device.get().strip():
            self.board_device.set(path)

    def _sync_lab_pick(self) -> None:
        labels = [choice_label(item) for item in self._board_infos]
        self.lab_camera_box.configure(values=labels)
        selected = self.board_device.get().strip()
        label = next((choice_label(item) for item in self._board_infos
                      if item.get("device") == selected), "")
        if label != self.lab_camera_pick.get():
            self._choice_guard = True
            try:
                self.lab_camera_pick.set(label)
            finally:
                self._choice_guard = False

    def _preferred_serial(self) -> str:
        from .portable_connect import connection_settings
        return str(connection_settings().get("serial") or "")

    def _merged_board(self, board: dict[str, Any] | None = None) -> dict[str, Any]:
        facts = dict(board or self._board_facts)
        host = urlsplit(self.board_url.get().strip()).hostname or ""
        if host:
            facts["address"] = host
        return facts

    def _refresh_lab_identity(self) -> None:
        connected = self._board_connected
        self.lab_board_var.set(board_sentence(self._merged_board()) if connected
                               else "开发板未连接")
        selected = self.board_device.get().strip()
        info = next((item for item in self._board_infos if item.get("device") == selected), None)
        if info:
            self.lab_camera_var.set(camera_sentence(info))
        elif len(self._board_infos) > 1:
            self.lab_camera_var.set(f"{len(self._board_infos)} 只摄像头")
        elif connected:
            self.lab_camera_var.set("未发现摄像头")
        else:
            self.lab_camera_var.set("未发现摄像头")
        if self.board_session_id:
            self.lab_step_var.set("采集中")
        elif getattr(self, "_live_stop_event", None) is not None:
            self.lab_step_var.set("预览中")
        else:
            self.lab_step_var.set("")

    def _selected_camera_info(self) -> dict[str, Any] | None:
        selected = self.board_device.get().strip()
        return next((item for item in self._board_infos if item.get("device") == selected), None)

    def _note_board_cameras(self, infos: list[dict[str, Any]], board: dict[str, Any],
                            *, announce: bool = True) -> None:
        infos = [item for item in infos if isinstance(item, dict)]
        message = arrival_message(self._board_infos, infos, self._merged_board(board))
        self._board_infos = infos
        if board:
            self._board_facts = board
        if not self.board_session_id:
            chosen, note = choose_camera(infos, self.board_device.get().strip(),
                                         self._preferred_serial())
            known = {str(item.get("device") or "") for item in infos}
            if chosen and chosen != self.board_device.get().strip():
                self.board_device.set(chosen)
            elif not chosen and self.board_device.get().strip() not in known:
                self.board_device.set("")
            if note and announce and message:
                self._log(note)
        self._sync_lab_pick()
        self._refresh_lab_identity()
        if message and announce:
            self._log(message)
            self._maybe_auto_preview()

    def _maybe_auto_preview(self) -> None:
        if not self.lab_auto_preview.get() or self._preview_after_connect:
            return
        if self.working or self.board_session_id or not self.board_device.get().strip():
            return
        if getattr(self, "_live_stop_event", None) is not None:
            self._reopen_live_board()
            return
        self._live_board()

    def _tuning_kwargs(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        known = bool(self.lab_controls)
        for item in TUNING:
            if item.kind == "int":
                text = getattr(self, f"board_{item.name}").get()
            elif item.name == "white_balance_auto":
                text = self.board_wb.get()
            elif item.name == "focus_auto":
                text = self.board_focus.get()
            else:
                text = self.board_power_line.get()
            support = self.lab_support.get(item.name) if known else None
            if known and not support:
                values[item.name] = None
                continue
            low, high = item.low, item.high
            if isinstance(support, dict) and support.get("min") is not None and support.get("max") is not None:
                low, high = int(support["min"]), int(support["max"])
            values[item.name] = read_tuning(item.kind, text, item.label, low, high)
        if values.get("white_balance_auto") == 1:
            values["white_balance_temperature"] = None
        if values.get("focus_auto") == 1:
            values["focus_absolute"] = None
        return values

    def _apply_lab(self) -> None:
        try:
            self._board_options()
        except ValueError as exc:
            messagebox.showerror("参数", str(exc))
            return
        info = self._selected_camera_info() or {}
        warning = slow_usb_warning(str(info.get("speed") or ""),
                                   int(self.board_width.get() or 0),
                                   int(self.board_height.get() or 0))
        if warning:
            self._log(warning)
        if getattr(self, "_live_stop_event", None) is not None:
            self._reopen_live_board()
        else:
            self._live_board()

    def _read_lab_controls(self) -> None:
        client = self._safe_client()
        device = self.board_device.get().strip()
        if client is None or not device:
            self._log("先认出开发板上的摄像头，再读取它能调什么。")
            return

        def done(payload: dict[str, Any]) -> None:
            paint_lab_support(self, payload.get("controls") or [], str(payload.get("error") or ""))
            self._log(self.lab_support_var.get())

        self._run("正在读取这只摄像头能调的项目…",
                  lambda: client.request("GET", "/controls?device=" + quote(device)), done)

    def _fill_lab_controls(self) -> None:
        if not self.lab_controls:
            self._log("先点「读出这只能调什么」。")
            return
        filled = 0
        for item in TUNING:
            if item.kind != "int":
                continue
            support = self.lab_support.get(item.name) or {}
            variable = getattr(self, f"board_{item.name}")
            if variable.get().strip() or support.get("value") is None:
                continue
            variable.set(str(support["value"]))
            filled += 1
        self._log(f"已填入 {filled} 个当前数值。不需要的可以清空，留空就不会改。")

    def _clear_lab_tuning(self) -> None:
        for item in TUNING:
            if item.kind == "int":
                getattr(self, f"board_{item.name}").set("")
        self.board_power_line.set("不改")
        self.board_wb.set("不改")
        self.board_focus.set("不改")
        self._log("亮暗、颜色和对焦已留空，下次看画面时不再改这些项目。")

    def _lab_fluorescent(self) -> None:
        self.board_preset.set("看清画面")
        self.board_power_line.set("50 Hz")
        self.board_wb.set("自动")
        self._log("已按室内日光灯填写：自动曝光、自动白平衡、50 Hz。点「按这个参数看画面」。")

    def _lab_short(self) -> None:
        self.duration_var.set("60 秒短检")
        self.pc_tab.master.select(self.lab_tab)
        self._start_board()

    def _identify_now(self) -> None:
        self._next_connect = 0
        self._watch_once()

    def _quiet(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        def worker() -> None:
            try:
                result = work()
                self.results.put((done, result, None, True))
            except Exception as exc:
                self.results.put((done, None, str(exc), True))

        threading.Thread(target=worker, daemon=True).start()

    def _watch_tick(self) -> None:
        try:
            self._watch_once()
        finally:
            self._watch_after_id = self.after(5000, self._watch_tick)

    def _watch_once(self) -> None:
        if not self.lab_auto_watch.get() or self.working or self._watch_busy:
            return
        self._watch_busy = True
        generation = self._watch_generation

        def work() -> tuple[Any, ...]:
            pc: list[str] | None = None
            pc_error = None
            if self.local_recorder is None:
                try:
                    pc = list_dshow_devices(self._tool("ffmpeg", self.ffmpeg_var))
                except Exception as exc:
                    pc_error = str(exc)
            board = None
            board_error = None
            if self.board_url.get().strip() and self.board_token.get().strip() and self._board_connected:
                try:
                    board = self._client().request("GET", "/devices")
                except Exception as exc:
                    board_error = str(exc)
            return pc, pc_error, board, board_error

        def done(result: tuple[Any, ...]) -> None:
            self._watch_busy = False
            if generation != self._watch_generation:
                return
            pc, pc_error, board, board_error = result
            if pc is not None and pc != self._pc_devices:
                before = list(self._pc_devices)
                self._apply_local_devices(pc, pc_error)
                added = [name for name in pc if name not in before]
                if len(added) == 1 and not self.local_recorder:
                    self._log("电脑上认出摄像头：" + added[0] + "。要调亮度颜色，请改插到开发板。")
            if board_error:
                self._board_connected = False
                self.lab_watch_var.set("开发板连接中断，正在重试…")
                self._refresh_lab_identity()
                return
            if isinstance(board, dict):
                self.lab_watch_var.set("正在监视插拔")
                self._apply_board_devices(board.get("devices") or [], None,
                                          status_connected=True, announce=False)
                if "device_info" in board:
                    self._note_board_cameras(board.get("device_info") or [], board.get("board") or {})
            elif not self._board_connected:
                self._try_auto_connect()

        def failed(message: str) -> None:
            self._watch_busy = False
            self._log("自动识别：" + message)

        self._quiet(work, lambda result: done(result) if result is not None else failed("没有结果"))

    def _try_auto_connect(self) -> None:
        if self.working or self._board_connected or self.board_session_id:
            self._watch_busy = False
            return
        if time.monotonic() < self._next_connect:
            return
        self._next_connect = time.monotonic() + 20
        from .portable_connect import connection_settings
        settings = connection_settings()
        if not settings.get("key") or not Path(str(settings.get("key"))).is_file():
            self.lab_watch_var.set("缺少密钥")
            return
        self.lab_watch_var.set("正在连接 " + str(settings.get("host") or ""))
        self._auto_connect_board(quiet=True)

    def _reopen_live_board(self) -> None:
        client = getattr(self, "_live_client", None)
        self._stop_live_board(remote=False, quiet=True)
        if client is None:
            self._live_board()
            return

        def stopped(_result: Any) -> None:
            self._live_board()

        self._run("正在按这个拍法重新打开画面…",
                  lambda: client.request("POST", "/live/stop", {}, timeout=10), stopped)

    def _boot_preset(self, name: str) -> None:
        name = PRESET_ALIASES.get(name, name)
        if name not in EXPOSURE_PRESETS:
            self._log("没有这个拍法：" + name)
            return
        self.pc_tab.master.select(self.board_tab)
        self._apply_exposure_preset(name, restart=False)
        self._preview_after_connect = True
        self._auto_connect_board()

    def _board_options(self) -> CaptureOptions:
        source_format = self.board_format.get()
        labels = {"自动": 0, "手动": 1, "快门优先": 2}
        label = self.board_exposure_mode.get()
        if label not in labels:
            raise ValueError("曝光模式必须是自动、手动或快门优先")
        exposure_mode = labels[label]
        exposure_absolute = None
        if exposure_mode != 0:
            text = self.board_exposure_absolute.get().strip()
            if not text.isdigit():
                raise ValueError("手动或快门优先需要 1 到 10000 的绝对曝光")
            exposure_absolute = int(text)
        info = self._selected_camera_info() or {}
        options = CaptureOptions(device=self.board_device.get().strip(),
                                 width=int(self.board_width.get()), height=int(self.board_height.get()),
                                 fps=int(self.board_fps.get()), source_format=source_format,
                                 codec="copy" if source_format == "mjpeg" else "h264",
                                 bitrate_kbps=int(self.board_bitrate.get()),
                                 exposure_mode=exposure_mode, exposure_absolute=exposure_absolute,
                                 camera_serial=str(info.get("serial") or ""),
                                 usb_speed=str(info.get("speed") or ""),
                                 **self._tuning_kwargs(), **self._scene())
        options.validate("kv260_usb")
        return options

    def _arm_auto_stop(self, mode: str, session_id: str) -> None:
        seconds = self._planned_seconds()
        metrics = self.pc_metrics_var if mode == "pc" else self.board_metrics_var
        if seconds is None:
            self._auto_stop = None
            metrics.set("录制已启动，结束时点停止并校验")
            return
        self._auto_stop = {"mode": mode, "seconds": seconds, "started": time.monotonic(),
                           "session_id": session_id}
        metrics.set(f"限时采集还剩 {seconds} 秒，到时自动停止并校验")

    def _list_local_sessions(self) -> None:
        root = self._output_root()
        rows = []
        if root.is_dir():
            paths = sorted((path for path in root.iterdir() if path.is_dir()), reverse=True)
            for path in paths:
                if not SESSION_ID.fullmatch(path.name) or not (path / "session.json").is_file():
                    continue
                try:
                    item = load_json(path / "session.json")
                except (OSError, ValueError):
                    continue
                gates = item.get("gates") or {}
                if gates.get("dataset_ready"):
                    ready = "可入库"
                elif gates:
                    ready = "不可入库"
                else:
                    ready = "未校验"
                rows.append({"session_id": item.get("session_id", path.name),
                             "created_utc": item.get("created_utc", ""),
                             "status": item.get("status", ""), "ready": ready})
                if len(rows) >= 40:
                    break
        populate_sessions(self, rows)
        self._log(f"本机会话 {len(rows)} 个")

    def _show_png(self, body: bytes, mode: str) -> None:
        show_preview(self, body, mode)

    def _open_large_view(self) -> None:
        from .desktop_ui import open_large_preview
        open_large_preview(self)
        if getattr(self, "_live_stop_event", None) is None:
            self._live_board()

    def _live_board(self) -> None:
        if getattr(self, '_live_stop_event', None) is not None:
            self._stop_live_board()
            return
        client = self._safe_client()
        if client is None:
            return
        try:
            options = self._board_options()
        except ValueError as error:
            messagebox.showerror('预览设置', str(error))
            return
        def ready(_):
            stop = threading.Event()
            self._live_stop_event = stop
            self._live_frames = queue.Queue(maxsize=1)
            frames = self._live_frames
            self._live_client = client
            self._live_metrics_received = time.monotonic()
            from .frame_rates import FrameRates
            self._live_display_rates = FrameRates()
            self._live_last_body = None
            self.board_live_button.configure(text='停止预览')
            self._log('实时预览已开启；开始采集会自动停止预览')
            metrics = {}
            def measure():
                nonlocal metrics
                while not stop.is_set():
                    try:
                        value = client.request('GET', '/live/metrics', timeout=5)
                        value['_received_at'] = time.monotonic()
                        metrics = value
                    except RuntimeError:
                        pass
                    stop.wait(1)
            def worker():
                from .live_preview import read_png
                def publish(item):
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        pass
                    frames.put_nowait(item)
                request = Request(client.base_url + '/live/stream',
                                  headers={'Authorization': 'Bearer '+client.token})
                try:
                    with urlopen(request, timeout=10) as stream:
                        while not stop.is_set():
                            publish((read_png(stream), None, metrics))
                except Exception as error:
                    if not stop.is_set():
                        publish((None, str(error), {}))
                        stop.set()
            threading.Thread(target=measure, daemon=True).start()
            threading.Thread(target=worker, daemon=True).start()
        self._run('正在开启实时预览…', lambda: client.request('POST', '/live/start', options.__dict__), ready)

    def _stop_live_board(self, remote: bool = True, *, quiet: bool = False) -> None:
        stop = getattr(self, '_live_stop_event', None)
        if stop is not None:
            stop.set()
            self._live_stop_event = None
            self.board_live_button.configure(text='实时预览')
            if not quiet:
                self._log('实时预览已停止')
            self.board_live_metrics_var.set('实际取流帧率：— · 预览输出：—')
            if remote:
                client = self._live_client
                self._run('正在释放预览摄像头…', lambda: client.request('POST', '/live/stop', {}, timeout=10), lambda _: None)

    def _preview_local(self) -> None:
        if self.local_recorder is not None and self.local_recorder.status()["running"]:
            self._log("请先停止电脑录制，再占用摄像头预览")
            return
        try:
            options = self._pc_options()
            ffmpeg = self._tool("ffmpeg", self.ffmpeg_var)
            root = self._output_root()
            root.mkdir(parents=True, exist_ok=True)
        except (ValueError, OSError) as exc:
            messagebox.showerror("预览设置", str(exc))
            return

        def work() -> bytes:
            target = root / ".capture_preview.png"
            command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "dshow",
                       "-video_size", f"{options.width}x{options.height}", "-framerate", str(options.fps),
                       "-i", f"video={options.device}", "-vf", "scale=320:-2", "-frames:v", "1", str(target)]
            try:
                result = subprocess.run(command, capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", timeout=25)
                if result.returncode != 0 or not target.is_file():
                    raise RuntimeError("camera preview failed: " + result.stderr[-600:])
                return target.read_bytes()
            finally:
                target.unlink(missing_ok=True)

        self._run("正在获取电脑摄像头预览…", work,
                  lambda body: (self._show_png(body, "pc"), self._log("电脑画面已确认")))

    def _preview_board(self) -> None:
        self._stop_live_board(remote=False)
        client = self._safe_client()
        if client is None:
            return
        try:
            options = self._board_options()
        except ValueError as exc:
            messagebox.showerror("预览设置", str(exc))
            return
        self._run("正在获取开发板 摄像头预览…", lambda: client.snapshot(options),
                  lambda body: (self._show_png(body, "board"), self._log("板端画面已确认")))

    def _start_local(self) -> None:
        if self.local_recorder is not None:
            self._log("电脑采集已在运行")
            return
        try:
            options = self._pc_options()
            ffmpeg = self._tool("ffmpeg", self.ffmpeg_var)
            output_root = self._output_root()
            output_root.mkdir(parents=True, exist_ok=True)
            free_bytes = shutil.disk_usage(output_root).free
            if free_bytes < 100_000_000:
                raise ValueError("data disk has less than 100 MB free")
        except (ValueError, OSError) as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        def work() -> Path:
            preflight = preflight_dshow(ffmpeg, options)
            session = new_session(self._output_root(), "pc_usb", options)
            update_session(session, image_preflight=preflight, exposure_applied="not_applied")
            recorder = ProcessRecorder(session, local_ffmpeg_command(ffmpeg, options, session), "ffmpeg")
            recorder.start()
            self.local_recorder = recorder
            self._local_exit_reported = False
            return session

        def done(session: Path) -> None:
            self.current_session = session
            self.pc_session_var.set("会话 " + session.name)
            self._arm_auto_stop("pc", session.name)
            set_badge(self, "pc", "正在录制", live=True)
            self._log(f"电脑采集中：{session.name}")
            self._save_settings()

        self._run("正在启动电脑采集…", work, done)

    def _stop_local(self) -> None:
        self._auto_stop = None
        recorder = self.local_recorder
        if recorder is None:
            self._log("没有运行中的电脑采集")
            return

        def work() -> tuple[dict[str, Any], dict[str, Any] | None]:
            manifest = recorder.stop()
            audit = None
            if manifest["status"] == "recorded":
                try:
                    audit = audit_session(recorder.session, self._tool("ffprobe", self.ffprobe_var))
                except (RuntimeError, ValueError, FileNotFoundError) as exc:
                    audit = {"error": str(exc), "needs_review": True}
            return manifest, audit

        def done(value: tuple[dict[str, Any], dict[str, Any] | None]) -> None:
            self.local_recorder = None
            manifest, audit = value
            self._show_gates(recorder.session, "pc")
            self.pc_session_var.set("会话 " + manifest["session_id"])
            self._log(f"电脑采集结束：{manifest['status']}")
            if audit and "error" in audit:
                self._log("校验失败：" + audit["error"])

        self._run("正在停止并校验电脑采集…", work, done)

    def _board_connection_changed(self) -> None:
        self._watch_generation += 1
        self._board_connected = False
        self._board_devices = []
        self._board_infos = []
        self._board_facts = {}
        self._board_device_error = None
        self.board_device_box.configure(values=[])
        if not self.board_session_id:
            self.board_device.set("")
            set_badge(self, "board", "未连接")
        self.board_scan_var.set("待连接" if self.board_url.get().strip() and
                                self.board_token.get().strip() else "未连接")
        self._update_board_device_display()

    def _update_board_device_display(self) -> None:
        name = self.board_device.get().strip()
        if name and self.board_session_id:
            label = f"当前设备：{name}（录制中）"
        elif name in self._board_devices and self._board_connected:
            label = f"当前设备：{name}"
        elif name:
            label = f"手动指定：{name}（尚未验证）"
        elif self._board_device_error:
            label = "当前设备：查询失败，请检查板端服务后重试"
        elif not self._board_connected:
            label = "当前设备：未连接板端，请填写地址和令牌后连接"
        elif self._board_devices:
            label = "当前设备：未选择，请从列表选择"
        else:
            label = "当前设备：板端未检测到视频设备"
        info = self._selected_camera_info()
        if info and name and name in self._board_devices and self._board_connected:
            label = "当前设备：" + camera_sentence(info)
            if self.board_session_id:
                label += "（录制中）"
        self.board_current_var.set(label)
        self._sync_lab_pick()
        self._refresh_lab_identity()
        refresh_controls(self)

    def _apply_board_devices(self, devices: list[str], error: str | None = None,
                             *, status_connected: bool = False, announce: bool = True) -> None:
        self._board_connected = error is None or status_connected
        self._board_device_error = error
        self._board_devices = devices
        self.board_device_box.configure(values=devices)
        if not self.board_session_id:
            selected = self.board_device.get().strip()
            if selected not in devices:
                self.board_device.set(devices[0] if len(devices) == 1 else "")
        self.board_scan_var.set("查询失败" if error else
                                (f"已找到 {len(devices)} 台" if devices else "未检测到"))
        self._update_board_device_display()
        if not announce:
            return
        if error:
            if not self.board_session_id:
                set_badge(self, "board", "设备查询失败" if status_connected else "连接异常")
            self._log("开发板设备查询失败：" + error)
        else:
            self._log("开发板设备：" + ("、".join(devices) if devices else
                                      "未检测到；请检查摄像头 USB 连接"))

    def _configure_board(self) -> None:
        if self.working or self.board_session_id or getattr(self, '_live_stop_event', None) is not None:
            self._log('请先结束当前操作、预览或录制，再更改连接。')
            return
        from .portable_connect import configure
        configure(self, self._auto_connect_board)

    def _auto_connect_board(self, settings=None, *, quiet: bool = False) -> None:
        if self.working:
            return
        from .portable_connect import connection_settings
        settings = settings or connection_settings()
        if not settings.get('key') or not Path(settings['key']).is_file():
            if not quiet:
                self._configure_board()
            else:
                self.lab_watch_var.set("缺少密钥")
            return
        if not settings.get('host') and quiet:
            self.lab_watch_var.set("缺少地址")
            return
        import argparse
        import socket
        from .connect_kv260 import open_connection

        def work():
            if not settings.get('host'):
                from .board_discover import find_board
                host, note = find_board()
                if not host:
                    raise RuntimeError(note)
                settings['host'] = host
            # Use an unused local port, never adopt another application's tunnel.
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            args = argparse.Namespace(host=settings['host'], user=settings['user'],
                ssh_key=Path(settings['key']), board_root=settings['board_root'],
                camera_serial=settings.get('serial') or '', device=None, local_port=port,
                password=settings.get('password') or '')
            return open_connection(args)

        def done(connection):
            old_tunnel = self._ssh_tunnel
            self._ssh_tunnel = connection['tunnel']
            if old_tunnel is not None:
                old_tunnel.terminate()
            self.board_url.set(connection['url'])
            self.board_token.set(connection['token'])
            self.board_device.set(connection['device'])
            self.board_width.set('640')
            self.board_height.set('480')
            self.board_fps.set('30')
            self.board_format.set('mjpeg')
            if connection.get('sync_note'):
                self._log(connection['sync_note'])
            self._log('已通过SSH自动读取令牌并识别USB图像设备：' + connection['device'])
            if connection.get('selection_note'):
                self._log(connection['selection_note'])
            self._board_status()

        self._quiet_errors = quiet
        self._run('正在通过SSH连接开发板并识别摄像头…', work, done)

    def _connect_board(self) -> None:
        if self.board_url.get().strip() and self.board_token.get().strip():
            self._board_status()
        else:
            self._auto_connect_board()

    def _board_status(self) -> None:
        if self.working:
            self._log("另一项操作尚未完成")
            return
        try:
            client = self._client()
        except ValueError as exc:
            self.board_scan_var.set("请填写地址和令牌")
            self._log("开发板连接设置：" + str(exc))
            return
        self.board_scan_var.set("连接中…")

        def work() -> tuple[Any, ...]:
            try:
                status = client.request("GET", "/status")
            except Exception as exc:
                return None, [], str(exc), [], {}, False
            try:
                payload = client.request("GET", "/devices")
                return (status, payload.get("devices") or [], None,
                        payload.get("device_info") or [], payload.get("board") or {},
                        "device_info" in payload)
            except Exception as exc:
                return status, [], str(exc), [], {}, False

        def done(result: tuple[Any, ...]) -> None:
            value, devices, error, infos, board, has_info = result
            if value is None:
                self._apply_board_devices([], error or "无法读取板端状态")
                return
            session = value.get("session") or {}
            if value.get("recording"):
                self.board_session_id = session.get("session_id")
                if session.get("device"):
                    self.board_device.set(session["device"])
                self.remote_session.set(self.board_session_id or "")
                self.board_session_var.set("会话 " + (self.board_session_id or ""))
                self.board_metrics_var.set(
                    f"{session.get('elapsed_s', 0)} 秒 · "
                    f"{session.get('bytes', 0) / 1e6:.1f} MB 已写入板端")
                set_badge(self, "board", "正在录制", live=True)
            else:
                self.board_session_id = None
                self.board_session_var.set("板端尚无活动会话")
                self.board_metrics_var.set("可预览或开始新会话")
                set_badge(self, "board", "已连接")
            self._apply_board_devices(devices, error, status_connected=True)
            if error is None and has_info:
                self._note_board_cameras(infos, board)
            self._log("开发板状态：" + json.dumps(value, ensure_ascii=False))
            if self._preview_after_connect and not value.get("recording"):
                self._preview_after_connect = False
                self.after(400, self._live_board)
            elif self._preview_after_connect:
                self._preview_after_connect = False

        self._run("正在读取开发板 状态和摄像头…", work, done)

    def _list_board_devices(self) -> None:
        if self.working:
            self._log("另一项操作尚未完成")
            return
        try:
            client = self._client()
        except ValueError as exc:
            self.board_scan_var.set("请填写地址和令牌")
            self._log("开发板连接设置：" + str(exc))
            return
        self.board_scan_var.set("正在检测…")

        def work() -> tuple[dict[str, Any], str | None]:
            try:
                return client.request("GET", "/devices"), None
            except Exception as exc:
                return {}, str(exc)

        def done(result: tuple[dict[str, Any], str | None]) -> None:
            payload, error = result
            self._apply_board_devices(payload.get("devices") or [], error,
                                      status_connected=error is None and bool(payload))
            if error is None and "device_info" in payload:
                self._note_board_cameras(payload.get("device_info") or [], payload.get("board") or {})

        self._run("正在列出开发板 摄像头…", work, done)

    def _start_board(self) -> None:
        self._stop_live_board(remote=False)
        try:
            options = self._board_options()
            client = self._client()
        except (ValueError, FileNotFoundError) as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        def done(value: dict[str, Any]) -> None:
            self.board_session_id = value["session_id"]
            self.remote_session.set(self.board_session_id)
            self.board_session_var.set("会话 " + self.board_session_id)
            self._arm_auto_stop("board", self.board_session_id)
            set_badge(self, "board", "正在录制", live=True)
            self._log(f"开发板采集中：{self.board_session_id}")
            self._save_settings()

        if has_image_tuning(options):
            self._log("这次改了亮度、颜色或对焦，使用通用采集。专用快路径只保留给没改这些项的已核对摄像头。")
        warning = slow_usb_warning(options.usb_speed, options.width, options.height)
        if warning:
            self._log(warning)
        self._run("正在确认画面并启动 开发板采集…",
                  lambda: client.request("POST", "/start", options.__dict__, timeout=60), done)

    def _stop_board(self) -> None:
        self._auto_stop = None
        client = self._safe_client()
        if client is None:
            return
        root = self._output_root()

        def work() -> tuple[dict[str, Any], Path]:
            # Closing media segments and hashing a long recording can take minutes.
            manifest = client.request("POST", "/stop", {}, timeout=3600)
            if manifest.get("status") != "recorded":
                text = format_gates(manifest["gates"]) if manifest.get("gates") else "录制失败"
                raise RuntimeError(text)
            session = client.download_session(manifest["session_id"], root)
            return manifest, session

        def done(value: tuple[dict[str, Any], Path]) -> None:
            manifest, session = value
            self.board_session_id = None
            self.current_session = session
            self.remote_session.set(manifest["session_id"])
            self.board_session_var.set("会话 " + manifest["session_id"])
            self.board_metrics_var.set("已取回电脑，正在校验四关")
            set_badge(self, "board", "已取回")
            self._log(f"开发板已停止并取回：{session}")
            self._audit_path(session)

        self._run("正在停止开发板 并取回文件…", work, done)

    def _list_board_sessions(self) -> None:
        client = self._safe_client()
        if client is None:
            return
        def done(value: dict[str, Any]) -> None:
            populate_sessions(self, value["sessions"])
            self._log(f"已找到 {len(value['sessions'])} 个板端会话")

        self._run("正在列出板端会话…", lambda: client.request("GET", "/sessions"), done)

    def _fetch_board(self) -> None:
        client = self._safe_client()
        if client is None:
            return
        session_id = self.remote_session.get().strip()
        self._run("正在取回开发板 会话…", lambda: client.download_session(session_id, self._output_root()),
                  lambda path: (self._log(f"已取回：{path}"), self._audit_path(path)))

    def _audit_chosen(self) -> None:
        chosen = filedialog.askdirectory(title="选择包含 session.json 的会话目录")
        if chosen:
            self._audit_path(Path(chosen))

    def _audit_path(self, path: Path) -> None:
        try:
            probe = self._tool("ffprobe", self.ffprobe_var)
        except FileNotFoundError as exc:
            self._log(f"文件已保存，但尚未校验：{exc}")
            return
        def done(_value: dict[str, Any]) -> None:
            mode = "board" if load_json(path / "session.json").get("mode") == "kv260_usb" else "pc"
            self._show_gates(path, mode)

        self._run("正在校验四关…", lambda: audit_session(path, probe), done)

    def _show_gates(self, path: Path, mode: str) -> None:
        gates = load_json(path / "session.json").get("gates")
        paint_gates(self, gates)
        if not gates:
            set_badge(self, mode, "需要检查")
            return
        metrics = self.pc_metrics_var if mode == "pc" else self.board_metrics_var
        metrics.set(format_gates(gates))
        set_badge(self, mode, "可入库" if gates.get("dataset_ready") else "不可入库",
                  live=bool(gates.get("dataset_ready")))
        self._log(format_gates(gates))
        for line in gate_lines(gates):
            self._log(line)
        self.pc_tab.master.select(self.review_tab)
        self._list_local_sessions()

    def _poll(self) -> None:
        if getattr(self, '_live_stop_event', None) is not None and time.monotonic()-getattr(self, '_live_metrics_received', 0) > 3:
            self.board_live_metrics_var.set('实际取流帧率：数据已过期')
        frames = getattr(self, '_live_frames', None)
        if frames is not None:
            try:
                body, error, metrics = frames.get_nowait()
                if error:
                    self._stop_live_board()
                    self._log('实时预览中断：'+error)
                elif getattr(self, '_live_stop_event', None) is not None:
                    if body != getattr(self, '_live_last_body', None):
                        self._show_png(body, 'board')
                        self._live_last_body = body
                        self._live_display_rates.tick(source=False)
                    set_badge(self, 'board', '实时预览 · 最多30帧/秒', live=True)
                    source = metrics.get('source_fps')
                    preview = metrics.get('preview_fps')
                    self._live_metrics_received = metrics.get('_received_at', 0)
                    if time.monotonic()-self._live_metrics_received > 3:
                        source = preview = None
                    if source is None or preview is None:
                        self.board_live_metrics_var.set('实际取流帧率：等待稳定…' if metrics.get('warming_up') else '实际取流帧率：暂无数据')
                    else:
                        displayed = self._live_display_rates.status()['preview_fps']
                        display_text = f'{displayed:.1f}' if displayed is not None else '等待稳定'
                        self.board_live_metrics_var.set(f'取流：{source:.1f} · 输出：{preview:.1f} · 界面刷新：{display_text} fps')
            except queue.Empty:
                pass
        while True:
            try:
                item = self.results.get_nowait()
            except queue.Empty:
                break
            if len(item) == 4:
                done, result, error, quiet = item
                if not quiet:
                    self._complete(done, result, error)
                elif error:
                    self._watch_busy = False
                    self._log("自动识别：" + error)
                else:
                    done(result)
            else:
                done, result, error = item
                self._complete(done, result, error)
        if self.local_recorder is not None:
            state = self.local_recorder.status()
            if state["running"]:
                self.pc_metrics_var.set(
                    f"{state['elapsed_s']} 秒 · {state['bytes'] / 1e6:.1f} MB 已写入")
                if not self.working:
                    self.status_var.set(f"电脑采集中 · {state['elapsed_s']} 秒 · {state['bytes'] / 1e6:.1f} MB")
            elif not self.working and not self._local_exit_reported:
                self._local_exit_reported = True
                self._log("电脑录制进程已退出；请点“停止并校验”查看结果")
        plan = self._auto_stop
        if plan and not self.working:
            remain = plan["seconds"] - (time.monotonic() - plan["started"])
            metrics = self.pc_metrics_var if plan["mode"] == "pc" else self.board_metrics_var
            if remain > 0:
                written = ""
                if plan["mode"] == "pc" and self.local_recorder is not None:
                    written = f" · {self.local_recorder.status()['bytes'] / 1e6:.1f} MB"
                metrics.set(f"限时采集还剩 {remain:.0f} 秒{written}，到时自动停止并校验")
            else:
                self._auto_stop = None
                if plan["mode"] == "board":
                    self._stop_board()
                else:
                    self._stop_local()
        self._poll_after_id = self.after(8 if getattr(self, '_live_stop_event', None) is not None else 200, self._poll)

    def _load_settings(self) -> None:
        if not self.settings_path.is_file():
            return
        try:
            settings = load_json(self.settings_path)
            mapping = {"output": self.output_var, "ffmpeg": self.ffmpeg_var,
                       "ffprobe": self.ffprobe_var, "board_url": self.board_url,
                       "pc_width": self.pc_width, "pc_height": self.pc_height,
                       "pc_fps": self.pc_fps, "pc_codec": self.pc_codec,
                       "board_width": self.board_width, "board_height": self.board_height,
                       "board_fps": self.board_fps, "board_format": self.board_format,
                       "board_bitrate": self.board_bitrate,
                       "board_exposure_mode": self.board_exposure_mode,
                       "board_exposure_absolute": self.board_exposure_absolute,
                       "board_preset": self.board_preset,
                       "board_resolution": self.board_resolution,
                       "board_power_line": self.board_power_line,
                       "board_wb": self.board_wb, "board_focus": self.board_focus,
                       "board_gain": self.board_gain, "board_brightness": self.board_brightness,
                       "board_contrast": self.board_contrast, "board_saturation": self.board_saturation,
                       "board_sharpness": self.board_sharpness, "board_gamma": self.board_gamma,
                       "board_white_balance_temperature": self.board_white_balance_temperature,
                       "board_backlight_compensation": self.board_backlight_compensation,
                       "board_focus_absolute": self.board_focus_absolute,
                       "operator": self.operator, "notes": self.notes,
                       "duration": self.duration_var, "lens": self.lens_var,
                       "lighting": self.light_var, "distance": self.distance_var}
            for key, variable in mapping.items():
                if isinstance(settings.get(key), str):
                    variable.set(settings[key])
            from .desktop_ui import update_board_exposure, update_duration, update_preset_hint
            update_board_exposure(self)
            update_duration(self)
            update_preset_hint(self)
            if settings.get("lab_auto_watch") in ("0", "1"):
                self.lab_auto_watch.set(settings["lab_auto_watch"] == "1")
            if settings.get("lab_auto_preview") in ("0", "1"):
                self.lab_auto_preview.set(settings["lab_auto_preview"] == "1")
            if (self.board_exposure_mode.get() == "快门优先" and
                    not self.board_exposure_absolute.get().strip()):
                self._apply_exposure_preset("看清画面", restart=False, announce=False)
            for variable in (self.ffmpeg_var, self.ffprobe_var):
                configured = variable.get()
                if configured and not (self.root_dir / configured).is_file() and not Path(configured).is_file():
                    variable.set("")
        except (OSError, ValueError):
            self._log("设置文件无法读取，已使用默认值")

    def _save_settings(self) -> None:
        settings = {"output": self.output_var.get(), "ffmpeg": self.ffmpeg_var.get(),
                    "ffprobe": self.ffprobe_var.get(), "board_url": self.board_url.get(),
                    "pc_width": self.pc_width.get(), "pc_height": self.pc_height.get(),
                    "pc_fps": self.pc_fps.get(), "pc_codec": self.pc_codec.get(),
                    "board_width": self.board_width.get(), "board_height": self.board_height.get(),
                    "board_fps": self.board_fps.get(), "board_format": self.board_format.get(),
                    "board_bitrate": self.board_bitrate.get(),
                    "board_exposure_mode": self.board_exposure_mode.get(),
                    "board_exposure_absolute": self.board_exposure_absolute.get(),
                    "board_preset": self.board_preset.get(),
                    "board_resolution": self.board_resolution.get(),
                    "board_power_line": self.board_power_line.get(),
                    "board_wb": self.board_wb.get(), "board_focus": self.board_focus.get(),
                    "board_gain": self.board_gain.get(), "board_brightness": self.board_brightness.get(),
                    "board_contrast": self.board_contrast.get(),
                    "board_saturation": self.board_saturation.get(),
                    "board_sharpness": self.board_sharpness.get(), "board_gamma": self.board_gamma.get(),
                    "board_white_balance_temperature": self.board_white_balance_temperature.get(),
                    "board_backlight_compensation": self.board_backlight_compensation.get(),
                    "board_focus_absolute": self.board_focus_absolute.get(),
                    "lab_auto_watch": "1" if self.lab_auto_watch.get() else "0",
                    "lab_auto_preview": "1" if self.lab_auto_preview.get() else "0",
                    "operator": self.operator.get(), "notes": self.notes.get(),
                    "duration": self.duration_var.get(), "lens": self.lens_var.get(),
                    "lighting": self.light_var.get(), "distance": self.distance_var.get()}
        for key in ('output', 'ffmpeg', 'ffprobe'):
            value = settings[key]
            if value:
                try:
                    settings[key] = Path(value).resolve().relative_to(self.root_dir.resolve()).as_posix()
                except ValueError:
                    pass
        try:
            self.settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
        except OSError as exc:
            self._log(f"设置未保存：{exc}")

    def _close(self) -> None:
        self._stop_live_board()
        if self.working:
            messagebox.showwarning("操作进行中", "请等待当前操作完成。")
            return
        if self.local_recorder is not None and self.local_recorder.status()["running"]:
            messagebox.showwarning("仍在采集", "请先停止电脑采集并等待校验完成。")
            return
        self._save_settings()
        self.destroy()

    def destroy(self) -> None:
        tunnel = getattr(self, '_ssh_tunnel', None)
        if tunnel is not None:
            tunnel.terminate()
            self._ssh_tunnel = None
        for callback in (getattr(self, "_poll_after_id", None),
                         getattr(self, "_scan_after_id", None),
                         getattr(self, "_watch_after_id", None)):
            if callback is not None:
                try:
                    self.after_cancel(callback)
                except tk.TclError:
                    pass
        super().destroy()


def main() -> None:
    if os.name != "nt":
        raise SystemExit("Desktop UI currently targets Windows; run board_agent on the board (Linux)")
    preset = sys.argv[2] if len(sys.argv) >= 3 and sys.argv[1] == "--preset" else None
    app = CaptureDesktop()
    if preset:
        app.after(500, lambda: app._boot_preset(preset))
    app.mainloop()


if __name__ == "__main__":
    main()
