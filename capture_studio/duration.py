"""Recording length: named presets, or a custom clock within 10 seconds and 2 hours."""
from __future__ import annotations

from typing import Any

PRESETS = {"60 秒短检": 60, "10 分钟关口": 650, "手动停止": None}
CUSTOM = "自定义"
MIN_SECONDS = 10
MAX_SECONDS = 7200
# Size estimates only. Manual recording has no stop timer.
MANUAL_ESTIMATE_SECONDS = 600


def planned_seconds(settings: dict[str, Any]) -> int | None:
    """Seconds until auto-stop. None means the operator stops the recording."""
    label = str(settings.get("duration") or "60 秒短检")
    if label in PRESETS:
        return PRESETS[label]
    if label != CUSTOM:
        raise ValueError("时长请选择短检、10 分钟关口、自定义或手动停止")
    total = _clock(settings)
    if not MIN_SECONDS <= total <= MAX_SECONDS:
        raise ValueError("自定义时长需在 10 秒到 2 小时之间")
    return total


def estimate_seconds(settings: dict[str, Any]) -> int:
    """Length used for a size estimate. Manual stop uses a 10-minute budget."""
    try:
        value = planned_seconds(settings)
    except ValueError:
        return PRESETS["60 秒短检"]
    return MANUAL_ESTIMATE_SECONDS if value is None else value


def _clock(settings: dict[str, Any]) -> int:
    try:
        hours = int(settings.get("custom_hours") or 0)
        minutes = int(settings.get("custom_minutes") or 0)
        seconds = int(settings.get("custom_seconds") or 0)
    except (TypeError, ValueError):
        raise ValueError("自定义时长需要填写数字") from None
    if hours < 0 or minutes < 0 or seconds < 0:
        raise ValueError("自定义时长需要填写数字")
    return hours * 3600 + minutes * 60 + seconds
