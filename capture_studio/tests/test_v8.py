import unittest

from capture_studio.board_discover import decode_console, ignored_address, prefixes_from_ipconfig
from capture_studio.desktop import parse_dshow_cameras, parse_dshow_devices
from capture_studio import lan_scan


IPCONFIG = """
以太网适配器 以太网:
   IPv4 地址 . . . . . . . . . . . . : 192.168.110.232
   子网掩码  . . . . . . . . . . . . : 255.255.255.0
   默认网关. . . . . . . . . . . . . : 192.168.110.1

未知适配器 Meta:
   IPv4 地址 . . . . . . . . . . . . : 198.18.0.1
   子网掩码  . . . . . . . . . . . . : 255.255.255.252
   默认网关. . . . . . . . . . . . . : 198.18.0.2

以太网适配器 VMware Network Adapter VMnet8:
   IPv4 地址 . . . . . . . . . . . . : 192.168.19.1
   子网掩码  . . . . . . . . . . . . : 255.255.255.0
   默认网关. . . . . . . . . . . . . : 192.168.19.2
"""

DSHOW = r"""
[dshow @ 1] DirectShow video devices
[dshow @ 1]  "USB Camera" (video)
[dshow @ 1]     Alternative name "@device_pnp_\\?\usb#vid_1c45&pid_6200&mi_00#a"
[dshow @ 1]  "USB Camera" (video)
[dshow @ 1]     Alternative name "@device_pnp_\\?\usb#vid_046d&pid_0825&mi_00#b"
[dshow @ 1] DirectShow audio devices
[dshow @ 1]  "Microphone" (audio)
"""


class DiscoveryTests(unittest.TestCase):
    def test_chinese_console_and_virtual_adapters_are_ignored(self):
        text = decode_console(IPCONFIG.encode("gbk"))
        self.assertIn("网关", text)
        self.assertEqual(["192.168.110."], prefixes_from_ipconfig(text))
        self.assertTrue(ignored_address("198.18.0.26"))
        self.assertFalse(ignored_address("192.168.110.35"))

    def test_fake_ip_and_empty_banner_are_not_boards(self):
        hosts = lan_scan.candidate_hosts([("198.18.0.1", 30), ("192.168.110.232", 24)])
        self.assertTrue(hosts)
        self.assertTrue(all(item.startswith("192.168.110.") for item in hosts))
        self.assertIsNone(lan_scan.probe("10.0.0.9", connect=lambda addr, timeout: _Sock(b"")))
        found = lan_scan.probe("10.0.0.9", connect=lambda addr, timeout: _Sock(b"SSH-2.0-OpenSSH_8.9\r\n"))
        self.assertEqual(found["hint"], "OpenSSH")


class CameraIdentityTests(unittest.TestCase):
    def test_same_dshow_name_keeps_vid_pid(self):
        cameras = parse_dshow_cameras(DSHOW)
        self.assertEqual(["USB Camera"], parse_dshow_devices(DSHOW))
        self.assertEqual([("1c45", "6200"), ("046d", "0825")], [(item["vid"], item["pid"]) for item in cameras])
        self.assertEqual(cameras[0]["label"], "USB Camera · 1c45:6200")
        self.assertTrue(all(item["value"] != item["name"] for item in cameras))


class _Sock:
    def __init__(self, banner: bytes) -> None:
        self.banner = banner

    def settimeout(self, _timeout: float) -> None:
        return None

    def recv(self, _count: int) -> bytes:
        return self.banner

    def close(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
