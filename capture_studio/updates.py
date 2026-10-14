"""v12 update check: asks GitHub Releases for the latest version. Read-only and never replaces any file;
the user downloads the new package in the browser."""
from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable

REPO = "nulihou/kv260-capture-studio"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases"
DAY = 24 * 3600


def parse_version(text: str) -> tuple[int, int, int, int]:
    """'v0.12.0' -> (0, 12, 0, 1); a pre-release suffix (-rc1, -beta) sorts before the final release."""
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?(-[0-9A-Za-z.]+)?", text or "")
    if not match:
        return (0, 0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0), 0 if match.group(4) else 1)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def pick_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    zips = [a for a in assets or [] if str(a.get("name", "")).lower().endswith(".zip")]
    return zips[0] if zips else None


def _fetch(url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "kv260-capture-studio-update-check"})
    # urllib uses the system / environment proxy settings automatically
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, dict(response.headers), response.read()


def check(current: str, fetch: Callable[[str, float], tuple[int, dict[str, str], bytes]] = _fetch,
          timeout: float = 6.0) -> dict[str, Any]:
    """{state: newer|latest|error, version, notes, url, asset_url, asset_name, asset_size, message}."""
    try:
        status, _headers, body = fetch(API, timeout)
        data = json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        headers = dict(exc.headers or {})
        if exc.code in (403, 429) and (str(headers.get("X-RateLimit-Remaining", "")) == "0" or exc.code == 429):
            return {"state": "error", "message": "GitHub 访问次数暂时用完，请一小时后再试"}
        if exc.code == 404:
            return {"state": "error", "message": "还没有发布版本"}
        if exc.code == 407:
            return {"state": "error", "message": "代理需要登录，请检查系统代理设置"}
        return {"state": "error", "message": f"GitHub 返回错误 {exc.code}"}
    except (socket.timeout, TimeoutError):
        return {"state": "error", "message": "连接 GitHub 超时，请检查网络或代理"}
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc)).lower()
        if "proxy" in reason or "tunnel" in reason:
            return {"state": "error", "message": "代理连接失败，请检查系统代理设置"}
        if "timed out" in reason:
            return {"state": "error", "message": "连接 GitHub 超时，请检查网络或代理"}
        return {"state": "error", "message": "无法连接 GitHub，请检查网络"}
    except (OSError, ValueError, UnicodeDecodeError):
        return {"state": "error", "message": "无法读取更新信息"}
    if not isinstance(data, dict) or not data.get("tag_name"):
        return {"state": "error", "message": "无法读取更新信息"}
    version = str(data["tag_name"]).lstrip("vV")
    asset = pick_asset(data.get("assets") or [])
    return {"state": "newer" if is_newer(version, current) else "latest", "version": version,
            "notes": str(data.get("body") or "").strip()[:4000], "url": str(data.get("html_url") or RELEASES),
            "asset_url": asset.get("browser_download_url", "") if asset else "",
            "asset_name": asset.get("name", "") if asset else "", "asset_size": int(asset.get("size", 0)) if asset else 0,
            "checked_at": time.time()}


def due(settings: dict[str, Any], now: float | None = None) -> bool:
    """Quiet startup check: on unless switched off, at most once a day."""
    if str(settings.get("update_check", "1")) in ("", "0", "False", "false"):
        return False
    now = time.time() if now is None else now
    try:
        last = float(settings.get("update_checked_at") or 0)
    except (TypeError, ValueError):
        last = 0
    return now - last >= DAY


def safe_url(url: str) -> bool:
    """Only GitHub pages for this repository are opened in the browser."""
    return bool(re.match(rf"^https://(github\.com/{re.escape(REPO)}/|objects\.githubusercontent\.com/)", url or ""))
