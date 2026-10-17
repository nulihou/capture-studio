"""v0.12.5: PC and board keep separate capture modes; old shared settings migrate."""

import json
import tempfile
import types
import unittest
from pathlib import Path

from capture_studio import camera_modes, health, product
from capture_studio.camera_modes import apply_mode, migrate_pc_mode, mode_view, saved_mode, to_kind


class PcModeKeys(unittest.TestCase):
    def test_apply_and_read_are_separate(self):
        settings = {"width": "1920", "height": "1080", "fps": "30", "format": "mjpeg"}
        migrate_pc_mode(settings, {})
        apply_mode(settings, {"width": 640, "height": 480, "fps": 15, "format": "raw"}, "pc")
        self.assertEqual(saved_mode(settings), {"width": 1920, "height": 1080, "fps": 30, "format": "mjpeg"})
        self.assertEqual(saved_mode(settings, "pc"), {"width": 640, "height": 480, "fps": 15, "format": "raw"})
        self.assertEqual(mode_view(settings, "pc_usb")["width"], "640")
        self.assertEqual(mode_view(settings, "board")["width"], "1920")

    def test_old_shared_settings_seed_pc_mode_once(self):
        settings = {"width": "1280", "height": "720", "fps": "60", "format": "mjpeg",
                    "pc_width": "", "pc_height": "", "pc_fps": "", "pc_format": ""}
        migrate_pc_mode(settings, {"width": "1280"})
        self.assertEqual(saved_mode(settings, "pc"), saved_mode(settings))
        kept = dict(settings, pc_width="800", pc_height="600")
        migrate_pc_mode(kept, {"pc_width": "800", "pc_height": "600", "pc_fps": "60", "pc_format": "mjpeg"})
        self.assertEqual(kept["pc_width"], "800")

    def test_to_kind_routes_template_mode_to_pc(self):
        current = {"width": "1920", "height": "1080", "fps": "30", "format": "mjpeg"}
        routed = to_kind({"width": "640", "height": "480", "fps": "30", "format": "raw", "codec": "ffv1"}, "pc", current)
        self.assertEqual((routed["pc_width"], routed["width"], routed["codec"]), ("640", "1920", "ffv1"))
        self.assertEqual(to_kind({"width": "640"}, "board", current)["width"], "640")

    def test_health_estimate_uses_the_page_mode(self):
        settings = {"width": "1920", "height": "1080", "fps": "30", "format": "raw", "codec": "ffv1",
                    "pc_width": "320", "pc_height": "240", "pc_fps": "30", "pc_format": "raw"}
        self.assertLess(health.estimate(settings, "pc")["bytes_per_s"], health.estimate(settings, "board")["bytes_per_s"])

    def test_studio_load_migrates_pre_0125_settings_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "studio_settings.json"
            path.write_text(json.dumps({"width": "1280", "height": "720", "fps": "60", "format": "mjpeg"}), encoding="utf-8")
            loaded = product.Studio._load(types.SimpleNamespace(_settings_path=lambda: path))
        self.assertEqual((loaded["width"], loaded["pc_width"], loaded["pc_fps"]), ("1280", "1280", "60"))

    def test_capture_options_use_pc_keys(self):
        studio = product.STUDIO
        saved = dict(studio.settings)
        try:
            studio.settings.update({"width": "1920", "height": "1080", "fps": "30", "format": "mjpeg",
                                    "pc_width": "640", "pc_height": "480", "pc_fps": "30", "pc_format": "mjpeg",
                                    "pc_device": "USB Cam"})
            options = studio._options("pc_usb")
            self.assertEqual((options.width, options.height), (640, 480))
        finally:
            studio.settings.clear()
            studio.settings.update(saved)


if __name__ == "__main__":
    unittest.main()
