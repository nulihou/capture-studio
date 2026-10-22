"""Inference protocol, alignment, and the board-agent result channel.

No model runtime is involved. The desktop and these tests only parse and route JSON.
"""
import io
import json
import re
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from capture_studio.board_agent import AgentState, make_handler
from capture_studio.board_infer_push import adapt, detections_from_frame, result_for_envelope
from capture_studio.inference import (SCHEMA, align_result, class_counts, demo_overlay, load_jsonl,
                                      parse_result, png_size, read_envelope, read_jsonl, result_line,
                                      visible_detections, write_envelope)
from capture_studio.desktop import BoardClient
from capture_studio.tests.test_capture import scratch


ROOT = Path(__file__).resolve().parents[1]
BANNED = ("torch", "onnxruntime", "ultralytics", "openvino", "tensorrt")


def _png(width: int = 4, height: int = 2) -> bytes:
    # A valid signature plus a fake IHDR is enough for png_size and the envelope framer.
    # read_png needs a real chunk stream, so build a minimal PNG with an IEND only after IHDR.
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class ProtocolTests(unittest.TestCase):
    def test_pixel_result_round_trip(self):
        raw = {
            "schema": SCHEMA, "frame_id": 3, "timestamp_ns": 99, "width": 640, "height": 480,
            "model": "yolo", "backend": "kv260-dpu", "latency_ms": 12.5,
            "detections": [{"bbox": [1, 2, 30, 40], "class": "car", "class_id": 2, "score": 0.5, "track_id": 7}],
        }
        parsed = parse_result(raw)
        self.assertEqual(parsed["detections"][0]["bbox"], [1, 2, 30, 40])
        self.assertEqual(parsed["backend"], "kv260-dpu")
        again = parse_result(json.loads(result_line(parsed)))
        self.assertEqual(again["frame_id"], 3)
        hinted = parse_result({**raw, "preview_only": True, "infer_fps": 30})
        self.assertEqual(hinted["infer_fps"], 30.0)
        self.assertNotIn("infer_fps", parsed)

    def test_norm_boxes_become_pixels(self):
        parsed = parse_result({
            "frame_id": 1, "width": 200, "height": 100, "coord": "norm",
            "detections": [{"bbox": [0.1, 0.2, 0.5, 0.4], "class": "bird", "score": 1}],
        })
        self.assertEqual(parsed["detections"][0]["bbox"], [20.0, 20.0, 100.0, 40.0])

    def test_rejects_bad_shapes(self):
        base = {"frame_id": 1, "width": 10, "height": 10, "detections": []}
        for broken in (
            {"schema": "other", **base},
            {**base, "frame_id": -1},
            {**base, "frame_id": True},
            {**base, "detections": [{"bbox": [0, 0, 1], "class": "a", "score": 0.2}]},
            {**base, "detections": [{"bbox": [0, 0, 1, 1], "class": "a", "score": 1.2}]},
            {**base, "width": 0},
        ):
            with self.assertRaises(ValueError):
                parse_result(broken)

    def test_align_prefers_frame_id_then_lag_then_time(self):
        rows = [
            parse_result({"frame_id": 4, "timestamp_ns": 1_000, "width": 8, "height": 8, "detections": []}),
            parse_result({"frame_id": 8, "timestamp_ns": 5_000, "width": 8, "height": 8, "detections": []}),
        ]
        found, how = align_result(rows, frame_id=8, timestamp_ns=1_000)
        self.assertEqual(how, "frame_id")
        self.assertEqual(found["frame_id"], 8)
        found, how = align_result(rows, frame_id=10)
        self.assertEqual((how, found["frame_id"]), ("lag", 8))
        found, how = align_result(rows, frame_id=40, timestamp_ns=1_000, window_ns=50)
        self.assertEqual((how, found["frame_id"]), ("timestamp", 4))
        found, how = align_result(rows, frame_id=40, timestamp_ns=9_000_000_000)
        self.assertEqual((found, how), (None, "none"))

    def test_filter_counts_and_jsonl(self):
        result = demo_overlay(0, 320, 240)
        self.assertTrue(result["preview_only"])
        self.assertNotIn("image", demo_overlay.__code__.co_varnames)
        visible = visible_detections(result, 0.95)
        self.assertLess(len(visible), len(result["detections"]))
        hidden = visible_detections(result, 0.0, disabled=["car"])
        self.assertNotIn("car", class_counts(hidden))
        text = "\n".join(result_line(demo_overlay(i, 64, 48)) for i in range(3)) + "\n"
        self.assertEqual([row["frame_id"] for row in read_jsonl(text)], [0, 1, 2])
        with self.assertRaises(ValueError):
            read_jsonl("{}\n")

    def test_envelope_and_png_size(self):
        png = _png(6, 5)
        self.assertEqual(png_size(png), (6, 5))
        stream = io.BytesIO()
        write_envelope(stream, {"frame_id": 2, "timestamp_ns": 8, "width": 6, "height": 5}, png)
        stream.seek(0)
        meta, body = read_envelope(stream)
        self.assertEqual(meta["frame_id"], 2)
        self.assertEqual(body, png)

    def test_no_model_runtime_imported(self):
        pattern = re.compile(r"^\s*(?:import|from)\s+(" + "|".join(BANNED) + r")\b", re.M)
        for path in ROOT.rglob("*.py"):
            if "dist" in path.parts or "build_tmp" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(text), path)


class BoardChannelTests(unittest.TestCase):
    def test_post_and_align_on_the_agent(self):
        with scratch() as board_dir:
            state = AgentState(Path(board_dir), "b" * 32)

            class Live:
                def latest(self):
                    return _png(8, 4)

                def telemetry(self):
                    return {"frame_id": 5, "timestamp_ns": 50, "source_fps": 30, "preview_fps": 30}

            state.live = Live()
            state.submit_inference(demo_overlay(5, 8, 4))
            state.submit_inference(demo_overlay(2, 8, 4))
            view = state.inference_view()
            self.assertEqual(view["aligned"], "frame_id")
            self.assertEqual(view["result"]["frame_id"], 5)
            self.assertEqual(view["preview"]["frame_id"], 5)
            lagged = state.inference_view(frame_id=4)
            self.assertEqual(lagged["result"]["frame_id"], 2)

    def test_http_infer_requires_the_token(self):
        with scratch() as board_dir:
            state = AgentState(Path(board_dir), "c" * 32)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(url + "/infer", data=b"{}", method="POST"), timeout=3)
                self.assertEqual(401, caught.exception.code)
                client = BoardClient(url, "c" * 32)
                accepted = client.request("POST", "/infer", demo_overlay(1, 32, 32))
                self.assertTrue(accepted["accepted"])
                # No preview yet, so the live alignment does not invent a match.
                self.assertIsNone(client.request("GET", "/infer")["result"])
                matched = client.request("GET", "/infer?frame_id=1")
                self.assertEqual(matched["result"]["frame_id"], 1)
                with self.assertRaises(RuntimeError):
                    client.request("POST", "/infer", {
                        "frame_id": 1, "width": 8, "height": 8,
                        "detections": [{"bbox": [0, 0, 1, 1], "class": "a", "score": 2}],
                    })
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_sender_adapts_raw_boxes_and_stub_is_not_a_detector(self):
        parsed = adapt({
            "frame_id": 1, "width": 640, "height": 480, "time_ns": 10, "ms": 8.5,
            "model": "example", "backend": "rk3588-rknn",
            "boxes": [{"xyxy": [10, 20, 110, 80], "label": "car", "conf": 0.91, "class_id": 2, "track_id": 7}],
        })
        self.assertEqual(parsed["detections"][0]["bbox"], [10.0, 20.0, 100.0, 60.0])
        self.assertEqual(parsed["backend"], "rk3588-rknn")
        png = _png(16, 8)
        stub = result_for_envelope({"frame_id": 3, "timestamp_ns": 9}, png, detections_from_frame)
        self.assertEqual(stub["model"], "not-configured")
        self.assertEqual(stub["detections"], [])
        self.assertEqual(stub["frame_id"], 3)
        path = Path(self.id().replace(".", "_") + ".jsonl")
        try:
            path.write_text(result_line(parsed) + "\n", encoding="utf-8")
            self.assertEqual(load_jsonl(path)[0]["frame_id"], 1)
        finally:
            path.unlink(missing_ok=True)
