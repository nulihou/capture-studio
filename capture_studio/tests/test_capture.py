from __future__ import annotations

from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
import shutil
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from capture_studio.board_agent import AgentState, make_handler
from capture_studio.core import (CaptureOptions, ProcessRecorder, audit_session,
                                 board_gst_command, load_json, new_session,
                                 safe_session, sha256, update_session)
from capture_studio.desktop import BoardClient, decode_dshow_text, parse_dshow_devices


TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / "test_scratch"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


@contextmanager
def scratch():
    path = TEST_TEMP_ROOT / uuid4().hex
    path.mkdir()
    try:
        yield str(path)
    finally:
        if not path.resolve().is_relative_to(TEST_TEMP_ROOT.resolve()):
            raise RuntimeError("unsafe test scratch cleanup path")
        shutil.rmtree(path)


class CaptureContractTests(unittest.TestCase):
    def test_dshow_device_parser_handles_new_and_old_ffmpeg_output(self) -> None:
        output = ('[dshow @ 123] "USB 摄像头" (video)\n'
                  '[dshow @ 123] "USB 麦克风" (audio)\n'
                  '[dshow @ 123] DirectShow video devices\n'
                  '[dshow @ 123] "Legacy Cam"\n'
                  '[dshow @ 123]   Alternative name "@device_pnp_long"\n'
                  '[dshow @ 123] DirectShow audio devices\n'
                  '[dshow @ 123] "Legacy Mic"\n')
        self.assertEqual(["USB 摄像头", "Legacy Cam"], parse_dshow_devices(output))

    def test_dshow_names_survive_the_system_code_page(self) -> None:
        text = '[dshow @ 1] DirectShow video devices\n[dshow @ 1] "集成摄像头"\n'
        self.assertEqual(["集成摄像头"], parse_dshow_devices(decode_dshow_text(text.encode("gbk"))))
        self.assertEqual(["集成摄像头"], parse_dshow_devices(decode_dshow_text(text.encode("utf-8"))))

    def test_board_mode_requires_matching_codec_and_safe_device(self) -> None:
        with self.assertRaises(ValueError):
            CaptureOptions(device="/tmp/camera", source_format="mjpeg", codec="copy").validate("kv260_usb")
        with self.assertRaises(ValueError):
            CaptureOptions(device="/dev/video0", source_format="mjpeg", codec="h264").validate("kv260_usb")
        options = CaptureOptions(device="/dev/video3", source_format="mjpeg", codec="copy")
        with scratch() as directory:
            command = board_gst_command(options, Path(directory))
        self.assertNotIn("jpegparse", command)
        self.assertIn("do-timestamp=false", command)
        self.assertNotIn("omxh264enc", command)

    def test_session_path_rejects_traversal(self) -> None:
        with scratch() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                safe_session(root, "../elsewhere")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
    def test_synthetic_recording_and_frame_audit(self) -> None:
        with scratch() as directory:
            options = CaptureOptions(device="synthetic", width=64, height=64, fps=10)
            session = new_session(Path(directory), "pc_usb", options)
            command = [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                       "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10", "-t", "2",
                       "-c:v", "ffv1", "-f", "segment", "-segment_time", "1",
                       "-reset_timestamps", "0", "-segment_format", "matroska",
                       str(session / "segments" / "part_%05d.mkv")]
            recorder = ProcessRecorder(session, [str(x) for x in command], "ffmpeg")
            recorder.start()
            recorder.process.wait(timeout=20)
            manifest = recorder.stop()
            self.assertEqual("recorded", manifest["status"])
            report = audit_session(session, Path(shutil.which("ffprobe")))
            self.assertEqual(20, report["frame_count"])
            self.assertEqual(0, report["missing_pts"])
            self.assertEqual(0, report["nonmonotonic_pts"])
            self.assertEqual(20, len((session / "frames.jsonl").read_text().splitlines()))
            gates = load_json(session / "session.json")["gates"]
            self.assertEqual("pass", gates["integrity"]["status"])
            self.assertEqual("pending", gates["frame_rate"]["status"])
            self.assertIn(gates["image"]["status"], ("pass", "pending"))
            self.assertEqual("pass", gates["closeout"]["status"])
            self.assertFalse(gates["dataset_ready"])


class BoardTransferTests(unittest.TestCase):
    def test_active_board_status_reports_recording_device(self) -> None:
        with scratch() as board_dir:
            root = Path(board_dir)
            options = CaptureOptions(device="/dev/video2", source_format="mjpeg", codec="copy")
            session = new_session(root, "kv260_usb", options)
            state = AgentState(root, "a" * 32)

            class FakeRecorder:
                def __init__(self, path):
                    self.session = path

                def status(self):
                    return {"running": True, "session_id": self.session.name}

            state.recorder = FakeRecorder(session)
            self.assertEqual("/dev/video2", state.status()["session"]["device"])

    def test_authenticated_transfer_and_checksum(self) -> None:
        with scratch() as board_dir, scratch() as pc_dir:
            root = Path(board_dir)
            options = CaptureOptions(device="/dev/video0", source_format="mjpeg", codec="copy")
            session = new_session(root, "kv260_usb", options)
            media = session / "segments" / "part_00000.mkv"
            media.write_bytes(b"test media bytes")
            update_session(session, status="recorded",
                           files=[{"path": "segments/part_00000.mkv", "size": media.stat().st_size,
                                   "sha256": sha256(media)}])
            state = AgentState(root, "a" * 32)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(url + "/status"), timeout=3)
                self.assertEqual(401, caught.exception.code)
                client = BoardClient(url, "a" * 32)
                result = client.download_session(session.name, Path(pc_dir))
                self.assertEqual(media.read_bytes(), (result / "segments" / media.name).read_bytes())
                self.assertEqual("recorded", load_json(result / "session.json")["status"])
                # An already verified file is reusable on a second download.
                self.assertEqual(result, client.download_session(session.name, Path(pc_dir)))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
