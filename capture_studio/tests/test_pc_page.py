"""PC page must not show the board stream or board cards (v0.12.5 fix)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt" and not os.environ.get("QT_QPA_FONTDIR"):
    # The offscreen platform has no font database on Windows unless pointed at the system fonts;
    # without it every text width is measured with a fallback ~2x too wide and layout checks fail.
    os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


class PcPageIsolation(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from capture_studio import window as w
        self.w = w
        self.S = S = w.STUDIO
        self._saved = {k: getattr(S, k) for k in ("_save", "scan_pc", "start_live", "client", "connected", "live",
                                                  "board_label", "camera_label", "pc_devices", "preview", "settings")}
        S._save = lambda *a, **k: None
        S.scan_pc = lambda *a, **k: None
        S.start_live = lambda *a, **k: None
        S.settings = dict(S.settings)
        self.win = w.StudioWindow()
        self.win.timer.stop()

    def tearDown(self):
        self.win.close()
        for key, value in self._saved.items():
            setattr(self.S, key, value)
        self.app.processEvents()

    def _board_live(self):
        S = self.S
        with S.lock:
            S.client = None  # stop_live then has nothing remote to call
            S.connected = True
            S.live = True
            S.board_label = "开发板：ZynqMP KV260 revB"
            S.camera_label = "USB 2.0 Camera · 序号 HHW001"
            S.pc_devices = []
            S.settings["pc_device"] = ""
        S._remember_frame(b"board-frame")
        self.win.show_page("board")
        self.win.refresh(S.state())

    def _texts(self):
        return {key: tile.toolTip() or tile.text() for key, tile in self.win.tiles.items()}

    def _enabled(self, text):
        shown = self.w._button_text(text)
        return [b.isEnabled() for b in self.win.actions if b.text() == shown and b.property("needs") == "pc_cam"]

    def test_switch_to_pc_stops_board_live_and_hides_board_cards(self):
        self._board_live()
        self.assertIn("KV260", " ".join(self._texts().values()))
        self.win.show_page("pc")
        self.win.refresh(self.S.state())
        self.assertFalse(self.S.live)
        self.assertIsNone(self.S.preview)
        joined = " ".join(self._texts().values())
        self.assertNotIn("KV260", joined)
        self.assertNotIn("HHW001", joined)
        self.assertNotIn("实时预览中", joined)
        self.assertEqual(self.win.viewport.empty_title, "本机未检测到摄像头")
        self.assertEqual(self._enabled("预览一帧"), [False])
        self.assertEqual(self._enabled("开始采集"), [False])

    def test_pc_camera_enables_actions_and_board_page_restores_cards(self):
        self._board_live()
        self.win.show_page("pc")
        with self.S.lock:
            self.S.pc_devices = [{"label": "USB Cam", "value": "USB Cam", "id": "1:2"}]
            self.S.settings["pc_device"] = "USB Cam"
        self.win.refresh(self.S.state())
        self.assertIn("USB Cam", " ".join(self._texts().values()))
        self.assertEqual(self.win.viewport.empty_title, "")
        self.assertEqual(self._enabled("预览一帧"), [True])
        self.assertEqual(self._enabled("开始采集"), [True])
        self.win.show_page("board")
        self.win.refresh(self.S.state())
        self.assertIn("KV260", " ".join(self._texts().values()))
        self.assertFalse(self.S.live)  # never auto-restarted

    def test_pc_page_stream_card_shows_pc_mode(self):
        self._board_live()
        with self.S.lock:
            self.S.settings.update({"width": "1920", "height": "1080", "fps": "30", "format": "mjpeg",
                                    "pc_width": "640", "pc_height": "480", "pc_fps": "15", "pc_format": "raw"})
        self.win.refresh(self.S.state())
        self.assertIn("1920", self.win.tiles["stream"]._full)
        self.win.show_page("pc")
        self.win.refresh(self.S.state())
        self.assertIn("640", self.win.tiles["stream"]._full)
        self.assertIn("15 fps", self.win.tiles["stream"]._full)

    def test_navigation_refreshes_cards_without_timer_or_manual_refresh(self):
        self._board_live()
        with self.S.lock:
            self.S.settings.update({'width': '1920', 'height': '1080', 'fps': '30', 'format': 'mjpeg',
                                    'pc_width': '640', 'pc_height': '480', 'pc_fps': '15', 'pc_format': 'raw'})
        self.win.show_page('pc')
        self.assertNotIn('KV260', ' '.join(self._texts().values()))
        self.assertIn('640', self.win.tiles['stream']._full)
        self.assertIn('15 fps', self.win.tiles['stream']._full)
        self.assertEqual(self._enabled('开始采集'), [False])
        self.win.show_page('board')
        self.assertIn('KV260', ' '.join(self._texts().values()))
        self.assertIn('1920', self.win.tiles['stream']._full)


if __name__ == "__main__":
    unittest.main()
