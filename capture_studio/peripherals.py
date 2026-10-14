"""Peripheral discovery for any SSH Linux board (v6).

One read-only POSIX-sh script runs over the existing SSH login (`sh -s`, nothing installed).
Every probe is optional and guarded by `timeout` when available; missing tools simply
yield no entries.  I2C bus scanning (`i2cdetect -y -r`, read-only) only runs on explicit request
because probing a camera sensor bus while streaming is not something to do implicitly.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Callable

try:
    from .textcodec import safe_decode
except ImportError:  # loaded as a plain script
    from textcodec import safe_decode

CATEGORIES = ("usb", "video", "serial", "i2c", "spi", "net", "storage", "audio", "gpio", "display", "pci")
CATEGORY_NAMES = {"usb": "USB", "video": "视频", "serial": "串口", "i2c": "I2C", "spi": "SPI", "net": "网络",
                  "storage": "存储", "audio": "音频", "gpio": "GPIO", "display": "显示", "pci": "PCIe"}

SCRIPT = r"""
export LC_ALL=C LANG=C LANGUAGE=C  # parsers expect English tool output (aplay/arecord are localised)
T(){ if command -v timeout >/dev/null 2>&1; then timeout 6 "$@"; else "$@"; fi; }
B(){ [ -e "$1" ] && basename "$(readlink -f "$1")"; }
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] || continue
  echo "@@usb $(basename $d)"
  for f in idVendor idProduct manufacturer product bDeviceClass speed version serial busnum devnum maxchild; do
    [ -r "$d/$f" ] && printf '%s=%s\n' $f "$(cat $d/$f 2>/dev/null)"; done
  for i in $d/*:1.*; do [ -d "$i" ] && echo "iface=$(cat $i/bInterfaceClass 2>/dev/null) $(B $i/driver)"; done
done
echo "@@lsusb"; T lsusb 2>/dev/null
for v in /dev/video*; do [ -e "$v" ] || continue
  echo "@@video $v"; echo "sysname=$(cat /sys/class/video4linux/$(basename $v)/name 2>/dev/null)"
  T v4l2-ctl -d "$v" -D 2>/dev/null
  echo "@@vfmt $v"; T v4l2-ctl -d "$v" --list-formats-ext 2>/dev/null
done
for t in /dev/ttyUSB* /dev/ttyACM* /dev/ttyPS* /dev/ttyAMA* /dev/ttyTHS* /dev/ttyS[0-9]*; do [ -e "$t" ] || continue
  n=$(basename $t); [ -e /sys/class/tty/$n/device ] || continue
  echo "@@serial $t"; echo "SYSDRIVER=$(B /sys/class/tty/$n/device/driver)"
  T udevadm info -q property -n "$t" 2>/dev/null
done
for b in /sys/bus/i2c/devices/i2c-*; do [ -d "$b" ] || continue
  n=${b##*-}; echo "@@i2c $n"; echo "name=$(cat $b/name 2>/dev/null)"
  for c in $b/$n-*; do [ -d "$c" ] && echo "client=$(basename $c)|$(cat $c/name 2>/dev/null)|$(B $c/driver)"; done
  if [ "$I2CSCAN" = 1 ] && command -v i2cdetect >/dev/null 2>&1; then echo "@@i2cscan $n"; T i2cdetect -y -r "$n" 2>&1; fi
done
for s in /sys/bus/spi/devices/*; do [ -d "$s" ] || continue
  echo "@@spi $(basename $s)"; echo "modalias=$(cat $s/modalias 2>/dev/null)"; echo "driver=$(B $s/driver)"
done
echo "@@spidev"; ls /dev/spidev* 2>/dev/null
for n in /sys/class/net/*; do [ -d "$n" ] || continue
  echo "@@net $(basename $n)"
  for f in operstate speed address mtu type; do printf '%s=%s\n' $f "$(cat $n/$f 2>/dev/null)"; done
  echo "driver=$(B $n/device/driver)"; [ -d "$n/wireless" ] && echo "wireless=1"
done
echo "@@ipaddr"; ip -o addr show 2>/dev/null
echo "@@lsblk"; T lsblk -J -b -o NAME,SIZE,FSTYPE,MOUNTPOINT,MODEL,TYPE,TRAN,RM 2>/dev/null
echo "@@aplay"; T aplay -l 2>/dev/null
echo "@@arecord"; T arecord -l 2>/dev/null
echo "@@asound"; cat /proc/asound/cards 2>/dev/null
echo "@@gpiodetect"; T gpiodetect 2>/dev/null
for g in /sys/class/gpio/gpiochip*; do [ -d "$g" ] || continue
  echo "@@gpiochip $(basename $g)"; echo "label=$(cat $g/label 2>/dev/null)"; echo "ngpio=$(cat $g/ngpio 2>/dev/null)"; echo "base=$(cat $g/base 2>/dev/null)"
done
for c in /sys/class/drm/card*-*; do [ -f "$c/status" ] || continue
  echo "@@drm $(basename $c)"; echo "status=$(cat $c/status)"; echo "enabled=$(cat $c/enabled 2>/dev/null)"
  echo "mode=$(head -n 1 $c/modes 2>/dev/null)"; echo "edid=$(od -An -tx1 -v $c/edid 2>/dev/null | tr -d ' \n')"
done
echo "@@lspci"; T lspci -nnk 2>/dev/null
echo "@@end"
"""

SERIAL_CHIPS = {
    "1a86:7523": "CH340", "1a86:5523": "CH341", "1a86:55d4": "CH9102", "1a86:55d3": "CH343",
    "10c4:ea60": "CP210x", "10c4:ea70": "CP2105", "0403:6001": "FTDI FT232R", "0403:6010": "FTDI FT2232",
    "0403:6011": "FTDI FT4232", "0403:6014": "FTDI FT232H", "0403:6015": "FTDI FT-X", "067b:2303": "PL2303",
    "067b:23a3": "PL2303GC", "2e8a:000a": "Raspberry Pi Pico (CDC)", "303a:1001": "ESP32-S3 USB-JTAG/serial",
}
SERIAL_DRIVERS = {"ch341": "CH34x", "cp210x": "CP210x", "ftdi_sio": "FTDI", "pl2303": "PL2303",
                  "cdc_acm": "USB CDC-ACM", "xuartps": "Xilinx PS UART", "uartlite": "Xilinx UART Lite",
                  "serial8250": "8250/16550", "dw-apb-uart": "DesignWare UART", "uart-pl011": "ARM PL011",
                  "tegra-uart": "Tegra UART", "tegra-hsuart": "Tegra HS UART"}
USB_CLASSES = {"00": "按接口", "01": "音频", "02": "通信", "03": "HID", "06": "图像", "07": "打印机",
               "08": "大容量存储", "09": "集线器", "0a": "CDC 数据", "0e": "视频", "e0": "无线", "ef": "复合",
               "ff": "厂商自定义"}


def blocks(text: str) -> list[tuple[str, str, str]]:
    """'@@kind arg' sections -> [(kind, arg, body)], repeated kinds kept in order."""
    out: list[tuple[str, str, str]] = []
    kind = arg = ""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith("@@"):
            if kind:
                out.append((kind, arg, "\n".join(lines).strip("\n")))
            head = raw[2:].strip().split(" ", 1)
            kind, arg, lines = head[0], head[1] if len(head) > 1 else "", []
        elif kind:
            lines.append(raw)
    if kind and kind != "end":
        out.append((kind, arg, "\n".join(lines).strip("\n")))
    return [item for item in out if item[0] != "end"]


def _kv(body: str, sep: str = "=") -> dict[str, str]:
    result: dict[str, str] = {}
    for line in body.splitlines():
        if sep in line:
            key, value = line.split(sep, 1)
            result.setdefault(key.strip(), value.strip())
    return result


def _dev(category: str, key: str, name: str, summary: str, props: list[tuple[str, str]]) -> dict[str, Any]:
    return {"category": category, "id": f"{category}:{key}", "name": name or key, "summary": summary,
            "props": [(k, str(v)) for k, v in props if str(v).strip() != ""]}


def _size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return ""


def parse_lsusb(body: str) -> dict[str, str]:
    names = {}
    for line in body.splitlines():
        match = re.match(r"Bus \d+ Device \d+: ID ([0-9a-f]{4}:[0-9a-f]{4})\s*(.*)$", line.strip(), re.I)
        if match and match.group(2):
            names[match.group(1).lower()] = match.group(2).strip()
    return names


def usb_speed(mbps: str) -> str:
    return {"1.5": "USB 1.0 低速", "12": "USB 1.1 全速", "480": "USB 2.0 高速", "5000": "USB 3.0 超速",
            "10000": "USB 3.1 超速+", "20000": "USB 3.2 2x2"}.get(mbps.strip(), f"{mbps} Mbps" if mbps else "")


def edid_name(hexstr: str) -> str:
    """Monitor name (descriptor tag 0xFC) from EDID hex; '' when absent or malformed."""
    try:
        data = bytes.fromhex(hexstr.strip())
    except ValueError:
        return ""
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return ""
    for offset in (54, 72, 90, 108):
        desc = data[offset:offset + 18]
        if desc[:3] == b"\x00\x00\x00" and desc[3] == 0xFC:
            return desc[5:18].split(b"\n")[0].decode("ascii", "replace").strip()
    return ""


def edid_vendor(hexstr: str) -> str:
    try:
        data = bytes.fromhex(hexstr.strip())
        word = (data[8] << 8) | data[9]
        return "".join(chr(((word >> s) & 0x1F) + 64) for s in (10, 5, 0))
    except (ValueError, IndexError):
        return ""


def parse_peripherals(text: str) -> list[dict[str, Any]]:
    from .camera_lab import parse_v4l2_formats  # same parser the mode dropdown uses
    items: list[dict[str, Any]] = []
    secs = blocks(text)
    single = {kind: body for kind, arg, body in secs if not arg}
    usb_names = parse_lsusb(single.get("lsusb", ""))
    formats = {arg: body for kind, arg, body in secs if kind == "vfmt"}
    ips: dict[str, list[str]] = {}
    for line in single.get("ipaddr", "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] in ("inet", "inet6"):
            ips.setdefault(parts[1], []).append(parts[3])
    for kind, arg, body in secs:
        if kind == "usb":
            kv = _kv(body)
            vid, pid = kv.get("idVendor", ""), kv.get("idProduct", "")
            vp = f"{vid}:{pid}".lower()
            ifaces = [line.split("=", 1)[1].split() for line in body.splitlines() if line.startswith("iface=")]
            drivers = sorted({p[1] for p in ifaces if len(p) > 1})
            klass = kv.get("bDeviceClass", "").lower()
            if klass == "00" and ifaces:
                klass = ifaces[0][0].lower() if ifaces[0] else klass
            hub = klass == "09"
            fallback = usb_names.get(vp, "")
            name = " ".join(x for x in (kv.get("manufacturer", ""), kv.get("product", "")) if x) or fallback or vp
            items.append(_dev("usb", arg, name, " · ".join(x for x in (vp, usb_speed(kv.get("speed", ""))) if x), [
                ("VID:PID", vp), ("厂商", kv.get("manufacturer", "")), ("产品", kv.get("product", "")),
                ("lsusb", fallback), ("类别", USB_CLASSES.get(klass, klass)), ("速度", usb_speed(kv.get("speed", ""))),
                ("USB 版本", kv.get("version", "")), ("驱动", ", ".join(drivers)), ("序列号", kv.get("serial", "")),
                ("总线/设备", f"{kv.get('busnum', '')}/{kv.get('devnum', '')}" if kv.get("busnum") else ""),
                ("端口数", kv.get("maxchild", "") if hub else ""), ("sysfs", arg)]))
        elif kind == "video":
            kv = _kv(body, ":")
            caps = re.findall(r"^\s{2,}(Video Capture|Video Output|Metadata Capture|Streaming|Extended Pix Format|"
                              r"Video Memory-to-Memory|Device Capabilities)", body, re.M)
            modes = parse_v4l2_formats(formats.get(arg, ""))
            capture = "Video Capture" in body or "Video Capture Multiplanar" in body
            meta_only = "Metadata Capture" in body and not capture
            card = kv.get("Card type", "") or _kv(body).get("sysname", "")
            mode_text = [f"{m['width']}×{m['height']} {m['fps']}fps {str(m['format']).upper()}" for m in modes]
            summary = f"{len(modes)} 种模式" if modes else ("元数据节点" if meta_only else "")
            props = [("设备", arg), ("名称", card), ("驱动", kv.get("Driver name", "")), ("总线", kv.get("Bus info", "")),
                     ("驱动版本", kv.get("Driver version", "")), ("能力", ", ".join(dict.fromkeys(caps)))]
            props += [(f"模式 {i + 1}", text) for i, text in enumerate(mode_text[:40])]
            if len(mode_text) > 40:
                props.append(("更多模式", str(len(mode_text) - 40)))
            items.append(_dev("video", arg, card or arg, " · ".join(x for x in (arg, summary) if x), props))
        elif kind == "serial":
            kv = _kv(body)
            if kv.get("SYSDRIVER") == "port" and arg.startswith("/dev/ttyS"):
                continue  # legacy 8250 placeholder with no hardware behind it
            vp = f"{kv.get('ID_VENDOR_ID', '')}:{kv.get('ID_MODEL_ID', '')}".lower()
            driver = kv.get("SYSDRIVER", "") or kv.get("ID_USB_DRIVER", "")
            chip = SERIAL_CHIPS.get(vp) or SERIAL_DRIVERS.get(driver, "")
            name = kv.get("ID_MODEL_FROM_DATABASE") or kv.get("ID_MODEL", "").replace("_", " ") or chip or arg
            items.append(_dev("serial", arg, name, " · ".join(x for x in (arg, chip) if x), [
                ("设备", arg), ("芯片", chip), ("驱动", driver), ("VID:PID", vp if vp != ":" else ""),
                ("厂商", kv.get("ID_VENDOR_FROM_DATABASE") or kv.get("ID_VENDOR", "").replace("_", " ")),
                ("序列号", kv.get("ID_SERIAL_SHORT", "")), ("路径", kv.get("ID_PATH", "")),
                ("稳定链接", next((x for x in kv.get("DEVLINKS", "").split() if "/by-id/" in x), ""))]))
        elif kind == "i2c":
            clients = [line.split("=", 1)[1].split("|") for line in body.splitlines() if line.startswith("client=")]
            bus_name = _kv(body).get("name", "")
            props = [("总线", f"/dev/i2c-{arg}"), ("适配器", bus_name)]
            for client in clients:
                client += ["", "", ""]
                addr = client[0].split("-")[-1]
                props.append((f"0x{addr[-2:]}" if addr else client[0], " · ".join(x for x in client[1:3] if x)))
            items.append(_dev("i2c", arg, f"i2c-{arg}", " · ".join(x for x in (bus_name, f"{len(clients)} 个设备") if x), props))
        elif kind == "i2cscan":
            found = parse_i2cdetect(body)
            target = next((it for it in items if it["id"] == f"i2c:{arg}"), None)
            if target is not None:
                target["props"].append(("扫描结果", " ".join(found) if found else ("无应答" if "--" in body else body.strip()[:80])))
                target["scan"] = found
        elif kind == "spi":
            kv = _kv(body)
            items.append(_dev("spi", arg, arg, kv.get("modalias", ""), [
                ("设备", arg), ("modalias", kv.get("modalias", "")), ("驱动", kv.get("driver", ""))]))
        elif kind == "net":
            kv = _kv(body)
            if arg == "lo":
                continue
            speed = kv.get("speed", "")
            speed = f"{speed} Mb/s" if speed.isdigit() and int(speed) > 0 else ""
            kind_name = "无线" if kv.get("wireless") else ("虚拟" if not kv.get("driver") else "有线")
            items.append(_dev("net", arg, arg, " · ".join(x for x in (kv.get("operstate", ""), speed, kind_name) if x), [
                ("接口", arg), ("状态", kv.get("operstate", "")), ("速率", speed), ("MAC", kv.get("address", "")),
                ("IP", " ".join(ips.get(arg, []))), ("MTU", kv.get("mtu", "")), ("驱动", kv.get("driver", "")),
                ("类型", kind_name)]))
        elif kind == "gpiochip" and not single.get("gpiodetect"):
            kv = _kv(body)
            items.append(_dev("gpio", arg, arg, f"{kv.get('label', '')} · {kv.get('ngpio', '?')} lines", [
                ("芯片", arg), ("标签", kv.get("label", "")), ("引脚数", kv.get("ngpio", "")), ("sysfs base", kv.get("base", ""))]))
        elif kind == "drm":
            kv = _kv(body)
            monitor = edid_name(kv.get("edid", ""))
            connector = re.sub(r"^card\d+-", "", arg)
            items.append(_dev("display", arg, monitor or connector, " · ".join(x for x in (connector, kv.get("status", ""), kv.get("mode", "")) if x), [
                ("接口", connector), ("状态", kv.get("status", "")), ("启用", kv.get("enabled", "")),
                ("显示器", monitor), ("厂商代码", edid_vendor(kv.get("edid", "")) if monitor else ""), ("首选模式", kv.get("mode", ""))]))
    items += parse_lsblk(single.get("lsblk", ""))
    items += parse_alsa(single.get("aplay", ""), "播放") + parse_alsa(single.get("arecord", ""), "录音")
    if not any(it["category"] == "audio" for it in items):
        items += parse_asound_cards(single.get("asound", ""))
    items += parse_gpiodetect(single.get("gpiodetect", ""))
    spidev = single.get("spidev", "").split()
    for node in spidev:
        items.append(_dev("spi", node, node, "用户态 spidev", [("设备", node)]))
    items += parse_lspci(single.get("lspci", ""))
    order = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(items, key=lambda it: (order.get(it["category"], 99), _natural(it["id"])))


def _natural(text: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def parse_i2cdetect(body: str) -> list[str]:
    found = []
    for line in body.splitlines():
        match = re.match(r"^([0-7]0):\s+(.*)$", line.strip())
        if not match:
            continue
        cells = match.group(2).split()
        base = int(match.group(1), 16)
        # rows start at column 0 except the first row, which is padded with blanks for 0x00-0x02
        start = 16 - len(cells) if base == 0 else 0
        for index, cell in enumerate(cells):
            if cell not in ("--", "") and re.fullmatch(r"[0-9a-fA-F]{2}|UU", cell):
                found.append(f"0x{base + start + index:02x}" + (" (驱动占用)" if cell == "UU" else ""))
    return found


def parse_lsblk(body: str) -> list[dict[str, Any]]:
    if not body.strip():
        return []
    try:
        data = json.loads(body)
    except ValueError:
        return []
    out = []

    def walk(nodes: list[dict[str, Any]], parent: str = "") -> None:
        for node in nodes or []:
            name = str(node.get("name") or "")
            if node.get("type") in ("loop", "ram", "zram") or (str(node.get("name", "")).startswith(("loop", "zram", "ram"))):
                continue
            size = node.get("size")
            try:
                size_text = _size(float(size)) if size is not None else ""
            except (TypeError, ValueError):
                size_text = str(size)
            model = str(node.get("model") or "").strip()
            mount = node.get("mountpoint") or ""
            out.append(_dev("storage", name, f"/dev/{name}", " · ".join(x for x in (size_text, node.get("fstype") or "", mount) if x), [
                ("设备", f"/dev/{name}"), ("类型", node.get("type") or ""), ("容量", size_text), ("型号", model),
                ("文件系统", node.get("fstype") or ""), ("挂载点", mount), ("接口", node.get("tran") or ""),
                ("可移动", "是" if str(node.get("rm")) in ("1", "True", "true") else ""), ("上级", parent)]))
            walk(node.get("children") or [], name)

    walk(data.get("blockdevices") or [])
    return out


def parse_alsa(body: str, direction: str) -> list[dict[str, Any]]:
    out = []
    for line in body.splitlines():
        match = re.match(r"^(?:card|卡|声卡)\s*(\d+)\s*[:：]\s*(\S+) \[(.*?)\][,，]\s*(?:device|设备|裝置)\s*(\d+)\s*[:：]\s*(.*?) \[(.*?)\]",
                         line.strip())
        if match:
            card, short, long, device, _, dev_name = match.groups()
            key = f"{direction}:hw:{card},{device}"
            out.append(_dev("audio", key, long or short, f"{direction} · hw:{card},{device}", [
                ("方向", direction), ("ALSA 设备", f"hw:{card},{device}"), ("声卡", f"{short} [{long}]"), ("设备名", dev_name)]))
    return out


def parse_asound_cards(body: str) -> list[dict[str, Any]]:
    out = []
    for line in body.splitlines():
        match = re.match(r"^\s*(\d+) \[(\S+)\s*\]: (.*?) - (.*)$", line)
        if match:
            out.append(_dev("audio", f"card{match.group(1)}", match.group(4).strip(), f"card {match.group(1)} · {match.group(3)}",
                            [("声卡", match.group(1)), ("ID", match.group(2)), ("驱动", match.group(3)), ("名称", match.group(4).strip())]))
    return out


def parse_gpiodetect(body: str) -> list[dict[str, Any]]:
    out = []
    for line in body.splitlines():
        match = re.match(r"^(gpiochip\d+) \[(.*?)\] \((\d+) lines\)", line.strip())
        if match:
            out.append(_dev("gpio", match.group(1), match.group(1), f"{match.group(2)} · {match.group(3)} lines",
                            [("芯片", match.group(1)), ("标签", match.group(2)), ("引脚数", match.group(3))]))
    return out


def parse_lspci(body: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in body.splitlines():
        match = re.match(r"^([0-9a-f]{2,4}:[0-9a-f]{2}:[0-9a-f]{2}\.\d|[0-9a-f]{2}:[0-9a-f]{2}\.\d) (.*?) \[([0-9a-f]{4})\]: (.*?)(?: \[([0-9a-f]{4}:[0-9a-f]{4})\])?(?: \(rev ([0-9a-f]+)\))?$", line, re.I)
        if match:
            slot, cls, code, desc, ids, rev = match.groups()
            current = _dev("pci", slot, desc, f"{cls} · {ids or ''}".strip(" ·"), [
                ("插槽", slot), ("类别", f"{cls} [{code}]"), ("设备", desc), ("VID:DID", ids or ""), ("版本", rev or "")])
            out.append(current)
        elif current is not None and ":" in line and line.startswith("\t"):
            key, value = line.strip().split(":", 1)
            label = {"Subsystem": "子系统", "Kernel driver in use": "驱动", "Kernel modules": "内核模块"}.get(key.strip())
            if label:
                current["props"].append((label, value.strip()))
    return out


def as_text(items: list[dict[str, Any]], translate: Callable[[str], str] = lambda s: s) -> str:
    lines = []
    for item in items:
        lines.append(f"[{translate(CATEGORY_NAMES.get(item['category'], item['category']))}] {item['name']}  {translate(item['summary'])}")
        for key, value in item["props"]:
            lines.append(f"    {translate(key)}: {translate(value)}")
    return "\n".join(lines)


def signature(items: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in items}


def diff(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    before, after = {i["id"]: i["name"] for i in old}, {i["id"]: i["name"] for i in new}
    return ([after[k] for k in after if k not in before], [before[k] for k in before if k not in after])


_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def scan(ssh_args: list[str], i2c_scan: bool = False, run: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    script = ("I2CSCAN=1\n" if i2c_scan else "I2CSCAN=0\n") + SCRIPT
    result = run(list(ssh_args) + ["sh", "-s"], input=script.encode(), capture_output=True, timeout=90, creationflags=_FLAGS)
    raw = result.stdout
    text = safe_decode(raw) if isinstance(raw, bytes) else str(raw or "")
    if "@@" not in text:
        raise RuntimeError("无法读取外设列表")
    return parse_peripherals(text)
