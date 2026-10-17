"""Pre-capture health check and recording size estimate (v7).  Pure functions, no I/O."""
from __future__ import annotations

import re
from typing import Any

# v9: no guessed compression coefficients.  Sizes come from format math where it is exact (uncompressed
# YUYV = 2 bytes/pixel; H.264 = its target bitrate), otherwise from what recent sessions with the same
# format/codec actually wrote; with no history the figure is an explicit upper bound (uncompressed size).
YUYV_BYTES_PER_PIXEL = 2.0
BASIS_TEXT = {"exact": "按格式计算", "bitrate": "按目标码率", "measured": "按最近会话实测", "upper": "上限（按未压缩计）"}
DURATIONS = {"60 秒短检": 60, "10 分钟关口": 650, "手动停止": 600}  # 650 s includes warmup; manual budget is advisory


def seconds_for(duration: str) -> int:
    if duration in DURATIONS:
        return DURATIONS[duration]
    match = re.match(r"^\s*(\d+)", str(duration))
    return int(match.group(1)) if match else 60


def stored_codec(fmt: str, codec: str, mode: str) -> str:
    fmt = "raw" if (fmt or "mjpeg").lower() in ("raw", "yuyv", "yuy2") else "mjpeg"
    if mode != "pc":
        return "h264" if fmt == "raw" else "copy"
    return (codec or "copy").lower()


def _key(fmt: str, codec: str) -> tuple[str, str]:
    return ("raw" if (fmt or "").lower() in ("raw", "yuyv", "yuy2") else "mjpeg", (codec or "copy").lower())


def measured_bpp(history: list[dict[str, Any]] | None, fmt: str, codec: str) -> tuple[float, int] | None:
    """Median bytes per pixel-frame written by recent sessions with the same source format and codec."""
    samples = []
    for row in history or []:
        try:
            pixels = float(row.get("width") or 0) * float(row.get("height") or 0)
            frames = float(row.get("frames") or 0) or float(row.get("duration") or 0) * float(row.get("fps") or 0)
            size = float(row.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if pixels <= 0 or frames <= 0 or size <= 0:
            continue
        if _key(str(row.get("format") or ""), str(row.get("codec") or "copy")) != _key(fmt, codec):
            continue
        samples.append(size / (pixels * frames))
    if not samples:
        return None
    samples.sort()
    return samples[len(samples) // 2], len(samples)


def rate_and_basis(width: float, height: float, fps: float, fmt: str, codec: str, bitrate_kbps: float,
                   history: list[dict[str, Any]] | None = None) -> tuple[float, str, int]:
    raw = "raw" if (fmt or "").lower() in ("raw", "yuyv", "yuy2") else "mjpeg"
    if raw == "raw" and codec == "copy":
        return width * height * fps * YUYV_BYTES_PER_PIXEL, "exact", 0
    if codec == "h264" and bitrate_kbps > 0:
        return bitrate_kbps * 1000 / 8, "bitrate", 0
    found = measured_bpp(history, fmt, codec)
    if found:
        return width * height * fps * found[0], "measured", found[1]
    return width * height * fps * YUYV_BYTES_PER_PIXEL, "upper", 0


def bytes_per_second(width: int, height: int, fps: float, fmt: str, codec: str = "copy",
                     bitrate_kbps: float = 0, history: list[dict[str, Any]] | None = None) -> float:
    return rate_and_basis(float(width), float(height), float(fps), fmt, (codec or "copy").lower(), bitrate_kbps, history)[0]


def estimate(settings: dict[str, Any], mode: str = "pc", history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from .camera_modes import mode_view
    settings = mode_view(settings, mode)
    def num(key: str, default: float) -> float:
        try:
            return float(settings.get(key) or default)
        except (TypeError, ValueError):
            return default
    width, height, fps = num("width", 640), num("height", 480), num("fps", 30)
    fmt = str(settings.get("format") or "mjpeg")
    codec = stored_codec(fmt, str(settings.get("codec") or "copy"), mode)
    rate, basis, samples = rate_and_basis(width, height, fps, fmt, codec, num("bitrate", 0), history)
    seconds = seconds_for(str(settings.get("duration") or ""))
    return {"bytes_per_s": rate, "mbps": rate * 8 / 1e6, "seconds": seconds, "bytes": rate * seconds,
            "basis": basis, "samples": samples, "label": BASIS_TEXT[basis]}


# Documented thermal limits by detected family (v9).  Only vendor-published numbers; others fall back to a
# clearly labelled generic rule.  Kernel trip points reported by the board itself always win.
DOCUMENTED_LIMITS = {
    # Raspberry Pi documentation: firmware throttles from 80 °C and further at 85 °C.
    "raspberrypi": (80.0, 85.0, "Raspberry Pi 官方文档：80 °C 开始降频，85 °C 进一步降频"),
    # AMD Kria K26 SOM data sheet (DS987): commercial-grade junction temperature 0–100 °C.
    "kv260": (90.0, 100.0, "Kria K26 数据手册 DS987：商业级结温上限 100 °C"),
}
GENERIC_LIMITS = (80.0, 90.0, "通用阈值（未识别到该板的官方温度上限）")


def temp_limits(board_info: dict[str, Any] | None) -> tuple[float, float, str]:
    """(warn °C, fail °C, source) — board trip points > documented family limits > generic."""
    info = board_info or {}
    trips = [t for t in info.get("thermal_trips") or [] if len(t) == 3]
    critical = [float(t[2]) for t in trips if str(t[1]) in ("critical", "hot")]
    passive = [float(t[2]) for t in trips if str(t[1]) == "passive"]
    if critical or passive:
        fail = min(critical) if critical else max(passive) + 10
        warn = min(passive) if passive and min(passive) < fail else fail - 10
        return warn, fail, f"开发板内核温控点（{'降频' if passive else '告警'} {warn:.0f} °C / 关机 {fail:.0f} °C）"
    family = str(info.get("family") or "")
    if family in DOCUMENTED_LIMITS:
        return DOCUMENTED_LIMITS[family]
    return GENERIC_LIMITS


def human(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit in ("B", "KB") else f"{num:.1f} {unit}"
        num /= 1024
    return ""


def check(settings: dict[str, Any], mode: str, local_free: float | None, board_status: dict[str, Any],
          camera_label: str = "", link_mbps: float | None = None, last_audit: dict[str, Any] | None = None,
          board_info: dict[str, Any] | None = None, history: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """Return [{level: ok|warn|fail, title, detail, fix}] — every item actionable."""
    from .camera_modes import mode_view
    settings = mode_view(settings, mode)
    est = estimate(settings, mode, history)
    items: list[dict[str, str]] = []

    def add(level: str, title: str, detail: str, fix: str = "") -> None:
        items.append({"level": level, "title": title, "detail": detail, "fix": fix})

    need = est["bytes"] * 1.2
    add("ok", "预计大小（估算）", f"约 {human(est['bytes'])}（{est['mbps']:.0f} Mb/s × {int(est['seconds'])} 秒，{est['label']}）")
    if local_free is not None:
        if local_free < need:
            add("fail", "电脑磁盘空间不足", f"剩余 {human(local_free)}，需要约 {human(need)}",
                "换到空间更大的输出文件夹，或缩短时长、降低分辨率")
        elif local_free < need * 3:
            add("warn", "电脑磁盘空间偏紧", f"剩余 {human(local_free)}，本次约 {human(need)}", "录完后及时取回并清理")
        else:
            add("ok", "电脑磁盘空间", f"剩余 {human(local_free)}")
    if mode == "board" and board_status.get("disk_total"):
        free = float(board_status["disk_total"]) - float(board_status.get("disk_used") or 0)
        if free < need:
            add("fail", "开发板存储不足", f"剩余 {human(free)}，需要约 {human(need)}", "清理板端旧会话（取回后删除）或插入更大的存储")
        else:
            add("ok", "开发板存储", f"剩余 {human(free)}")
    temp = board_status.get("temp_max")
    if mode == "board" and isinstance(temp, (int, float)):
        warn_at, fail_at, source = temp_limits(board_info)
        if temp >= fail_at:
            add("fail", "开发板过热", f"{temp:.0f} °C ≥ {fail_at:.0f} °C · {source}", "加风扇或散热片，等降温后再录")
        elif temp >= warn_at:
            add("warn", "开发板温度偏高", f"{temp:.0f} °C ≥ {warn_at:.0f} °C · {source}", "长时间录制可能降频掉帧，建议加强散热")
        else:
            add("ok", "开发板温度", f"{temp:.0f} °C（上限 {warn_at:.0f} °C · {source}）")
    cpu = board_status.get("cpu")
    if mode == "board" and isinstance(cpu, (int, float)) and cpu >= 85:
        add("warn", "开发板 CPU 繁忙", f"{cpu:.0f}%", "关闭板上其他程序后再录")
    usb2 = "USB 2.0" in camera_label or "USB 1." in camera_label
    def _n(key: str, default: float) -> float:
        try:
            return float(settings.get(key) or default)
        except (TypeError, ValueError):
            return default
    source_mbps = _n("width", 640) * _n("height", 480) * _n("fps", 30) * YUYV_BYTES_PER_PIXEL * 8 / 1e6
    if usb2 and source_mbps > 320 and str(settings.get("format") or "").lower() in ("raw", "yuyv"):
        add("fail", "USB 带宽不够", f"未压缩 {source_mbps:.0f} Mb/s 超过 USB 2.0 实际约 320 Mb/s",
            "改用 MJPEG，或降低分辨率/帧率，或接 USB 3.0 口")
    if link_mbps:
        if est["mbps"] > link_mbps * 0.6:
            add("warn", "网络带宽可能不够", f"码率 {est['mbps']:.0f} Mb/s，链路 {link_mbps:.0f} Mb/s",
                "板端录制不受影响，但实时预览和取回会变慢；可用千兆网线")
        else:
            add("ok", "网络带宽", f"链路 {link_mbps:.0f} Mb/s")
    rx = board_status.get("rx_bps")
    if mode == "board" and isinstance(rx, (int, float)) and rx * 8 / 1e6 > 50:
        add("warn", "网络正忙", f"当前接收 {rx * 8 / 1e6:.0f} Mb/s", "暂停其他传输后再录")
    if last_audit:
        gaps = int(last_audit.get("possible_gap_intervals") or 0)
        frames = int(last_audit.get("frame_count") or 0)
        if gaps:
            add("warn", "上次录制有疑似掉帧", f"{gaps} 处间隔 / {frames} 帧",
                "检查 USB 线和供电，尝试降低帧率或换 MJPEG")
        elif frames:
            add("ok", "上次录制无掉帧", f"{frames} 帧")
    return items


def worst(items: list[dict[str, str]]) -> str:
    levels = [item["level"] for item in items]
    return "fail" if "fail" in levels else ("warn" if "warn" in levels else "ok")
