"""Small native UI checks for the operator's critical controls."""

import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch

import tkinter as tk

from capture_studio.desktop import CaptureDesktop
from capture_studio.desktop_ui import layout_preview, populate_sessions, preview_fit
from capture_studio.portable_connect import resolve_connection_key


class CaptureDesktopUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = CaptureDesktop()
        self.app.geometry("960x650")
        self.app.update()

    def tearDown(self) -> None:
        self.app.destroy()

    def test_critical_actions_and_footer_fit_small_window(self) -> None:
        book = self.app.pc_tab.master
        for tab, button in ((self.app.pc_tab, self.app.pc_stop_button),
                            (self.app.board_tab, self.app.board_stop_button)):
            book.select(tab)
            self.app.update()
            left = self.app.winfo_rootx()
            top = self.app.winfo_rooty()
            right = left + self.app.winfo_width()
            bottom = top + self.app.winfo_height()
            self.assertGreaterEqual(button.winfo_rootx(), left)
            self.assertGreaterEqual(button.winfo_rooty(), top)
            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), right)
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), bottom)
            notebook_bottom = book.winfo_rooty() + book.winfo_height()
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), notebook_bottom)
            self.assertGreaterEqual(self.app.footer.winfo_height(), 22)
            self.assertLessEqual(self.app.footer.winfo_rooty() +
                                 self.app.footer.winfo_height(), bottom)
            label = self.app.status_label
            self.assertGreaterEqual(label.winfo_height(), 14)
            self.assertLessEqual(label.winfo_rooty() + label.winfo_height(),
                                 self.app.footer.winfo_rooty() + self.app.footer.winfo_height())

    def test_timed_capture_is_the_default_and_manual_stop_remains(self) -> None:
        self.assertEqual(60, self.app._planned_seconds())
        self.assertEqual("限时采集", self.app.pc_start_button.cget("text"))
        self.app.lens_var.set("8mm")
        self.app.light_var.set("室内")
        self.app.distance_var.set("2m")
        self.app.board_device.set("/dev/video0")
        options = self.app._board_options()
        self.assertEqual((60, "8mm", "室内", "2m"),
                         (options.planned_seconds, options.lens, options.lighting, options.distance))
        self.app.duration_var.set("手动停止")
        self.app.update()
        self.assertIsNone(self.app._planned_seconds())
        self.assertEqual("开始采集", self.app.board_start_button.cget("text"))

    def test_board_exposure_is_shared_by_the_capture_options(self) -> None:
        self.app.board_device.set("/dev/video0")
        self.app.board_preset.set("看清画面")
        self.app.update()
        self.assertIn("disabled", str(self.app.board_exposure_entry.cget("state")))
        self.app.board_exposure_mode.set("快门优先")
        self.app.board_exposure_absolute.set("100")
        options = self.app._board_options()
        self.assertEqual((2, 100), (options.exposure_mode, options.exposure_absolute))
        self.assertEqual("自己设置", self.app.board_preset.get())
        self.app.board_preset.set("看清画面")
        self.app.update()
        self.assertIn("disabled", str(self.app.board_exposure_entry.cget("state")))
        auto = self.app._board_options()
        self.assertEqual((0, None), (auto.exposure_mode, auto.exposure_absolute))

    def test_shooting_choices_are_plain_and_hide_the_numbers(self) -> None:
        self.app.board_device.set("/dev/video0")
        self.app.board_preset.set("看清画面")
        self.app.update()
        self.assertEqual("看清画面", self.app.board_preset.get())
        self.assertIn("更亮", self.app.board_preset_note.get())
        self.assertEqual({}, self.app.exposure_row.grid_info())
        self.app.board_preset.set("看流畅")
        self.app.update()
        shutter = self.app._board_options()
        self.assertEqual((2, 100), (shutter.exposure_mode, shutter.exposure_absolute))
        self.assertIn("变暗", self.app.board_preset_note.get())
        self.assertEqual({}, self.app.exposure_row.grid_info())
        self.app.board_preset.set("快门 10ms")
        self.app.update()
        self.assertEqual("看流畅", self.app.board_preset.get())
        renamed = self.app._board_options()
        self.assertEqual((2, 100), (renamed.exposure_mode, renamed.exposure_absolute))
        self.app.board_preset.set("自己设置")
        self.app.update()
        self.assertEqual("13", str(self.app.exposure_row.grid_info().get("row")))
        self.app.board_exposure_mode.set("手动")
        self.app.board_exposure_absolute.set("100")
        manual = self.app._board_options()
        self.assertEqual((1, 100), (manual.exposure_mode, manual.exposure_absolute))
        self.assertEqual("自己设置", self.app.board_preset.get())

    def test_board_format_and_session_selection(self) -> None:
        self.assertIn("disabled", self.app.board_bitrate_entry.state())
        self.app.board_format.set("raw")
        self.assertNotIn("disabled", self.app.board_bitrate_entry.state())
        populate_sessions(self.app, [{"session_id": "20260924T030000Z_abcdef12",
                                      "created_utc": "2026-09-24T03:00:00Z",
                                      "status": "recorded", "files": 2}])
        self.app.pc_tab.master.select(self.app.review_tab)
        self.app.session_tree.selection_set("20260924T030000Z_abcdef12")
        self.app.update()
        self.assertEqual("20260924T030000Z_abcdef12", self.app.remote_session.get())

    def test_pc_device_status_tracks_empty_single_and_multiple_results(self) -> None:
        self.app._apply_local_devices([])
        self.assertEqual("未检测到", self.app.pc_scan_var.get())
        self.assertIn("未检测到摄像头", self.app.pc_current_var.get())
        self.assertIn("disabled", self.app.pc_start_button.state())

        self.app._apply_local_devices(["USB Camera"])
        self.assertEqual("USB Camera", self.app.pc_device.get())
        self.assertEqual("当前设备：USB Camera", self.app.pc_current_var.get())
        self.assertNotIn("disabled", self.app.pc_start_button.state())

        self.app._apply_local_devices(["Camera A", "Camera B"])
        self.assertEqual("", self.app.pc_device.get())
        self.assertEqual("已找到 2 台", self.app.pc_scan_var.get())
        self.assertIn("未选择", self.app.pc_current_var.get())
        self.app.pc_device.set("Camera B")
        self.assertEqual("当前设备：Camera B", self.app.pc_current_var.get())

    def test_board_device_status_and_connection_change(self) -> None:
        self.assertIn("未连接板端", self.app.board_current_var.get())
        self.app.board_url.set("http://kv260.local:8765")
        self.app.board_token.set("test-token")
        self.assertEqual("待连接", self.app.board_scan_var.get())
        self.app._apply_board_devices(["/dev/video0"])
        self.assertEqual("/dev/video0", self.app.board_device.get())
        self.assertEqual("当前设备：/dev/video0", self.app.board_current_var.get())
        self.assertNotIn("disabled", self.app.board_start_button.state())
        self.app._apply_board_devices([], "device endpoint failed", status_connected=True)
        self.assertIn("查询失败", self.app.board_current_var.get())
        self.assertEqual("设备查询失败", self.app.board_badge.cget("text"))
        self.app.board_url.set("http://another-board.local:8765")
        self.assertEqual("", self.app.board_device.get())
        self.assertIn("未连接板端", self.app.board_current_var.get())
        self.assertIn("disabled", self.app.board_start_button.state())

    def test_startup_auto_scan_shows_detected_camera(self) -> None:
        with patch.object(self.app, "_tool", return_value=Path(__file__)), \
                patch("capture_studio.desktop.list_dshow_devices", return_value=["Demo Camera"]):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and self.app.pc_device.get() != "Demo Camera":
                self.app.update()
                time.sleep(0.02)
        self.assertEqual("Demo Camera", self.app.pc_device.get())
        self.assertEqual("当前设备：Demo Camera", self.app.pc_current_var.get())

    def test_board_connect_fetches_status_and_devices_together(self) -> None:
        self.app.board_url.set("http://kv260.local:8765")
        self.app.board_token.set("test-token")
        calls = []

        class FakeClient:
            def request(self, _method, endpoint):
                calls.append(endpoint)
                if endpoint == "/status":
                    return {"recording": False, "session": None}
                return {"devices": ["/dev/video2"]}

        with patch.object(self.app, "_client", return_value=FakeClient()):
            self.app._board_status()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and self.app.board_device.get() != "/dev/video2":
                self.app.update()
                time.sleep(0.02)
        self.assertEqual(["/status", "/devices"], calls)
        self.assertEqual("当前设备：/dev/video2", self.app.board_current_var.get())
        self.assertEqual("已连接", self.app.board_badge.cget("text"))

    def test_board_reconnect_restores_active_device(self) -> None:
        self.app.board_url.set("http://kv260.local:8765")
        self.app.board_token.set("test-token")

        class FakeClient:
            def request(self, _method, endpoint):
                if endpoint == "/status":
                    return {"recording": True, "session": {
                        "session_id": "20260924T030000Z_abcdef12", "device": "/dev/video2",
                        "elapsed_s": 10, "bytes": 1000}}
                return {"devices": ["/dev/video0", "/dev/video2"]}

        with patch.object(self.app, "_client", return_value=FakeClient()):
            self.app._board_status()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and self.app.board_device.get() != "/dev/video2":
                self.app.update()
                time.sleep(0.02)
        self.assertEqual("/dev/video2", self.app.board_device.get())
        self.assertIn("/dev/video2（录制中）", self.app.board_current_var.get())
        self.assertNotIn("disabled", self.app.board_stop_button.state())

    def test_preview_picture_fills_its_own_canvas(self) -> None:
        self.assertEqual((5, 4, 400, 300), preview_fit(320, 240, 400, 300))
        zoom, _subsample, width, height = preview_fit(320, 240, 500, 360)
        self.assertLessEqual(width, 500)
        self.assertLessEqual(height, 360)
        self.assertEqual(320 * zoom // _subsample, width)
        image = tk.PhotoImage(width=320, height=240)
        image.put("#336655", to=(0, 0, 320, 240))
        canvas = self.app.board_preview_canvas
        canvas.source_image = image
        layout_preview(canvas, box=(400, 300))
        fitted = canvas.fitted_image
        self.assertEqual((400, 300), (fitted.width(), fitted.height()))
        self.assertEqual((400, 300), (int(canvas["width"]), int(canvas["height"])))

    def test_connection_key_from_another_computer_is_ignored(self) -> None:
        self.assertEqual("", resolve_connection_key("", Path("/no/such/home")))
        self.assertEqual("", resolve_connection_key(r"C:\Users\Other\.ssh\id_ed25519_kv260",
                                                    Path("/no/such/home")))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = root / "id_ed25519_kv260"
            key.write_text("not-a-real-key\n", encoding="utf-8")
            self.assertEqual(str(key), resolve_connection_key(str(key), Path("/no/such/home")))
            home = root / "pretend-home"
            (home / ".ssh").mkdir(parents=True)
            fallback = home / ".ssh" / "id_ed25519_kv260"
            fallback.write_text("local-key\n", encoding="utf-8")
            self.assertEqual(str(fallback), resolve_connection_key(str(root / "missing"), home))

    def test_camera_lab_adjustments_enter_the_capture_options(self) -> None:
        self.app.board_device.set("/dev/video0")
        self.app.board_resolution.set("640×480")
        self.app.update()
        self.assertEqual(("640", "480"), (self.app.board_width.get(), self.app.board_height.get()))
        self.app.board_gain.set("16")
        self.app.board_power_line.set("50 Hz")
        self.app.board_wb.set("自动")
        self.app.board_white_balance_temperature.set("4000")
        self.app.update()
        self.assertEqual("disabled", str(self.app.lab_entries["white_balance_temperature"].cget("state")))
        options = self.app._board_options()
        self.assertEqual(16, options.gain)
        self.assertEqual(1, options.power_line_frequency)
        self.assertEqual((1, None), (options.white_balance_auto, options.white_balance_temperature))
        self.assertEqual((640, 480), (options.width, options.height))
        self.assertIn("摄像头测试", self.app.lab_tab.master.tab(self.app.lab_tab, "text"))

    def test_plug_in_identity_selects_the_only_new_camera(self) -> None:
        self.app.board_url.set("http://kv260.local:8765")
        self.app.board_token.set("test-token")
        infos = [{"device": "/dev/video3", "name": "USB Camera", "product": "DeskCam",
                  "vid": "1c45", "pid": "6200", "serial": "CAM9", "speed": "480",
                  "usb_path": "1-1.4"}]
        self.app._apply_board_devices(["/dev/video3"], announce=False)
        self.app._note_board_cameras(infos, {"model": "KV260", "hostname": "kria"})
        self.assertEqual("/dev/video3", self.app.board_device.get())
        self.assertIn("DeskCam", self.app.lab_camera_var.get())
        self.assertIn("KV260", self.app.lab_board_var.get())
        self.assertIn("USB 2.0", self.app.lab_camera_var.get())
        self.assertIn("CAM9", self.app.lab_camera_pick.get())


if __name__ == "__main__":
    unittest.main()
