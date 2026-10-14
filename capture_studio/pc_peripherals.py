"""PC-side peripheral scan (v7, Windows, read-only): PnP devices via PowerShell + COM ports via pyserial."""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Callable

try:
    from .textcodec import safe_decode
except ImportError:
    from textcodec import safe_decode

_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
CLASS_MAP = {"Camera": "video", "Image": "video", "Ports": "serial", "USB": "usb", "AudioEndpoint": "audio",
             "MEDIA": "audio", "Monitor": "display", "Net": "net", "DiskDrive": "storage", "HIDClass": "usb",
             "Bluetooth": "usb"}
PS_SCRIPT = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
             "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
             "Where-Object { $_.Class -in @('Camera','Image','Ports','USB','AudioEndpoint','MEDIA','Monitor','Net','DiskDrive','HIDClass','Bluetooth') } | "
             "Select-Object Class,FriendlyName,InstanceId,Status,Manufacturer | ConvertTo-Json -Compress")


def vid_pid(instance: str) -> str:
    match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", instance or "", re.I)
    return f"{match.group(1)}:{match.group(2)}".lower() if match else ""


def parse_pnp(text: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    items = []
    for row in data:
        if not isinstance(row, dict):
            continue
        klass = str(row.get("Class") or "")
        category = CLASS_MAP.get(klass)
        if not category:
            continue
        instance = str(row.get("InstanceId") or "")
        if klass == "USB" and re.search(r"ROOT_HUB|USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}&MI_", instance, re.I):
            continue  # root hubs and per-interface children add noise
        name = str(row.get("FriendlyName") or instance)
        vp = vid_pid(instance)
        items.append({"category": category, "id": f"pc-{category}:{instance}", "name": name,
                      "summary": " · ".join(x for x in (vp, str(row.get("Status") or "")) if x),
                      "props": [(k, str(v)) for k, v in (("类别", klass), ("名称", name), ("VID:PID", vp),
                                ("厂商", row.get("Manufacturer") or ""), ("状态", row.get("Status") or ""),
                                ("实例", instance)) if str(v)], "side": "pc"})
    return items


def com_ports(list_ports: Callable[[], Any] | None = None) -> list[dict[str, Any]]:
    if list_ports is None:
        try:
            from serial.tools.list_ports import comports as list_ports
        except Exception:
            return []
    from .peripherals import SERIAL_CHIPS
    out = []
    for port in list_ports():
        vp = f"{port.vid:04x}:{port.pid:04x}" if getattr(port, "vid", None) is not None else ""
        chip = SERIAL_CHIPS.get(vp, "")
        out.append({"category": "serial", "id": f"pc-serial:{port.device}", "name": port.description or port.device,
                    "summary": " · ".join(x for x in (port.device, chip) if x), "side": "pc", "port": port.device,
                    "props": [(k, str(v)) for k, v in (("端口", port.device), ("芯片", chip), ("VID:PID", vp),
                              ("厂商", getattr(port, "manufacturer", "") or ""), ("序列号", getattr(port, "serial_number", "") or ""),
                              ("硬件 ID", getattr(port, "hwid", "") or "")) if str(v)]})
    return out


def scan(run: Callable[..., Any] = subprocess.run, list_ports: Callable[[], Any] | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if os.name == "nt" or run is not subprocess.run:
        try:
            result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT],
                         capture_output=True, timeout=25, creationflags=_FLAGS)
            raw = result.stdout
            items += parse_pnp(safe_decode(raw) if isinstance(raw, bytes) else str(raw or ""))
        except Exception:
            pass
    ports = com_ports(list_ports)
    known = {p["port"] for p in ports}
    items = [i for i in items if not (i["category"] == "serial" and any(f"({p})" in i["name"] for p in known))]
    return sorted(ports + items, key=lambda i: (i["category"], i["name"].lower()))
