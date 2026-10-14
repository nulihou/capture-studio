"""Shared capture contract, process supervision, and recorded-media audit."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
from typing import Any, Literal
from uuid import uuid4


SCHEMA = "capture_studio_session_v1"
SESSION_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class CaptureOptions:
    device: str
    width: int = 1920
    height: int = 1080
    fps: int = 30
    segment_seconds: int = 300
    source_format: Literal["auto", "mjpeg", "raw"] = "auto"
    codec: Literal["ffv1", "copy", "mjpeg", "h264"] = "ffv1"
    bitrate_kbps: int = 20000
    operator: str = ""
    notes: str = ""
    lens: str = ""
    lighting: str = ""
    distance: str = ""
    planned_seconds: int | None = None
    exposure_mode: int | None = None
    exposure_absolute: int | None = None
    gain: int | None = None
    brightness: int | None = None
    contrast: int | None = None
    saturation: int | None = None
    sharpness: int | None = None
    gamma: int | None = None
    white_balance_auto: int | None = None
    white_balance_temperature: int | None = None
    power_line_frequency: int | None = None
    backlight_compensation: int | None = None
    focus_auto: int | None = None
    focus_absolute: int | None = None
    camera_serial: str = ""
    usb_speed: str = ""

    def validate(self, mode: Literal["pc_usb", "kv260_usb"]) -> None:
        if not self.device or "\x00" in self.device or len(self.device) > 512:
            raise ValueError("camera device/name is required")
        if not (1 <= self.width <= 8192 and 1 <= self.height <= 8192):
            raise ValueError("invalid capture resolution")
        if not (1 <= self.fps <= 240 and 10 <= self.segment_seconds <= 3600):
            raise ValueError("invalid FPS or segment duration")
        if not (1000 <= self.bitrate_kbps <= 100000):
            raise ValueError("bitrate_kbps must be between 1000 and 100000")
        if len(self.operator) > 200 or len(self.notes) > 2000:
            raise ValueError("operator or notes too long")
        if len(self.lens) > 200 or len(self.lighting) > 200 or len(self.distance) > 200:
            raise ValueError("镜头、光照或距离备注过长")
        if self.planned_seconds is not None and not 10 <= self.planned_seconds <= 7200:
            raise ValueError("采集时长需在 10 到 7200 秒之间")
        if self.exposure_mode not in (None, 0, 1, 2):
            raise ValueError("曝光模式只能是自动、手动或快门优先")
        if self.exposure_mode in (None, 0):
            if self.exposure_absolute is not None:
                raise ValueError("自动曝光不能同时填写绝对曝光")
        elif not isinstance(self.exposure_absolute, int) or not 1 <= self.exposure_absolute <= 10000:
            raise ValueError("手动或快门优先需要 1 到 10000 的绝对曝光")
        from .camera_lab import validate_tuning
        validate_tuning(self)
        if mode == "pc_usb":
            if self.codec not in ("ffv1", "copy", "mjpeg"):
                raise ValueError("PC codec must be ffv1, copy, or mjpeg")
        elif mode == "kv260_usb":
            if self.source_format not in ("mjpeg", "raw"):
                raise ValueError("开发板采集格式需是 mjpeg 或 raw")
            if self.codec != ("copy" if self.source_format == "mjpeg" else "h264"):
                raise ValueError("MJPEG 需原样封装；raw 需 H.264")
            if not re.fullmatch(r"/dev/video[0-9]+", self.device):
                raise ValueError("开发板摄像头需是 /dev/videoN")
        else:
            raise ValueError("unknown capture mode")


def new_session(root: Path, mode: Literal["pc_usb", "kv260_usb"], options: CaptureOptions) -> Path:
    options.validate(mode)
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:8]
    session = root / session_id
    (session / "segments").mkdir(parents=True, exist_ok=False)
    atomic_json(session / "session.json", {
        "schema": SCHEMA,
        "session_id": session_id,
        "mode": mode,
        "status": "starting",
        "created_utc": utc_now(),
        "options": asdict(options),
        "timestamp_contract": "Recorded container PTS are audited after capture; sensor exposure time is not claimed.",
        "files": [],
    })
    return session


def update_session(session: Path, **fields: Any) -> dict[str, Any]:
    manifest = load_json(session / "session.json")
    manifest.update(fields)
    atomic_json(session / "session.json", manifest)
    return manifest


def local_ffmpeg_command(ffmpeg: Path, options: CaptureOptions, session: Path) -> list[str]:
    options.validate("pc_usb")
    argv = [str(ffmpeg), "-hide_banner", "-loglevel", "info", "-y",
            "-f", "dshow", "-video_size", f"{options.width}x{options.height}",
            "-framerate", str(options.fps), "-i", f"video={options.device}",
            "-map", "0:v:0", "-an", "-fps_mode", "passthrough"]
    if options.codec == "ffv1":
        argv += ["-c:v", "ffv1", "-level", "3", "-g", "1"]
    elif options.codec == "mjpeg":
        argv += ["-c:v", "mjpeg", "-q:v", "2"]
    else:
        argv += ["-c:v", "copy"]
    argv += ["-f", "segment", "-segment_time", str(options.segment_seconds),
             "-reset_timestamps", "0", "-segment_format", "matroska",
             str(session / "segments" / "part_%05d.mkv")]
    return argv


def board_gst_command(options: CaptureOptions, session: Path) -> list[str]:
    options.validate("kv260_usb")
    from .camera_lab import extra_controls_token
    argv = ["gst-launch-1.0", "-e", "v4l2src", f"device={options.device}"]
    controls = extra_controls_token(options)
    if controls:
        argv.append(controls)
    argv += ["io-mode=mmap",
             "do-timestamp=false" if options.source_format == "mjpeg" else "do-timestamp=true", "!",
             (f"image/jpeg,width={options.width},height={options.height},framerate={options.fps}/1"
              if options.source_format == "mjpeg" else
              f"video/x-raw,width={options.width},height={options.height},framerate={options.fps}/1"), "!"]
    # V4L2 MJPEG delivers one complete JPEG per buffer. Feeding these through
    # jpegparse can synthesize a requested-FPS PTS on the board's GStreamer,
    # while leaving actual acquisition time in DTS. splitmuxsink then splits
    # by that synthetic clock. Mux the framed camera buffers directly instead.
    if options.source_format == "mjpeg":
        # Preserve native V4L2 PTS: generated arrival DTS otherwise overrides
        # it in matroskamux after a writer stall. A bounded nonleaky queue
        # separates acquisition from writing without silently dropping frames.
        argv += ["queue", "max-size-buffers=256", "max-size-bytes=33554432",
                 "max-size-time=0", "leaky=no", "!"]
    else:
        argv += ["videoconvert", "!", "video/x-raw,format=NV12", "!",
                 "omxh264enc", f"target-bitrate={options.bitrate_kbps}", "!", "h264parse", "!"]
    argv += ["splitmuxsink", f"location={session / 'segments' / 'part_%05d.mkv'}",
             f"max-size-time={options.segment_seconds * 1_000_000_000}",
             "muxer-factory=matroskamux"]
    if options.source_format == "mjpeg":
        # Finalize old segments asynchronously; keep microsecond precision.
        argv += ["async-finalize=true", "muxer-properties=properties,timecodescale=(gint64)1000"]
    return argv


class ProcessRecorder:
    """One camera process; file writing never depends on GUI/network polling."""

    def __init__(self, session: Path, argv: list[str], kind: Literal["ffmpeg", "gst"]) -> None:
        self.session = session
        self.argv = argv
        self.kind = kind
        self.process: subprocess.Popen[str] | None = None
        self.started_monotonic: float | None = None
        self._log_thread: threading.Thread | None = None

    def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("recorder already started")
        log_path = self.session / "capture.log"
        log_handle = log_path.open("w", encoding="utf-8", errors="replace")
        try:
            self.process = subprocess.Popen(
                self.argv, stdin=subprocess.PIPE if self.kind == "ffmpeg" else subprocess.DEVNULL,
                stdout=log_handle, stderr=subprocess.STDOUT, text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except Exception:
            log_handle.close()
            update_session(self.session, status="failed", error="capture process could not start")
            raise
        self.started_monotonic = time.monotonic()
        update_session(self.session, status="recording", started_utc=utc_now(), command=self.argv)

        def close_log() -> None:
            assert self.process is not None
            self.process.wait()
            log_handle.close()

        self._log_thread = threading.Thread(target=close_log, daemon=True)
        self._log_thread.start()

    def status(self) -> dict[str, Any]:
        if self.process is None:
            return {"running": False, "exit_code": None, "elapsed_s": 0, "bytes": 0}
        code = self.process.poll()
        size = sum(p.stat().st_size for p in (self.session / "segments").glob("*.mkv"))
        return {"running": code is None, "exit_code": code,
                "elapsed_s": round(time.monotonic() - (self.started_monotonic or time.monotonic()), 1),
                "bytes": size, "session_id": self.session.name}

    def stop(self) -> dict[str, Any]:
        if self.process is None:
            raise RuntimeError("recorder was never started")
        process = self.process
        if process.poll() is None:
            if self.kind == "ffmpeg" and process.stdin is not None:
                try:
                    process.stdin.write("q\n")
                    process.stdin.flush()
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            elif os.name != "nt":
                process.send_signal(signal.SIGINT)
            else:
                process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if self._log_thread is not None:
            self._log_thread.join(timeout=5)
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        files = []
        for path in sorted((self.session / "segments").glob("*.mkv")):
            files.append({"path": path.relative_to(self.session).as_posix(),
                          "size": path.stat().st_size, "sha256": sha256(path)})
        valid = process.returncode == 0 and bool(files) and all(item["size"] > 0 for item in files)
        native_summary = None
        native_path = self.session / 'native_capture.json'
        if native_path.exists():
            native = load_json(native_path)
            native_summary = {key: native[key] for key in (
                'status', 'buffers', 'whole_window_hz', 'invalid_kernel_timestamps',
                'duplicate_timestamps', 'backward_timestamps', 'restoration')}
            valid = valid and native['status'] == 'complete' and native['restoration']['verified']
        extra: dict[str, Any] = {}
        if not valid:
            from .gates import _result, incomplete_gates
            if native_summary is not None and not native_summary["restoration"]["verified"]:
                closeout = _result("fail", "相机控制未恢复")
            else:
                closeout = _result("fail", "录制进程未正常结束或没有视频")
            extra["gates"] = incomplete_gates(closeout)
        return update_session(self.session, status="recorded" if valid else "failed",
                              stopped_utc=utc_now(), exit_code=process.returncode, files=files,
                              native_capture=native_summary,
                              error=None if valid else "capture exited unsuccessfully or produced no media",
                              **extra)


def audit_session(session: Path, ffprobe: Path) -> dict[str, Any]:
    """Write recorded-container frame inventory; no sensor-frame claim."""
    manifest = load_json(session / "session.json")
    paths = []
    for item in manifest.get("files", []):
        relative = item["path"]
        if not re.fullmatch(r"segments/part_[0-9]{5}\.mkv", relative):
            raise ValueError("session manifest contains an unsafe media path")
        paths.append(session / relative)
    if not paths or any(not p.is_file() for p in paths):
        raise ValueError("session media is incomplete")
    for item, path in zip(manifest["files"], paths):
        if path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
            raise ValueError(f"session media checksum mismatch: {path.name}")
    frame_count = missing_pts = nonmonotonic = possible_gaps = 0
    stream_mismatches: list[str] = []
    streams: list[dict[str, Any]] = []
    fps = int(manifest["options"]["fps"])
    output = session / "frames.jsonl"
    with output.open("w", encoding="utf-8") as handle:
        for path in paths:
            last_pts: float | None = None
            stream_result = subprocess.run(
                [str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=codec_name,width,height,avg_frame_rate", "-of", "json", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            if stream_result.returncode != 0:
                output.unlink(missing_ok=True)
                raise RuntimeError(f"ffprobe stream inspection failed on {path.name}")
            stream_items = json.loads(stream_result.stdout).get("streams", [])
            if not stream_items:
                output.unlink(missing_ok=True)
                raise ValueError(f"video stream missing in {path.name}")
            stream = {"segment": path.relative_to(session).as_posix(), **stream_items[0]}
            streams.append(stream)
            if (stream.get("width"), stream.get("height")) != (
                manifest["options"]["width"], manifest["options"]["height"]
            ):
                stream_mismatches.append(path.name)
            completed = subprocess.run(
                [str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
            )
            if completed.returncode != 0:
                output.unlink(missing_ok=True)
                raise RuntimeError(f"ffprobe failed on {path.name}: {completed.stderr[-600:]}")
            for line in completed.stdout.splitlines():
                value = line.strip().rstrip(",")
                if not value:
                    continue
                try:
                    pts = float(value)
                except ValueError:
                    pts = None
                if pts is None:
                    missing_pts += 1
                elif last_pts is not None:
                    delta = pts - last_pts
                    if delta <= 0:
                        nonmonotonic += 1
                    elif delta > 1.5 / fps:
                        possible_gaps += 1
                frame_count += 1
                handle.write(json.dumps({"recorded_frame_id": frame_count - 1,
                                         "segment": path.relative_to(session).as_posix(),
                                         "container_pts_s": pts,
                                         "timestamp_source": "recorded_container_pts"}) + "\n")
                if pts is not None:
                    last_pts = pts
    audit = {"frame_count": frame_count, "missing_pts": missing_pts,
             "nonmonotonic_pts": nonmonotonic, "possible_gap_intervals": possible_gaps,
             "stream_mismatch_segments": stream_mismatches, "streams": streams,
             "interpretation": "Gap count is a container-PTS heuristic, not a sensor drop count."}
    from .gates import evaluate_gates
    gates = evaluate_gates(session, audit, ffprobe)
    update_session(session, audit=audit, gates=gates,
                   status="audited" if frame_count and not missing_pts and not nonmonotonic
                   and not possible_gaps and not stream_mismatches else "needs_review")
    return audit


def resolve_tool(name: str, configured: str, app_root: Path) -> Path:
    candidate = Path(configured)
    if configured:
        if not candidate.is_absolute():
            candidate = app_root / candidate
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(f"{name} not found: {candidate}")
    bundled = app_root / "bin" / (name + (".exe" if os.name == "nt" else ""))
    if bundled.is_file():
        return bundled.resolve()
    found = shutil.which(name)
    if found:
        return Path(found).resolve()
    raise FileNotFoundError(f"{name} is missing; place it in bin/ or select its path")


def safe_session(root: Path, session_id: str) -> Path:
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError("invalid session ID")
    session = (root / session_id).resolve()
    if session.parent != root.resolve() or not session.is_dir():
        raise FileNotFoundError("session not found")
    return session
