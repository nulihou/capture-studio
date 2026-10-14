"""Parsers and defaults for capture-mode detection (v6). Pure CPU, no camera needed."""
import unittest

from capture_studio.camera_lab import parse_v4l2_formats, query_v4l2_formats
from capture_studio.camera_modes import (PRESETS, apply_mode, choose_mode, mode_label, parse_dshow_options,
                                         saved_mode, sort_modes)
from capture_studio.desktop import parse_dshow_devices
from capture_studio.textcodec import safe_decode

V4L2_NEW = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\t\tInterval: Discrete 0.040s (25.000 fps)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.017s (60.000 fps)
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t[1]: 'YUYV' (YUYV 4:2:2)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.200s (5.000 fps)
\t[2]: 'H264' (H.264, compressed)
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.033s (30.000 fps)
"""

V4L2_OLD = """ioctl: VIDIOC_ENUM_FMT
\tIndex       : 0
\tType        : Video Capture
\tPixel Format: 'YUYV'
\tName        : YUYV 4:2:2
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\tSize: Stepwise 16x16 - 1920x1080 with step 1/1
"""

DSHOW_OPTIONS = """[dshow @ 000001] DirectShow video device options (from video devices)
[dshow @ 000001]  Pin "捕获" (alternative pin name "0")
[dshow @ 000001]   vcodec=mjpeg  min s=1920x1080 fps=5 max s=1920x1080 fps=30
[dshow @ 000001]   vcodec=mjpeg  min s=1280x720 fps=5 max s=1280x720 fps=60.0002
[dshow @ 000001]   pixel_format=yuyv422  min s=640x480 fps=5 max s=640x480 fps=30 (tv, bt470bg/bt709/unknown, topleft)
[dshow @ 000001]   pixel_format=nv12  min s=640x480 fps=5 max s=640x480 fps=30
video=USB 摄像头: Immediate exit requested
"""


class V4l2FormatTests(unittest.TestCase):
    def test_new_style_keeps_known_formats_and_rounds_fps(self) -> None:
        modes = parse_v4l2_formats(V4L2_NEW)
        self.assertIn({"width": 1920, "height": 1080, "fps": 30, "format": "mjpeg"}, modes)
        self.assertIn({"width": 1280, "height": 720, "fps": 60, "format": "mjpeg"}, modes)
        self.assertIn({"width": 640, "height": 480, "fps": 30, "format": "raw"}, modes)
        self.assertFalse(any(m["fps"] == 30 and m["format"] not in ("mjpeg", "raw") for m in modes))
        self.assertEqual(6, len(modes))  # H264 skipped, nothing duplicated

    def test_old_style_and_stepwise_is_not_guessed(self) -> None:
        self.assertEqual([{"width": 640, "height": 480, "fps": 30, "format": "raw"}],
                         parse_v4l2_formats(V4L2_OLD))

    def test_garbage_and_empty(self) -> None:
        self.assertEqual([], parse_v4l2_formats(""))
        self.assertEqual([], parse_v4l2_formats("VIDIOC_ENUM_FMT: Inappropriate ioctl"))

    def test_query_uses_runner_and_validates_device(self) -> None:
        seen = []
        result = query_v4l2_formats("/dev/video0", lambda argv: (seen.append(argv), V4L2_NEW)[1])
        self.assertEqual(["v4l2-ctl", "-d", "/dev/video0", "--list-formats-ext"], seen[0])
        self.assertTrue(result["modes"])
        with self.assertRaises(ValueError):
            query_v4l2_formats("/dev/../etc/passwd", lambda argv: "")


class DshowTests(unittest.TestCase):
    def test_options_parse_uses_max_size_and_fps(self) -> None:
        modes = parse_dshow_options(DSHOW_OPTIONS)
        self.assertEqual([
            {"width": 1920, "height": 1080, "fps": 30, "format": "mjpeg"},
            {"width": 1280, "height": 720, "fps": 60, "format": "mjpeg"},
            {"width": 640, "height": 480, "fps": 30, "format": "raw"},
        ], modes)

    def test_gbk_bytes_with_chinese_device_names_decode_cleanly(self) -> None:
        raw = ('[dshow @ 0000] DirectShow video devices\n'
               '[dshow @ 0000]  "USB 高清摄像头" (video)\n'
               '[dshow @ 0000]   vcodec=mjpeg  min s=1280x720 fps=5 max s=1280x720 fps=30\n').encode("gbk")
        text = safe_decode(raw)
        self.assertNotIn("\ufffd", text)
        self.assertEqual(["USB 高清摄像头"], parse_dshow_devices(text))
        self.assertEqual([{"width": 1280, "height": 720, "fps": 30, "format": "mjpeg"}], parse_dshow_options(text))

    def test_utf8_bytes_also_decode(self) -> None:
        raw = '[dshow @ 0] "罗技 C920" (video)\n'.encode("utf-8")
        self.assertEqual(["罗技 C920"], parse_dshow_devices(safe_decode(raw)))


class DefaultTests(unittest.TestCase):
    modes = parse_v4l2_formats(V4L2_NEW)

    def test_saved_mode_is_kept_when_supported(self) -> None:
        saved = {"width": 640, "height": 480, "fps": 30, "format": "raw"}
        self.assertEqual(saved, choose_mode(self.modes, saved))

    def test_default_is_largest_at_30fps_preferring_mjpeg(self) -> None:
        self.assertEqual({"width": 1920, "height": 1080, "fps": 30, "format": "mjpeg"},
                         choose_mode(self.modes, {"width": 3840, "height": 2160, "fps": 30, "format": "mjpeg"}))

    def test_slow_only_camera_still_gets_a_mode(self) -> None:
        slow = [{"width": 1920, "height": 1080, "fps": 5, "format": "raw"}]
        self.assertEqual(slow[0], choose_mode(slow, None))
        self.assertIsNone(choose_mode([], None))

    def test_sort_and_label(self) -> None:
        ordered = sort_modes(self.modes)
        self.assertEqual("mjpeg", ordered[0]["format"])
        self.assertEqual("1920×1080 · 30 fps · MJPEG", mode_label(ordered[0]))

    def test_settings_round_trip_keeps_old_format(self) -> None:
        settings = {"width": "640", "height": "480", "fps": "30", "format": "mjpeg", "preset": "看清画面"}
        apply_mode(settings, {"width": 1280, "height": 720, "fps": 60, "format": "mjpeg"})
        self.assertEqual({"width": "1280", "height": "720", "fps": "60", "format": "mjpeg", "preset": "看清画面"}, settings)
        self.assertEqual({"width": 1280, "height": 720, "fps": 60, "format": "mjpeg"}, saved_mode(settings))
        self.assertIsNone(saved_mode({"width": "", "height": "480", "fps": "30"}))

    def test_presets_cover_common_sizes(self) -> None:
        sizes = {(m["width"], m["height"]) for m in PRESETS}
        self.assertTrue({(640, 480), (1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)} <= sizes)


if __name__ == "__main__":
    unittest.main()
