"""Automatic PC camera choice (v9): last used -> same VID:PID -> the only USB (UVC) camera -> manual."""
from __future__ import annotations

from typing import Any

REASONS = {
    "last": "自动选择：上次使用",
    "vidpid": "自动选择：同型号（VID:PID）",
    "sole_uvc": "自动选择：唯一的 USB 摄像头",
    "sole": "自动选择：唯一的摄像头",
    "manual": "手动选择",
    "need_manual": "有多只摄像头，请手动选择",
    "none": "未检测到摄像头",
}


def camera_id(item: dict[str, Any]) -> str:
    return f"{item.get('vid')}:{item.get('pid')}" if item.get("vid") else ""


def pick_camera(cameras: list[dict[str, Any]], last_value: str = "", last_id: str = "") -> tuple[str, str]:
    """Return (device value, reason key).  Never guesses between several indistinguishable cameras."""
    if not cameras:
        return "", "none"
    values = [str(item.get("value") or item.get("name") or "") for item in cameras]
    if last_value and last_value in values:
        return last_value, "last"
    if last_id:
        same = [v for v, item in zip(values, cameras) if camera_id(item) == last_id]
        if len(same) == 1:
            return same[0], "vidpid"
    usb = [v for v, item in zip(values, cameras) if item.get("vid")]
    if len(usb) == 1:
        return usb[0], "sole_uvc"
    if len(values) == 1:
        return values[0], "sole"
    return "", "need_manual"
