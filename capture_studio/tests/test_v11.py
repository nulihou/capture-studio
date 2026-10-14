"""v11: icon status pills, health icons and reduced-motion aware animation helpers."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from capture_studio import icons, motion  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Motion(unittest.TestCase):
    def tearDown(self):
        motion.set_reduced(None)
        os.environ.pop("CAPTURE_STUDIO_REDUCED_MOTION", None)

    def test_reduced_sources(self):
        motion.set_reduced(None)
        os.environ["CAPTURE_STUDIO_REDUCED_MOTION"] = "1"
        self.assertTrue(motion.reduced())
        os.environ.pop("CAPTURE_STUDIO_REDUCED_MOTION")
        motion.set_reduced(True)
        self.assertTrue(motion.reduced())
        motion.set_reduced(False)
        self.assertFalse(motion.reduced())

    def test_durations_restrained(self):
        for ms in (motion.PAGE_MS, motion.PILL_MS, motion.REVEAL_MS, motion.TOAST_IN_MS):
            self.assertTrue(120 <= ms <= 220, ms)

    def test_reduced_is_instant(self):
        motion.set_reduced(True)
        widget = QWidget()
        called = []
        motion.fade_in(widget, done=lambda: called.append(1))
        self.assertEqual(called, [1])
        self.assertIsNone(widget.graphicsEffect())
        holder = QWidget()
        child = QWidget(holder)
        holder.show()
        motion.reveal(child, False)
        self.assertFalse(child.isVisible())
        motion.reveal(child, True)
        self.assertTrue(child.isVisible())
        self.assertEqual(child.maximumHeight(), 16777215)

    def test_fade_animates_then_clears(self):
        motion.set_reduced(False)
        widget = QWidget()
        widget.show()
        done = []
        motion.fade_in(widget, 30, done=lambda: done.append(1))
        self.assertIsNotNone(widget.graphicsEffect())
        import time
        t = time.time()
        while not done and time.time() - t < 2:
            APP.processEvents()
        self.assertEqual(done, [1])
        self.assertIsNone(widget.graphicsEffect())


class PillIcons(unittest.TestCase):
    def test_pill_and_health_icons_exist(self):
        from capture_studio import window
        for kind, (name, _bg, _fg) in window.PILL_KINDS.items():
            self.assertTrue(icons.file_for(name).is_file(), kind)
            for dpr in icons.DPRS:
                self.assertFalse(icons.pixmap(name, 12, "ok", dpr).isNull())
        for name in ("st.ok", "st.warn", "st.fail"):
            self.assertTrue(icons.file_for(name).is_file())

    def test_pill_state_and_cache(self):
        from capture_studio import window
        pill = window.Pill("未连接", "neutral")
        pill.show()
        pill.set_state("ok", "KV260")
        self.assertEqual(pill.kind, "ok")
        pill.set_state("bogus", "x")
        self.assertEqual(pill.kind, "neutral")
        pill.set_state("warn", "w")
        pill.grab()  # forces paintEvent even when the window is not exposed
        self.assertTrue(window._PILL_CACHE)


if __name__ == "__main__":
    unittest.main()
