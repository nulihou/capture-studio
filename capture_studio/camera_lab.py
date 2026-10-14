"""Camera-test adjustments and plug-in identity for a first-time operator.

Numbers the student leaves blank are not sent. A camera that does not advertise
a control is skipped instead of being given a guessed value.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess
from typing import Any, Callable


SPEED_TEXT = {
    "1.5": "USB 1.0 低速",
    "12": "USB 1.1 全速",
    "480": "USB 2.0 高速",
    "5000": "USB 3.0 超速",
    "10000": "USB 3.1",
    "20000": "USB 3.2",
}

RESOLUTION_PRESETS = {
    "640×480": (640, 480),
    "1280×720": (1280, 720),
    "1920×1080": (1920, 1080),
}


def preview_frame_size(width: int, height: int, max_edge: int = 1280) -> tuple[int, int]:
    """Preview keeps the capture frame, and only shrinks when the long side is above max_edge."""
    width, height = max(2, int(width)), max(2, int(height))
    width -= width % 2
    height -= height % 2
    long_side = max(width, height)
    if long_side <= max_edge:
        return width, height
    scale = max_edge / long_side
    out_w = max(2, int(width * scale) // 2 * 2)
    out_h = max(2, int(height * scale) // 2 * 2)
    return out_w, out_h

POWER_LINE_CHOICES = ("不改", "关闭", "50 Hz", "60 Hz")
AUTO_MANUAL_CHOICES = ("不改", "自动", "手动")


@dataclass(frozen=True)
class Tuning:
    name: str
    v4l2: str
    label: str
    kind: str
    low: int
    high: int
    hint: str


# Ranges cover common UVC cameras. A later control read replaces the hint
# with the range that particular camera reports.
TUNING: tuple[Tuning, ...] = (
    Tuning("gain", "gain", "增益", "int", 0, 1023,
           "留空不改。数字加大通常更亮，噪点也会变多。"),
    Tuning("brightness", "brightness", "亮度", "int", -128, 255,
           "留空不改。这是画面加减，不是曝光时间。"),
    Tuning("contrast", "contrast", "对比度", "int", 0, 255, "留空不改。"),
    Tuning("saturation", "saturation", "饱和度", "int", 0, 255, "留空不改。0 接近黑白。"),
    Tuning("sharpness", "sharpness", "锐度", "int", 0, 255, "留空不改。加太高边缘会发虚。"),
    Tuning("gamma", "gamma", "伽马", "int", 1, 500, "留空不改。"),
    Tuning("white_balance_auto", "white_balance_temperature_auto", "白平衡", "auto", 0, 1,
           "自动适合大多数室内。选手动后才填色温。"),
    Tuning("white_balance_temperature", "white_balance_temperature", "色温", "int", 2000, 10000,
           "大约 2800 偏暖，6500 偏冷。白平衡为自动时不要填。"),
    Tuning("power_line_frequency", "power_line_frequency", "灯光频率", "power", 0, 2,
           "室内日光灯闪烁时选 50 Hz。"),
    Tuning("backlight_compensation", "backlight_compensation", "逆光补偿", "int", 0, 10,
           "留空不改。对着窗户发黑时可以试 1。"),
    Tuning("focus_auto", "focus_automatic_continuous", "对焦", "auto", 0, 1,
           "自动对焦会自己找清晰点。固定机位可以改手动。"),
    Tuning("focus_absolute", "focus_absolute", "焦距", "int", 0, 1023,
           "只在手动对焦时填写。"),
)

TUNING_BY_NAME = {item.name: item for item in TUNING}
_CONTROL_LINE = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s+0x[0-9a-fA-F]+\s+\((int|bool|menu)\)\s*:\s*(.*)$")
_MIN = re.compile(r"\bmin=(-?\d+)")
_MAX = re.compile(r"\bmax=(-?\d+)")
_VALUE = re.compile(r"\bvalue=(-?\d+)")
_DEFAULT = re.compile(r"\bdefault=(-?\d+)")
_NODE = re.compile(r"(/dev/video[0-9]+)\s*$")


def speed_text(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    return SPEED_TEXT.get(value, f"USB {value} Mb/s")


def camera_sentence(info: dict[str, Any]) -> str:
    name = info.get("product") or info.get("name") or "摄像头"
    serial = info.get("serial") or "无序号"
    vid = str(info.get("vid") or "?").lower()
    pid = str(info.get("pid") or "?").lower()
    parts = [str(name), f"序号 {serial}", f"{vid}:{pid}"]
    speed = speed_text(str(info.get("speed") or ""))
    if speed:
        parts.append(speed)
    node = str(info.get("device") or "")
    if node:
        parts.append(node)
    return " · ".join(parts)


def choice_label(info: dict[str, Any]) -> str:
    name = info.get("product") or info.get("name") or "摄像头"
    serial = info.get("serial") or "无序号"
    return f"{name} · {serial} · {info.get('device') or ''}"


def path_from_choice(text: str) -> str:
    match = _NODE.search((text or "").strip())
    return match.group(1) if match else ""


def board_sentence(board: dict[str, Any] | None) -> str:
    board = board or {}
    model = str(board.get("model") or "").strip()
    host = str(board.get("hostname") or "").strip()
    address = str(board.get("address") or "").strip()
    if not model and not host and not address:
        return "开发板：还没连上"
    parts = [model or "开发板"]
    if host and host not in parts:
        parts.append(host)
    if address and address not in parts:
        parts.append(address)
    return "开发板：" + " · ".join(parts)


def fingerprint(infos: list[dict[str, Any]]) -> tuple:
    rows = []
    for info in infos:
        rows.append((str(info.get("serial") or ""), str(info.get("vid") or ""),
                     str(info.get("pid") or ""), str(info.get("usb_path") or ""),
                     str(info.get("device") or "")))
    return tuple(sorted(rows))


def choose_camera(infos: list[dict[str, Any]], current: str,
                  preferred_serial: str) -> tuple[str, str]:
    """Pick the image node a beginner should see. Several unmatched cameras stay unpicked."""
    if not infos:
        return "", "开发板上还没有摄像头。把摄像头插到开发板的 USB 口，不要同时插在电脑上。"
    current = (current or "").strip()
    preferred = (preferred_serial or "").strip()
    if len(infos) == 1:
        only = infos[0]
        serial = str(only.get("serial") or "")
        note = ""
        if preferred and serial and serial != preferred:
            note = f"记下的序号是 {preferred}，现在只插着 {serial}，已改用这一只。"
        elif preferred and not serial:
            note = f"记下的序号是 {preferred}，这一只没有序号，已改用唯一的摄像头。"
        return str(only.get("device") or ""), note
    if preferred:
        matches = [item for item in infos if str(item.get("serial") or "") == preferred]
        if len(matches) == 1:
            return str(matches[0].get("device") or ""), ""
    if current and any(str(item.get("device") or "") == current for item in infos):
        return current, ""
    names = "、".join(camera_sentence(item) for item in infos)
    return "", "开发板上有多只摄像头，请选一只：" + names


def arrival_message(previous: list[dict[str, Any]], current: list[dict[str, Any]],
                    board: dict[str, Any] | None) -> str:
    if fingerprint(previous) == fingerprint(current):
        return ""
    if not current:
        return "开发板上的摄像头已经拔掉。" if previous else ""
    if not previous and len(current) == 1:
        return board_sentence(board) + "。已认出摄像头：" + camera_sentence(current[0])
    if not previous:
        return board_sentence(board) + "。插着多只摄像头，请选一只。"

    def key(info: dict[str, Any]) -> tuple[str, str, str, str]:
        return (str(info.get("serial") or ""), str(info.get("vid") or ""),
                str(info.get("pid") or ""), str(info.get("usb_path") or ""))

    before = {key(item): item for item in previous}
    after = {key(item): item for item in current}
    parts: list[str] = []
    for ident, info in after.items():
        if ident not in before:
            parts.append("插上了摄像头：" + camera_sentence(info))
        elif before[ident].get("device") != info.get("device"):
            parts.append("摄像头重新编号，仍是 " + (info.get("serial") or "这一只")
                         + f"：{before[ident].get('device')} → {info.get('device')}")
    for ident, info in before.items():
        if ident not in after:
            parts.append("拔掉了摄像头：" + camera_sentence(info))
    return " ".join(parts)


def identity_record(board: dict[str, Any] | None, info: dict[str, Any] | None,
                    device: str) -> dict[str, str]:
    board = board or {}
    info = info or {}
    speed = str(info.get("speed") or "")
    return {
        "board_model": str(board.get("model") or ""),
        "board_hostname": str(board.get("hostname") or ""),
        "device": device,
        "name": str(info.get("name") or ""),
        "product": str(info.get("product") or ""),
        "serial": str(info.get("serial") or ""),
        "vid": str(info.get("vid") or ""),
        "pid": str(info.get("pid") or ""),
        "usb_speed": speed,
        "usb_speed_text": speed_text(speed),
        "usb_path": str(info.get("usb_path") or ""),
    }


def _number(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1)) if match else None


def parse_v4l2_controls(text: str) -> list[dict[str, Any]]:
    """Parse `v4l2-ctl --list-ctrls`. Unreadable lines are ignored."""
    found = []
    for line in text.splitlines():
        match = _CONTROL_LINE.match(line)
        if match is None:
            continue
        body = match.group(3)
        found.append({
            "name": match.group(1),
            "kind": match.group(2),
            "min": _number(_MIN, body),
            "max": _number(_MAX, body),
            "default": _number(_DEFAULT, body),
            "value": _number(_VALUE, body),
            "inactive": "inactive" in body,
        })
    return found


def support_for(controls: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    by_v4l2 = {str(item.get("name")): item for item in controls}
    return {item.name: by_v4l2.get(item.v4l2) for item in TUNING}


def read_tuning(kind: str, text: str, label: str, low: int, high: int) -> int | None:
    raw = (text or "").strip()
    if kind == "int":
        if not raw:
            return None
        if not re.fullmatch(r"-?\d+", raw):
            raise ValueError(f"{label}要填整数，或留空表示不改")
        value = int(raw)
    elif kind == "auto":
        value = {"不改": None, "自动": 1, "手动": 0}.get(raw)
        if raw not in {"不改", "自动", "手动"}:
            raise ValueError(f"{label}请选不改、自动或手动")
        return value
    elif kind == "power":
        value = {"不改": None, "关闭": 0, "50 Hz": 1, "60 Hz": 2}.get(raw)
        if raw not in POWER_LINE_CHOICES:
            raise ValueError(f"{label}请选不改、关闭、50 Hz 或 60 Hz")
        return value
    else:
        raise ValueError("unknown tuning kind")
    if not low <= value <= high:
        raise ValueError(f"{label}要在 {low} 到 {high} 之间，或留空")
    return value


def validate_tuning(options: Any) -> None:
    for item in TUNING:
        value = getattr(options, item.name)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or not item.low <= value <= item.high:
            raise ValueError(f"{item.label}要在 {item.low} 到 {item.high} 之间")
    serial = str(getattr(options, "camera_serial", "") or "")
    speed = str(getattr(options, "usb_speed", "") or "")
    if len(serial) > 128 or len(speed) > 32 or "\n" in serial or "\x00" in serial:
        raise ValueError("摄像头序号或 USB 速度无法保存")
    if getattr(options, "white_balance_auto", None) == 1 and getattr(
            options, "white_balance_temperature", None) is not None:
        raise ValueError("自动白平衡不要再填色温")
    if getattr(options, "focus_auto", None) == 1 and getattr(
            options, "focus_absolute", None) is not None:
        raise ValueError("自动对焦不要再填焦距")


def has_image_tuning(options: Any) -> bool:
    return any(getattr(options, item.name, None) is not None for item in TUNING)


def extra_controls_token(options: Any) -> str | None:
    """One gst-launch property. Quotes stay inside the argument so commas survive parsing."""
    parts: list[str] = []
    mode = getattr(options, "exposure_mode", None)
    absolute = getattr(options, "exposure_absolute", None)
    if mode is not None:
        parts.append(f"exposure_auto={int(mode)}")
    if absolute is not None:
        parts.append(f"exposure_absolute={int(absolute)}")
    for item in TUNING:
        value = getattr(options, item.name, None)
        if value is not None:
            parts.append(f"{item.v4l2}={int(value)}")
    if not parts:
        return None
    return 'extra-controls="c,' + ",".join(parts) + '"'


def v4l2_source_launch(options: Any) -> str:
    token = extra_controls_token(options)
    extra = f" {token}" if token else ""
    return f"v4l2src name=camera device={options.device} io-mode=mmap{extra} ! "


def query_v4l2_controls(device: str, runner: Callable[[list[str]], str] | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"/dev/video[0-9]+", device or ""):
        raise ValueError("device must be /dev/videoN")
    if runner is None:
        if shutil.which("v4l2-ctl") is None:
            return {"device": device, "controls": [],
                    "error": "板上没有 v4l2-ctl，先用常用范围。安装 v4l-utils 后可以读出这只摄像头真正支持的项目。"}

        def runner(argv: list[str]) -> str:
            result = subprocess.run(argv, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=8)
            return (result.stdout or "") + "\n" + (result.stderr or "")

    text = runner(["v4l2-ctl", "-d", device, "--list-ctrls"])
    return {"device": device, "controls": parse_v4l2_controls(text)}


def slow_usb_warning(speed: str, width: int, height: int) -> str:
    if speed in {"12", "1.5"} and width * height >= 1280 * 720:
        return "这是 USB 全速口，高分辨率可能会卡。可以先用 640×480。"
    return ""


# ---- supported capture modes (v6) ------------------------------------------------
V4L2_FORMATS = {"MJPG": "mjpeg", "YUYV": "raw"}


def parse_v4l2_formats(text: str) -> list[dict[str, Any]]:
    """Parse `v4l2-ctl --list-formats-ext` (new "[0]: 'MJPG'" and old "Pixel Format: 'MJPG'" styles).

    Returns modes as {"width", "height", "fps", "format"} with format in the app's vocabulary
    ("mjpeg" / "raw"). Unknown pixel formats and stepwise sizes are skipped, never guessed.
    """
    modes: list[dict[str, Any]] = []
    fmt: str | None = None
    size: tuple[int, int] | None = None
    for line in text.splitlines():
        found = re.search(r"(?:\[\d+\]:|Pixel Format:)\s*'([A-Z0-9 ]{4})'", line)
        if found:
            fmt = V4L2_FORMATS.get(found.group(1).strip())
            size = None
            continue
        found = re.search(r"Size:\s*Discrete\s+(\d+)x(\d+)", line)
        if found:
            size = (int(found.group(1)), int(found.group(2)))
            continue
        found = re.search(r"Interval:\s*Discrete\s+[\d.]+s\s*\(([\d.]+)\s*fps\)", line)
        if found and fmt and size:
            fps = int(round(float(found.group(1))))
            mode = {"width": size[0], "height": size[1], "fps": fps, "format": fmt}
            if fps > 0 and mode not in modes:
                modes.append(mode)
    return modes


def query_v4l2_formats(device: str, runner: Callable[[list[str]], str] | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"/dev/video[0-9]+", device or ""):
        raise ValueError("device must be /dev/videoN")
    if runner is None:
        if shutil.which("v4l2-ctl") is None:
            return {"device": device, "modes": [], "error": "板上没有 v4l2-ctl，无法检测模式"}

        def runner(argv: list[str]) -> str:
            result = subprocess.run(argv, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=8)
            return (result.stdout or "") + "\n" + (result.stderr or "")

    text = runner(["v4l2-ctl", "-d", device, "--list-formats-ext"])
    return {"device": device, "modes": parse_v4l2_formats(text)}
