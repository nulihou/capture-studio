"""KV260 USB camera recorder controlled by the desktop over a trusted LAN.

Run this service in the KV260 environment that provides gst-launch-1.0,
jpegparse, splitmuxsink, and (for raw input) omxh264enc.
"""

from __future__ import annotations

import argparse
from dataclasses import fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .core import (CaptureOptions, ProcessRecorder, board_gst_command, load_json,
                   new_session, safe_session, update_session)


class AgentState:
    def __init__(self, root: Path, token: str) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.token = token
        self.lock = threading.RLock()
        self.recorder: ProcessRecorder | None = None
        self.live = None

    def live_start(self, payload):
        from .live_preview import LivePreview
        options = CaptureOptions(**payload)
        options.validate('kv260_usb')
        if not Path(options.device).is_char_device():
            raise ValueError('camera device is unavailable')
        with self.lock:
            self._finish_exited()
            if self.recorder is not None:
                raise RuntimeError('请先停止录制，再开启实时预览')
            self.live_stop()
            self.live = LivePreview(options)
        return {'preview': True, 'max_display_fps': min(options.fps, 30)}

    def live_stop(self):
        with self.lock:
            if self.live is not None:
                self.live.stop()
                self.live = None
        return {'preview': False}

    def live_frame(self):
        with self.lock:
            if self.live is None:
                raise RuntimeError('preview is not running')
            return self.live.latest()

    def live_metrics(self):
        with self.lock:
            if self.live is None:
                return {'preview': False, 'source_fps': None, 'preview_fps': None}
            return {'preview': True, **self.live.telemetry()}

    def _finish_exited(self) -> None:
        if self.recorder is not None and not self.recorder.status()["running"]:
            self.recorder.stop()
            self.recorder = None

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {field.name for field in fields(CaptureOptions)}
        if set(payload) - allowed:
            raise ValueError("unknown capture option")
        options = CaptureOptions(**payload)
        options.validate("kv260_usb")
        if not Path(options.device).is_char_device():
            raise ValueError("camera device is unavailable")
        if shutil.which("gst-launch-1.0") is None:
            raise RuntimeError("gst-launch-1.0 is unavailable in the board environment")
        with self.lock:
            self._finish_exited()
            if self.recorder is not None:
                raise RuntimeError("another capture is recording")
            self.live_stop()
            from .gates import gray_from_png, judge_luminance, preflight_native, reject_if_dim
            from .native_source import effective_exposure, uses_native
            if uses_native(options):
                options = effective_exposure(options)
                preflight = preflight_native(options)
                exposure_applied = "native"
            else:
                preflight = reject_if_dim(options, judge_luminance(gray_from_png(self._grab_png(options))))
                exposure_applied = "not_applied"
            session = new_session(self.root, "kv260_usb", options)
            update_session(session, image_preflight=preflight, exposure_applied=exposure_applied,
                           camera=_camera_record(options.device))
            if exposure_applied == "native":
                command = [sys.executable, '-m', 'capture_studio.native_worker',
                           json.dumps(options.__dict__), str(session)]
            else:
                command = board_gst_command(options, session)
            recorder = ProcessRecorder(session, command, "gst")
            recorder.start()
            self.recorder = recorder
            return {"session_id": session.name, "status": recorder.status()}

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if self.recorder is None:
                raise RuntimeError("no active capture")
            result = self.recorder.stop()
            self.recorder = None
            return result

    def status(self) -> dict[str, Any]:
        with self.lock:
            self._finish_exited()
            if self.recorder is None:
                return {"recording": False, "session": None}
            current = self.recorder.status()
            current["device"] = load_json(self.recorder.session / "session.json")["options"]["device"]
            log = self.recorder.session / "capture.log"
            if log.exists():
                with log.open("rb") as handle:
                    handle.seek(max(0, log.stat().st_size - 1500))
                    current["log_tail"] = handle.read().decode("utf-8", errors="replace")
            return {"recording": True, "session": current}

    def _grab_png(self, options: CaptureOptions) -> bytes:
        # Caller holds the lock. A running preview is already the same exposure.
        if self.live is not None:
            return self.live.latest()
        from .live_preview import LivePreview
        preview = LivePreview(options)
        try:
            time.sleep(3)
            deadline = time.monotonic() + 7
            while True:
                try:
                    return preview.latest()
                except RuntimeError as error:
                    if str(error) != "preview warming up" or time.monotonic() >= deadline:
                        raise
                    time.sleep(.1)
        finally:
            preview.stop()

    def snapshot(self, payload: dict[str, Any]) -> bytes:
        allowed = {field.name for field in fields(CaptureOptions)}
        if set(payload) - allowed:
            raise ValueError("unknown capture option")
        options = CaptureOptions(**payload)
        options.validate("kv260_usb")
        if not Path(options.device).is_char_device():
            raise ValueError("camera device is unavailable")
        with self.lock:
            self._finish_exited()
            if self.recorder is not None:
                raise RuntimeError("stop recording before taking a preview frame")
            return self._grab_png(options)

    def sessions(self) -> list[dict[str, Any]]:
        with self.lock:
            self._finish_exited()
            result = []
            for path in sorted(self.root.iterdir(), reverse=True):
                if path.is_dir() and (path / "session.json").is_file():
                    item = load_json(path / "session.json")
                    gates = item.get("gates") or {}
                    result.append({"session_id": path.name, "status": item.get("status"),
                                   "created_utc": item.get("created_utc"),
                                   "files": len(item.get("files", [])),
                                   "dataset_ready": bool(gates.get("dataset_ready"))})
            return result


def _camera_record(device: str) -> dict[str, str]:
    from .board_devices import board_facts, usb_image_devices
    from .camera_lab import identity_record
    try:
        matched = next((item for item in usb_image_devices() if item.get("device") == device), None)
        return identity_record(board_facts(), matched, device)
    except OSError:
        return identity_record({}, None, device)


def make_handler(state: AgentState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "CaptureStudioBoard/0.1"

        def log_message(self, fmt: str, *args: object) -> None:
            # Access logs intentionally omit Authorization headers.
            super().log_message(fmt, *args)

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + state.token):
                self._json(401, {"error": "unauthorized"})
                return False
            return True

        def _json(self, code: int, value: Any) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _png(self, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _payload(self) -> dict[str, Any]:
            size = int(self.headers.get("Content-Length", "0"))
            if not (0 <= size <= 16384):
                raise ValueError("request body exceeds 16 KiB")
            value = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def do_GET(self) -> None:
            if not self._authorized():
                return
            try:
                path = urlsplit(self.path).path
                if path == "/status":
                    self._json(200, state.status())
                elif path == '/live/frame':
                    self._png(state.live_frame())
                elif path == '/live/stream':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/x-png-stream')
                    self.end_headers()
                    previous = None
                    while True:
                        try:
                            body = state.live_frame()
                        except RuntimeError:
                            if state.live is None:
                                break
                            time.sleep(.02)
                            continue
                        if body != previous:
                            try:
                                self.wfile.write(body)
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError):
                                break
                            previous = body
                        time.sleep(1/240)
                elif path == '/live/metrics':
                    self._json(200, state.live_metrics())
                elif path == "/devices":
                    from capture_studio.board_devices import board_facts, usb_image_devices
                    info = usb_image_devices()
                    self._json(200, {"devices": [item['device'] for item in info],
                                     "device_info": info, "board": board_facts()})
                elif path == "/formats":
                    from capture_studio.camera_lab import query_v4l2_formats
                    device = (parse_qs(urlsplit(self.path).query).get("device") or [""])[0]
                    self._json(200, query_v4l2_formats(device))
                elif path == "/controls":
                    from capture_studio.camera_lab import query_v4l2_controls
                    device = (parse_qs(urlsplit(self.path).query).get("device") or [""])[0]
                    self._json(200, query_v4l2_controls(device))
                elif path == "/sessions":
                    self._json(200, {"sessions": state.sessions()})
                elif path.startswith("/sessions/"):
                    rest = path[len("/sessions/"):]
                    session_id, sep, suffix = rest.partition("/")
                    session = safe_session(state.root, session_id)
                    manifest = load_json(session / "session.json")
                    if not sep:
                        self._json(200, manifest)
                    elif suffix.startswith("files/"):
                        relative = unquote(suffix[len("files/"):])
                        allowed = {item["path"] for item in manifest.get("files", [])}
                        allowed.update({"session.json", "capture.log", "frames.jsonl"})
                        if relative not in allowed:
                            raise FileNotFoundError("file is not part of session")
                        target = (session / relative).resolve()
                        if not target.is_relative_to(session) or not target.is_file():
                            raise FileNotFoundError("session file not found")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(target.stat().st_size))
                        self.end_headers()
                        with target.open("rb") as handle:
                            shutil.copyfileobj(handle, self.wfile, length=1024 * 1024)
                    else:
                        raise FileNotFoundError("unknown endpoint")
                else:
                    raise FileNotFoundError("unknown endpoint")
            except (ValueError, FileNotFoundError) as exc:
                self._json(404, {"error": str(exc)})
            except Exception as exc:
                self._json(500, {"error": str(exc)})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            try:
                path = urlsplit(self.path).path
                if path == "/start":
                    self._json(200, state.start(self._payload()))
                elif path == '/live/start':
                    self._json(200, state.live_start(self._payload()))
                elif path == '/live/stop':
                    self._json(200, state.live_stop())
                elif path == "/stop":
                    self._json(200, state.stop())
                elif path == "/snapshot":
                    self._png(state.snapshot(self._payload()))
                else:
                    raise FileNotFoundError("unknown endpoint")
            except (TypeError, ValueError, RuntimeError, FileNotFoundError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                self._json(500, {"error": str(exc)})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("captures"))
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--init-token", action="store_true", help="create a new private token file and exit")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.init_token:
        args.token_file.parent.mkdir(parents=True, exist_ok=True)
        with args.token_file.open("x", encoding="ascii") as handle:
            handle.write(secrets.token_urlsafe(32) + "\n")
        args.token_file.chmod(0o600)
        print(f"Token saved to {args.token_file}; copy its contents into the desktop app for this run.")
        return
    token = args.token_file.read_text(encoding="ascii").strip()
    if len(token) < 32:
        raise ValueError("token file must contain at least 32 characters")
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(AgentState(args.output_root, token)))
    print(f"Board agent listening on {args.bind}:{args.port}; output={args.output_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
