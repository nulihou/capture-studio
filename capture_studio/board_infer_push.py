"""Push board-side model output into the Capture Studio agent.

Run this on the board, next to the agent. It does not load a model and does
not import a runtime. Your own runtime (DPU, TensorRT, RKNN, Ascend, …)
produces boxes; this process only reshapes them into the protocol and POSTs
them to ``/infer``.

Stdin, one JSON object per line (a protocol result, or a raw record with
``boxes``)::

    python3 -m capture_studio.board_infer_push \\
        --url http://127.0.0.1:8765 --token-file ./capture_token.txt

Envelope: read the preview the agent is already producing, then call
``detections_from_frame``. Replace that function with your runtime. Until
you do, it sends zero boxes and ``model: not-configured`` so the desktop
shows “model not attached” instead of fake detections.

    python3 -m capture_studio.board_infer_push --envelope \\
        --url http://127.0.0.1:8765 --token-file ./capture_token.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from .inference import SCHEMA, parse_result, png_size, post_result, read_envelope

DetectFn = Callable[[dict[str, Any], bytes], dict[str, Any]]


def adapt(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a protocol object or a small raw shape into a validated result.

    Raw shape::

        {"frame_id", "width", "height", "time_ns"|"timestamp_ns",
         "model", "backend", "ms"|"latency_ms",
         "boxes": [{"bbox"|"xywh"|"xyxy", "class"|"label"|"name",
                    "score"|"conf", "class_id"?, "track_id"?}]}
    """
    if not isinstance(raw, dict):
        raise ValueError("model output must be a JSON object")
    if "detections" in raw and "frame_id" in raw:
        return parse_result(raw)
    boxes = raw.get("boxes") if "boxes" in raw else raw.get("objects")
    if not isinstance(boxes, list):
        raise ValueError("raw output needs detections or boxes")
    detections = []
    for index, item in enumerate(boxes):
        if not isinstance(item, dict):
            raise ValueError(f"boxes[{index}] must be an object")
        if "xyxy" in item:
            x1, y1, x2, y2 = (float(part) for part in item["xyxy"])
            bbox = [x1, y1, x2 - x1, y2 - y1]
        elif "xywh" in item:
            bbox = [float(part) for part in item["xywh"]]
        elif "bbox" in item:
            bbox = [float(part) for part in item["bbox"]]
        else:
            raise ValueError(f"boxes[{index}] needs bbox, xywh, or xyxy")
        score = item.get("score", item.get("conf"))
        det: dict[str, Any] = {
            "bbox": bbox,
            "class": str(item.get("class") or item.get("label") or item.get("name") or "object"),
            "score": float(score),
        }
        if "class_id" in item and item["class_id"] is not None:
            det["class_id"] = int(item["class_id"])
        if "track_id" in item and item["track_id"] is not None:
            det["track_id"] = item["track_id"]
        detections.append(det)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "frame_id": int(raw["frame_id"]),
        "width": int(raw["width"]),
        "height": int(raw["height"]),
        "model": str(raw.get("model") or "board-model"),
        "backend": str(raw.get("backend") or "board"),
        "detections": detections,
    }
    stamp = raw.get("timestamp_ns", raw.get("time_ns"))
    if stamp is not None:
        payload["timestamp_ns"] = int(stamp)
    latency = raw.get("latency_ms", raw.get("ms"))
    if latency is not None:
        payload["latency_ms"] = float(latency)
    if raw.get("coord") in ("pixel", "norm"):
        payload["coord"] = raw["coord"]
    return parse_result(payload)


def detections_from_frame(meta: dict[str, Any], png: bytes) -> dict[str, Any]:
    """Replace this with the board runtime.

    ``png`` is the preview frame (so you can run the model on the same pixels
    the desktop shows). Return a protocol object that echoes ``meta["frame_id"]``.
    The default sends no boxes. ``model`` is ``not-configured`` on purpose:
    the desktop then says the channel is up and no model is attached.
    """
    del png  # the stub does not look at pixels
    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    return {
        "schema": SCHEMA,
        "frame_id": int(meta["frame_id"]),
        "timestamp_ns": int(meta.get("timestamp_ns") or 0),
        "width": width,
        "height": height,
        "model": "not-configured",
        "backend": "board-infer-push",
        "latency_ms": 0,
        "detections": [],
    }


def result_for_envelope(meta: dict[str, Any], png: bytes,
                        detect: DetectFn = detections_from_frame) -> dict[str, Any]:
    """Build the object that should be posted for one envelope frame."""
    width, height = png_size(png)
    header = dict(meta)
    if width and height:
        header.setdefault("width", width)
        header.setdefault("height", height)
    return adapt(detect(header, png))


def _token(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if len(text) < 32:
        raise ValueError("token file must contain at least 32 characters")
    return text


def push_stdin(url: str, token: str) -> int:
    count = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        post_result(url, token, adapt(json.loads(line)))
        count += 1
    return count


def push_envelope(url: str, token: str, detect: DetectFn = detections_from_frame) -> None:
    request = Request(url.rstrip("/") + "/live/envelope",
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=10) as stream:
        while True:
            meta, png = read_envelope(stream)
            post_result(url, token, result_for_envelope(meta, png, detect))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--envelope", action="store_true",
                        help="read /live/envelope and post detections_from_frame")
    parser.add_argument("--check", action="store_true",
                        help="adapt a built-in raw sample and print it, no network")
    args = parser.parse_args(argv)
    if args.check:
        sample = {
            "frame_id": 1, "width": 640, "height": 480, "time_ns": 10,
            "model": "example", "backend": "board", "ms": 8.5,
            "boxes": [{"xyxy": [10, 20, 110, 80], "label": "car", "conf": 0.91,
                       "class_id": 2, "track_id": 7}],
        }
        json.dump(adapt(sample), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    if args.token_file is None:
        raise SystemExit("--token-file is required")
    token = _token(args.token_file)
    if args.envelope:
        push_envelope(args.url, token)
    else:
        push_stdin(args.url, token)


if __name__ == "__main__":
    main()
