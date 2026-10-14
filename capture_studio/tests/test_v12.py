import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from capture_studio import board_discover, discovery, i18n

IPCONFIG_EN = """
Windows IP Configuration

Ethernet adapter Ethernet:

   Connection-specific DNS Suffix  . :
   Description . . . . . . . . . . . : Realtek PCIe GbE Family Controller
   Physical Address. . . . . . . . . : 3C-7C-3F-11-22-33
   Autoconfiguration IPv4 Address. . : 169.254.12.7(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.0.0
   Default Gateway . . . . . . . . . :

Wireless LAN adapter Wi-Fi:

   Description . . . . . . . . . . . : Intel(R) Wi-Fi 6 AX201
   Physical Address. . . . . . . . . : F4-B5-20-00-00-01
   Link-local IPv6 Address . . . . . : fe80::1234%5(Preferred)
   IPv4 Address. . . . . . . . . . . : 192.168.50.232(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.252.0
   Default Gateway . . . . . . . . . : fe80::1%5
                                       192.168.50.1

Unknown adapter Meta:

   Description . . . . . . . . . . . : Meta Tunnel
   IPv4 Address. . . . . . . . . . . : 198.18.0.1(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.255.252
   Default Gateway . . . . . . . . . :
"""

IPCONFIG_ZH = """
Windows IP 配置

以太网适配器 以太网:

   连接特定的 DNS 后缀 . . . . . . . :
   描述. . . . . . . . . . . . . . . : Realtek PCIe GbE Family Controller
   物理地址. . . . . . . . . . . . . : 3C-7C-3F-11-22-33
   IPv4 地址 . . . . . . . . . . . . : 192.168.1.20(首选)
   子网掩码  . . . . . . . . . . . . : 255.255.255.0
   默认网关. . . . . . . . . . . . . :

无线局域网适配器 WLAN:

   媒体状态  . . . . . . . . . . . . : 媒体已断开连接
   描述. . . . . . . . . . . . . . . : Intel(R) Wi-Fi 6 AX201
"""

ARP_ZH = """
接口: 169.254.12.7 --- 0x5
  Internet 地址         物理地址              类型
  169.254.88.3          00-0a-35-01-02-03     动态
  169.254.255.255       ff-ff-ff-ff-ff-ff     静态
  224.0.0.22            01-00-5e-00-00-16     静态

接口: 192.168.50.232 --- 0x9
  Internet 地址         物理地址              类型
  192.168.50.1         a4-bb-6d-00-00-01     动态
"""

ARP_EN = """
Interface: 10.1.2.3 --- 0x7
  Internet Address      Physical Address      Type
  10.1.2.50             dc-a6-32-aa-bb-cc     dynamic
"""

NEIGH = json.dumps([
    {"IPAddress": "192.168.0.10", "LinkLayerAddress": "00-0A-35-09-08-07", "State": 4, "InterfaceAlias": "以太网"},
    {"IPAddress": "192.168.0.11", "LinkLayerAddress": "00-00-00-00-00-00", "State": 0, "InterfaceAlias": "以太网"},
    {"IPAddress": "10.9.9.9", "LinkLayerAddress": "", "State": "Incomplete", "InterfaceAlias": "WLAN"},
])


class Ipconfig(unittest.TestCase):
    def test_english_link_local_and_gateway_continuation(self):
        adapters = discovery.parse_ipconfig(IPCONFIG_EN)
        eth, wifi, meta = adapters
        self.assertEqual(eth["ips"], [("169.254.12.7", 16)])
        self.assertEqual(eth["gateway"], "")
        self.assertEqual(wifi["ips"], [("192.168.50.232", 22)])
        self.assertEqual(wifi["gateway"], "192.168.50.1")
        self.assertTrue(wifi["wireless"])
        self.assertTrue(meta["virtual"])
        # consistent /24 rule: the /22 Wi-Fi only scans its own /24; 169.254 and fake-ip are never swept
        self.assertEqual([str(n) for n in discovery.subnets(adapters)], ["192.168.50.0/24"])

    def test_chinese_locale(self):
        eth, wlan = discovery.parse_ipconfig(IPCONFIG_ZH)
        self.assertEqual(eth["ips"], [("192.168.1.20", 24)])
        self.assertEqual(eth["mac"], "3C-7C-3F-11-22-33")
        self.assertEqual(eth["gateway"], "")
        self.assertTrue(wlan["disconnected"])
        self.assertTrue(wlan["wireless"])

    def test_guidance(self):
        en = discovery.guidance(discovery.parse_ipconfig(IPCONFIG_EN))
        self.assertEqual(len(en), 1)
        self.assertIn("169.254", en[0])
        zh = discovery.guidance(discovery.parse_ipconfig(IPCONFIG_ZH))
        self.assertEqual(len(zh), 1)
        self.assertIn("没有默认网关", zh[0])
        i18n.LANG = "en"
        try:
            self.assertNotRegex(i18n.tr_msg(en[0]).replace("以太网", ""), "[\u4e00-\u9fff]")
            self.assertNotRegex(i18n.tr_msg(zh[0]).replace("以太网", ""), "[\u4e00-\u9fff]")
        finally:
            i18n.LANG = "zh"


class Neighbors(unittest.TestCase):
    def test_arp_zh_en(self):
        zh = discovery.parse_arp(ARP_ZH)
        self.assertEqual(zh["169.254.88.3"]["interface"], "169.254.12.7")
        self.assertEqual(zh["169.254.88.3"]["type"], "动态")
        self.assertIn("10.1.2.50", discovery.parse_arp(ARP_EN))

    def test_filter(self):
        table = discovery.parse_arp(ARP_ZH)
        keep = discovery.usable_neighbors(table, {"169.254.12.7"})
        self.assertIn("169.254.88.3", keep)  # link-local neighbour kept
        self.assertNotIn("169.254.255.255", keep)
        self.assertNotIn("224.0.0.22", keep)

    def test_netneighbor(self):
        table = discovery.parse_netneighbor(NEIGH)
        self.assertEqual(list(table), ["192.168.0.10"])
        self.assertEqual(discovery.parse_netneighbor("{bad"), {})
        single = discovery.parse_netneighbor(json.dumps({"IPAddress": "10.0.0.2", "LinkLayerAddress": "B8-27-EB-00-00-01", "State": "Reachable"}))
        self.assertIn("10.0.0.2", single)

    def test_read_neighbors_merges(self):
        class R:
            def __init__(self, out):
                self.stdout = out

        def run(cmd, **kw):
            return R(NEIGH.encode() if cmd[0] == "powershell" else ARP_ZH.encode("gbk"))
        table = discovery.read_neighbors(run)
        self.assertIn("192.168.0.10", table)
        self.assertIn("169.254.88.3", table)


class Vendors(unittest.TestCase):
    def test_oui(self):
        self.assertEqual(discovery.vendor_of("00-0a-35-01-02-03"), ("Xilinx", "board"))
        self.assertEqual(discovery.vendor_of("B8:27:EB:00:00:00")[0], "Raspberry Pi")
        self.assertEqual(discovery.vendor_of("00:04:4b:00:00:00")[0], "NVIDIA")
        self.assertEqual(discovery.vendor_of("a4-bb-6d-00-00-01"), ("Dell", "pc"))
        self.assertEqual(discovery.vendor_of("02-11-22-33-44-55")[0], "随机 MAC")
        self.assertEqual(discovery.vendor_of(""), ("", ""))

    def test_classify_names_and_banner(self):
        self.assertEqual(discovery.classify({"host": "x", "name": "jetson.local"})["kind"], "board")
        self.assertEqual(discovery.classify({"host": "x", "banner": "SSH-2.0-dropbear_2020"})["kind"], "board")
        self.assertEqual(discovery.classify({"host": "x", "banner": "SSH-2.0-OpenSSH_for_Windows_8.1"})["kind"], "pc")
        self.assertEqual(discovery.classify({"host": "x", "banner": "SSH-2.0-OpenSSH_8.9 Ubuntu"})["kind"], "linux")


class Mdns(unittest.TestCase):
    def test_resolve_keeps_link_local(self):
        answers = {"kria.local": ["169.254.88.3"], "raspberrypi.local": ["192.168.1.30", "8.8.8.8"]}
        found = discovery.resolve_names(resolver=lambda h: answers.get(h, []))
        self.assertEqual(found, {"169.254.88.3": "kria.local", "192.168.1.30": "raspberrypi.local"})

    def test_timeout_does_not_block(self):
        import time
        start = time.time()
        found = discovery.resolve_names(names=["slow"], timeout=0.2, resolver=lambda h: time.sleep(1) or ["10.0.0.1"])
        self.assertEqual(found, {})
        self.assertLess(time.time() - start, 0.8)

    def test_zeroconf_optional(self):
        self.assertIsInstance(discovery.browse_ssh(0.01), dict)


class Discover(unittest.TestCase):
    def test_end_to_end_ranked(self):
        adapters = discovery.parse_ipconfig(IPCONFIG_EN)
        neighbors = discovery.parse_arp(ARP_ZH)
        neighbors.update(discovery.parse_netneighbor(NEIGH))
        ssh = {"169.254.88.3": "SSH-2.0-OpenSSH_8.9p1 Ubuntu", "192.168.50.7": "SSH-2.0-OpenSSH_for_Windows_9.5",
               "192.168.50.40": "SSH-2.0-OpenSSH_8.9 Debian", "192.168.0.10": "SSH-2.0-OpenSSH_8.2",
               "192.168.1.30": "SSH-2.0-OpenSSH_9.2 Raspbian"}
        probed = []

        def prober(host):
            probed.append(host)
            return {"host": host, "banner": ssh[host], "hint": discovery.banner_hint(ssh[host])} if host in ssh else None
        result = discovery.discover(adapters, neighbors, {"192.168.1.30": "raspberrypi.local"}, prober)
        hosts = [r["host"] for r in result["found"]]
        # boards first (Xilinx link-local, Xilinx static other subnet, RPi via mDNS), then Linux, then the Windows PC
        self.assertEqual(hosts, ["169.254.88.3", "192.168.0.10", "192.168.1.30", "192.168.50.40", "192.168.50.7"])
        self.assertEqual(result["found"][0]["vendor"], "Xilinx")
        self.assertTrue(result["found"][0]["link_local"])
        self.assertNotIn("169.254.12.7", probed)
        self.assertNotIn("192.168.50.232", probed)
        self.assertFalse(any(h.startswith("169.254.") and h != "169.254.88.3" for h in probed))  # no /16 sweep
        self.assertEqual(len(probed), 253 + 3)
        self.assertEqual(result["subnets"], ["192.168.50.0/24"])
        self.assertTrue(result["guidance"])
        label = discovery.label_for(result["found"][0])
        self.assertIn("开发板", label)
        self.assertIn("Xilinx", label)

    def test_pick(self):
        found = [{"host": "10.0.0.5", "kind": "board", "vendor": "Xilinx"}, {"host": "10.0.0.6", "kind": "pc"}]
        self.assertEqual(board_discover.pick_from_discovery(found)[0], "10.0.0.5")
        self.assertEqual(board_discover.pick_from_discovery([{"host": "10.0.0.6", "kind": "pc"},
                                                             {"host": "10.0.0.7", "kind": "linux"}])[0], "10.0.0.7")
        self.assertEqual(board_discover.pick_from_discovery(found[:1] * 2 + [{"host": "10.0.0.8", "kind": "board"}])[0], "")
        self.assertEqual(board_discover.pick_from_discovery([])[0], "")

    def test_test_one(self):
        ok, text = discovery.test_one("192.168.1.10", prober=lambda h: {"host": h, "banner": "SSH-2.0-x"})
        self.assertTrue(ok)
        self.assertIn("SSH-2.0-x", text)
        self.assertFalse(discovery.test_one("192.168.1.10", prober=lambda h: None)[0])
        self.assertFalse(discovery.test_one("a b;c", prober=lambda h: None)[0])


class WizardUi(unittest.TestCase):
    def test_wizard_shows_tags_guidance_and_test(self):
        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication.instance() or QApplication([])
        from capture_studio import v7_ui
        parent = QWidget()
        wiz = v7_ui.Wizard(parent, scanner=lambda: None)
        wiz._scan_finished({"found": [{"host": "169.254.88.3", "banner": "SSH-2.0-x", "hint": "Ubuntu",
                                       "mac": "00-0a-35-01-02-03"}], "guidance": ["有线网卡“以太网”（192.168.1.5）没有默认网关，可能是直连。"]})
        self.assertIn("Xilinx", wiz.hosts.item(0).text())
        self.assertFalse(wiz.guide.isHidden())
        self.assertEqual(wiz.chosen_host() or wiz.hosts.item(0).data(256), "169.254.88.3")
        wiz._scan_finished([{"host": "10.0.0.3", "banner": "SSH-2.0-x", "hint": ""}])  # legacy list shape
        self.assertEqual(wiz.hosts.count(), 1)
        self.assertTrue(wiz.guide.isHidden())
        wiz._test_finished([True, "10.0.0.3 有 SSH 应答：SSH-2.0-x"])
        self.assertTrue(wiz.test_button.isEnabled())
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
