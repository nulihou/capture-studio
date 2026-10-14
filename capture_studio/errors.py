"""Friendly error messages and the diagnostic bundle (v7)."""
from __future__ import annotations

import json
import platform
import re
import time
import zipfile
from pathlib import Path
from typing import Any

# (regex, title, advice, retry)
RULES = [
    (r"could not open port.*(PermissionError|Access is denied|拒绝访问)", "串口被占用",
     "这个串口正被其他程序（或另一个终端窗口）使用。关闭它后再打开。", True),
    (r"could not open port.*(FileNotFoundError|cannot find|找不到指定)", "找不到这个串口",
     "串口可能已拔出或编号变了。重新插好后点“刷新”，再选一次端口。", True),
    (r"Permission denied \(publickey|公钥还没有装到", "开发板拒绝登录",
     "这台电脑的密钥还没装到开发板上。在连接窗口填一次登录密码，软件会自动安装密钥。", True),
    (r"Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED", "开发板身份变了",
     "开发板重装过系统或换了一块板。确认无误后，在 known_hosts 里删除这台主机的旧记录再连。", False),
    (r"Could not resolve hostname|Name or service not known|getaddrinfo", "找不到这个地址",
     "检查开发板地址是否填错，或用“查找”自动搜索局域网。", True),
    (r"Connection refused", "开发板拒绝连接",
     "开发板开机了但 SSH 服务没开。等开机完成，或在板上启动 ssh 服务。", True),
    (r"No route to host|Network is unreachable|网络不可达", "网络不通",
     "电脑和开发板不在同一网络。检查网线/Wi-Fi，以及两边的 IP 网段。", True),
    (r"timed out|Timeout|超时", "连接超时",
     "开发板可能没开机、网线松了或 IP 变了。检查后点“重试”。", True),
    (r"No space left on device|磁盘空间不足", "磁盘满了", "清理输出文件夹或换一个空间更大的位置。", False),
    (r"Device or resource busy|设备忙", "摄像头被占用", "关闭其他正在用摄像头的程序（含实时预览），再试一次。", True),
    (r"Could not find video device|Could not enumerate video devices|I/O error|No such device|未发现摄像头", "找不到摄像头",
     "重新插拔摄像头，换一个 USB 口，然后点“扫描”。", True),
    (r"ffmpeg not found|ffprobe not found|找不到 ffmpeg", "缺少 ffmpeg",
     "在设置里指定 ffmpeg/ffprobe 的位置，或把它们放到软件的 bin 文件夹里。", False),
    (r"Board returned 404|not found", "开发板程序版本较旧", "重新连接一次，软件会自动同步板端程序。", True),
    (r"OpenSSH", "缺少 OpenSSH", "在 Windows“可选功能”里安装“OpenSSH 客户端”。", False),
]


def friendly(raw: str) -> dict[str, Any]:
    text = str(raw or "")
    for pattern, title, advice, retry in RULES:
        if re.search(pattern, text, re.I):
            return {"title": title, "advice": advice, "retry": retry, "raw": text}
    return {"title": "操作没有完成", "advice": "可以重试；如果反复出现，请复制诊断包发给维护者。", "retry": True, "raw": text}


SECRET_KEYS = re.compile(r"pass|token|secret|key", re.I)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if SECRET_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)",
                       "<private key removed>", value, flags=re.S)
        value = re.sub(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}", r"\1 ***", value)
        value = re.sub(r"(?i)(sshpass\s+-p\s*|plink\b.*?-pw\s+)\S+", r"\1***", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "sk-***", value)
        value = re.sub(r'''(?i)([\w-]*(?:password|passwd|pwd|token|secret|api[_-]?key)[\w-]*["']?\s*[=:]\s*)(["']?)[^\s"',}]+''',
                       r"\1\2***", value)
        return re.sub(r"[A-Za-z]:\\Users\\[^\\]+", r"C:\\Users\\<user>", value)
    return value


def bundle(path: Path, state: dict[str, Any], extra_logs: list[Path] | None = None) -> Path:
    """Zip with logs, board info, peripherals and settings — secrets redacted, no media, no keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact({
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": platform.platform(), "python": platform.python_version(),
        "status": state.get("status"), "connected": state.get("connected"),
        "board_label": state.get("board_label"), "camera_label": state.get("camera_label"),
        "settings": state.get("settings") or {}, "board_modes": state.get("board_modes"),
        "pc_modes": state.get("pc_modes"), "last_error": state.get("last_error"),
    })
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary.json", json.dumps(safe, ensure_ascii=False, indent=2))
        zf.writestr("logs.txt", "\n".join(str(x) for x in redact(state.get("logs") or [])))
        zf.writestr("board_info.json", json.dumps(redact(state.get("board_info") or {}), ensure_ascii=False, indent=2))
        zf.writestr("board_status.json", json.dumps(redact(state.get("board_status") or {}), ensure_ascii=False, indent=2))
        zf.writestr("peripherals.json", json.dumps(redact(state.get("peripherals") or []), ensure_ascii=False, indent=2))
        zf.writestr("pc_peripherals.json", json.dumps(redact(state.get("pc_peripherals") or []), ensure_ascii=False, indent=2))
        for log in extra_logs or []:
            if log.is_file() and log.stat().st_size < 2_000_000 and log.suffix in (".log", ".txt", ".json"):
                zf.writestr("extra/" + log.name, redact(log.read_text(encoding="utf-8", errors="replace")))
    return path
