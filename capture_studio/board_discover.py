"""Find a development board on the local network and create this computer's SSH key."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import ipaddress
import os
import re
import socket
import subprocess
from pathlib import Path


XILINX_OUI = "000a35"
FAKE_IP = ipaddress.IPv4Network("198.18.0.0/15")  # Clash/Meta fake-ip and the benchmarking range
IPV4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
ARP_ROW = re.compile(
    r"(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})")
VIRTUAL_ADAPTER = re.compile(
    r"vmware|virtualbox|hyper-?v|vethernet|wsl|bluetooth|loopback|meta\b|mihomo|clash|"
    r"\btun\b|\btap\b|npcap|sing-?box|letsvpn|\bvpn\b|docker|veth",
    re.I)


def ignored_address(ip: str) -> bool:
    """Skip loopback, link-local, and the fake-ip range that answers port 22 without SSH."""
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return True
    return addr.is_loopback or addr.is_link_local or addr.is_multicast or addr in FAKE_IP


def decode_console(data: bytes) -> str:
    """ipconfig/arp on Chinese Windows are the ANSI code page, not UTF-8."""
    if not data:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("mbcs" if os.name == "nt" else "utf-8", "replace")


def mac_compact(mac: str) -> str:
    return re.sub(r"[^0-9a-fA-F]", "", mac).lower()


def xilinx_mac(mac: str) -> bool:
    return mac_compact(mac).startswith(XILINX_OUI)


def prefixes_from_ipconfig(text: str) -> list[str]:
    """IPv4 /24 prefixes for physical adapters that have a real default gateway."""
    prefixes = []
    for block in re.split(r"(?:\r?\n){2,}", text.strip()):
        title = next((line.strip() for line in block.splitlines() if line.strip()), "")
        if VIRTUAL_ADAPTER.search(title):
            continue
        addresses: list[str] = []
        gateway = ""
        for line in block.splitlines():
            found = IPV4.findall(line)
            if not found:
                continue
            if "gateway" in line.lower() or "网关" in line:
                if found[-1] != "0.0.0.0":
                    gateway = found[-1]
            elif "mask" in line.lower() or "掩码" in line:
                continue
            else:
                addresses.extend(found)
        if not gateway or ignored_address(gateway):
            continue
        for ip in addresses:
            if ip != gateway and not ignored_address(ip):
                prefix = ".".join(ip.split(".")[:3]) + "."
                if prefix not in prefixes:
                    prefixes.append(prefix)
    return prefixes


def parse_arp(text: str) -> dict[str, str]:
    return {ip: mac for ip, mac in ARP_ROW.findall(text)}


def choose_board_host(port22: set[str], arp: dict[str, str], named: list[str]) -> tuple[str, str]:
    """Pick one board address. Several matches stay unselected."""
    ssh_hosts = set(port22)
    xilinx = sorted(ip for ip in ssh_hosts if xilinx_mac(arp.get(ip, "")))
    if len(xilinx) == 1:
        return xilinx[0], f"已找到开发板 {xilinx[0]}。"
    if len(xilinx) > 1:
        return "", "同一网络有多块 Xilinx 开发板：" + "、".join(xilinx) + "。请填写新板的地址。"
    named_ssh = [ip for ip in named if ip in ssh_hosts]
    if len(named_ssh) == 1:
        return named_ssh[0], f"已找到名为 kria 的设备 {named_ssh[0]}。"
    only = sorted(ssh_hosts)
    if len(only) == 1:
        return only[0], f"只找到一台开着 SSH 的设备 {only[0]}。若不是新开发板，请改地址。"
    if len(only) > 1:
        shown = "、".join(only[:6])
        return "", "找到多台开着 SSH 的设备：" + shown + "。请填写新板的地址。"
    return "", "没有在同一网络找到开发板。请确认新板已联网，或直接填写它的 IP。"


def ensure_ssh_key(home: Path, runner=None) -> Path:
    """Create this computer's KV260 key when it does not exist yet."""
    path = home / ".ssh" / "id_ed25519_kv260"
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    command = ["ssh-keygen", "-q", "-t", "ed25519", "-f", str(path), "-N", "", "-C", "capture-studio"]
    run = runner or subprocess.run
    result = run(command, capture_output=True, text=True, timeout=20)
    if getattr(result, "returncode", 1) != 0 or not path.is_file():
        detail = getattr(result, "stderr", "") or "ssh-keygen 没有生成私钥。"
        raise RuntimeError("没能在这台电脑上生成 SSH 私钥。" + str(detail)[-200:])
    return path


def probe_ssh(ip: str, timeout: float = 0.3) -> bool:
    """True only when the host sends an SSH banner. A bare TCP accept is not a board."""
    try:
        with socket.create_connection((ip, 22), timeout) as sock:
            sock.settimeout(0.5)
            try:
                banner = sock.recv(128)
            except OSError:
                banner = b""
            return banner.startswith(b"SSH-")
    except OSError:
        return False


def resolve_kria() -> list[str]:
    try:
        infos = socket.getaddrinfo("kria.local", 22, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return sorted(ip for ip in {item[4][0] for item in infos} if not ignored_address(ip))


def pick_from_discovery(found: list[dict]) -> tuple[str, str]:
    """Single board -> select it; otherwise only a single SSH host is auto-selected."""
    boards = [r["host"] for r in found if r.get("kind") == "board"]
    if len(boards) == 1:
        tag = next(r for r in found if r["host"] == boards[0])
        return boards[0], f"已找到开发板 {boards[0]}" + (f"（{tag['vendor']}）" if tag.get("vendor") else "") + "。"
    if len(boards) > 1:
        return "", "找到多块开发板：" + "、".join(boards[:6]) + "。请填写新板的地址。"
    hosts = [r["host"] for r in found if r.get("kind") != "pc"] or [r["host"] for r in found]
    if len(hosts) == 1:
        return hosts[0], f"只找到一台开着 SSH 的设备 {hosts[0]}。若不是新开发板，请改地址。"
    if hosts:
        return "", "找到多台开着 SSH 的设备：" + "、".join(hosts[:6]) + "。请填写新板的地址。"
    return "", "没有找到开发板。请确认新板已联网，或直接填写它的 IP。"


def find_board() -> tuple[str, str]:
    """v12: one discovery path for every caller (see discovery.py); no gateway requirement."""
    from . import discovery
    result = discovery.discover()
    host, note = pick_from_discovery(result["found"])
    if not host and result["guidance"]:
        note += "像是网线直连：打开“连接向导”查看直连提示，或填写开发板 IP 后点“测试这个 IP”。"
    return host, note
