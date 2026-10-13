"""Find a new KV260 on the local network and create this computer's SSH key."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re
import socket
import subprocess
from pathlib import Path


XILINX_OUI = "000a35"
IPV4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
ARP_ROW = re.compile(
    r"(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})")


def mac_compact(mac: str) -> str:
    return re.sub(r"[^0-9a-fA-F]", "", mac).lower()


def xilinx_mac(mac: str) -> bool:
    return mac_compact(mac).startswith(XILINX_OUI)


def prefixes_from_ipconfig(text: str) -> list[str]:
    """IPv4 /24 prefixes for adapters that have a real default gateway."""
    prefixes = []
    for block in re.split(r"(?:\r?\n){2,}", text.strip()):
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
        if not gateway:
            continue
        for ip in addresses:
            if ip != gateway and not ip.startswith("127."):
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
    try:
        with socket.create_connection((ip, 22), timeout):
            return True
    except OSError:
        return False


def resolve_kria() -> list[str]:
    try:
        infos = socket.getaddrinfo("kria.local", 22, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return sorted({item[4][0] for item in infos})


def find_board() -> tuple[str, str]:
    flags = subprocess.CREATE_NO_WINDOW if __import__("os").name == "nt" else 0
    config = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=10,
                            creationflags=flags, encoding="utf-8", errors="replace")
    prefixes = prefixes_from_ipconfig(config.stdout or "")
    own: set[str] = set()
    try:
        own.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    targets = [f"{prefix}{host}" for prefix in prefixes[:2] for host in range(1, 255)
               if f"{prefix}{host}" not in own]
    open_hosts: set[str] = set()
    if targets:
        with ThreadPoolExecutor(max_workers=80) as pool:
            for ip, opened in zip(targets, pool.map(probe_ssh, targets)):
                if opened:
                    open_hosts.add(ip)
    arp = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10,
                         creationflags=flags, encoding="utf-8", errors="replace")
    return choose_board_host(open_hosts, parse_arp(arp.stdout or ""), resolve_kria())
