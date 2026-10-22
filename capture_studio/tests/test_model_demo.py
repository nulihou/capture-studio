"""Offscreen checks for the model demo page. Boxes are protocol data, not a detector."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QSlider  # noqa: E402

from capture_studio import i18n, motion  # noqa: E402
from capture_studio.inference import demo_overlay, load_jsonl  # noqa: E402
from capture_studio.model_demo import (ModelDemoPage, _box_stroke, _readable_box, badge_copy,  # noqa: E402
                                       class_color, fit_rect, gallery_picture_rect, map_box,
                                       stage_content_rect, uniform_dest, zoom_source)

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
        self.assertGreaterEqual(len(self.page.visible_detections()), 3)
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

    def test_board_source_clears_demo_readout(self):
        self.page.step(frame_id=4, now=10.0)
        self.page.step(frame_id=5, now=10.05)
        self.assertTrue(self.page.events)
        self.assertNotEqual(self.page.readout_numbers()[1], "—")
        self.page._choose_source("board")
        self.page.step(now=20.0)
        self.page.timer.stop()
        self.page._stop_poller()
        self.assertEqual(self.page.source, "board")
        self.assertTrue(self.page.source_buttons["board"].isChecked())
        self.assertEqual(self.page.kind, "offline")
        self.assertEqual(self.page.events, [])
        self.assertEqual(self.page.fps_samples, [])
        self.assertEqual(self.page.latency_samples, [])
        self.assertEqual(self.page.class_samples, [])
        self.assertEqual(self.page.count_samples, [])
        self.assertEqual(self.page.visible_detections(), [])
        self.assertEqual(self.page.slots, {})
        self.assertEqual(self.page.readout_numbers(), ("—", "—", "—"))
        self.assertEqual(self.page.health_rows["temp"].text(), "—")
        self.assertEqual(self.page.health_rows["cpu"].text(), "—")

    def test_demo_theme_defaults_light_and_is_separate(self):
        from capture_studio import model_demo, theme
        theme.DARK_MODE = True
        try:
            model_demo.set_demo_dark(False)
            self.assertFalse(model_demo.DEMO_DARK)
            self.page.set_demo_theme(True)
            self.assertTrue(model_demo.DEMO_DARK)
            self.assertTrue(self.page.theme_buttons[True].isChecked())
            self.assertTrue(theme.DARK_MODE)
            self.page.set_demo_theme(False)
            self.assertFalse(model_demo.DEMO_DARK)
            self.assertTrue(theme.DARK_MODE)
        finally:
            theme.DARK_MODE = False
            model_demo.set_demo_dark(False)

    def test_known_pixel_box_maps_across_window_sizes_and_fullscreen(self):
        image_w, image_h = 1280, 720
        bbox = (400, 200, 80, 40)
        views = (
            QRectF(0, 0, 1280, 720),
            QRectF(10, 20, 960, 540),
            QRectF(0, 0, 400, 400),
            QRectF(0, 0, 1000, 400),
            QRectF(0, 0, 1920, 1080),
        )
        for bounds in views:
            rect = fit_rect(image_w, image_h, bounds, cover=True)
            self.assertAlmostEqual(rect.width() / image_w, rect.height() / image_h, places=4)
            mapped = map_box(bounds, image_w, image_h, image_w, image_h, bbox, cover=True)
            self.assertAlmostEqual(mapped.left(), rect.left() + bbox[0] / image_w * rect.width(), places=3)
            self.assertAlmostEqual(mapped.top(), rect.top() + bbox[1] / image_h * rect.height(), places=3)
            self.assertAlmostEqual(mapped.width() / bbox[2], mapped.height() / bbox[3], places=4)
            center = map_box(bounds, image_w, image_h, image_w, image_h,
                             (image_w / 2 - 1, image_h / 2 - 1, 2, 2), cover=True)
            self.assertAlmostEqual(center.center().x(), bounds.center().x(), delta=0.6)
            self.assertAlmostEqual(center.center().y(), bounds.center().y(), delta=0.6)
        # A result authored at a different size still uses that size, not the view.
        half = map_box(QRectF(0, 0, 640, 360), 640, 360, 1280, 720, (576, 324, 128, 72), cover=True)
        self.assertAlmostEqual(half.center().x(), 320, delta=1.0)
        self.assertAlmostEqual(half.center().y(), 180, delta=1.0)

        tiny = _readable_box(QRectF(10, 20, 8, 12))
        self.assertGreaterEqual(tiny.width(), 24)
        self.assertGreaterEqual(tiny.height(), 24)
        self.assertAlmostEqual(tiny.center().x(), 14, places=3)
        self.assertAlmostEqual(tiny.center().y(), 26, places=3)
        self.assertGreaterEqual(_box_stroke(0.75), 2.0)
        self.assertLessEqual(_box_stroke(0.75), 3.2)
        self.assertGreater(_box_stroke(2.0), _box_stroke(0.75) + 2)

        tall = gallery_picture_rect(QRectF(0, 0, 100, 420), 18)
        wide = gallery_picture_rect(QRectF(0, 0, 420, 100), 18)
        self.assertAlmostEqual(tall.width(), tall.height())
        self.assertAlmostEqual(wide.width(), wide.height())
        self.assertLess(tall.width(), 120)
        self.assertAlmostEqual(wide.width(), 82, delta=0.1)
        src = zoom_source({"bbox": [10, 30, 20, 40]}, 200, 200)
        self.assertAlmostEqual(src.width(), src.height(), places=3)
        drawn, _scale = uniform_dest(QRectF(0, 0, 40, 200), src)
        self.assertAlmostEqual(drawn.width(), drawn.height(), places=3)
        self.assertAlmostEqual(drawn.width() / src.width(), drawn.height() / src.height(), places=4)

        bird = class_color("bird")
        self.assertGreater(bird.red() - bird.green(), 150)
        self.assertLess(bird.green(), 80)
        drone = class_color("drone")
        self.assertGreater(drone.red(), 220)
        self.assertGreater(drone.green(), 180)
        self.assertLess(drone.blue(), 140)
        bus = class_color("bus")
        self.assertLess(bus.green(), 100)
        self.assertGreater(bus.blue(), 200)

        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor(170, 206, 230))
        painter = QPainter(image)
        painter.fillRect(120, 70, 40, 24, QColor(0, 255, 0))
        painter.end()
        result = {
            "schema": "capture-studio.inference.v1", "frame_id": 3, "width": 320, "height": 180,
            "model": "demo", "backend": "test", "latency_ms": 1, "preview_only": True,
            "detections": [{"bbox": [120, 70, 40, 24], "class": "bird", "score": 0.8, "track_id": 1}],
        }
        self.page.show_board_frame(image, result, None, connected=True)
        self.page.timer.stop()
        self.page._stop_poller()

        def green_center(grab, expected):
            x0 = max(0, int(expected.left()) - 6)
            y0 = max(0, int(expected.top()) - 6)
            x1 = min(grab.width() - 1, int(expected.right()) + 6)
            y1 = min(grab.height() - 1, int(expected.bottom()) + 6)
            sx = sy = n = 0
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    color = grab.pixelColor(x, y)
                    if color.green() > 150 and color.green() > color.red() + 40 and color.green() > color.blue() + 40:
                        sx += x
                        sy += y
                        n += 1
            self.assertGreater(n, 8)
            return sx / n, sy / n

        try:
            for size in ((1280, 720), (1600, 900), (1100, 800)):
                self.page.resize(*size)
                APP.processEvents()
                self.page.stage.repaint()
                self.assertGreater(self.page.stage.width(), 200)
                grab = self.page.stage.grab().toImage()
                inner = stage_content_rect(QRectF(self.page.stage.rect()))
                expected = map_box(inner, 320, 180, 320, 180, (120, 70, 40, 24), cover=True)
                cx, cy = green_center(grab, expected)
                self.assertAlmostEqual(cx, expected.center().x(), delta=2.0)
                self.assertAlmostEqual(cy, expected.center().y(), delta=2.0)
            self.page.open_showcase()
            APP.processEvents()
            stage = self.page._showcase.stage
            stage.repaint()
            grab = stage.grab().toImage()
            inner = stage_content_rect(QRectF(stage.rect()))
            expected = map_box(inner, 320, 180, 320, 180, (120, 70, 40, 24), cover=True)
            cx, cy = green_center(grab, expected)
            self.assertAlmostEqual(cx, expected.center().x(), delta=2.0)
            self.assertAlmostEqual(cy, expected.center().y(), delta=2.0)
        finally:
            if self.page.showcase_open():
                self.page._showcase.close()

    def test_demo_marks_sit_on_birds_inside_the_frame(self):
        from capture_studio.model_demo import clip_frame
        counts = []
        for frame_id in range(24):
            image, result = clip_frame(frame_id)
            self.assertEqual((image.width(), image.height()), (result["width"], result["height"]))
            self.assertTrue(result["preview_only"])
            dets = result["detections"]
            self.assertGreaterEqual(len(dets), 6)
            for det in dets:
                self.assertEqual(det["class"], "bird")
                self.assertLess(float(det["score"]), 0.95)
                x, y, w, h = det["bbox"]
                self.assertGreaterEqual(w, 8)
                self.assertGreaterEqual(h, 8)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + w, result["width"] + 0.5)
                self.assertLessEqual(y + h, result["height"] + 0.5)
            counts.append(len(dets))
        self.assertGreaterEqual(sum(counts) / len(counts), 8)

    def test_english_chrome(self):
        i18n.LANG = "en"
        page = ModelDemoPage()
        try:
            self.assertEqual(page.source_buttons["synthetic"].text(), "Demo clip")
            self.assertEqual(page.source_buttons["board"].text(), "Board")
            self.assertEqual(badge_copy("demo"), ("Demo data", "Demo marks, not recognition"))
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
