"""Exposure policy, brightness rejection, and the four dataset gates."""

import struct
import zlib
from pathlib import Path
from unittest.mock import patch
import unittest

from capture_studio.board_agent import AgentState
from capture_studio.core import CaptureOptions
from capture_studio.gates import (combine_gates, format_gates, gray_from_png, guard_long_capture,
                                  judge_luminance, _result)
from capture_studio.native_source import effective_exposure, native_argv
from test_capture import scratch


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class GateTests(unittest.TestCase):
    def test_near_black_flat_and_visible_frames(self) -> None:
        dark = judge_luminance(bytes([1, 2, 1, 3]) * 16)
        self.assertFalse(dark["passed"])
        self.assertEqual("画面过暗", dark["reason"])
        self.assertFalse(judge_luminance(bytes([250]) * 64)["passed"])
        self.assertEqual("画面细节不足", judge_luminance(bytes([120]) * 64)["reason"])
        visible = judge_luminance(bytes(range(32, 220)))
        self.assertTrue(visible["passed"])

    def test_png_uses_rec601_luminance(self) -> None:
        gray = gray_from_png(_png(2, 1, [bytes([0, 0, 0, 255, 255, 255])]))
        self.assertEqual(0, gray[0])
        self.assertEqual(255, gray[1])

    def test_dataset_ready_requires_all_four_gates(self) -> None:
        gates = combine_gates(_result("pass", "完整"), _result("pending", "未满 10 分钟"),
                              _result("pass", "画面可用"), _result("pass", "已恢复"))
        self.assertFalse(gates["dataset_ready"])
        self.assertIn("帧率未测", format_gates(gates))
        self.assertIn("不可入库", format_gates(gates))
        ready = combine_gates(_result("pass", "a"), _result("pass", "b"),
                              _result("pass", "c"), _result("pass", "d"))
        self.assertTrue(ready["dataset_ready"])
        self.assertIn("可入库", format_gates(ready))

    def test_auto_and_shutter_share_one_argument_list(self) -> None:
        common = dict(device="/dev/video0", width=640, height=480, fps=30,
                      source_format="mjpeg", codec="copy")
        auto = native_argv(Path("native_capture"), CaptureOptions(**common, exposure_mode=0),
                           Path("report.json"))
        self.assertEqual("0", auto[auto.index("--exposure-mode") + 1])
        shutter = native_argv(Path("native_capture"),
                              CaptureOptions(**common, exposure_mode=2, exposure_absolute=100),
                              Path("report.json"))
        self.assertEqual(["2", "100"], [shutter[shutter.index("--exposure-mode") + 1],
                                         shutter[shutter.index("--manual-exposure") + 1]])
        self.assertEqual(0, effective_exposure(CaptureOptions(**common)).exposure_mode)

    def test_dark_preflight_does_not_create_a_session(self) -> None:
        with scratch() as directory:
            state = AgentState(Path(directory), "a" * 32)
            payload = CaptureOptions("/dev/video0", width=640, height=480, fps=30,
                                     source_format="mjpeg", codec="copy", exposure_mode=2,
                                     exposure_absolute=100).__dict__
            with patch("capture_studio.native_source.uses_native", return_value=True), \
                    patch("capture_studio.gates.preflight_native",
                          side_effect=ValueError("画面未通过")), \
                    patch.object(Path, "is_char_device", return_value=True), \
                    patch("capture_studio.board_agent.shutil.which", return_value="gst"):
                with self.assertRaises(ValueError):
                    state.start(payload)
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_slow_preflight_cancels_only_the_long_capture(self) -> None:
        slow = {"source_fps": 26.1}
        with self.assertRaises(ValueError):
            guard_long_capture(650, slow)
        guard_long_capture(60, slow)
        guard_long_capture(650, {"source_fps": 29.5})
        guard_long_capture(None, slow)

    def test_absolute_exposure_is_rejected_for_auto(self) -> None:
        with self.assertRaises(ValueError):
            CaptureOptions("/dev/video0", source_format="mjpeg", codec="copy",
                           exposure_mode=0, exposure_absolute=100).validate("kv260_usb")
