"""Board-agnostic info / status parsers (v6) with realistic sample outputs. Pure CPU, no board needed."""
import unittest

from capture_studio.board_probe import (INFO_SCRIPT, STATUS_SCRIPT, StatusMonitor, StatusParser, capabilities,
                                        parse_info, parse_tegrastats, probe_info, sections, ssh_command)

KV260 = """@@model
ZynqMP SMK-K26 Rev1/B/A
@@compatible
xlnx,zynqmp-sk-kv260-revB
xlnx,zynqmp-sk-kv260
xlnx,zynqmp
@@dmi
sys_vendor=
product_name=
board_vendor=
board_name=
@@tegra
@@cpuinfo
processor\t: 0
@@osrelease
PRETTY_NAME="Ubuntu 22.04.4 LTS"
NAME="Ubuntu"
@@kernel
Linux 5.15.0-1027-xilinx-zynqmp aarch64
@@nproc
4
@@meminfo
MemTotal:        3955140 kB
MemAvailable:    3012345 kB
@@df
/dev/mmcblk1p2  30297672 9123456 19842312  32% /
@@hostname
kria
@@ip
192.168.1.50 172.17.0.1
@@uptime
93784.21 350000.00
@@tools
xmutil
fpgautil
v4l2-ctl
python3
@@fpga
operating
fpga0
@@xmutil
       Accelerator          Accel_type                            Base           Base_type      #slots(PL+AIE)         Active_slot

    k26-starter-kits             XRT_FLAT                k26-starter-kits            XRT_FLAT               (0+0)                  0,
      kv260-smartcam             XRT_FLAT                  kv260-smartcam           XRT_FLAT               (0+0)                  -1
@@rknpu
@@end
"""

JETSON = """@@model
NVIDIA Jetson Orin Nano Developer Kit
@@compatible
nvidia,p3768-0000+p3767-0005
nvidia,tegra234
@@dmi
@@tegra
# R35 (release), REVISION: 4.1, GCID: 33958178, BOARD: t186ref, EABI: aarch64, DATE: Tue Aug  1 19:57:35 UTC 2023
@@cpuinfo
model name\t: ARMv8 Processor rev 1 (v8l)
@@osrelease
PRETTY_NAME="Ubuntu 20.04.6 LTS"
@@kernel
Linux 5.10.120-tegra aarch64
@@nproc
6
@@meminfo
MemTotal:        7471004 kB
MemAvailable:    5000000 kB
@@df
/dev/nvme0n1p1 122485160 30000000 86230000 26% /
@@hostname
orin
@@ip
10.0.0.7
@@tools
tegrastats
v4l2-ctl
gst-launch-1.0
@@fpga
@@xmutil
@@rknpu
@@end
"""

RPI = """@@model
Raspberry Pi 5 Model B Rev 1.0
@@compatible
raspberrypi,5-model-b
brcm,bcm2712
@@cpuinfo
Revision\t: d04170
Serial\t\t: 1234abcd
Model\t\t: Raspberry Pi 5 Model B Rev 1.0
@@osrelease
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
@@kernel
Linux 6.6.31+rpt-rpi-2712 aarch64
@@nproc
4
@@tools
vcgencmd
@@end
"""

RK3588 = """@@model
Radxa ROCK 5B
@@compatible
radxa,rock-5b
rockchip,rk3588
@@osrelease
PRETTY_NAME="Debian GNU/Linux 11 (bullseye)"
@@kernel
Linux 5.10.110-99-rockchip-g aarch64
@@nproc
8
@@rknpu
/sys/kernel/debug/rknpu
0.9.6
@@end
"""

X86 = """@@model

@@compatible
@@dmi
sys_vendor=Intel(R) Client Systems
product_name=NUC11TNHi5
board_vendor=Intel Corporation
board_name=NUC11TNBi5
@@cpuinfo
model name\t: 11th Gen Intel(R) Core(TM) i5-1135G7 @ 2.40GHz
@@osrelease
PRETTY_NAME="Ubuntu 24.04 LTS"
@@kernel
Linux 6.8.0-45-generic x86_64
@@nproc
8
@@end
"""

X86_NO_DMI = """@@model
@@dmi
sys_vendor=To Be Filled By O.E.M.
product_name=Default string
@@cpuinfo
model\t\t: 80
model name\t: AMD Ryzen 7 5800U
@@kernel
Linux 6.1.0 x86_64
@@end
"""

PYNQ = """@@model
Avnet Ultra96 Rev1
@@compatible
xlnx,zynqmp-zcu100-revC
xlnx,zynqmp
@@osrelease
PRETTY_NAME="PynqLinux, based on Ubuntu 22.04"
@@tools
fpgautil
@@fpga
operating
@@end
"""

BUSYBOX = """@@model
@@kernel
Linux 4.19.0 armv7l
@@nproc
@@meminfo
MemTotal:          60000 kB
@@end
"""


def status_block(user: int, idle: int, rx: int, tx: int, extra: str = "") -> str:
    return f"""@@stat
cpu  {user} 0 0 {idle} 0 0 0 0 0 0
@@meminfo
MemTotal:        4000000 kB
MemAvailable:    1000000 kB
@@thermal
cpu-thermal=52300
gpu-thermal=48100
bogus=abc
@@df
/dev/root 1000000 250000 750000 25% /
@@net
    lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0
  eth0: {rx} 10 0 0 0 0 0 0 {tx} 10 0 0 0 0 0 0
@@load
0.42 0.30 0.20 1/200 1234
{extra}@@end
"""


class InfoTests(unittest.TestCase):
    def test_kv260(self):
        info = parse_info(KV260)
        self.assertEqual(info["family"], "kv260")
        self.assertEqual(info["model"], "ZynqMP SMK-K26 Rev1/B/A")
        self.assertEqual(info["os"], "Ubuntu 22.04.4 LTS")
        self.assertEqual(info["arch"], "aarch64")
        self.assertEqual(info["cores"], 4)
        self.assertEqual(info["mem_total"], 3955140 * 1024)
        self.assertEqual(info["disk_free"], 19842312 * 1024)
        self.assertEqual(info["ip"], "192.168.1.50 172.17.0.1")
        self.assertEqual(info["uptime_s"], 93784)
        self.assertEqual(info["fpga_state"], "operating")
        self.assertEqual(info["fpga_app"], "k26-starter-kits")
        self.assertIn("xmutil", info["capabilities"])
        self.assertIn("fpga", info["capabilities"])
        self.assertNotIn("gpu", info["capabilities"])

    def test_jetson(self):
        info = parse_info(JETSON)
        self.assertEqual(info["family"], "jetson")
        self.assertEqual(info["l4t"], "L4T R35.4.1")
        self.assertIn("gpu", info["capabilities"])
        self.assertNotIn("xmutil", info["capabilities"])
        self.assertNotIn("fpga_state", info)

    def test_raspberry_pi(self):
        info = parse_info(RPI)
        self.assertEqual(info["family"], "raspberrypi")
        self.assertTrue(info["model"].startswith("Raspberry Pi 5"))
        self.assertEqual(info["os"], "Debian GNU/Linux 12 (bookworm)")
        self.assertEqual(info["capabilities"], [])

    def test_rk3588(self):
        info = parse_info(RK3588)
        self.assertEqual(info["family"], "rockchip")
        self.assertEqual(info["cores"], 8)
        self.assertIn("npu", info["capabilities"])
        self.assertIn("RKNPU", info["npu"])

    def test_x86_dmi_fallback(self):
        info = parse_info(X86)
        self.assertEqual(info["family"], "linux")
        self.assertEqual(info["model"], "Intel(R) Client Systems NUC11TNHi5")
        self.assertIn("i5-1135G7", info["cpu"])
        self.assertEqual(info["arch"], "x86_64")

    def test_placeholder_dmi_ignored(self):
        info = parse_info(X86_NO_DMI)
        self.assertEqual(info["model"], "Linux")
        self.assertEqual(info["cpu"], "AMD Ryzen 7 5800U")

    def test_pynq_zynq(self):
        info = parse_info(PYNQ)
        self.assertEqual(info["family"], "zynq")
        self.assertIn("fpga", info["capabilities"])
        self.assertNotIn("xmutil", info["capabilities"])

    def test_minimal_busybox_and_crlf(self):
        info = parse_info(BUSYBOX.replace("\n", "\r\n"))
        self.assertEqual(info["model"], "Linux")
        self.assertEqual(info["arch"], "armv7l")
        self.assertNotIn("cores", info)
        self.assertNotIn("os", info)

    def test_chinese_hostname_and_empty(self):
        info = parse_info("@@hostname\n实验板-1\n@@end\n")
        self.assertEqual(info["hostname"], "实验板-1")
        self.assertEqual(parse_info("")["family"], "linux")

    def test_sections(self):
        self.assertEqual(sections("junk\n@@a\n1\n@@b\n@@end\n"), {"a": "1", "b": ""})

    def test_capabilities_from_tools(self):
        self.assertEqual(capabilities({"tools": ["v4l2-ctl"]}), ["v4l2"])


class StatusTests(unittest.TestCase):
    def test_two_samples(self):
        parser = StatusParser()
        first = parser.feed(status_block(100, 900, 1000, 500), now=10.0)
        self.assertNotIn("cpu", first)
        self.assertNotIn("rx_bps", first)
        self.assertEqual(first["mem_used"], 3000000 * 1024)
        self.assertEqual(first["temp_max"], 52.3)
        self.assertEqual(len(first["temps"]), 2)
        self.assertEqual(first["disk_used"], 250000 * 1024)
        self.assertEqual(first["load"], "0.42")
        second = parser.feed(status_block(150, 950, 3000, 1500), now=12.0)
        self.assertEqual(second["cpu"], 50.0)
        self.assertEqual(second["rx_bps"], 1000.0)  # lo excluded
        self.assertEqual(second["tx_bps"], 500.0)

    def test_accelerators(self):
        block = status_block(1, 1, 1, 1, "@@gpu\n734\n@@npu\nNPU load:  Core0: 30%, Core1: 10%, Core2:  2%,\n@@fpga\noperating\n")
        status = StatusParser().feed(block, now=1.0)
        self.assertEqual(status["gpu"], 73.4)
        self.assertEqual(status["npu"], 14.0)
        self.assertEqual(status["fpga_state"], "operating")

    def test_absent_probes(self):
        self.assertEqual(StatusParser().feed("@@stat\n@@end\n"), {})

    def test_tegrastats(self):
        line = "RAM 2716/7620MB (lfb 1x4MB) CPU [3%@729,1%@729] GR3D_FREQ 45% cpu@48.5C"
        out = parse_tegrastats(line)
        self.assertEqual(out["gpu"], 45.0)
        self.assertEqual(out["mem_total"], 7620 << 20)


class TransportTests(unittest.TestCase):
    def test_script_on_stdin(self):
        self.assertEqual(ssh_command(["ssh", "u@h"], INFO_SCRIPT)[-2:], ["sh", "-s"])
        self.assertIn("sleep 2", STATUS_SCRIPT % {"interval": 2})

    def test_probe_info_decodes_gbk(self):
        class Result:
            stdout = ("@@hostname\n实验板\n@@end\n").encode("gbk")
        seen = {}

        def run(args, **kwargs):
            seen.update(kwargs)
            return Result()
        info = probe_info(["ssh", "u@h"], run=run)
        self.assertEqual(info["hostname"], "实验板")
        self.assertIn(b"s model", seen["input"])

    def test_probe_info_failure(self):
        class Result:
            stdout = b"Permission denied"
        with self.assertRaises(RuntimeError):
            probe_info(["ssh"], run=lambda *a, **k: Result())

    def test_monitor_streams(self):
        import io
        import threading
        got, done = [], threading.Event()

        class Proc:
            def __init__(self, *a, **k):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO((status_block(1, 9, 0, 0) * 2).encode())

            def terminate(self):
                pass

        def on(status):
            got.append(status)
            if len(got) == 2:
                done.set()
        monitor = StatusMonitor(["ssh"], on, 2.0, popen=Proc)
        monitor.start()
        self.assertTrue(done.wait(3))
        monitor.stop()
        self.assertIn("mem_total", got[0])


if __name__ == "__main__":
    unittest.main()
