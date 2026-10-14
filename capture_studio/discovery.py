"""v12 unified board discovery (replaces the two v11 paths in lan_scan.py and board_discover.py).

Candidates, all probed only on TCP 22 for an `SSH-` banner. Nothing logs in, and nothing is sent after the banner:
  1. the /24 around each real adapter address (max 3 adapters; a wider subnet still only scans its own /24);
  2. every neighbour Windows already knows (`arp -a` / Get-NetNeighbor), on any private or 169.254 subnet. This
     finds direct-cable boards with link-local or static addresses without sweeping a /16;
  3. common mDNS names (kria.local, ubuntu.local, raspberrypi.local, ...) plus an optional DNS-SD `_ssh._tcp`
     browse when the `zeroconf` package is installed. 169.254 answers are kept.
No gateway is required. The PC's network settings are never changed; direct-connect problems only produce guidance.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Callable, Iterable

MAX_ADAPTERS = 3
SCAN_PREFIX = 24
FAKE_IP = ipaddress.IPv4Network("198.18.0.0/15")
LINK_LOCAL = ipaddress.IPv4Network("169.254.0.0/16")
VIRTUAL_ADAPTER = re.compile(
    r"vmware|virtualbox|hyper-?v|vethernet|wsl|bluetooth|蓝牙|loopback|meta\b|mihomo|clash|"
    r"\btun\b|\btap\b|npcap|sing-?box|letsvpn|\bvpn\b|docker|veth|zerotier|tailscale|wintun|wireguard",
    re.I)
WIRELESS = re.compile(r"wi-?fi|wlan|wireless|无线|802\.11", re.I)
MDNS_NAMES = ("kria", "ubuntu", "raspberrypi", "jetson", "nano", "orin", "xavier", "rockchip", "orangepi5",
              "rock-5b", "radxa", "petalinux", "xilinx-kv260", "kv260", "linaro-alip")
RULE_TEXT = "扫描范围：每块真实网卡所在的 /24（最多 3 块），加上系统邻居表里已出现的地址和常见 .local 名称；只测 22 端口的 SSH 应答。"
_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# MAC OUI -> (vendor, kind). kind: board | pc
OUI = {
    "000a35": ("Xilinx", "board"),
    "b827eb": ("Raspberry Pi", "board"), "dca632": ("Raspberry Pi", "board"), "e45f01": ("Raspberry Pi", "board"),
    "28cdc1": ("Raspberry Pi", "board"), "d83add": ("Raspberry Pi", "board"), "2ccf67": ("Raspberry Pi", "board"),
    "00044b": ("NVIDIA", "board"), "48b02d": ("NVIDIA", "board"), "3c6d66": ("NVIDIA", "board"),
    "e0d55e": ("Rockchip / Radxa", "board"), "c0742b": ("Rockchip / Radxa", "board"),
    "001132": ("Synology", "pc"), "00155d": ("Hyper-V", "pc"), "000c29": ("VMware", "pc"), "005056": ("VMware", "pc"),
    "080027": ("VirtualBox", "pc"), "3c7c3f": ("ASUSTek", "pc"), "f4b520": ("Intel", "pc"), "a4bb6d": ("Dell", "pc"),
    "00e04c": ("Realtek", "pc"), "d8bbc1": ("Micro-Star", "pc"), "6c4b90": ("Lenovo", "pc"), "f875a4": ("Lenovo", "pc"),
}
BOARD_NAMES = re.compile(r"kria|kv260|zynq|petalinux|xilinx|raspberry|jetson|nano|orin|xavier|tegra|rockchip|rk35|radxa|orangepi|rock-?5", re.I)


# ----------------------------------------------------------------------------------------- addresses
def ignored(ip: str, allow_link_local: bool = False) -> bool:
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return True
    if addr in LINK_LOCAL:
        return not allow_link_local
    return addr.is_loopback or addr.is_multicast or addr.is_unspecified or addr in FAKE_IP or \
        str(addr).endswith(".255") or not addr.is_private


def mac_compact(mac: str) -> str:
    return re.sub(r"[^0-9a-fA-F]", "", mac or "").lower()


def vendor_of(mac: str) -> tuple[str, str]:
    """(vendor, kind) for a MAC; locally administered (random) MACs are labelled as such."""
    compact = mac_compact(mac)
    if len(compact) != 12:
        return "", ""
    if compact[:6] in OUI:
        return OUI[compact[:6]]
    if int(compact[1], 16) & 0x2:
        return "随机 MAC", ""
    return "", ""


def decode_console(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


# ----------------------------------------------------------------------------------------- adapters
def parse_ipconfig(text: str) -> list[dict[str, Any]]:
    """`ipconfig /all` (English or Chinese Windows) -> [{name, ips:[(ip, prefix)], gateway, mac, wireless, virtual}].

    gateway is "" when the adapter has none (direct cable) and the IPv4 gateway otherwise."""
    ipv4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    last_key = ""
    for raw in text.replace("\r\n", "\n").split("\n"):
        if not raw.strip():
            continue
        if not raw.startswith(" ") and raw.rstrip().endswith((":", "：")):
            current = {"name": re.sub(r"^.*?(?:adapter|适配器)\s+", "", raw.strip().rstrip(":：").strip()), "ips": [], "gateway": "", "mac": "", "media": ""}
            out.append(current)
            last_key = ""
            continue
        if current is None:
            continue
        match = re.match(r"^\s+(\S.*?)[\s.]*[:：]\s?(.*)$", raw)
        if not match:  # continuation line (second gateway / DNS value)
            found = ipv4.search(raw)
            if found and last_key == "gateway" and not current["gateway"] and found.group(0) != "0.0.0.0":
                current["gateway"] = found.group(0)
            continue
        key, value = match.group(1).lower(), match.group(2).strip()
        found = ipv4.search(value)
        last_key = ""
        if "description" in key or "描述" in key:
            current["description"] = value
        elif "physical address" in key or "物理地址" in key:
            current["mac"] = value
        elif "media state" in key or "媒体状态" in key:
            current["media"] = value
        elif "ipv4" in key and found:
            current["ips"].append([found.group(0), 24])
        elif ("subnet mask" in key or "子网掩码" in key) and found and current["ips"]:
            current["ips"][-1][1] = ipaddress.IPv4Network(f"0.0.0.0/{found.group(0)}").prefixlen
        elif "default gateway" in key or "默认网关" in key:
            last_key = "gateway"
            if found and found.group(0) != "0.0.0.0":
                current["gateway"] = found.group(0)
    for item in out:
        label = f"{item['name']} {item.get('description', '')}"
        item["virtual"] = bool(VIRTUAL_ADAPTER.search(label))
        item["wireless"] = bool(WIRELESS.search(label))
        item["disconnected"] = "disconnected" in item["media"].lower() or "断开" in item["media"]
        item["ips"] = [tuple(x) for x in item["ips"]]
    return out


def qt_adapters() -> list[dict[str, Any]]:
    """Fallback when ipconfig is unavailable: Qt interfaces (no gateway information)."""
    try:
        from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
    except Exception:
        return []
    out = []
    for iface in QNetworkInterface.allInterfaces():
        flags = iface.flags()
        if not (flags & QNetworkInterface.InterfaceFlag.IsUp) or (flags & QNetworkInterface.InterfaceFlag.IsLoopBack):
            continue
        ips = [(e.ip().toString(), e.prefixLength()) for e in iface.addressEntries()
               if e.ip().protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol]
        label = f"{iface.name()} {iface.humanReadableName()}"
        out.append({"name": iface.humanReadableName(), "ips": ips, "gateway": None, "mac": iface.hardwareAddress(),
                    "virtual": bool(VIRTUAL_ADAPTER.search(label)), "wireless": bool(WIRELESS.search(label)),
                    "disconnected": not (flags & QNetworkInterface.InterfaceFlag.IsRunning)})
    return out


def subnets(adapters: list[dict[str, Any]]) -> list[ipaddress.IPv4Network]:
    """Consistent rule: the /24 around each real, connected adapter's private address. No gateway needed."""
    nets: list[ipaddress.IPv4Network] = []
    for adapter in adapters:
        if adapter.get("virtual") or adapter.get("disconnected"):
            continue
        for ip, _prefix in adapter.get("ips", []):
            if ignored(ip):
                continue
            net = ipaddress.IPv4Network(f"{ip}/{SCAN_PREFIX}", strict=False)
            if net not in nets:
                nets.append(net)
    return nets[:MAX_ADAPTERS]


def own_addresses(adapters: list[dict[str, Any]]) -> set[str]:
    return {ip for adapter in adapters for ip, _ in adapter.get("ips", [])}


# ----------------------------------------------------------------------------------------- neighbours
ARP_ROW = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})\s+(\S+)", re.M)


def parse_arp(text: str) -> dict[str, dict[str, str]]:
    """`arp -a` (English: dynamic/static, Chinese: 动态/静态) -> {ip: {mac, type, interface}}."""
    out: dict[str, dict[str, str]] = {}
    interface = ""
    for line in text.replace("\r\n", "\n").split("\n"):
        head = re.match(r"^\s*(?:Interface|接口)\s*[:：]\s*(\d{1,3}(?:\.\d{1,3}){3})", line)
        if head:
            interface = head.group(1)
            continue
        row = ARP_ROW.match(line)
        if row:
            ip, mac, kind = row.groups()
            out[ip] = {"mac": mac.replace(":", "-").lower(), "type": kind, "interface": interface}
    return out


def parse_netneighbor(text: str) -> dict[str, dict[str, str]]:
    """Get-NetNeighbor -AddressFamily IPv4 | ConvertTo-Json -> same shape as parse_arp."""
    try:
        data = json.loads(text) if text.strip() else []
    except ValueError:
        return {}
    rows = data if isinstance(data, list) else [data]
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        state = str(row.get("State", ""))
        state = {"0": "Unreachable", "1": "Incomplete", "2": "Probe", "3": "Delay", "4": "Stale", "5": "Reachable",
                 "6": "Permanent"}.get(state, state)
        mac = str(row.get("LinkLayerAddress") or "")
        if state in ("Unreachable", "Incomplete") or not mac_compact(mac).strip("0"):
            continue
        out[str(row.get("IPAddress"))] = {"mac": mac.replace(":", "-").lower(), "type": state,
                                          "interface": str(row.get("InterfaceAlias") or "")}
    return out


def usable_neighbors(table: dict[str, dict[str, str]], own: set[str]) -> dict[str, dict[str, str]]:
    keep = {}
    for ip, row in table.items():
        compact = mac_compact(row.get("mac", ""))
        if ip in own or ignored(ip, allow_link_local=True) or compact in ("ffffffffffff", "000000000000"):
            continue
        if compact.startswith("01005e"):  # IPv4 multicast MACs
            continue
        keep[ip] = row
    return keep


def read_neighbors(run: Callable[..., Any] = subprocess.run) -> dict[str, dict[str, str]]:
    table: dict[str, dict[str, str]] = {}
    try:
        ps = ("Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
              "Select-Object IPAddress,LinkLayerAddress,State,InterfaceAlias | ConvertTo-Json -Compress")
        result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                     capture_output=True, timeout=15, creationflags=_FLAGS)
        table.update(parse_netneighbor(decode_console(result.stdout or b"")))
    except Exception:
        pass
    try:
        result = run(["arp", "-a"], capture_output=True, timeout=10, creationflags=_FLAGS)
        for ip, row in parse_arp(decode_console(result.stdout or b"")).items():
            table.setdefault(ip, row)
    except Exception:
        pass
    return table


# ----------------------------------------------------------------------------------------- mDNS
def resolve_names(names: Iterable[str] = MDNS_NAMES, timeout: float = 2.5,
                  resolver: Callable[[str], list[str]] | None = None) -> dict[str, str]:
    """{ip: name.local}. Windows 10+ resolves .local through its mDNS stack; 169.254 answers are kept."""
    def default(host: str) -> list[str]:
        try:
            return [i[4][0] for i in socket.getaddrinfo(host, 22, socket.AF_INET, socket.SOCK_STREAM)]
        except OSError:
            return []
    resolver = resolver or default
    found: dict[str, str] = {}
    pool = ThreadPoolExecutor(max_workers=8)
    futures = {pool.submit(resolver, f"{name}.local"): f"{name}.local" for name in names}
    done, _ = wait(futures, timeout=timeout)
    for future in done:
        for ip in future.result() or []:
            if not ignored(ip, allow_link_local=True):
                found.setdefault(ip, futures[future])
    pool.shutdown(wait=False, cancel_futures=True)
    return found


def browse_ssh(seconds: float = 1.5) -> dict[str, str]:
    """Optional DNS-SD `_ssh._tcp.local.` browse; empty when the `zeroconf` package is not installed."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf  # type: ignore
    except Exception:
        return {}
    import time
    found: dict[str, str] = {}

    class Listener:
        def add_service(self, zc: Any, kind: str, name: str) -> None:
            info = zc.get_service_info(kind, name, 800)
            for raw in (info.addresses if info else []):
                ip = socket.inet_ntoa(raw)
                if not ignored(ip, allow_link_local=True):
                    found.setdefault(ip, (info.server or name).rstrip("."))

        update_service = remove_service = lambda *a: None

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, "_ssh._tcp.local.", Listener())
        time.sleep(seconds)
    finally:
        zc.close()
    return found


# ----------------------------------------------------------------------------------------- probing
def banner_hint(banner: str) -> str:
    low = banner.lower()
    for key, label in (("ubuntu", "Ubuntu"), ("debian", "Debian"), ("raspbian", "Raspberry Pi OS"),
                       ("petalinux", "PetaLinux"), ("dropbear", "Dropbear (嵌入式)"), ("windows", "Windows"),
                       ("openssh", "OpenSSH")):
        if key in low:
            return label
    return ""


def probe(host: str, port: int = 22, timeout: float = 0.4, connect: Callable[..., Any] = socket.create_connection) -> dict[str, Any] | None:
    """Banner only: connect, read up to 128 bytes, close. A bare TCP accept is not counted."""
    try:
        sock = connect((host, port), timeout=timeout)
    except OSError:
        return None
    banner = ""
    try:
        sock.settimeout(0.8)
        banner = sock.recv(128).decode("ascii", "replace").strip()
    except OSError:
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if not banner.startswith("SSH-"):
        return None
    return {"host": host, "banner": banner, "hint": banner_hint(banner)}


def test_one(host: str, prober: Callable[[str], dict[str, Any] | None] = probe) -> tuple[bool, str]:
    """'Test this IP' button: SSH banner check on one address, with a plain-language answer."""
    host = host.strip()
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host or "-"):
            return False, "地址格式不对"
    result = prober(host)
    if result:
        return True, f"{host} 有 SSH 应答：{result['banner'][:60]}"
    return False, f"{host} 没有 SSH 应答（不在同一网段、没开机，或 SSH 没启动）"


def classify(item: dict[str, Any]) -> dict[str, Any]:
    vendor, kind = vendor_of(item.get("mac", ""))
    text = " ".join(str(item.get(k, "")) for k in ("name", "banner"))
    if not kind and BOARD_NAMES.search(text):
        kind = "board"
    if not kind and re.search(r"petalinux|dropbear", text, re.I):
        kind = "board"
    if not kind and re.search(r"windows", text, re.I):
        kind = "pc"
    item["vendor"] = vendor
    item["kind"] = kind or "linux"
    return item


def label_for(item: dict[str, Any], t: Callable[[str], str] = lambda x: x) -> str:
    kind = {"board": "开发板", "pc": "电脑 / 服务器", "linux": "Linux 设备"}[item["kind"]]
    parts = [item["host"], t(kind)]
    if item.get("vendor"):
        parts.append(t(item["vendor"]))
    if item.get("name"):
        parts.append(item["name"])
    if item.get("hint"):
        parts.append(t(item["hint"]))
    return "  ·  ".join(parts)


RANK = {"board": 0, "linux": 1, "pc": 2}


def discover(adapters: list[dict[str, Any]] | None = None, neighbors: dict[str, dict[str, str]] | None = None,
             names: dict[str, str] | None = None, prober: Callable[[str], dict[str, Any] | None] = probe,
             cancel: Callable[[], bool] = lambda: False, workers: int = 64) -> dict[str, Any]:
    """One pass: candidates from /24s + neighbour table + mDNS, banner-probed in parallel, classified and ranked."""
    adapters = load_adapters() if adapters is None else adapters
    own = own_addresses(adapters)
    live_table = neighbors is None
    neighbors = usable_neighbors(read_neighbors() if live_table else neighbors, own)
    if names is None:
        names = resolve_names()
        names.update({ip: n for ip, n in browse_ssh().items() if ip not in names})
    nets = subnets(adapters)
    sources: dict[str, set[str]] = {}
    for net in nets:
        for host in net.hosts():
            text = str(host)
            if text not in own and not text.endswith(".255"):
                sources.setdefault(text, set()).add("subnet")
    for ip in neighbors:
        sources.setdefault(ip, set()).add("neighbor")
    for ip in names:
        if ip not in own:
            sources.setdefault(ip, set()).add("mdns")
    found: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 64))) as pool:
        futures = {ip: pool.submit(lambda h=ip: None if cancel() else prober(h)) for ip in sources}
        for ip, future in futures.items():
            result = future.result()
            if not result:
                continue
            result = dict(result)
            result["mac"] = neighbors.get(ip, {}).get("mac", "")
            result["name"] = names.get(ip, "")
            result["sources"] = sorted(sources[ip])
            result["link_local"] = ipaddress.IPv4Address(ip) in LINK_LOCAL
            found.append(classify(result))
    if live_table and any(r["host"] not in neighbors for r in found):
        # the probe itself fills the ARP cache, so a second read tags /24 hits with their MAC vendor
        late = usable_neighbors(read_neighbors(), own)
        for r in found:
            if not r["mac"] and r["host"] in late:
                r["mac"] = late[r["host"]]["mac"]
                classify(r)
    found.sort(key=lambda r: (RANK[r["kind"]], tuple(int(x) for x in r["host"].split("."))))
    return {"found": found, "subnets": [str(n) for n in nets], "neighbors": len(neighbors), "names": len(names),
            "candidates": len(sources), "guidance": guidance(adapters)}


def load_adapters(run: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    try:
        result = run(["ipconfig", "/all"], capture_output=True, timeout=10, creationflags=_FLAGS)
        adapters = parse_ipconfig(decode_console(result.stdout or b""))
        if adapters:
            return adapters
    except Exception:
        pass
    return qt_adapters()


def guidance(adapters: list[dict[str, Any]]) -> list[str]:
    """Direct-cable hints for wired adapters that have only 169.254 or no gateway. Text only; nothing is changed."""
    tips: list[str] = []
    for adapter in adapters:
        if adapter.get("virtual") or adapter.get("wireless") or adapter.get("disconnected") or not adapter.get("ips"):
            continue
        ips = [ip for ip, _ in adapter["ips"]]
        name = adapter["name"]
        if all(ipaddress.IPv4Address(ip) in LINK_LOCAL for ip in ips):
            tips.append(f"有线网卡“{name}”只有 169.254 自动地址（{ips[0]}），像是网线直连且没有 DHCP。"
                        "开发板若也用 169.254 地址，上面的邻居表和 .local 名称会找到它；"
                        "否则请在 Windows 网络设置里给这块网卡设一个与开发板同网段的静态 IP"
                        "（例如开发板是 192.168.1.10 时设 192.168.1.20 / 255.255.255.0，网关留空），"
                        "或直接在下面填写开发板 IP 并点“测试这个 IP”。")
        elif adapter.get("gateway") == "":
            tips.append(f"有线网卡“{name}”（{ips[0]}）没有默认网关，可能是直连。已按 /24 扫描它所在的网段；"
                        "如果开发板用的是其他网段的静态 IP，请填写它的 IP 并点“测试这个 IP”。")
    return tips


def direct_cable_tips(adapters: list[dict[str, Any]] | None = None) -> list[str]:
    """Alias for guidance(); static one-pager bullets when adapters is omitted."""
    if adapters is None:
        return [
            "网线直连时电脑常拿到 169.254 地址：可用“查找”扫邻居表与 .local，或给网卡设与开发板同网段的静态 IP。",
            "也可直接填写开发板 IP（含 169.254.x.x）再连接。",
        ]
    return guidance(adapters)
