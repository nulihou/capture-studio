"""Offscreen checks for the model demo page. Boxes are protocol data, not a detector."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QSlider  # noqa: E402

from capture_studio import i18n, motion  # noqa: E402
from capture_studio.inference import demo_overlay, load_jsonl  # noqa: E402
from capture_studio.model_demo import ModelDemoPage, badge_copy  # noqa: E402

APP = QApplication.instance() or QApplication([])


class PageTests(unittest.TestCase):
    def setUp(self):
        motion.set_reduced(True)
        self.page = ModelDemoPage()
        self.page.resize(1280, 720)
        self.page.show()
        APP.processEvents()

    def tearDown(self):
        self.page.shutdown()
        self.page.close()
        motion.set_reduced(None)
        i18n.LANG = "zh"
        APP.processEvents()

    def test_synthetic_demo_is_labeled_and_draws_boxes(self):
        self.page.set_active(True)
        self.page.step(frame_id=12, now=10.0)
        self.page.step(frame_id=13, now=10.05)
        self.assertEqual(self.page.kind, "demo")
        self.assertEqual(badge_copy(self.page.kind)[0], "演示数据")
        self.assertIn("不是识别", badge_copy(self.page.kind)[1])
        self.assertTrue(self.page.state.result["preview_only"])
        self.assertFalse(self.page.state.image.isNull())
        self.assertGreaterEqual(len(self.page.visible_detections()), 4)
        self.assertEqual(self.page.zoom_detection()["class"], "bird")
        self.page.set_min_score(0.95)
        self.assertEqual(self.page.visible_detections(), [])
        self.page.set_min_score(0.2)
        self.page.set_class_enabled("car", False)
        self.assertNotIn("car", {row["class"] for row in self.page.visible_detections()})

    def test_record_and_replay_stay_marked(self):
        self.page.step(frame_id=0, now=1.0)
        self.page.step(frame_id=1, now=1.1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            self.page.start_recording(path)
            self.page.step(frame_id=2, now=2.0)
            self.page.step(frame_id=3, now=2.1)
            count = self.page.stop_recording()
            self.assertEqual(count, 2)
            rows = load_jsonl(path)
            self.assertTrue(all(row["preview_only"] for row in rows))
            self.page.load_replay(path)
            self.assertIn(self.page.kind, ("replay", "replay_demo"))
            self.assertIn("回放", badge_copy(self.page.kind)[0])
            self.assertTrue(self.page.visible_detections())

    def test_board_frame_is_not_relabeled_as_demo(self):
        image = QImage(64, 48, QImage.Format.Format_RGB32)
        image.fill(0x112233)
        result = demo_overlay(4, 64, 48)
        result.pop("preview_only")
        result["model"] = "yolov8n"
        result["backend"] = "ascend"
        self.page.show_board_frame(image, result, {"temp_max": 51.0, "cpu": 22.0,
                                                   "mem_used": 1024, "mem_total": 4096})
        self.assertEqual(self.page.kind, "board")
        self.assertEqual(self.page.health_rows["temp"].text(), "51 °C")
        self.assertEqual(self.page.health_rows["cpu"].text(), "22%")
        self.assertIn("car", {row["class"] for row in self.page.visible_detections()})
        self.page.show_board_frame(image, {"schema": "capture-studio.inference.v1", "frame_id": 1,
                                           "width": 64, "height": 48, "model": "not-configured",
                                           "backend": "board-infer-push", "latency_ms": 0,
                                           "detections": []}, None, connected=True)
        # show_board_frame does not re-parse; model is read as given.
        self.assertEqual(self.page.kind, "unconfigured")
        self.page.show_board_frame(image, None, None, connected=False)
        self.assertEqual(self.page.kind, "offline")

    def test_pin_smallest_box_and_fullscreen_hides_controls(self):
        self.page.step(frame_id=6, now=3.0)
        bird = next(row for row in self.page.visible_detections() if row["class"] == "bird")
        x, y, w, h = bird["bbox"]
        self.page.pin_at_image(x + w / 2, y + h / 2)
        self.assertEqual(self.page.zoom_detection()["track_id"], bird["track_id"])
        self.page.set_presentation(title="港口小目标", customer="北港", logo_pos="右上")
        self.assertEqual(self.page.state.title, "港口小目标")
        self.assertEqual(self.page.state.logo_pos, "右上")
        self.page.open_showcase()
        APP.processEvents()
        self.assertTrue(self.page.showcase_open())
        self.assertEqual(self.page._showcase.findChildren(QSlider), [])
        self.assertTrue(self.page.operator.isVisible())

    def test_fps_survives_a_backwards_clock(self):
        self.page.step(frame_id=1, now=5000.0)
        self.page.step(frame_id=2, now=5000.04)
        self.assertGreater(self.page.fps_value, 10)
        self.page.step(frame_id=3, now=1.0)
        self.page.step(frame_id=4, now=1.05)
        self.assertGreater(self.page.fps_value, 10)
        self.assertLess(self.page.fps_value, 40)
        self.assertEqual(self.page.health_caption.text(), "示意读数，不是板端")

    def test_english_chrome(self):
        i18n.LANG = "en"
        page = ModelDemoPage()
        try:
            self.assertEqual(page.source_buttons["synthetic"].text(), "Synthetic")
            self.assertEqual(page.source_buttons["board"].text(), "Board")
            self.assertEqual(badge_copy("demo"), ("Demo data", "Scripted boxes, not recognition"))
            self.assertEqual(badge_copy("board")[0], "On-board live")
        finally:
            page.shutdown()
            page.close()


class WindowHookTests(unittest.TestCase):
    def setUp(self):
        from capture_studio import window as window_module
        self.window_module = window_module
        studio = window_module.STUDIO
        self._save = studio._save
        studio._save = lambda *args, **kwargs: None
        self.win = window_module.StudioWindow()
        self.win.timer.stop()
        self.win.resize(1280, 800)
        self.win.show()
        APP.processEvents()

    def tearDown(self):
        self.win.demo_page.shutdown()
        self.win.timer.stop()
        self.win.close()
        self.window_module.STUDIO._save = self._save
        APP.processEvents()

    def test_nav_page_and_existing_pages(self):
        self.assertIn("demo", self.win.page_buttons)
        self.assertFalse(self.win.page_buttons["demo"].icon().isNull())
        self.win.show_page("demo")
        APP.processEvents()
        self.assertEqual(self.win.current_page, "demo")
        self.assertEqual(self.win.canvas_stack.currentWidget(), self.win.demo_page)
        self.assertFalse(self.win.duration_bar.isVisible())
        self.assertGreater(len(self.win.demo_page.visible_detections()), 0)
        self.win.open_large()
        APP.processEvents()
        self.assertTrue(self.win.demo_page.showcase_open())
        self.assertIsNone(self.win.large)
        self.win.open_large()
        self.assertFalse(self.win.demo_page.showcase_open())
        for name in ("lab", "pc", "board", "periph", "sessions", "settings"):
            self.win.show_page(name)
            APP.processEvents()
            self.assertEqual(self.win.current_page, name)
            self.assertEqual(self.win.canvas_stack.currentWidget(), self.win.workspace)
        self.win.resize(1280, 800)
        self.win.show_page("settings")
        APP.processEvents()
        self.assertEqual(self.win.side_scroll.verticalScrollBar().maximum(), 0)
        self.win.open_large()
        APP.processEvents()
        self.assertIsNotNone(self.win.large)
        self.assertTrue(self.win.large.isVisible())
