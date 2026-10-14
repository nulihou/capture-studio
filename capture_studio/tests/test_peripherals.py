"""Peripheral discovery parsers (v6) with realistic sample outputs. Pure CPU, no board needed."""
import unittest

from capture_studio.peripherals import (as_text, blocks, diff, edid_name, parse_i2cdetect, parse_lspci,
                                        parse_peripherals, scan)

def _edid(name=b"DELL P2419H"):
    data = bytearray(128)
    data[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    data[8:10] = bytes([0x10, 0xAC])  # "DEL"
    data[72:77] = b"\x00\x00\x00\xfc\x00"
    data[77:90] = (name + b"\n").ljust(13, b" ")
    return data.hex()


EDID = _edid()

SAMPLE = f"""@@usb 1-1
idVendor=046d
idProduct=0825
manufacturer=
product=
bDeviceClass=ef
speed=480
version= 2.00
serial=4A1B2C3D
busnum=1
devnum=3
iface=0e uvcvideo
iface=0e uvcvideo
iface=01 snd-usb-audio
@@usb 1-2
idVendor=1a86
idProduct=7523
product=USB Serial
bDeviceClass=ff
speed=12
iface=ff ch341
@@usb usb1
idVendor=1d6b
idProduct=0002
manufacturer=Linux 5.15.0 xhci-hcd
product=xHCI Host Controller
bDeviceClass=09
speed=480
maxchild=4
@@lsusb
Bus 001 Device 003: ID 046d:0825 Logitech, Inc. Webcam C270
Bus 001 Device 004: ID 1a86:7523 QinHeng Electronics CH340 serial converter
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
@@video /dev/video0
sysname=UVC Camera (046d:0825)
Driver Info:
\tDriver name      : uvcvideo
\tCard type        : UVC Camera (046d:0825)
\tBus info         : usb-xhci-hcd.1.auto-1
\tDriver version   : 5.15.39
\tCapabilities     : 0x84a00001
\t\tVideo Capture
\t\tMetadata Capture
\t\tStreaming
\t\tExtended Pix Format
\t\tDevice Capabilities
\tDevice Caps      : 0x04200001
\t\tVideo Capture
\t\tStreaming
\t\tExtended Pix Format
@@vfmt /dev/video0
ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'YUYV' (YUYV 4:2:2)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t[1]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.033s (30.000 fps)
@@video /dev/video1
sysname=UVC Camera (046d:0825)
Driver Info:
\tDriver name      : uvcvideo
\tDevice Caps      : 0x04a00000
\t\tMetadata Capture
\t\tStreaming
@@vfmt /dev/video1
@@serial /dev/ttyUSB0
SYSDRIVER=ch341-uart
ID_VENDOR_ID=1a86
ID_MODEL_ID=7523
ID_MODEL=USB_Serial
ID_VENDOR_FROM_DATABASE=QinHeng Electronics
ID_MODEL_FROM_DATABASE=CH340 serial converter
ID_PATH=platform-xhci-hcd.1.auto-usb-0:1.2:1.0
DEVLINKS=/dev/serial/by-path/platform-xhci-hcd.1.auto-usb-0:1.2:1.0-port0 /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
@@serial /dev/ttyPS1
SYSDRIVER=xuartps
@@serial /dev/ttyS3
SYSDRIVER=port
@@serial /dev/ttyACM0
SYSDRIVER=cdc_acm
ID_VENDOR_ID=2e8a
ID_MODEL_ID=000a
ID_SERIAL_SHORT=E66038B7134D5A2F
@@i2c 1
name=Cadence I2C at ff030000
client=1-0050|24c02|at24
client=1-001a|imx219|
@@i2cscan 1
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- UU -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: 50 -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- 68 -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- --
@@spi spi0.0
modalias=spi:spidev
driver=spidev
@@spidev
/dev/spidev0.0
@@net lo
operstate=unknown
@@net eth0
operstate=up
speed=1000
address=00:0a:35:00:22:01
mtu=1500
type=1
driver=macb
@@net wlan0
operstate=down
speed=
address=dc:a6:32:01:02:03
driver=brcmfmac
wireless=1
@@ipaddr
1: lo    inet 127.0.0.1/8 scope host lo
2: eth0    inet 192.168.1.50/24 brd 192.168.1.255 scope global eth0
@@lsblk
{{"blockdevices": [
  {{"name":"mmcblk1", "size":31914983424, "fstype":null, "mountpoint":null, "model":null, "type":"disk", "tran":null, "rm":false,
    "children": [{{"name":"mmcblk1p1", "size":268435456, "fstype":"vfat", "mountpoint":"/boot/firmware", "model":null, "type":"part", "tran":null, "rm":false}},
                 {{"name":"mmcblk1p2", "size":31645483008, "fstype":"ext4", "mountpoint":"/", "model":null, "type":"part", "tran":null, "rm":false}}]}},
  {{"name":"sda", "size":"64023257088", "fstype":"exfat", "mountpoint":"/media/U盘", "model":"SanDisk 3.2Gen1", "type":"disk", "tran":"usb", "rm":true}},
  {{"name":"loop0", "size":1000, "type":"loop"}}
]}}
@@aplay
**** List of PLAYBACK Hardware Devices ****
card 0: C270 [USB Device 0x46d:0x825], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
@@arecord
**** List of CAPTURE Hardware Devices ****
card 0: C270 [USB Device 0x46d:0x825], device 0: USB Audio [USB Audio]
@@asound
 0 [C270           ]: USB-Audio - USB Device 0x46d:0x825
@@gpiodetect
gpiochip0 [zynqmp_gpio] (174 lines)
gpiochip1 [firmware:zynqmp-firmware:gpio] (4 lines)
@@gpiochip gpiochip338
label=zynqmp_gpio
ngpio=174
@@drm card0-DP-1
status=connected
enabled=enabled
mode=1920x1080
edid={EDID}
@@drm card0-HDMI-A-1
status=disconnected
enabled=disabled
mode=
edid=
@@lspci
0000:00:00.0 PCI bridge [0604]: NVIDIA Corporation Device [10de:229e] (rev a1)
\tKernel driver in use: pcieport
0000:01:00.0 Non-Volatile memory controller [0108]: Samsung Electronics Co Ltd NVMe SSD Controller SM981/PM981/PM983 [144d:a808]
\tSubsystem: Samsung Electronics Co Ltd SSD 970 EVO Plus [144d:a801]
\tKernel driver in use: nvme
\tKernel modules: nvme
@@end
"""


def by_id(items, key):
    return next(item for item in items if item["id"] == key)


def props(item):
    return dict(item["props"])


class PeripheralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = parse_peripherals(SAMPLE)

    def test_categories_sorted(self):
        cats = [item["category"] for item in self.items]
        self.assertEqual(cats, sorted(cats, key=["usb", "video", "serial", "i2c", "spi", "net", "storage", "audio", "gpio", "display", "pci"].index))

    def test_usb_with_lsusb_fallback_and_drivers(self):
        cam = by_id(self.items, "usb:1-1")
        self.assertEqual(cam["name"], "Logitech, Inc. Webcam C270")
        p = props(cam)
        self.assertEqual(p["VID:PID"], "046d:0825")
        self.assertEqual(p["速度"], "USB 2.0 高速")
        self.assertEqual(p["驱动"], "snd-usb-audio, uvcvideo")
        self.assertEqual(p["总线/设备"], "1/3")
        hub = props(by_id(self.items, "usb:usb1"))
        self.assertEqual(hub["端口数"], "4")
        self.assertEqual(hub["类别"], "集线器")

    def test_video_modes_and_metadata_node(self):
        v0 = by_id(self.items, "video:/dev/video0")
        self.assertEqual(props(v0)["驱动"], "uvcvideo")
        self.assertIn("2 种模式", v0["summary"])
        self.assertIn("1280×720 30fps MJPEG", [v for k, v in v0["props"] if k.startswith("模式")])
        self.assertIn("元数据节点", by_id(self.items, "video:/dev/video1")["summary"])

    def test_serial_chips(self):
        ch340 = by_id(self.items, "serial:/dev/ttyUSB0")
        self.assertEqual(props(ch340)["芯片"], "CH340")
        self.assertEqual(ch340["name"], "CH340 serial converter")
        self.assertTrue(props(ch340)["稳定链接"].startswith("/dev/serial/by-id/"))
        self.assertEqual(props(by_id(self.items, "serial:/dev/ttyPS1"))["芯片"], "Xilinx PS UART")
        self.assertEqual(props(by_id(self.items, "serial:/dev/ttyACM0"))["芯片"], "Raspberry Pi Pico (CDC)")
        self.assertFalse(any(item["id"] == "serial:/dev/ttyS3" for item in self.items))

    def test_i2c_clients_and_scan(self):
        bus = by_id(self.items, "i2c:1")
        p = props(bus)
        self.assertEqual(p["0x50"], "24c02 · at24")
        self.assertEqual(p["0x1a"], "imx219")
        self.assertEqual(bus["scan"], ["0x1a (驱动占用)", "0x50", "0x68"])

    def test_i2cdetect_first_row_offset(self):
        body = "     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f\n00:          03 -- -- -- -- -- -- -- -- -- -- -- --\n"
        self.assertEqual(parse_i2cdetect(body), ["0x03"])
        self.assertEqual(parse_i2cdetect("Error: Could not open file `/dev/i2c-1': Permission denied"), [])

    def test_spi(self):
        self.assertEqual(props(by_id(self.items, "spi:spi0.0"))["驱动"], "spidev")
        self.assertIn("spi:/dev/spidev0.0", [item["id"] for item in self.items])

    def test_net(self):
        ids = [item["id"] for item in self.items]
        self.assertNotIn("net:lo", ids)
        eth = props(by_id(self.items, "net:eth0"))
        self.assertEqual((eth["速率"], eth["IP"], eth["MAC"]), ("1000 Mb/s", "192.168.1.50/24", "00:0a:35:00:22:01"))
        self.assertEqual(props(by_id(self.items, "net:wlan0"))["类型"], "无线")

    def test_storage_tree_and_unicode_mount(self):
        sda = props(by_id(self.items, "storage:sda"))
        self.assertEqual((sda["型号"], sda["挂载点"], sda["可移动"], sda["接口"]), ("SanDisk 3.2Gen1", "/media/U盘", "是", "usb"))
        self.assertEqual(sda["容量"], "59.6 GB")
        self.assertEqual(props(by_id(self.items, "storage:mmcblk1p2"))["上级"], "mmcblk1")
        self.assertNotIn("storage:loop0", [item["id"] for item in self.items])

    def test_audio_playback_and_capture(self):
        audio = [item for item in self.items if item["category"] == "audio"]
        self.assertEqual(len(audio), 2)
        self.assertEqual(props(audio[0])["ALSA 设备"], "hw:0,0")

    def test_gpio_prefers_gpiodetect(self):
        gpio = [item for item in self.items if item["category"] == "gpio"]
        self.assertEqual([g["id"] for g in gpio], ["gpio:gpiochip0", "gpio:gpiochip1"])
        self.assertEqual(props(gpio[0])["引脚数"], "174")

    def test_display_edid(self):
        dp = by_id(self.items, "display:card0-DP-1")
        self.assertEqual(dp["name"], "DELL P2419H")
        self.assertEqual(props(dp)["厂商代码"], "DEL")
        self.assertEqual(edid_name(""), "")
        self.assertEqual(edid_name("zz"), "")
        self.assertEqual(by_id(self.items, "display:card0-HDMI-A-1")["name"], "HDMI-A-1")

    def test_lspci(self):
        nvme = by_id(self.items, "pci:0000:01:00.0")
        p = props(nvme)
        self.assertEqual((p["VID:DID"], p["驱动"], p["子系统"]), ("144d:a808", "nvme", "Samsung Electronics Co Ltd SSD 970 EVO Plus [144d:a801]"))
        self.assertEqual(len(parse_lspci("00:02.0 VGA compatible controller [0300]: Intel Corporation UHD Graphics 620 [8086:5917] (rev 07)")), 1)

    def test_absent_everything(self):
        self.assertEqual(parse_peripherals("@@lsusb\n@@lsblk\nnot json\n@@end\n"), [])
        self.assertEqual(parse_peripherals(""), [])

    def test_fallbacks_gpio_sysfs_and_asound(self):
        text = "@@gpiochip gpiochip0\nlabel=pinctrl-bcm2711\nngpio=58\n@@asound\n 0 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones\n@@end\n"
        items = parse_peripherals(text)
        self.assertEqual([i["category"] for i in items], ["audio", "gpio"])
        self.assertEqual(items[0]["name"], "bcm2835 Headphones")

    def test_crlf_and_blocks(self):
        self.assertEqual(blocks("@@a x\r\n1\r\n@@end\r\n"), [("a", "x", "1")])

    def test_text_and_diff(self):
        text = as_text(self.items)
        self.assertIn("[USB] Logitech, Inc. Webcam C270", text)
        old = [i for i in self.items if i["id"] != "serial:/dev/ttyUSB0"]
        added, removed = diff(old, self.items)
        self.assertEqual((added, removed), (["CH340 serial converter"], []))

    def test_scan_read_only_and_gbk(self):
        seen = {}

        class Result:
            stdout = "@@net eth0\noperstate=up\ndriver=r8169\n@@ipaddr\n2: eth0 inet 10.0.0.2/24\n@@lsblk\n{\"blockdevices\":[{\"name\":\"sda\",\"size\":1,\"mountpoint\":\"/媒体\",\"type\":\"disk\"}]}\n@@end\n".encode("gbk")

        def run(args, **kwargs):
            seen["args"], seen["input"] = args, kwargs["input"]
            return Result()
        items = scan(["ssh", "u@h"], run=run)
        self.assertEqual(seen["args"][-2:], ["sh", "-s"])
        self.assertTrue(seen["input"].startswith(b"I2CSCAN=0"))
        self.assertEqual(props(by_id(items, "storage:sda"))["挂载点"], "/媒体")
        import re
        for pattern in (rb"i2cset", rb"i2ctransfer", rb">\s*/dev/(?!null)", rb"\brm\s", rb">\s*/sys", rb"\bdd\b", rb"\bsudo\b"):
            self.assertIsNone(re.search(pattern, seen["input"]), pattern)
        scan(["ssh"], i2c_scan=True, run=run)
        self.assertTrue(seen["input"].startswith(b"I2CSCAN=1"))
        self.assertIn(b"i2cdetect -y -r", seen["input"])

    def test_scan_failure(self):
        class Result:
            stdout = b"Permission denied (publickey)."
        with self.assertRaises(RuntimeError):
            scan(["ssh"], run=lambda *a, **k: Result())


if __name__ == "__main__":
    unittest.main()
