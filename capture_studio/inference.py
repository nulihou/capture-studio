"""Board inference result protocol for Capture Studio.

The desktop never runs a model. A process on the board posts one JSON object
per frame to the board agent; the desktop aligns that object with the preview
frame and draws it. ``demo_overlay`` is a scripted stand-in for the page
preview when no board is attached. It does not look at pixels.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen

SCHEMA = "capture-studio.inference.v1"
MAX_DETECTIONS = 400
MAX_EDGE = 8192


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _int(value: Any, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def png_size(data: bytes) -> tuple[int, int]:
    """Read width and height from a PNG IHDR. Returns (0, 0) when it is not a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return 0, 0
    return struct.unpack(">II", data[16:24])


def parse_result(payload: Any) -> dict[str, Any]:
    """Validate one result and return pixel-space boxes.

    ``coord`` may be ``pixel`` (default) or ``norm`` (0–1 of width/height).
    The returned object is always in pixels so the desktop has one drawing path.
    """
    if not isinstance(payload, dict):
        raise ValueError("inference result must be a JSON object")
    schema = payload.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise ValueError(f"unsupported inference schema: {schema}")
    frame_id = _int(payload.get("frame_id"), "frame_id")
    if frame_id < 0:
        raise ValueError("frame_id must be >= 0")
    width = _int(payload.get("width"), "width")
    height = _int(payload.get("height"), "height")
    if not (1 <= width <= MAX_EDGE and 1 <= height <= MAX_EDGE):
        raise ValueError("width and height are out of range")
    coord = payload.get("coord", "pixel")
    if coord not in ("pixel", "norm"):
        raise ValueError("coord must be pixel or norm")
    raw_items = payload.get("detections", [])
    if not isinstance(raw_items, list):
        raise ValueError("detections must be a list")
    if len(raw_items) > MAX_DETECTIONS:
        raise ValueError(f"detections exceed {MAX_DETECTIONS}")
    detections = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ValueError(f"detections[{index}] must be an object")
        box = item.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError(f"detections[{index}].bbox must be [x, y, w, h]")
        x, y, bw, bh = (_finite(part, f"detections[{index}].bbox") for part in box)
        if coord == "norm":
            x, y, bw, bh = x * width, y * height, bw * width, bh * height
        if bw <= 0 or bh <= 0:
            raise ValueError(f"detections[{index}].bbox size must be positive")
        name = item.get("class")
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise ValueError(f"detections[{index}].class must be a short string")
        score = _finite(item.get("score"), f"detections[{index}].score")
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"detections[{index}].score must be between 0 and 1")
        det: dict[str, Any] = {
            "bbox": [round(x, 3), round(y, 3), round(bw, 3), round(bh, 3)],
            "class": name.strip(),
            "score": round(score, 4),
        }
        if "class_id" in item and item["class_id"] is not None:
            det["class_id"] = _int(item["class_id"], f"detections[{index}].class_id")
        if "track_id" in item and item["track_id"] is not None:
            track = item["track_id"]
            if type(track) is int:
                det["track_id"] = track
            elif isinstance(track, str) and 0 < len(track) <= 32:
                det["track_id"] = track
            else:
                raise ValueError(f"detections[{index}].track_id must be an int or short string")
        detections.append(det)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "frame_id": frame_id,
        "width": width,
        "height": height,
        "detections": detections,
    }
    if "timestamp_ns" in payload and payload["timestamp_ns"] is not None:
        stamp = _int(payload["timestamp_ns"], "timestamp_ns")
        if stamp < 0:
            raise ValueError("timestamp_ns must be >= 0")
        result["timestamp_ns"] = stamp
    if "latency_ms" in payload and payload["latency_ms"] is not None:
        latency = _finite(payload["latency_ms"], "latency_ms")
        if not 0 <= latency <= 600_000:
            raise ValueError("latency_ms is out of range")
        result["latency_ms"] = round(latency, 3)
    for key in ("model", "backend"):
        if key in payload and payload[key] is not None:
            text = payload[key]
            if not isinstance(text, str) or len(text) > 80:
                raise ValueError(f"{key} must be a short string")
            result[key] = text
    if payload.get("preview_only") is True:
        result["preview_only"] = True
    # Optional demo-clip hint. The desktop ignores it unless the source is the demo clip.
    if "infer_fps" in payload and payload["infer_fps"] is not None:
        infer_fps = _finite(payload["infer_fps"], "infer_fps")
        if not 0 < infer_fps <= 240:
            raise ValueError("infer_fps is out of range")
        result["infer_fps"] = round(infer_fps, 3)
    return result


def align_result(results: Iterable[dict[str, Any]], *, frame_id: int | None = None,
                 timestamp_ns: int | None = None, window_ns: int = 80_000_000,
                 max_lag: int = 3) -> tuple[dict[str, Any] | None, str]:
    """Pick the result that belongs to the displayed frame.

    Shared ``frame_id`` wins. A result up to ``max_lag`` frames behind is kept
    so a slightly slower model still sticks to the right picture. When the
    model captures on its own clock, ``timestamp_ns`` (``time.time_ns()``)
    matches within ``window_ns``.
    """
    rows = list(results)
    if frame_id is not None:
        exact = [row for row in rows if row.get("frame_id") == frame_id]
        if exact:
            return exact[-1], "frame_id"
        earlier = [row for row in rows
                   if type(row.get("frame_id")) is int and 0 <= frame_id - row["frame_id"] <= max_lag]
        if earlier:
            return max(earlier, key=lambda row: row["frame_id"]), "lag"
    if timestamp_ns is not None:
        best: dict[str, Any] | None = None
        best_gap: int | None = None
        for row in rows:
            stamp = row.get("timestamp_ns")
            if type(stamp) is not int:
                continue
            gap = timestamp_ns - stamp
            if -40_000_000 <= gap <= window_ns and (best_gap is None or abs(gap) < abs(best_gap)):
                best, best_gap = row, gap
        if best is not None:
            return best, "timestamp"
    return None, "none"


def visible_detections(result: dict[str, Any] | None, min_score: float,
                       disabled: Iterable[str] = ()) -> list[dict[str, Any]]:
    if not result:
        return []
    blocked = set(disabled)
    return [det for det in result.get("detections") or []
            if float(det.get("score") or 0) >= min_score and det.get("class") not in blocked]


def class_counts(detections: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for det in detections:
        name = str(det.get("class") or "")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


def result_line(result: dict[str, Any]) -> str:
    clean = {key: value for key, value in result.items() if not str(key).startswith("_")}
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def read_jsonl(text: str) -> list[dict[str, Any]]:
    rows = []
    for index, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(parse_result(json.loads(line)))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"line {index}: {exc}") from exc
    return rows


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(Path(path).read_text(encoding="utf-8"))


class JsonlRecorder:
    """Append-only session log. One protocol object per line."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        self.count = 0

    def write(self, result: dict[str, Any]) -> None:
        self._handle.write(result_line(result) + "\n")
        self._handle.flush()
        self.count += 1

    def close(self) -> None:
        self._handle.close()


def board_health(status: dict[str, Any] | None) -> dict[str, Any]:
    """Pick the fields the demo page draws from a board_probe status dict."""
    status = status or {}
    cpu = status.get("cpu")
    temp = status.get("temp_max")
    used = status.get("mem_used")
    total = status.get("mem_total")
    return {
        "cpu": float(cpu) if isinstance(cpu, (int, float)) and not isinstance(cpu, bool) else None,
        "temp": float(temp) if isinstance(temp, (int, float)) and not isinstance(temp, bool) else None,
        "mem_used": int(used) if isinstance(used, (int, float)) and not isinstance(used, bool) else None,
        "mem_total": int(total) if isinstance(total, (int, float)) and not isinstance(total, bool) else None,
        "live": any(status.get(key) is not None for key in ("cpu", "temp_max", "mem_total")),
    }


def demo_overlay(frame_id: int, width: int, height: int) -> dict[str, Any]:
    """Scripted boxes for the desktop page preview.

    This is not a detector. The arguments are a frame counter and a canvas
    size; the function never receives pixels. ``preview_only`` is set so the
    page can label the boxes as demo data.
    """
    if type(frame_id) is not int or frame_id < 0:
        raise ValueError("frame_id must be a non-negative integer")
    if not (1 <= width <= MAX_EDGE and 1 <= height <= MAX_EDGE):
        raise ValueError("width and height are out of range")
    specs = (
        ("car", 0.30, 0.70, 0.20, 0.14, 0.93, 1),
        ("person", 0.50, 0.64, 0.055, 0.22, 0.84, 2),
        ("bicycle", 0.68, 0.70, 0.11, 0.15, 0.76, 3),
        ("drone", 0.74, 0.24, 0.07, 0.055, 0.90, 4),
        ("bird", 0.36, 0.20, 0.014, 0.020, 0.62, 5),
    )
    tick = frame_id / 30.0
    detections = []
    for index, (name, nx, ny, nw, nh, score, track) in enumerate(specs):
        phase = tick * (0.42 + index * 0.08)
        cx = min(0.92, max(0.08, nx + 0.07 * math.sin(phase)))
        cy = min(0.90, max(0.08, ny + 0.035 * math.cos(phase * 0.85)))
        wobble = 0.04 * math.sin(phase * 2.2 + index)
        detections.append({
            "bbox": [round((cx - nw / 2) * width, 3), round((cy - nh / 2) * height, 3),
                     round(nw * width, 3), round(nh * height, 3)],
            "class": name,
            "class_id": index,
            "score": round(max(0.35, min(0.99, score + wobble)), 4),
            "track_id": track,
        })
    latency = 12.4 + 3.1 * math.sin(frame_id / 6.0) + (1.6 if frame_id % 19 == 0 else 0.0)
    return parse_result({
        "schema": SCHEMA,
        "frame_id": frame_id,
        "timestamp_ns": 1_700_000_000_000_000_000 + frame_id * 33_333_333,
        "width": width,
        "height": height,
        "model": "demo-overlay",
        "backend": "preview",
        "latency_ms": latency,
        "detections": detections,
        "preview_only": True,
    })


def post_result(base_url: str, token: str, result: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
    """POST one protocol object to a board agent. Used by the board-side sender."""
    body = json.dumps(result, ensure_ascii=False).encode("utf-8")
    request = Request(base_url.rstrip("/") + "/infer", data=body, method="POST",
                      headers={"Authorization": "Bearer " + token,
                               "Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def read_envelope(stream: Any) -> tuple[dict[str, Any], bytes]:
    """Read one ``/live/envelope`` record: uint32 header length, JSON, PNG."""
    from .live_preview import read_exact, read_png
    length = struct.unpack(">I", read_exact(stream, 4))[0]
    if not 2 <= length <= 65536:
        raise ValueError("envelope header length is out of range")
    meta = json.loads(read_exact(stream, length).decode("utf-8"))
    if not isinstance(meta, dict):
        raise ValueError("envelope header must be an object")
    return meta, read_png(stream)


def write_envelope(stream: Any, meta: dict[str, Any], png: bytes) -> None:
    header = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stream.write(struct.pack(">I", len(header)))
    stream.write(header)
    stream.write(png)
