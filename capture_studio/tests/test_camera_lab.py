import unittest

from capture_studio.camera_lab import (arrival_message, choose_camera, extra_controls_token,
                                       parse_v4l2_controls, preview_frame_size, query_v4l2_controls,
                                       read_tuning, slow_usb_warning, speed_text)
from capture_studio.core import CaptureOptions, board_gst_command
from test_capture import scratch
from pathlib import Path


SAMPLE = """
                     brightness 0x00980900 (int)    : min=0 max=255 step=1 default=128 value=128
                           gain 0x00980913 (int)    : min=0 max=100 step=1 default=0 value=4
         power_line_frequency 0x00980918 (menu)   : min=0 max=2 default=1 value=1
white_balance_temperature_auto 0x0098090c (bool)   : default=1 value=1
"""


class CameraLabTests(unittest.TestCase):
    def test_speed_and_controls_parse(self):
        self.assertEqual((640, 480), preview_frame_size(640, 480))
        self.assertEqual((1280, 720), preview_frame_size(1920, 1080))
        self.assertEqual((1280, 720), preview_frame_size(1280, 720))
        self.assertEqual("", speed_text(""))
        controls = parse_v4l2_controls(SAMPLE)
        gain = next(item for item in controls if item["name"] == "gain")
        self.assertEqual((0, 100, 4), (gain["min"], gain["max"], gain["value"]))
        self.assertEqual(1, read_tuning("power", "50 Hz", "灯光频率", 0, 2))
        self.assertIsNone(read_tuning("int", "", "增益", 0, 100))
        with self.assertRaises(ValueError):
            read_tuning("int", "200", "增益", 0, 100)

    def test_one_camera_is_chosen_and_several_are_not(self):
        only = [{"device": "/dev/video3", "serial": "CAM9", "name": "DeskCam",
                 "vid": "1111", "pid": "2222", "speed": "480"}]
        self.assertEqual("/dev/video3", choose_camera(only, "", "HHW001")[0])
        self.assertIn("CAM9", choose_camera(only, "", "HHW001")[1])
        many = [{"device": "/dev/video0", "serial": "A", "name": "A"},
                {"device": "/dev/video2", "serial": "B", "name": "B"}]
        self.assertEqual("", choose_camera(many, "", "HHW001")[0])
        self.assertEqual("/dev/video2", choose_camera(many, "", "B")[0])
        self.assertIn("插上了摄像头", arrival_message(only, many, {"model": "KV260"}))
        self.assertEqual("", arrival_message(only, only, {"model": "KV260"}))
        self.assertIn("已认出摄像头", arrival_message([], only, {"model": "KV260", "hostname": "kria"}))

    def test_requested_controls_are_one_gst_argument(self):
        plain = CaptureOptions("/dev/video0", source_format="mjpeg", codec="copy")
        with scratch() as directory:
            command = board_gst_command(plain, Path(directory))
        self.assertFalse(any(part.startswith("extra-controls=") for part in command))
        tuned = CaptureOptions("/dev/video0", source_format="mjpeg", codec="copy",
                               exposure_mode=0, gain=8, power_line_frequency=1)
        self.assertEqual(
            'extra-controls="c,exposure_auto=0,gain=8,power_line_frequency=1"',
            extra_controls_token(tuned))
        with scratch() as directory:
            recorded = board_gst_command(tuned, Path(directory))
        self.assertIn(extra_controls_token(tuned), recorded)
        self.assertIn("USB 全速口", slow_usb_warning("12", 1920, 1080))
        self.assertEqual("", slow_usb_warning("480", 1920, 1080))

    def test_missing_v4l2_ctl_is_explained(self):
        result = query_v4l2_controls("/dev/video0", runner=lambda _argv: SAMPLE)
        self.assertEqual(4, len(result["controls"]))
        with self.assertRaises(ValueError):
            query_v4l2_controls("video0")


if __name__ == "__main__":
    unittest.main()
