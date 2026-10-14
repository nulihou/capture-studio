"""Board-agnostic information and live status over the existing SSH login (v6).

Works with any SSH-reachable Linux board: KV260 / Zynq / PYNQ, Jetson, Raspberry Pi,
Rockchip (RK3588 ...), generic x86/ARM.  Every probe is optional; anything the board does
not have is simply absent from the result.  Nothing is installed on the board: one short
POSIX-sh script is sent over ssh and its sectioned output is parsed here.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from typing import Any, Callable

try:
    from .textcodec import safe_decode
except ImportError:  # loaded as a plain script
    from textcodec import safe_decode

# ---------------------------------------------------------------------------------------
# remote scripts (POSIX sh, BusyBox compatible, every command guarded with 2>/dev/null)
INFO_SCRIPT = r"""
s(){ echo "@@$1"; }
s model; tr -d '\0' </proc/device-tree/model 2>/dev/null || tr -d '\0' </sys/firmware/devicetree/base/model 2>/dev/null; echo
s compatible; tr '\0' '\n' </proc/device-tree/compatible 2>/dev/null || tr '\0' '\n' </sys/firmware/devicetree/base/compatible 2>/dev/null
s dmi; for f in sys_vendor product_name board_vendor board_name; do printf '%s=' $f; cat /sys/class/dmi/id/$f 2>/dev/null || echo; done
s tegra; cat /etc/nv_tegra_release 2>/dev/null
s cpuinfo; grep -iE '^(model name|hardware|revision|model|cpu part|cpu implementer|serial)[[:space:]]*:' /proc/cpuinfo 2>/dev/null
s osrelease; cat /etc/os-release 2>/dev/null
s kernel; uname -srm 2>/dev/null
s nproc; nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo 2>/dev/null
s meminfo; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo 2>/dev/null
s df; df -kP / 2>/dev/null | tail -n 1
s hostname; hostname 2>/dev/null || cat /etc/hostname 2>/dev/null
s ip; hostname -I 2>/dev/null || ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}'
s uptime; cat /proc/uptime 2>/dev/null
s tools; for t in xmutil fpgautil tegrastats jtop vcgencmd v4l2-ctl gst-launch-1.0 ffmpeg python3 nvidia-smi; do command -v $t >/dev/null 2>&1 && echo $t; done
s fpga; cat /sys/class/fpga_manager/fpga0/state 2>/dev/null; cat /sys/class/fpga_manager/fpga0/name 2>/dev/null
s xmutil; command -v xmutil >/dev/null 2>&1 && timeout 5 xmutil listapps 2>/dev/null | head -n 20
s trips; for z in /sys/class/thermal/thermal_zone*; do n=$(cat $z/type 2>/dev/null); for t in $z/trip_point_*_type; do [ -r "$t" ] && echo "$n:$(cat $t 2>/dev/null):$(cat ${t%_type}_temp 2>/dev/null)"; done; done
s rknpu; ls -d /sys/kernel/debug/rknpu /proc/rknpu 2>/dev/null; cat /sys/module/rknpu/version 2>/dev/null
s end
"""

STATUS_SCRIPT = r"""
while :; do
echo "@@stat"; head -n 1 /proc/stat 2>/dev/null
echo "@@meminfo"; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo 2>/dev/null
echo "@@thermal"; for z in /sys/class/thermal/thermal_zone*; do [ -r "$z/temp" ] && echo "$(cat $z/type 2>/dev/null)=$(cat $z/temp 2>/dev/null)"; done
echo "@@df"; df -kP / 2>/dev/null | tail -n 1
echo "@@net"; tail -n +3 /proc/net/dev 2>/dev/null
echo "@@load"; cat /proc/loadavg 2>/dev/null
echo "@@gpu"; cat /sys/devices/gpu.0/load /sys/devices/platform/gpu.0/load /sys/devices/platform/bus@0/17000000.gpu/load 2>/dev/null | head -n 1
echo "@@npu"; cat /sys/kernel/debug/rknpu/load 2>/dev/null || cat /proc/rknpu/load 2>/dev/null
echo "@@fpga"; cat /sys/class/fpga_manager/fpga0/state 2>/dev/null
echo "@@hot"; ls /sys/bus/usb/devices /dev 2>/dev/null | cksum
echo "@@end"
sleep %(interval)s
done
"""


def sections(text: str) -> dict[str, str]:
    """Split '@@name' sectioned output into {name: body}."""
    out: dict[str, str] = {}
    name = ""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith("@@"):
            if name:
                out[name] = "\n".join(lines).strip()
            name, lines = raw[2:].strip(), []
        elif name:
            lines.append(raw)
    if name and name != "end":
        out[name] = "\n".join(lines).strip()
    out.pop("end", None)
    return out


def _kv(text: str, sep: str = "=") -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if sep in line:
            key, value = line.split(sep, 1)
            result[key.strip().lower()] = value.strip().strip('"')
    return result


def _meminfo(text: str) -> tuple[int, int]:
    values = {k: int(re.sub(r"\D", "", v) or 0) for k, v in _kv(text, ":").items()}
    return values.get("memtotal", 0), values.get("memavailable", 0)


def _df(text: str) -> tuple[int, int]:
    parts = text.split()
    if len(parts) >= 4 and parts[1].isdigit() and parts[2].isdigit():
        return int(parts[1]) * 1024, int(parts[3]) * 1024
    return 0, 0


FAMILIES = (  # (family id, regex over model + compatible + cpuinfo + dmi)
    ("kv260", r"kv260|k26|smk-k26|xilinx k26"),
    ("zynq", r"zynqmp|zynq|xlnx,|pynq|ultra96|zcu1\d\d"),
    ("jetson", r"jetson|nvidia,tegra|tegra\d|p3768|p3701|p3448|p3737"),
    ("raspberrypi", r"raspberry pi|brcm,bcm27|brcm,bcm2835|brcm,bcm2712"),
    ("rockchip", r"rockchip|rk35\d\d|rk33\d\d|rk3588|orange pi 5|rock 5|radxa"),
)
FAMILY_NAMES = {"kv260": "AMD Xilinx KV260", "zynq": "Xilinx Zynq", "jetson": "NVIDIA Jetson",
                "raspberrypi": "Raspberry Pi", "rockchip": "Rockchip", "linux": "Linux"}


def parse_trips(text: str) -> list[tuple[str, str, float]]:
    """Kernel thermal trip points (zone, passive|hot|critical|active, °C) exactly as the board reports them (v9)."""
    trips: list[tuple[str, str, float]] = []
    for line in text.splitlines():
        parts = line.strip().rsplit(":", 2)
        if len(parts) != 3 or not parts[2].strip().lstrip("-").isdigit():
            continue
        raw = int(parts[2])
        celsius = raw / (1000 if abs(raw) > 200 else 1)
        if 30 <= celsius <= 150:
            trips.append((parts[0].strip() or "zone", parts[1].strip().lower(), round(celsius, 1)))
    return trips


def parse_info(text: str) -> dict[str, Any]:
    """Turn INFO_SCRIPT output into a flat, UI-ready dict.  Missing probes are omitted."""
    sec = sections(text)
    info: dict[str, Any] = {}
    cpu = _kv(sec.get("cpuinfo", ""), ":")
    dmi = {k: v for k, v in _kv(sec.get("dmi", "")).items()
           if v and not re.search(r"to be filled|default string|not specified|^system", v, re.I)}
    model = sec.get("model", "").strip().splitlines()[0].strip() if sec.get("model", "").strip() else ""
    if not model:
        model = " ".join(filter(None, (dmi.get("sys_vendor"), dmi.get("product_name")))) \
            or " ".join(filter(None, (dmi.get("board_vendor"), dmi.get("board_name")))) \
            or (cpu.get("model", "") if not cpu.get("model", "").isdigit() else "") or cpu.get("hardware", "")
    tegra = sec.get("tegra", "").strip()
    if tegra and not model:
        model = "NVIDIA Jetson"
    blob = " ".join([model, sec.get("compatible", ""), tegra, cpu.get("hardware", ""),
                     " ".join(dmi.values())]).lower()
    family = next((fid for fid, pattern in FAMILIES if re.search(pattern, blob)), "linux")
    info["family"] = family
    info["model"] = model or FAMILY_NAMES[family]
    if tegra:
        match = re.search(r"R(\d+)[^,]*,\s*REVISION:\s*([\d.]+)", tegra)
        info["l4t"] = f"L4T R{match.group(1)}.{match.group(2)}" if match else tegra.splitlines()[0][:60]
    osr = _kv(sec.get("osrelease", ""))
    if osr.get("pretty_name") or osr.get("name"):
        info["os"] = osr.get("pretty_name") or f"{osr.get('name')} {osr.get('version', '')}".strip()
    if sec.get("kernel"):
        parts = sec["kernel"].split()
        info["kernel"] = parts[1] if len(parts) >= 2 else sec["kernel"]
        if len(parts) >= 3:
            info["arch"] = parts[-1]
    cpu_name = cpu.get("model name", "")
    if cpu_name:
        info["cpu"] = re.sub(r"\s+", " ", cpu_name)
    if sec.get("nproc", "").strip().isdigit():
        info["cores"] = int(sec["nproc"].strip())
    total, available = _meminfo(sec.get("meminfo", ""))
    if total:
        info["mem_total"] = total * 1024
    disk_total, disk_free = _df(sec.get("df", ""))
    if disk_total:
        info["disk_total"], info["disk_free"] = disk_total, disk_free
    if sec.get("hostname"):
        info["hostname"] = sec["hostname"].splitlines()[0].strip()
    ips = [item.split("/")[0] for item in sec.get("ip", "").split() if re.match(r"^\d+\.\d+\.\d+\.\d+", item)]
    if ips:
        info["ip"] = " ".join(ips[:3])
    if sec.get("uptime"):
        try:
            info["uptime_s"] = int(float(sec["uptime"].split()[0]))
        except ValueError:
            pass
    tools = [line.strip() for line in sec.get("tools", "").splitlines() if line.strip()]
    info["tools"] = tools
    fpga = sec.get("fpga", "").split()
    if fpga:
        info["fpga_state"] = fpga[0]
    apps = sec.get("xmutil", "")
    if "xmutil" in tools:
        info["xmutil"] = True
        active = []
        for line in apps.splitlines():
            parts = line.split()
            if len(parts) >= 2 and not parts[0].lower().startswith("accelerator"):
                if parts[-1].rstrip(",").isdigit():
                    active.append(parts[0])
        if active:
            info["fpga_app"] = active[0]
    if sec.get("rknpu", "").strip():
        info["npu"] = "RKNPU " + (sec["rknpu"].splitlines()[-1].strip() if "/" not in sec["rknpu"].splitlines()[-1] else "")
        info["npu"] = info["npu"].strip()
    info["capabilities"] = capabilities(info)
    trips = parse_trips(sec.get("trips", ""))
    if trips:
        info["thermal_trips"] = trips
    return info


def capabilities(info: dict[str, Any]) -> list[str]:
    """Features this board can show.  KV260-only UI is gated on 'xmutil'/'fpga'."""
    tools = set(info.get("tools") or [])
    caps = []
    if "xmutil" in tools or info.get("xmutil"):
        caps.append("xmutil")
    if info.get("fpga_state") or info.get("family") in {"kv260", "zynq"}:
        caps.append("fpga")
    if info.get("family") == "jetson" or "tegrastats" in tools:
        caps.append("gpu")
    if info.get("npu") or info.get("family") == "rockchip":
        caps.append("npu")
    if "v4l2-ctl" in tools:
        caps.append("v4l2")
    return caps


class StatusParser:
    """Turns successive STATUS_SCRIPT blocks into rates/percentages (needs two samples for CPU/net)."""

    def __init__(self) -> None:
        self._cpu: tuple[int, int] | None = None
        self._net: tuple[int, int, float] | None = None

    def feed(self, block: str, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        sec = sections(block)
        status: dict[str, Any] = {}
        fields = sec.get("stat", "").split()
        if len(fields) >= 5 and fields[0] == "cpu":
            numbers = [int(x) for x in fields[1:] if x.isdigit()]
            idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
            total = sum(numbers[:8])
            if self._cpu and total > self._cpu[1]:
                busy = 1 - (idle - self._cpu[0]) / (total - self._cpu[1])
                status["cpu"] = round(max(0.0, min(1.0, busy)) * 100, 1)
            self._cpu = (idle, total)
        total, available = _meminfo(sec.get("meminfo", ""))
        if total:
            status["mem_used"], status["mem_total"] = (total - available) * 1024, total * 1024
        temps = []
        for line in sec.get("thermal", "").splitlines():
            if "=" in line:
                name, value = line.rsplit("=", 1)
                if value.strip().lstrip("-").isdigit():
                    celsius = int(value) / (1000 if abs(int(value)) > 200 else 1)
                    if -40 < celsius < 150:
                        temps.append((name.strip() or "zone", round(celsius, 1)))
        if temps:
            status["temps"] = temps
            status["temp_max"] = max(value for _, value in temps)
        disk_total, disk_free = _df(sec.get("df", ""))
        if disk_total:
            status["disk_used"], status["disk_total"] = disk_total - disk_free, disk_total
        rx = tx = 0
        for line in sec.get("net", "").splitlines():
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            if name.strip() == "lo":
                continue
            values = rest.split()
            if len(values) >= 9:
                rx += int(values[0])
                tx += int(values[8])
        if sec.get("net"):
            if self._net and now > self._net[2]:
                span = now - self._net[2]
                status["rx_bps"] = max(0.0, (rx - self._net[0]) / span)
                status["tx_bps"] = max(0.0, (tx - self._net[1]) / span)
            self._net = (rx, tx, now)
        if sec.get("load"):
            status["load"] = sec["load"].split()[0]
        gpu = sec.get("gpu", "").strip()
        if gpu.isdigit():
            status["gpu"] = round(int(gpu) / 10, 1)  # Jetson reports per-mille
        npu = sec.get("npu", "")
        loads = [int(x) for x in re.findall(r"(\d+)%", npu)]
        if loads:
            status["npu"] = round(sum(loads) / len(loads), 1)
        if sec.get("fpga"):
            status["fpga_state"] = sec["fpga"].split()[0]
        if sec.get("hot"):
            status["hotplug"] = sec["hot"].split()[0]  # changes when USB devices or /dev nodes come and go
        return status


def parse_tegrastats(line: str) -> dict[str, Any]:
    """Optional: parse one tegrastats line (GPU % via GR3D_FREQ)."""
    out: dict[str, Any] = {}
    match = re.search(r"GR3D_FREQ (\d+)%", line)
    if match:
        out["gpu"] = float(match.group(1))
    match = re.search(r"RAM (\d+)/(\d+)MB", line)
    if match:
        out["mem_used"], out["mem_total"] = int(match.group(1)) << 20, int(match.group(2)) << 20
    return out


# ---------------------------------------------------------------------------------------
_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def ssh_command(ssh_args: list[str], script: str) -> list[str]:
    """The script travels on stdin (`sh -s`), so no remote quoting is involved."""
    return list(ssh_args) + ["sh", "-s"]


def probe_info(ssh_args: list[str], run: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    result = run(ssh_command(ssh_args, INFO_SCRIPT), input=INFO_SCRIPT.encode(), capture_output=True, timeout=25, creationflags=_FLAGS)
    text = safe_decode(result.stdout) if isinstance(result.stdout, bytes) else str(result.stdout or "")
    if "@@" not in text:
        raise RuntimeError("无法读取开发板信息")
    return parse_info(text)


class StatusMonitor:
    """One long-lived ssh that prints a status block every `interval` seconds (off the UI thread)."""

    def __init__(self, ssh_args: list[str], on_status: Callable[[dict[str, Any]], None],
                 interval: float = 2.0, popen: Callable[..., Any] = subprocess.Popen) -> None:
        self.ssh_args, self.on_status, self.interval, self._popen = ssh_args, on_status, interval, popen
        self._proc: Any = None
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        parser = StatusParser()
        script = STATUS_SCRIPT % {"interval": int(max(1, self.interval))}
        while not self._stop.is_set():
            try:
                self._proc = self._popen(ssh_command(self.ssh_args, script), stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_FLAGS)
                self._proc.stdin.write(script.encode())
                self._proc.stdin.close()
                block: list[str] = []
                for raw in iter(self._proc.stdout.readline, b""):
                    if self._stop.is_set():
                        break
                    line = safe_decode(raw).rstrip("\r\n")
                    block.append(line)
                    if line == "@@end":
                        self.on_status(parser.feed("\n".join(block)))
                        block = []
            except Exception:
                pass
            finally:
                self._kill()
            self._stop.wait(5)  # reconnect slowly if the link dropped

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        self._kill()
