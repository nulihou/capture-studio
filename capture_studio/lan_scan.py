"""LAN discovery for the first-run wizard (v7).

Only a quick TCP connect to port 22 per address (plus reading the SSH banner the server sends
unprompted).  No ping sweeps, no other ports, no authentication attempts.  Bounded: at most
/24 per adapter, at most 3 adapters, short timeouts, run on a worker thread.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable

MAX_ADAPTERS = 3
FAKE_IP = ipaddress.IPv4Network("198.18.0.0/15")
VIRTUAL_ADAPTER = re.compile(
    r"vmware|virtualbox|hyper-?v|vethernet|wsl|bluetooth|loopback|meta\b|mihomo|clash|"
    r"\btun\b|\btap\b|npcap|sing-?box|letsvpn|\bvpn\b|docker|veth",
    re.I)


def ignored_address(ip: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return True
    return addr.is_loopback or addr.is_link_local or addr.is_multicast or addr in FAKE_IP


def candidate_hosts(addresses: Iterable[tuple[str, int]], limit_prefix: int = 24) -> list[str]:
    """[(ip, prefix_len)] of active adapters -> host list, own IPs excluded, private IPv4 only."""
    hosts: list[str] = []
    own = set()
    nets = []
    for ip, prefix in addresses:
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if ignored_address(ip) or not addr.is_private:
            continue
        own.add(str(addr))
        net = ipaddress.IPv4Network(f"{ip}/{max(int(prefix), limit_prefix)}", strict=False)
        if net not in nets:
            nets.append(net)
    for net in nets[:MAX_ADAPTERS]:
        for host in net.hosts():
            text = str(host)
            if text not in own and text not in hosts:
                hosts.append(text)
    return hosts


def local_addresses() -> list[tuple[str, int]]:
    """Active IPv4 adapters via Qt (no shell commands, locale independent)."""
    try:
        from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
    except Exception:
        return []
    out = []
    for iface in QNetworkInterface.allInterfaces():
        flags = iface.flags()
        if not (flags & QNetworkInterface.InterfaceFlag.IsUp) or (flags & QNetworkInterface.InterfaceFlag.IsLoopBack):
            continue
        if not (flags & QNetworkInterface.InterfaceFlag.IsRunning):
            continue
        if VIRTUAL_ADAPTER.search(f"{iface.name()} {iface.humanReadableName()}"):
            continue
        for entry in iface.addressEntries():
            ip = entry.ip()
            if ip.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol and not ignored_address(ip.toString()):
                out.append((ip.toString(), entry.prefixLength()))
    return out


def probe(host: str, port: int = 22, timeout: float = 0.35,
          connect: Callable[..., Any] = socket.create_connection) -> dict[str, Any] | None:
    try:
        sock = connect((host, port), timeout=timeout)
    except OSError:
        return None
    banner = ""
    try:
        sock.settimeout(0.6)
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


def banner_hint(banner: str) -> str:
    low = banner.lower()
    for key, label in (("ubuntu", "Ubuntu"), ("debian", "Debian"), ("raspbian", "Raspberry Pi OS"),
                       ("petalinux", "PetaLinux"), ("dropbear", "Dropbear (嵌入式)"), ("windows", "Windows"),
                       ("openssh", "OpenSSH")):
        if key in low:
            return label
    return ""


def scan(hosts: list[str], workers: int = 64, cancel: Callable[[], bool] = lambda: False,
         prober: Callable[[str], dict[str, Any] | None] = probe) -> list[dict[str, Any]]:
    found = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 64))) as pool:
        futures = [pool.submit(lambda h=h: None if cancel() else prober(h)) for h in hosts]
        for future in futures:
            result = future.result()
            if result:
                found.append(result)
    return sorted(found, key=lambda item: tuple(int(x) for x in item["host"].split(".")))
