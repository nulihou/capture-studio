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


MODE_KEYS = ("width", "height", "fps", "format")


def mode_prefix(kind: str) -> str:
    """v0.12.5: the PC camera keeps its own mode under pc_width/pc_height/pc_fps/pc_format;
    the board keeps the original width/height/fps/format keys (older settings load unchanged)."""
    return "pc_" if kind in ("pc", "pc_usb") else ""


def mode_view(settings: dict[str, Any], kind: str) -> dict[str, Any]:
    """Copy of settings whose width/height/fps/format are the given source's mode."""
    view = dict(settings)
    prefix = mode_prefix(kind)
    if prefix:
        for key in MODE_KEYS:
            if str(settings.get(prefix + key) or "") != "":
                view[key] = settings[prefix + key]
    return view


def to_kind(payload: dict[str, Any], kind: str, current: dict[str, Any]) -> dict[str, Any]:
    """Route width/height/fps/format in payload to the given source's keys; board keys keep current values."""
    prefix = mode_prefix(kind)
    if not prefix:
        return dict(payload)
    routed = dict(payload)
    for key in MODE_KEYS:
        if key in payload:
            routed[prefix + key] = payload[key]
            if key in current:
                routed[key] = current[key]
    return routed


def migrate_pc_mode(settings: dict[str, Any], saved: dict[str, Any]) -> None:
    """Settings saved before v0.12.5 had one shared mode; seed the PC mode from it once."""
    for key in MODE_KEYS:
        if str(saved.get("pc_" + key) or "") == "":
            settings["pc_" + key] = settings.get(key, "")


def saved_mode(settings: dict[str, Any], kind: str = "board") -> dict[str, Any] | None:
    view = mode_view(settings, kind)
    try:
        return {"width": int(str(view.get("width")).strip()), "height": int(str(view.get("height")).strip()),
                "fps": int(str(view.get("fps")).strip()), "format": str(view.get("format") or "mjpeg")}
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


def apply_mode(settings: dict[str, Any], mode: dict[str, Any], kind: str = "board") -> None:
    """Write a mode back in the existing settings format (strings); PC uses the pc_ keys."""
    prefix = mode_prefix(kind)
    settings[prefix + "width"] = str(int(mode["width"]))
    settings[prefix + "height"] = str(int(mode["height"]))
    settings[prefix + "fps"] = str(int(mode["fps"]))
    settings[prefix + "format"] = str(mode["format"])
