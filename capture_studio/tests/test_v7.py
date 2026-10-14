import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from capture_studio import credstore, errors, health, i2c_hints, lan_scan, pc_peripherals, serial_term, session_review, templates, theme


class LanScanTest(unittest.TestCase):
    def test_candidate_hosts_private_only_capped(self):
        hosts = lan_scan.candidate_hosts([("192.168.1.23", 24), ("10.0.0.5", 8), ("8.8.8.8", 24), ("127.0.0.1", 8), ("169.254.3.4", 16)])
        self.assertNotIn("192.168.1.23", hosts)          # own address
        self.assertIn("192.168.1.1", hosts)
        self.assertIn("10.0.0.1", hosts)                 # /8 clamped to /24
        self.assertFalse(any(h.startswith(("8.8.", "127.", "169.254.")) for h in hosts))
        self.assertEqual(len(hosts), 253 + 253)

    def test_probe_reads_banner_and_closes(self):
        class Sock:
            closed = False
            def settimeout(self, t): pass
            def recv(self, n): return b"SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.1\r\n"
            def close(self): Sock.closed = True
        result = lan_scan.probe("10.0.0.9", connect=lambda addr, timeout: Sock())
        self.assertEqual(result["hint"], "Ubuntu")
        self.assertTrue(Sock.closed)

    def test_probe_refused(self):
        def refuse(addr, timeout):
            raise ConnectionRefusedError()
        self.assertIsNone(lan_scan.probe("10.0.0.9", connect=refuse))

    def test_scan_sorted_numerically(self):
        found = lan_scan.scan(["10.0.0.20", "10.0.0.3", "10.0.0.100"], prober=lambda h: {"host": h} if h != "10.0.0.20" else None)
        self.assertEqual([f["host"] for f in found], ["10.0.0.3", "10.0.0.100"])


class CredTest(unittest.TestCase):
    def test_roundtrip_with_fake_keyring(self):
        store = {}
        kr = SimpleNamespace(set_password=lambda s, a, p: store.__setitem__((s, a), p),
                             get_password=lambda s, a: store.get((s, a)),
                             delete_password=lambda s, a: store.pop((s, a)))
        self.assertTrue(credstore.save("ubuntu", "10.0.0.2", "pw", backend=kr))
        self.assertEqual(credstore.load("ubuntu", "10.0.0.2", backend=kr), "pw")
        credstore.forget("ubuntu", "10.0.0.2", backend=kr)
        self.assertEqual(credstore.load("ubuntu", "10.0.0.2", backend=kr), "")
        self.assertFalse(credstore.save("u", "h", "", backend=kr))


class TemplateTest(unittest.TestCase):
    def test_save_load_apply(self):
        path = Path(tempfile.mkdtemp()) / "t.json"
        tpl = templates.capture({"width": "1920", "height": "1080", "fps": "30", "format": "mjpeg", "duration": "60 秒短检",
                                 "output": "D:/data", "host": "x"}, "走廊/夜间:1")
        self.assertNotIn("host", tpl)
        templates.save(path, "  夜间 ", tpl)
        data = templates.load_all(path)
        self.assertIn("夜间", data)
        payload = templates.apply({"output": "captures"}, data["夜间"], datetime(2026, 10, 13, 9, 0))
        self.assertEqual(payload["width"], "1920")
        self.assertEqual(Path(payload["output"]), Path("D:/data/20261013_走廊_夜间_1"))
        templates.delete(path, "夜间")
        self.assertEqual(templates.load_all(path), {})
        with self.assertRaises(ValueError):
            templates.save(path, "  ", tpl)

    def test_corrupt_file(self):
        path = Path(tempfile.mkdtemp()) / "t.json"
        path.write_text("{oops", encoding="utf-8")
        self.assertEqual(templates.load_all(path), {})


class HealthTest(unittest.TestCase):
    def test_estimates(self):
        mj = health.estimate({"width": "1920", "height": "1080", "fps": "30", "format": "mjpeg", "duration": "60 秒短检"})
        raw = health.estimate({"width": "1920", "height": "1080", "fps": "30", "format": "raw", "duration": "10 分钟关口"})
        # v9: no guessed coefficient; without history MJPEG is an explicit upper bound, raw is exact.
        self.assertEqual(mj["basis"], "upper")
        self.assertEqual(raw["basis"], "exact")
        self.assertAlmostEqual(raw["mbps"], 1920 * 1080 * 30 * 2 * 8 / 1e6)
        self.assertEqual(raw["seconds"], 600)

    def test_checks(self):
        s = {"width": "1920", "height": "1080", "fps": "30", "format": "raw", "duration": "60 秒短检"}
        items = health.check(s, "board", 10 * 2**30, {"temp_max": 83.0, "disk_total": 8e9, "disk_used": 7.9e9, "cpu": 90},
                             "UVC · USB 2.0", 100, {"frame_count": 1800, "possible_gap_intervals": 3})
        titles = {i["title"]: i["level"] for i in items}
        self.assertEqual(titles["开发板存储不足"], "fail")
        self.assertEqual(titles["开发板温度偏高"], "warn")
        self.assertEqual(titles["USB 带宽不够"], "fail")
        self.assertEqual(titles["网络带宽可能不够"], "warn")
        self.assertEqual(titles["上次录制有疑似掉帧"], "warn")
        self.assertTrue(all(i["fix"] for i in items if i["level"] != "ok"))
        self.assertEqual(health.worst(items), "fail")
        ok = health.check({"width": "640", "height": "480", "fps": "30", "format": "mjpeg"}, "pc", 1e12, {})
        self.assertEqual(health.worst(ok), "ok")


class ErrorsTest(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(errors.friendly("ssh: connect to host 1.2.3.4 port 22: Connection timed out")["title"], "连接超时")
        self.assertEqual(errors.friendly("ubuntu@1.2.3.4: Permission denied (publickey).")["title"], "开发板拒绝登录")
        self.assertFalse(errors.friendly("Host key verification failed.")["retry"])
        self.assertEqual(errors.friendly("[dshow] Could not find video device with name")["title"], "找不到摄像头")
        self.assertEqual(errors.friendly("weird")["title"], "操作没有完成")

    def test_bundle_redacts(self):
        path = Path(tempfile.mkdtemp()) / "d.zip"
        errors.bundle(path, {"settings": {"host": "h", "password": "hunter2", "key": "C:\\Users\\alice\\.ssh\\id"},
                             "logs": ["password=hunter2 ok", "C:\\Users\\alice\\x"], "peripherals": [{"name": "摄像头"}]})
        z = zipfile.ZipFile(path)
        blob = b"".join(z.read(n) for n in z.namelist())
        self.assertNotIn(b"hunter2", blob)
        self.assertNotIn(b"alice", blob)
        self.assertIn("摄像头", z.read("peripherals.json").decode("utf-8"))


class ReviewTest(unittest.TestCase):
    def test_find_and_summarize(self):
        root = Path(tempfile.mkdtemp())
        for parent, sid in ((root, "20261013T010000Z_00000001"), (root / "20261013_室外", "20261013T020000Z_00000002")):
            (parent / sid / "segments").mkdir(parents=True)
            (parent / sid / "segments" / "part_00000.mkv").write_bytes(b"0" * 100)
            (parent / sid / "session.json").write_text(json.dumps({"session_id": sid, "options": {"width": 640, "height": 480, "fps": 25},
                "files": [{"path": "segments/part_00000.mkv"}], "audit": {"frame_count": 250, "possible_gap_intervals": 0}}), encoding="utf-8")
        found = session_review.find_sessions(root)
        self.assertEqual([p.name for p in found], ["20261013T020000Z_00000002", "20261013T010000Z_00000001"])
        summary = session_review.summarize(found[0])
        self.assertEqual((summary["frames"], summary["duration"], summary["size"]), (250, 10.0, 100))
        self.assertIn("0:10", session_review.describe(summary))
        self.assertEqual(session_review.summarize(root / "nope")["size"], 0)

    def test_commands(self):
        cmd = session_review.frames_command(Path("ffmpeg"), "a.mkv", Path("out"))
        self.assertIn("fps=5,scale=480:-2", cmd)
        self.assertEqual(session_review.probe_duration(Path("ffprobe"), "a.mkv", run=lambda *a, **k: SimpleNamespace(stdout="12.5\n")), 12.5)


class SerialTest(unittest.TestCase):
    def test_hexdump_and_send(self):
        self.assertEqual(serial_term.hexdump(b"AB\x00"), "00000000  41 42 00" + " " * 39 + "  AB.")
        self.assertEqual(serial_term.parse_send("0x55, 0xAA", True), b"\x55\xaa")
        self.assertEqual(serial_term.parse_send("你好", False, "\n"), "你好\n".encode())
        with self.assertRaises(ValueError):
            serial_term.parse_send("5", True)

    def test_board_command_validates(self):
        cmd = serial_term.board_command(["ssh", "u@h"], "/dev/ttyUSB0", 115200)
        self.assertTrue(cmd[-1].startswith("stty -F /dev/ttyUSB0 115200 raw"))
        for port in ("/dev/sda", "/dev/ttyUSB0; rm -rf /"):
            with self.assertRaises(ValueError):
                serial_term.board_command(["ssh"], port, 115200)
        with self.assertRaises(ValueError):
            serial_term.board_command(["ssh"], "/dev/ttyUSB0", 1234)

    def test_pc_session_with_fake_serial(self):
        class Port:
            in_waiting = 0
            def __init__(self, *a, **k): self.args, self.data, self.out = a, [b"ok"], []
            def read(self, n): return self.data.pop() if self.data else b""
            def write(self, b): self.out.append(b)
            def close(self): self.closed = True
        got = []
        session = serial_term.open_pc("COM3", 9600, serial_factory=Port)
        session.start(got.append)
        session.write(b"x")
        import time
        time.sleep(0.05)
        session.close()
        self.assertEqual(got[:1], [b"ok"])


class HintsTest(unittest.TestCase):
    def test_i2c(self):
        self.assertIn("MPU6050/MPU9250 IMU", i2c_hints.hints(0x68))
        self.assertTrue(i2c_hints.describe("0x76").startswith("0x76 可能是"))
        self.assertEqual(i2c_hints.describe("0x03"), "0x03")


class PcPeriphTest(unittest.TestCase):
    def test_parse_pnp(self):
        text = json.dumps([
            {"Class": "Camera", "FriendlyName": "Logi C270 HD WebCam", "InstanceId": "USB\\VID_046D&PID_0825&MI_00\\7&1", "Status": "OK"},
            {"Class": "USB", "FriendlyName": "USB Root Hub (USB 3.0)", "InstanceId": "USB\\ROOT_HUB30\\4&1", "Status": "OK"},
            {"Class": "Ports", "FriendlyName": "USB-SERIAL CH340 (COM5)", "InstanceId": "USB\\VID_1A86&PID_7523\\5&2", "Status": "OK"},
            {"Class": "Printer", "FriendlyName": "x", "InstanceId": "y"}], ensure_ascii=False)
        items = pc_peripherals.parse_pnp(text)
        self.assertEqual([i["category"] for i in items], ["video", "serial"])
        self.assertEqual(items[0]["summary"], "046d:0825 · OK")
        self.assertEqual(pc_peripherals.parse_pnp("{\"Class\":\"Monitor\",\"FriendlyName\":\"戴尔显示器\",\"InstanceId\":\"DISPLAY\\\\DEL\"}")[0]["name"], "戴尔显示器")
        self.assertEqual(pc_peripherals.parse_pnp("garbage"), [])

    def test_scan_merges_com_ports_and_decodes_gbk(self):
        raw = json.dumps([{"Class": "Ports", "FriendlyName": "USB-SERIAL CH340 (COM5)", "InstanceId": "USB\\VID_1A86&PID_7523\\5"},
                          {"Class": "Camera", "FriendlyName": "集成摄像头", "InstanceId": "USB\\VID_0C45&PID_6713\\1"}], ensure_ascii=False).encode("gbk")
        port = SimpleNamespace(device="COM5", description="USB-SERIAL CH340 (COM5)", vid=0x1A86, pid=0x7523, manufacturer="wch.cn", serial_number="", hwid="USB VID:PID=1A86:7523")
        items = pc_peripherals.scan(run=lambda *a, **k: SimpleNamespace(stdout=raw), list_ports=lambda: [port])
        self.assertEqual(sorted(i["name"] for i in items), ["USB-SERIAL CH340 (COM5)", "集成摄像头"])
        serial = [i for i in items if i["category"] == "serial"][0]
        self.assertEqual(serial["port"], "COM5")
        self.assertIn("CH340", serial["summary"])


class ThemeTest(unittest.TestCase):
    def test_dark_css(self):
        css = "QWidget { color: #1D1D1F; background: #F5F5F7; } QPushButton#primary { color: #FFFFFF; background: #0071E3; } QToolTip { background: #1D1D1F; color: #FFFFFF; }"
        dark = theme.css(css, True)
        self.assertIn("color: #F5F5F7", dark)
        self.assertIn("background: #1C1C1E", dark)
        self.assertIn("color: #FFFFFF; background: #0071E3", dark)
        self.assertIn("QToolTip { background: #3A3A3C; color: #F5F5F7;", dark)
        self.assertEqual(theme.css(css, False), css)
        self.assertTrue(theme.resolve("深色"))
        self.assertFalse(theme.resolve("浅色"))


if __name__ == "__main__":
    unittest.main()
