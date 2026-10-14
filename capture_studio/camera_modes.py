"""Camera capture modes: detection (PC DirectShow), defaults and fallback presets.

Board-side parsing lives in camera_lab.parse_v4l2_formats because camera_lab is already
synced to the KV260. Modes are plain dicts {"width", "height", "fps", "format"} where
format uses the stored settings vocabulary ("mjpeg" / "raw"), so studio_settings.json
keeps exactly the same keys and value types (strings) as before.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .camera_lab import parse_v4l2_formats  # noqa: F401  (re-exported for callers/tests)
from .textcodec import safe_decode

FORMAT_LABEL = {"mjpeg": "MJPEG", "raw": "YUYV"}
DSHOW_FORMATS = {"mjpeg": "mjpeg", "yuyv422": "raw"}

PRESETS: list[dict[str, Any]] = [
    {"width": w, "height": h, "fps": fps, "format": fmt}
    for fmt in ("mjpeg", "raw")
    for (w, h) in ((3840, 2160), (2560, 1440), (1920, 1080), (1280, 720), (640, 480))
    for fps in (60, 30)
]


def parse_dshow_options(text: str) -> list[dict[str, Any]]:
    """Parse `ffmpeg -f dshow -list_options true -i video=NAME` (stderr, already decoded)."""
    modes: list[dict[str, Any]] = []
    pattern = re.compile(r"(vcodec|pixel_format)=(\S+)\s+min s=(\d+)x(\d+) fps=([\d.]+)\s+"
                         r"max s=(\d+)x(\d+) fps=([\d.]+)")
    for line in text.splitlines():
        found = pattern.search(line)
        if not found:
            continue
        fmt = DSHOW_FORMATS.get(found.group(2).lower())
        if fmt is None:
            continue
        width, height = int(found.group(6)), int(found.group(7))
        fps = int(round(float(found.group(8))))
        mode = {"width": width, "height": height, "fps": fps, "format": fmt}
        if fps > 0 and mode not in modes:
            modes.append(mode)
    return modes


def list_dshow_modes(ffmpeg: Path, device: str) -> list[dict[str, Any]]:
    result = subprocess.run([str(ffmpeg), "-hide_banner", "-f", "dshow", "-list_options", "true",
                             "-i", f"video={device}"], capture_output=True, timeout=20)
    return parse_dshow_options(safe_decode(result.stderr or b""))


def sort_modes(modes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MJPEG first (bandwidth), then larger frames, then higher frame rate."""
    return sorted(modes, key=lambda m: (m["format"] != "mjpeg", -m["width"] * m["height"], -m["fps"]))


def mode_key(mode: dict[str, Any]) -> str:
    return f"{int(mode['width'])}|{int(mode['height'])}|{int(mode['fps'])}|{mode['format']}"


def mode_label(mode: dict[str, Any]) -> str:
    return (f"{int(mode['width'])}×{int(mode['height'])} · {int(mode['fps'])} fps · "
            f"{FORMAT_LABEL.get(str(mode['format']), str(mode['format']).upper())}")


def saved_mode(settings: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return {"width": int(str(settings.get("width")).strip()), "height": int(str(settings.get("height")).strip()),
                "fps": int(str(settings.get("fps")).strip()), "format": str(settings.get("format") or "mjpeg")}
    except (TypeError, ValueError):
        return None


def choose_mode(modes: list[dict[str, Any]], saved: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep the saved mode if the camera still supports it; else highest resolution at >=30 fps,
    preferring MJPEG; else the best available mode."""
    if not modes:
        return None
    if saved is not None and mode_key(saved) in {mode_key(m) for m in modes}:
        return saved
    fast = [m for m in modes if m["fps"] >= 30]
    pool = fast or modes
    return sorted(pool, key=lambda m: (-m["width"] * m["height"], m["format"] != "mjpeg", -m["fps"]))[0]


def apply_mode(settings: dict[str, Any], mode: dict[str, Any]) -> None:
    """Write a mode back in the existing settings format (strings, same keys)."""
    settings["width"] = str(int(mode["width"]))
    settings["height"] = str(int(mode["height"]))
    settings["fps"] = str(int(mode["fps"]))
    settings["format"] = str(mode["format"])
