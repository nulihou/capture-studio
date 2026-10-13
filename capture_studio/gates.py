"""Four dataset gates. Container audit, frame rate, image, and closeout stay separate."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from .core import load_json

MIN_MEAN = 16.0
MAX_MEAN = 240.0
MIN_SPAN = 12.0
FRAME_RATE_FLOOR = 29.9
LONG_GATE_SECONDS = 600

NAMES = {"integrity": "完整性", "frame_rate": "帧率", "image": "画面", "closeout": "收尾"}
WORDS = {"pass": "通过", "fail": "未过", "pending": "未测"}
ORDER = ("integrity", "frame_rate", "image", "closeout")


def judge_luminance(gray: bytes) -> dict:
    """Judge one grayscale frame. Near-black, near-white, and flat frames fail."""
    if not gray:
        raise ValueError("样帧为空")
    histogram = [0] * 256
    total = 0
    for value in gray:
        histogram[value] += 1
        total += value
    count = len(gray)
    mean = total / count

    def percentile(fraction: float) -> int:
        target = max(1, fraction * count)
        seen = 0
        for value, bins in enumerate(histogram):
            seen += bins
            if seen >= target:
                return value
        return 255

    low = percentile(0.05)
    high = percentile(0.95)
    span = high - low
    if mean < MIN_MEAN:
        reason, passed = "画面过暗", False
    elif mean > MAX_MEAN:
        reason, passed = "画面过亮", False
    elif span < MIN_SPAN:
        reason, passed = "画面细节不足", False
    else:
        reason, passed = "画面可用", True
    return {"mean": round(mean, 2), "p5": low, "p95": high, "span": span,
            "passed": passed, "reason": reason}


def reject_if_dim(options, stats: dict) -> dict:
    if stats["passed"]:
        return stats
    if options.exposure_mode in (None, 0):
        policy = "自动曝光"
    else:
        policy = f"曝光模式 {options.exposure_mode}、绝对曝光 {options.exposure_absolute}"
    raise ValueError(
        f"画面未通过，已取消开始采集：{stats['reason']}（平均亮度 {stats['mean']:.1f}，"
        f"细节跨度 {stats['span']:.0f}）。当前为{policy}，预览和录制使用同一套曝光。")


def gray_from_png(data: bytes) -> bytes:
    """Decode an 8-bit non-interlaced PNG into luminance bytes."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("样帧不是 PNG")
    offset = 8
    width = height = color = None
    compressed = bytearray()
    while offset + 8 <= len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        start = offset + 8
        chunk = data[start:start + size]
        if len(chunk) != size or start + size + 4 > len(data):
            raise ValueError("PNG 分块不完整")
        expected = zlib.crc32(kind + chunk) & 0xFFFFFFFF
        actual = struct.unpack(">I", data[start + size:start + size + 4])[0]
        if expected != actual:
            raise ValueError("PNG 校验失败")
        if kind == b"IHDR":
            width, height, depth, color, _compression, _row_filter, interlace = struct.unpack(">IIBBBBB", chunk)
            if depth != 8 or color not in (0, 2, 6) or interlace:
                raise ValueError("只接受 8 位非隔行灰度或彩色 PNG")
        elif kind == b"IDAT":
            compressed.extend(chunk)
        elif kind == b"IEND":
            break
        offset = start + size + 4
    if not compressed or width is None:
        raise ValueError("PNG 缺少图像数据")
    channels = {0: 1, 2: 3, 6: 4}[color]
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    rows = []
    cursor = 0
    previous = bytearray(stride)
    for _ in range(height):
        if cursor >= len(raw):
            raise ValueError("PNG 行数据不足")
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor:cursor + stride])
        cursor += stride
        if len(row) != stride:
            raise ValueError("PNG 行长度不对")
        if filter_type == 1:
            for index in range(channels, stride):
                row[index] = (row[index] + row[index - channels]) & 255
        elif filter_type == 2:
            for index in range(stride):
                row[index] = (row[index] + previous[index]) & 255
        elif filter_type == 3:
            for index in range(stride):
                left = row[index - channels] if index >= channels else 0
                row[index] = (row[index] + ((left + previous[index]) // 2)) & 255
        elif filter_type == 4:
            for index in range(stride):
                left = row[index - channels] if index >= channels else 0
                up = previous[index]
                upper_left = previous[index - channels] if index >= channels else 0
                estimate = left + up - upper_left
                choices = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
                predictor = (left, up, upper_left)[choices.index(min(choices))]
                row[index] = (row[index] + predictor) & 255
        elif filter_type != 0:
            raise ValueError("PNG 使用了不支持的行过滤")
        rows.append(row)
        previous = row
    gray = bytearray()
    for row in rows:
        if channels == 1:
            gray.extend(row)
        else:
            for index in range(0, stride, channels):
                gray.append((row[index] * 299 + row[index + 1] * 587 + row[index + 2] * 114) // 1000)
    return bytes(gray)


def gray_from_encoded(path: Path) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        completed = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            capture_output=True, timeout=30)
        if completed.returncode == 0 and completed.stdout:
            return completed.stdout
    gst = shutil.which("gst-launch-1.0")
    if gst:
        raw = path.with_suffix(".gray")
        completed = subprocess.run(
            [gst, "-q", "filesrc", f"location={path}", "!", "jpegdec", "!", "videoconvert", "!",
             "video/x-raw,format=GRAY8", "!", "filesink", f"location={raw}"],
            capture_output=True, timeout=30)
        if completed.returncode == 0 and raw.is_file() and raw.stat().st_size:
            return raw.read_bytes()
    raise RuntimeError("无法解码样帧")


def preflight_native(options) -> dict:
    """Sample the recording binary with the same exposure, then restore the camera."""
    from .native_source import effective_exposure, native_argv
    options = effective_exposure(options)
    binary = Path(__file__).with_name("native_capture")
    if not binary.is_file():
        raise RuntimeError("板端尚未编译 native_capture，不能确认画面")
    with tempfile.TemporaryDirectory(prefix="capture_preflight_") as directory:
        root = Path(directory)
        report = root / "preflight.json"
        sample = root / "preflight.jpg"
        completed = subprocess.run(
            native_argv(binary, options, report, duration_sec=3, sample_jpeg=sample),
            capture_output=True, timeout=40)
        if not report.is_file():
            detail = completed.stderr.decode("utf-8", "replace")[-400:]
            raise RuntimeError(detail or "曝光预检没有写下报告")
        payload = json.loads(report.read_text(encoding="utf-8"))
        if not payload.get("restoration", {}).get("verified"):
            raise RuntimeError("曝光预检未能恢复相机控制，已取消开始采集")
        if completed.returncode != 0 or not sample.is_file() or sample.stat().st_size == 0:
            raise RuntimeError("曝光预检失败：" + str(payload.get("failure_stage") or "没有样帧"))
        stats = reject_if_dim(options, judge_luminance(gray_from_encoded(sample)))
        rate = payload.get("whole_window_hz")
        if isinstance(rate, (int, float)):
            stats["source_fps"] = round(float(rate), 3)
        guard_long_capture(options.planned_seconds, stats)
        return stats


def preflight_dshow(ffmpeg: Path, options) -> dict:
    completed = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "dshow",
         "-video_size", f"{options.width}x{options.height}", "-framerate", str(options.fps),
         "-i", f"video={options.device}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray",
         "pipe:1"],
        capture_output=True, timeout=20)
    expected = options.width * options.height
    if completed.returncode != 0 or len(completed.stdout) != expected:
        detail = completed.stderr.decode("utf-8", "replace")[-300:]
        raise RuntimeError("无法取得录制路径样帧" + (f"：{detail}" if detail else ""))
    return reject_if_dim(options, judge_luminance(completed.stdout))


def guard_long_capture(planned_seconds: int | None, stats: dict) -> None:
    """A short preflight cannot pass the 10-minute gate, but it can cancel a hopeless one."""
    if planned_seconds is None or planned_seconds < 600:
        return
    rate = stats.get("source_fps")
    if not isinstance(rate, (int, float)) or rate >= 28:
        return
    raise ValueError(
        f"预检取流 {float(rate):.1f} fps，低于长录所需。已取消 10 分钟采集，可先做 60 秒短检。")


def _result(status: str, detail: str) -> dict:
    return {"status": status, "detail": detail}


def combine_gates(integrity: dict, frame_rate: dict, image: dict, closeout: dict) -> dict:
    gates = {"integrity": integrity, "frame_rate": frame_rate, "image": image, "closeout": closeout}
    gates["dataset_ready"] = all(gates[key]["status"] == "pass" for key in ORDER)
    return gates


def incomplete_gates(closeout: dict) -> dict:
    pending = _result("pending", "录制未正常结束，此项未测")
    return combine_gates(pending, pending, pending, closeout)


def format_gates(gates: dict) -> str:
    parts = [f"{NAMES[key]}{WORDS[gates[key]['status']]}" for key in ORDER]
    parts.append("可入库" if gates.get("dataset_ready") else "不可入库")
    return " · ".join(parts)


def gate_lines(gates: dict) -> list[str]:
    return [f"{NAMES[key]}：{gates[key]['detail']}" for key in ORDER]


def _ffmpeg_beside(ffprobe: Path) -> Path | None:
    candidate = ffprobe.with_name("ffmpeg.exe" if ffprobe.suffix.lower() == ".exe" else "ffmpeg")
    if candidate.is_file():
        return candidate
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def _pts(session: Path) -> list[float]:
    values = []
    for line in (session / "frames.jsonl").read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        stamp = json.loads(line).get("container_pts_s")
        if stamp is None:
            raise ValueError("missing pts")
        values.append(float(stamp))
    return values


def _gray_frame(ffmpeg: Path, media: Path, width: int, height: int, seconds: float) -> bytes:
    completed = subprocess.run(
        [str(ffmpeg), "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(media),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True, timeout=60)
    if completed.returncode != 0 or len(completed.stdout) != width * height:
        raise RuntimeError("无法从录像抽出样帧")
    return completed.stdout


def _image_gate(session: Path, ffmpeg: Path | None) -> dict:
    manifest = load_json(session / "session.json")
    if ffmpeg is None:
        return _result("pending", "没有 FFmpeg，未从录像抽样")
    options = manifest["options"]
    width, height = int(options["width"]), int(options["height"])
    media = [session / item["path"] for item in manifest.get("files", [])]
    if not media:
        return _result("pending", "没有录像可抽样")
    if len(media) >= 3:
        chosen = [media[0], media[len(media) // 2], media[-1]]
    else:
        chosen = media
    samples = []
    for path in chosen:
        try:
            samples.append(judge_luminance(_gray_frame(ffmpeg, path, width, height, 0.2)))
        except (RuntimeError, ValueError):
            continue
    if not samples:
        return _result("pending", "录像样帧未能解码")
    failed = [item for item in samples if not item["passed"]]
    means = "、".join(f"{item['mean']:.1f}" for item in samples)
    if failed:
        return _result("fail", f"{failed[0]['reason']}；录像抽样平均亮度 {means}")
    preflight = manifest.get("image_preflight") or {}
    prefix = ""
    if preflight.get("mean") is not None:
        prefix = f"开始前样帧平均亮度 {preflight['mean']:.1f}；"
    return _result("pass", f"{prefix}录像抽样平均亮度 {means}")


def _frame_rate_gate(session: Path, ffmpeg: Path | None, stamps: list[float]) -> dict:
    if len(stamps) < 2 or stamps[-1] - stamps[0] < LONG_GATE_SECONDS:
        return _result("pending", "录像短于 10 分钟，帧率关口未测")
    if ffmpeg is None:
        return _result("pending", "没有 FFmpeg，未能做唯一图像帧率")
    hashes: list[str] = []
    manifest = load_json(session / "session.json")
    for item in manifest["files"]:
        media = session / item["path"]
        digest = media.with_suffix(".framemd5")
        completed = subprocess.run(
            [str(ffmpeg), "-v", "error", "-xerror", "-err_detect", "explode", "-i", str(media),
             "-map", "0:v:0", "-fps_mode", "passthrough", "-f", "framemd5", str(digest)],
            capture_output=True, text=True, timeout=3600)
        if completed.returncode != 0:
            digest.unlink(missing_ok=True)
            raise RuntimeError("严格解码失败，帧率关口未通过")
        hashes.extend(line.split(",")[-1].strip()
                      for line in digest.read_text(encoding="utf-8").splitlines()
                      if line and not line.startswith("#"))
        digest.unlink(missing_ok=True)
    if len(hashes) != len(stamps):
        return _result("fail", "解码帧数与逐帧清单不一致")
    windows = []
    start = 10.0
    while stamps[-1] >= start + 60:
        chosen = [hashes[index] for index, stamp in enumerate(stamps) if start <= stamp < start + 60]
        windows.append(len(set(chosen)) / 60)
        start += 60
    overall = (len(set(hashes)) - 1) / (stamps[-1] - stamps[0])
    if len(windows) < 10 or overall < FRAME_RATE_FLOOR or any(item < FRAME_RATE_FLOOR for item in windows):
        low = min(windows) if windows else 0
        return _result("fail", f"唯一图像全程 {overall:.3f} fps，窗口最低 {low:.3f} fps，门槛 29.9")
    return _result("pass", f"唯一图像全程 {overall:.3f} fps，{len(windows)} 个 60 秒窗口均不低于 29.9")


def _closeout_gate(session: Path) -> dict:
    manifest = load_json(session / "session.json")
    native = manifest.get("native_capture")
    report = session / "native_capture.json"
    if native is None and report.is_file():
        native = load_json(report)
    if native is not None:
        verified = native.get("restoration", {}).get("verified") is True and native.get("status") == "complete"
        if verified:
            return _result("pass", "停止后相机控制已恢复并读回")
        return _result("fail", "相机控制未恢复，或原生采集没有完成")
    if manifest.get("exit_code") not in (0, None):
        return _result("fail", "录制进程没有正常结束")
    return _result("pass", "本路径未改写相机控制，录制进程已结束")


def evaluate_gates(session: Path, audit: dict, ffprobe: Path) -> dict:
    mismatches = audit.get("stream_mismatch_segments") or []
    integrity_ok = bool(audit.get("frame_count")) and not audit.get("missing_pts") and not audit.get(
        "nonmonotonic_pts") and not mismatches
    if integrity_ok:
        integrity = _result("pass", f"解码 {audit['frame_count']} 帧，分辨率一致，PTS 无缺失、重复或倒退")
    else:
        integrity = _result("fail", "校验未通过：缺帧时间戳、PTS 不递增，或分辨率与请求不一致")
    ffmpeg = _ffmpeg_beside(ffprobe)
    try:
        stamps = _pts(session)
    except (OSError, ValueError):
        stamps = []
    try:
        frame_rate = _frame_rate_gate(session, ffmpeg, stamps)
    except RuntimeError as exc:
        frame_rate = _result("fail", str(exc))
        integrity = _result("fail", str(exc))
    return combine_gates(integrity, frame_rate, _image_gate(session, ffmpeg), _closeout_gate(session))
