"""v10 functional audit: mocked board outputs (5 families) and parser edge cases, incl. Chinese locale and secret redaction."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from capture_studio import board_probe, camera_modes, camera_pick, errors, i2c_hints, lan_scan, peripherals, pc_peripherals, templates

BOARDS = {
    "kv260": ("ZynqMP SMK-K26 Rev1/B/A", "xlnx,zynqmp-smk-k26\nxlnx,zynqmp", "", "aarch64"),
    "zynq": ("Avnet Ultra96 v2", "avnet,ultra96\nxlnx,zynqmp", "", "aarch64"),
    "jetson": ("NVIDIA Jetson Orin Nano Developer Kit", "nvidia,p3768-0000+p3767-0005\nnvidia,tegra234",
               "# R36 (release), REVISION: 3.0, GCID: 1, BOARD: generic", "aarch64"),
    "raspberrypi": ("Raspberry Pi 5 Model B Rev 1.0", "raspberrypi,5-model-b\nbrcm,bcm2712", "", "aarch64"),
    "rockchip": ("Radxa ROCK 5B", "radxa,rock-5b\nrockchip,rk3588", "", "aarch64"),
}


def info_text(model, compat, tegra, arch, extra=""):
    return (f"@@model\n{model}\n@@compatible\n{compat}\n@@dmi\nsys_vendor=\n@@tegra\n{tegra}\n@@cpuinfo\nHardware\t: x\n"
            f"@@osrelease\nPRETTY_NAME=\"Ubuntu 22.04.4 LTS\"\n@@kernel\nLinux 5.15.0 {arch}\n@@nproc\n4\n"
            f"@@meminfo\nMemTotal:        3940000 kB\nMemAvailable:    2000000 kB\n@@df\n/dev/root 30000000 10000000 20000000 34% /\n"
            f"@@hostname\nboard\n@@ip\n192.168.1.50 172.17.0.1\n@@uptime\n1234.5 99\n@@tools\nv4l2-ctl\nffmpeg\n{extra}@@end\n")


class BoardInfo(unittest.TestCase):
    def test_families(self):
        for family, (model, compat, tegra, arch) in BOARDS.items():
            info = board_probe.parse_info(info_text(model, compat, tegra, arch))
            self.assertEqual(info["family"], family, model)
            self.assertEqual(info["model"], model)
            self.assertEqual(info["cores"], 4)
            self.assertEqual(info["mem_total"], 3940000 * 1024)
            self.assertEqual(info["arch"], "aarch64")
        self.assertEqual(board_probe.parse_info(info_text(*BOARDS["jetson"]))["l4t"], "L4T R36.3.0")

    def test_kv260_xmutil_and_trips(self):
        extra = ("@@fpga\noperating\nfpga0\n@@xmutil\n       Accelerator          Accel_type   Base   Base_type  #slots(PL+AIE)  Active_slot\n"
                 "  k26-starter-kits             XRT_FLAT  k26-starter-kits  XRT_FLAT  (0+0)  0,\n"
                 "  kv260-smartcam            XRT_FLAT  kv260-smartcam  XRT_FLAT  (0+0)  -1\n"
                 "@@trips\ncpu-thermal:critical:100000\nbad line\n")
        text = info_text(*BOARDS["kv260"]).replace("@@tools\nv4l2-ctl\n", "@@tools\nxmutil\nv4l2-ctl\n").replace("@@end\n", extra + "@@end\n")
        info = board_probe.parse_info(text)
        self.assertEqual(info["fpga_app"], "k26-starter-kits")
        self.assertEqual(info["fpga_state"], "operating")
        self.assertEqual(info["thermal_trips"], [("cpu-thermal", "critical", 100.0)])

    def test_empty_and_garbage(self):
        info = board_probe.parse_info("")
        self.assertEqual(info["family"], "linux")
        board_probe.parse_info("@@model\n\n@@nproc\nabc\n@@uptime\nxx\n")


ZH_APLAY = ("**** PLAYBACK 硬體裝置清單 ****\n卡 0: PCH [HDA Intel PCH], 设备 0: ALC892 Analog [ALC892 Analog]\n"
            "  子设备: 1/1\n")
EN_APLAY = "**** List of PLAYBACK Hardware Devices ****\ncard 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]\n"


class BoardPeripherals(unittest.TestCase):
    def test_alsa_english_and_chinese_locale(self):
        self.assertEqual(len(peripherals.parse_alsa(EN_APLAY, "播放")), 1)
        zh = peripherals.parse_alsa(ZH_APLAY, "播放")
        self.assertEqual(len(zh), 1)
        self.assertEqual(zh[0]["name"], "HDA Intel PCH")

    def test_script_forces_c_locale(self):
        self.assertIn("LC_ALL=C", peripherals.SCRIPT.split("\n", 3)[1] + peripherals.SCRIPT.split("\n", 3)[0])

    def test_i2cdetect_rows(self):
        body = ("     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f\n00:          -- -- -- -- -- -- -- -- -- -- -- -- -- \n"
                "10: -- -- -- -- -- -- -- -- -- -- 1a -- -- -- -- -- \n30: -- -- -- -- -- -- UU -- -- -- -- -- 3c -- -- -- \n"
                "70: -- -- -- -- -- -- -- 77                         \n")
        self.assertEqual(peripherals.parse_i2cdetect(body), ["0x1a", "0x36 (驱动占用)", "0x3c", "0x77"])
        self.assertEqual(peripherals.parse_i2cdetect("Error: Could not open file `/dev/i2c-9'"), [])
        self.assertIn("IMX219", i2c_hints.describe("0x1a (驱动占用)"))
        self.assertTrue(i2c_hints.describe("zz"))

    def test_full_mock_inventory(self):
        text = "\n".join([
            "@@usb 1-1", "idVendor=1a86", "idProduct=7523", "product=USB Serial", "bDeviceClass=ff", "speed=12", "iface=ff ch341",
            "@@usb 2-1", "idVendor=046d", "idProduct=0825", "manufacturer=Logitech", "product=C270", "bDeviceClass=ef", "speed=480",
            "@@lsusb", "Bus 001 Device 002: ID 1a86:7523 QinHeng Electronics CH340 serial converter",
            "@@video /dev/video0", "sysname=UVC Camera", "Driver Info:", "\tDriver name      : uvcvideo", "\tCard type        : UVC Camera (046d:0825)",
            "\tBus info         : usb-xhci-1", "\tDevice Caps      : 0x04200001", "\t\tVideo Capture", "\t\tStreaming",
            "@@vfmt /dev/video0", "\t[0]: 'MJPG' (Motion-JPEG, compressed)", "\t\tSize: Discrete 1280x720", "\t\t\tInterval: Discrete 0.033s (30.000 fps)",
            "@@serial /dev/ttyUSB0", "SYSDRIVER=ch341", "ID_VENDOR_ID=1a86", "ID_MODEL_ID=7523",
            "@@serial /dev/ttyS3", "SYSDRIVER=port",
            "@@net lo", "operstate=unknown", "@@net eth0", "operstate=up", "speed=1000", "address=aa:bb", "driver=macb",
            "@@net wlan0", "operstate=down", "speed=-1", "driver=brcmfmac", "wireless=1",
            "@@ipaddr", "2: eth0    inet 192.168.1.50/24 brd 192.168.1.255 scope global eth0",
            "@@lsblk", json.dumps({"blockdevices": [{"name": "mmcblk0", "size": 31914983424, "type": "disk", "children": [
                {"name": "mmcblk0p1", "size": "268435456", "fstype": "vfat", "mountpoint": "/boot", "type": "part"}]},
                {"name": "loop0", "size": 1, "type": "loop"}]}),
            "@@aplay", EN_APLAY, "@@arecord", "", "@@asound", "", "@@gpiodetect", "gpiochip0 [zynqmp_gpio] (174 lines)",
            "@@drm card0-HDMI-A-1", "status=disconnected", "enabled=disabled", "mode=", "edid=",
            "@@spidev", "/dev/spidev0.0", "@@lspci", "", "@@end"])
        items = peripherals.parse_peripherals(text)
        cats = [i["category"] for i in items]
        for c in ("usb", "video", "serial", "net", "storage", "audio", "gpio", "display", "spi"):
            self.assertIn(c, cats)
        serial = [i for i in items if i["category"] == "serial"]
        self.assertEqual(len(serial), 1)  # ttyS placeholder dropped
        self.assertIn("CH34", serial[0]["summary"])
        video = next(i for i in items if i["category"] == "video")
        self.assertIn("1 种模式", video["summary"])
        self.assertNotIn("lo", [i["name"] for i in items if i["category"] == "net"])
        wlan = next(i for i in items if i["name"] == "wlan0")
        self.assertIn("无线", wlan["summary"])
        self.assertEqual(len([i for i in items if i["category"] == "storage"]), 2)
        self.assertTrue(peripherals.as_text(items))

    def test_garbage_blocks(self):
        self.assertEqual(peripherals.parse_peripherals(""), [])
        peripherals.parse_peripherals("@@lsblk\n{not json\n@@usb x\n@@video\n@@end")


class PcSide(unittest.TestCase):
    def test_pnp_parse(self):
        rows = [{"Class": "Camera", "FriendlyName": "USB2.0 HD UVC WebCam", "InstanceId": r"USB\VID_13D3&PID_56FF&MI_00\6&1",
                 "Status": "OK", "Manufacturer": "Microsoft"},
                {"Class": "USB", "FriendlyName": "USB Root Hub (USB 3.0)", "InstanceId": r"USB\ROOT_HUB30\4&1", "Status": "OK"},
                {"Class": "Ports", "FriendlyName": "USB-SERIAL CH340 (COM5)", "InstanceId": r"USB\VID_1A86&PID_7523\5&2", "Status": "OK"},
                {"Class": "Bogus", "FriendlyName": "x", "InstanceId": "y"}]
        items = pc_peripherals.parse_pnp(json.dumps(rows))
        self.assertEqual([i["category"] for i in items], ["video", "serial"])
        self.assertTrue(items[0]["summary"].startswith("13d3:56ff"))
        self.assertEqual(pc_peripherals.parse_pnp("garbage"), [])
        self.assertEqual(len(pc_peripherals.parse_pnp(json.dumps(rows[0]))), 1)

    def test_camera_pick_order(self):
        a = {"value": "Cam A", "vid": "046d", "pid": "0825"}
        b = {"value": "Cam B", "vid": "13d3", "pid": "56ff"}
        ir = {"value": "IR Cam"}
        self.assertEqual(camera_pick.pick_camera([a, b], "Cam B", ""), ("Cam B", "last"))
        self.assertEqual(camera_pick.pick_camera([a, b], "gone", "13d3:56ff"), ("Cam B", "vidpid"))
        self.assertEqual(camera_pick.pick_camera([a, ir], "", ""), ("Cam A", "sole_uvc"))
        self.assertEqual(camera_pick.pick_camera([ir], "", ""), ("IR Cam", "sole"))
        self.assertEqual(camera_pick.pick_camera([a, b], "", ""), ("", "need_manual"))
        self.assertEqual(camera_pick.pick_camera([], "", ""), ("", "none"))
        twins = [dict(a, value="Cam A #1"), dict(a, value="Cam A #2")]
        self.assertEqual(camera_pick.pick_camera(twins, "", "046d:0825")[1], "need_manual")

    def test_dshow_options(self):
        text = ("[dshow @ 0] vcodec=mjpeg  min s=1280x720 fps=5 max s=1280x720 fps=30\n"
                "[dshow @ 0] pixel_format=yuyv422  min s=640x480 fps=30 max s=640x480 fps=30 (tv, bt470bg/bt709/unknown, topleft)\n"
                "[dshow @ 0] pixel_format=nv12  min s=640x480 fps=30 max s=640x480 fps=30\n"
                "[dshow @ 0] vcodec=mjpeg  min s=1920x1080 fps=5 max s=1920x1080 fps=29.97\n")
        modes = camera_modes.parse_dshow_options(text)
        self.assertIn({"width": 1280, "height": 720, "fps": 30, "format": "mjpeg"}, modes)
        self.assertIn({"width": 640, "height": 480, "fps": 30, "format": "raw"}, modes)
        self.assertIn({"width": 1920, "height": 1080, "fps": 30, "format": "mjpeg"}, modes)
        self.assertEqual(len(modes), 3)


class Lan(unittest.TestCase):
    def test_banner_and_virtual(self):
        class Sock:
            def __init__(self, data): self.data = data
            def settimeout(self, t): pass
            def recv(self, n): return self.data
            def close(self): pass
        self.assertIsNone(lan_scan.probe("1.2.3.4", connect=lambda *a, **k: Sock(b"HTTP/1.1 400")))
        hit = lan_scan.probe("1.2.3.4", connect=lambda *a, **k: Sock(b"SSH-2.0-OpenSSH_8.9p1 Ubuntu-3\r\n"))
        self.assertEqual(hit["hint"], "Ubuntu")
        hosts = lan_scan.candidate_hosts([("198.18.0.1", 15), ("192.168.1.7", 24), ("169.254.1.1", 16), ("8.8.8.8", 24)])
        self.assertEqual(len(hosts), 253)
        self.assertNotIn("192.168.1.7", hosts)
        for name in ("vEthernet (WSL)", "Meta", "Mihomo", "VMware Network Adapter VMnet8", "Clash TUN"):
            self.assertTrue(lan_scan.VIRTUAL_ADAPTER.search(name), name)
        self.assertFalse(lan_scan.VIRTUAL_ADAPTER.search("以太网 Realtek PCIe GbE"))


class Secrets(unittest.TestCase):
    def test_redaction_variants(self):
        logs = ['{"password": "hunter2"}', "sshpass -p hunter2 ssh root@b", "CAPTURE_STUDIO_SSH_PASSWORD=hunter2",
                "Authorization: Bearer abcdef123456", "DEEPSEEK_API_KEY=sk-1234567890abcdef", "token: hunter2",
                r"C:\Users\PC\.ssh\id_ed25519", "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAhunter2\n-----END OPENSSH PRIVATE KEY-----"]
        state = {"logs": logs, "settings": {"password": "hunter2", "host": "192.168.1.50", "ssh_key": "C:/k"},
                 "last_error": "auth failed password=hunter2", "board_info": {"api_token": "sk-zzz"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = errors.bundle(Path(tmp) / "b.zip", state)
            with zipfile.ZipFile(path) as zf:
                blob = "\n".join(zf.read(n).decode("utf-8") for n in zf.namelist())
                for name in zf.namelist():
                    if name.endswith(".json"):
                        json.loads(zf.read(name))
        for secret in ("hunter2", "abcdef123456", "sk-1234567890abcdef", "sk-zzz", "AAAA"):
            self.assertNotIn(secret, blob, secret)
        self.assertNotIn(r"C:\Users\PC", blob)
        self.assertIn("192.168.1.50", blob)

    def test_serial_errors_are_specific(self):
        busy = "could not open port 'COM1': PermissionError(13, '拒绝访问。', None, 5)"
        gone = "could not open port 'COM99': FileNotFoundError(2, '系统找不到指定的文件。', None, 2)"
        self.assertEqual(errors.friendly(busy)["title"], "串口被占用")
        self.assertEqual(errors.friendly(gone)["title"], "找不到这个串口")

    def test_friendly(self):
        for raw in ("Permission denied (publickey,password)", "Connection timed out", "ssh: Could not resolve hostname x",
                    "No route to host", "Device or resource busy", "", "完全未知"):
            info = errors.friendly(raw)
            self.assertTrue(info["title"] and info["advice"])


class Templates(unittest.TestCase):
    def test_roundtrip_and_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.json"
            tpl = templates.capture({"width": 1280, "height": 720, "fps": 30, "output": r"D:\cap\20260101_lab"}, "实验 A/B")
            templates.save(path, "室内 / 日光灯", tpl)
            loaded = templates.load_all(path)
            self.assertEqual(len(loaded), 1)
            name = next(iter(loaded))
            applied = templates.apply({"output": r"D:\cap"}, loaded[name])
            self.assertEqual(str(applied.get("width")), "1280")
            templates.delete(path, name)
            self.assertEqual(templates.load_all(path), {})
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(templates.load_all(path), {})
        self.assertNotIn("/", templates.safe_scene("a/b\\c:d"))


class SerialSession(unittest.TestCase):
    def test_close_while_reading_is_not_an_error(self):
        import threading
        import time
        from capture_studio import serial_term
        gate = threading.Event()

        class Port:
            in_waiting = 0
            def read(self, n):
                gate.wait(1)
                raise OSError("port closed")
            def close(self):
                gate.set()
        session = serial_term.open_pc("COM9", 115200, serial_factory=lambda *a, **k: Port())
        session.start(lambda data: None)
        time.sleep(0.05)
        session.close()
        time.sleep(0.1)
        self.assertEqual(session.error, "")

    def test_open_missing_port_raises(self):
        from capture_studio import serial_term
        def factory(*a, **k):
            raise OSError("could not open port 'COM99'")
        session = serial_term.open_pc("COM99", 115200, serial_factory=factory)
        with self.assertRaises(OSError):
            session.start(lambda d: None)
        session.close()


if __name__ == "__main__":
    unittest.main()
