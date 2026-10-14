"""v9 fixes: template output, playback counter, thermal limits, size estimate, launcher package, camera choice."""
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from capture_studio import board_probe, camera_pick, health, i18n, session_review, templates

PKG_DIR = Path(templates.__file__).resolve().parent


class TemplateOutputTests(unittest.TestCase):
    def test_dated_folder_is_stripped_before_naming(self):
        now = datetime(2026, 10, 15, 8, 0)
        stuck = {"output": str(Path("D:/data/20261014_lab_A"))}
        payload = templates.apply(stuck, {"scene": "night"}, now)
        self.assertEqual(Path(payload["output"]), Path("D:/data/20261015_night"))

    def test_saved_template_never_keeps_an_old_date(self):
        tpl = templates.capture({"output": "captures/20261001_x", "width": "640"}, "y")
        self.assertEqual(Path(tpl["output"]), Path("captures"))
        self.assertEqual(templates.base_output("20261001_x"), "captures")
        self.assertEqual(templates.base_output("D:/data"), str(Path("D:/data")))

    def test_run_template_records_once_without_overwriting_base(self):
        from capture_studio.product import Studio
        studio = Studio.__new__(Studio)
        import threading
        studio.lock = threading.Lock()
        studio.settings = {"output": "captures"}
        studio.logs = []
        studio._log = lambda text: None
        folder = Path(tempfile.mkdtemp())
        studio.templates_path = lambda: folder / "t.json"
        templates.save(folder / "t.json", "a", {"scene": "s", "width": "640"})
        seen = []
        studio.start_record = lambda payload, mode: seen.append(dict(payload))
        studio.run_template("a", "pc")
        self.assertIn("_output_once", seen[0])
        self.assertNotIn("output", seen[0])
        self.assertEqual(studio.settings["output"], "captures")


class PlaybackTests(unittest.TestCase):
    def test_counter_wraps_and_shows_time(self):
        from capture_studio.v7_ui import playback_label
        self.assertEqual(playback_label(0, 10), "回放 · 1/10 · 0:00 / 0:02")
        self.assertEqual(playback_label(9, 10), "回放 · 10/10 · 0:01 / 0:02")


class ThermalTests(unittest.TestCase):
    def test_board_trip_points_win(self):
        trips = board_probe.parse_trips("cpu-thermal:passive:85000\ncpu-thermal:critical:105000\nx:bogus:abc")
        self.assertEqual(trips, [("cpu-thermal", "passive", 85.0), ("cpu-thermal", "critical", 105.0)])
        warn, fail, source = health.temp_limits({"family": "raspberrypi", "thermal_trips": trips})
        self.assertEqual((warn, fail), (85.0, 105.0))
        self.assertIn("内核温控点", source)

    def test_documented_and_generic(self):
        self.assertEqual(health.temp_limits({"family": "raspberrypi"})[:2], (80.0, 85.0))
        self.assertEqual(health.temp_limits({"family": "kv260"})[:2], (90.0, 100.0))
        warn, fail, source = health.temp_limits({"family": "jetson"})
        self.assertEqual((warn, fail), (80.0, 90.0))
        self.assertIn("通用", source)

    def test_check_uses_board_limits(self):
        items = health.check({}, "board", 1e12, {"temp_max": 87.0}, board_info={"family": "raspberrypi"})
        self.assertTrue(any(i["title"] == "开发板过热" for i in items))
        items = health.check({}, "board", 1e12, {"temp_max": 87.0}, board_info={"family": "kv260"})
        self.assertTrue(any(i["title"] == "开发板温度" for i in items))


class SizeEstimateTests(unittest.TestCase):
    def test_raw_is_exact_math(self):
        est = health.estimate({"width": 640, "height": 480, "fps": 30, "format": "raw", "codec": "copy"}, "pc")
        self.assertEqual(est["basis"], "exact")
        self.assertEqual(est["bytes_per_s"], 640 * 480 * 2 * 30)

    def test_board_raw_uses_h264_bitrate(self):
        est = health.estimate({"format": "raw", "bitrate": 8000}, "board")
        self.assertEqual(est["basis"], "bitrate")
        self.assertEqual(est["bytes_per_s"], 1_000_000)

    def test_mjpeg_measured_from_history_else_upper_bound(self):
        history = [{"width": 640, "height": 480, "fps": 30, "frames": 300, "size": 640 * 480 * 300 * 0.2,
                    "format": "mjpeg", "codec": "copy"},
                   {"width": 640, "height": 480, "fps": 30, "frames": 300, "size": 10**9, "format": "raw", "codec": "copy"}]
        est = health.estimate({"width": 1280, "height": 720, "fps": 30, "format": "mjpeg"}, "board", history)
        self.assertEqual(est["basis"], "measured")
        self.assertAlmostEqual(est["bytes_per_s"], 1280 * 720 * 30 * 0.2)
        self.assertEqual(health.estimate({"format": "mjpeg"}, "board")["basis"], "upper")

    def test_usb_check_uses_source_rate_not_stored_rate(self):
        items = health.check({"width": 1920, "height": 1080, "fps": 30, "format": "raw", "bitrate": 8000}, "board",
                             1e12, {}, "UVC · USB 2.0")
        self.assertTrue(any(i["title"] == "USB 带宽不够" for i in items))

    def test_summary_carries_codec(self):
        folder = Path(tempfile.mkdtemp()) / "20261014T000000Z_0123abcd"
        folder.mkdir()
        (folder / "session.json").write_text('{"options": {"codec": "ffv1", "format": "mjpeg"}}', encoding="utf-8")
        self.assertEqual(session_review.summarize(folder)["codec"], "ffv1")


class LauncherTests(unittest.TestCase):
    def test_no_hardcoded_package_on_pc_side(self):
        for name in ("launcher.py", "connect_kv260.py", "build_portable.py"):
            text = (PKG_DIR / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"^\s*from capture_studio\.", text, re.M), name)
            self.assertNotIn('"--hidden-import", "capture_studio.', text)
        cmd = (PKG_DIR / "Start-KV260-CaptureStudio.cmd").read_text(encoding="utf-8")
        self.assertIn("%PKG%", cmd)
        self.assertNotIn("python -m capture_studio", cmd)

    def test_launcher_starts_qt_window(self):
        text = (PKG_DIR / "launcher.py").read_text(encoding="utf-8")
        self.assertIn('_mod("window").main()', text)
        self.assertNotIn("CaptureDesktop", text)


class CameraPickTests(unittest.TestCase):
    CAMS = [{"name": "USB Camera", "value": "@a", "vid": "1c45", "pid": "6200"},
            {"name": "USB Camera", "value": "@b", "vid": "046d", "pid": "0825"},
            {"name": "OBS Virtual Camera", "value": "OBS Virtual Camera", "vid": "", "pid": ""}]

    def test_order(self):
        self.assertEqual(camera_pick.pick_camera(self.CAMS, "@b", ""), ("@b", "last"))
        self.assertEqual(camera_pick.pick_camera(self.CAMS, "@gone", "046d:0825"), ("@b", "vidpid"))
        self.assertEqual(camera_pick.pick_camera(self.CAMS[1:], "", ""), ("@b", "sole_uvc"))
        self.assertEqual(camera_pick.pick_camera(self.CAMS[2:], "", ""), ("OBS Virtual Camera", "sole"))
        self.assertEqual(camera_pick.pick_camera(self.CAMS, "", ""), ("", "need_manual"))
        self.assertEqual(camera_pick.pick_camera([], "x", "y"), ("", "none"))

    def test_manual_override_remembers_vidpid(self):
        from capture_studio.product import Studio
        import threading
        studio = Studio.__new__(Studio)
        studio.lock = threading.Lock()
        studio.settings = {"pc_device": "@a", "pc_device_id": "1c45:6200"}
        studio.pc_devices = [{"label": "a", "value": "@a", "id": "1c45:6200"}, {"label": "b", "value": "@b", "id": "046d:0825"}]
        studio.pc_pick = "last"
        studio._save = lambda: None
        studio.update_settings({"pc_device": "@b"})
        self.assertEqual(studio.settings["pc_device_id"], "046d:0825")
        self.assertEqual(studio.pc_pick, "manual")


class I18nTests(unittest.TestCase):
    def test_v9_strings_have_english(self):
        cjk = re.compile(r"[\u3400-\u9fff]")
        old = i18n.LANG
        try:
            i18n.LANG = "en"
            for text in list(camera_pick.REASONS.values()) + list(health.BASIS_TEXT.values()) + [
                    health.GENERIC_LIMITS[2]] + [v[2] for v in health.DOCUMENTED_LIMITS.values()]:
                self.assertIsNone(cjk.search(i18n.tr_msg(text)), text)
            for text in ("Workspace", "Language", "Appearance"):
                self.assertIn(text, i18n.UI.values())
        finally:
            i18n.LANG = old


if __name__ == "__main__":
    unittest.main()
