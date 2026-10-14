"""v12 update check: asks GitHub Releases for the latest version. Read-only and never replaces any file;
the user downloads the new package in the browser.

v0.12.1: if the system proxy is dead (refused / tunnel / timeout / generic connect failure),
retry once with no proxy. HTTP answers (including rate-limit and 404) are kept as-is and never
re-tried; a working proxy path is used only once.
"""
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
Fetch = Callable[[str, float], tuple[int, dict[str, str], bytes]]


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


def is_proxy_connect_failure(exc: BaseException) -> bool:
    """True when the proxy (or the route through it) never answered; False for HTTP answers and parse errors."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 407  # proxy auth — escape hatch is a direct retry
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, OSError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError, ConnectionError, OSError)):
            return True
        text = str(reason).lower()
        return any(token in text for token in (
            "proxy", "tunnel", "timed out", "timeout", "refused", "reset", "unreachable",
            "name or service not known", "getaddrinfo", "nodename", "temporary failure"))
    return False


def _request(url: str, timeout: float, proxies: dict[str, str] | None) -> tuple[int, dict[str, str], bytes]:
    """proxies=None → system / environment proxies; proxies={} → force direct."""
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "kv260-capture-studio-update-check"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    with opener.open(request, timeout=timeout) as response:
        return response.status, dict(response.headers), response.read()


def _default_fetch(url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
    try:
        return _request(url, timeout, None)
    except Exception as first:
        if not is_proxy_connect_failure(first):
            raise
        return _request(url, timeout, {})


def _error_from(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, urllib.error.HTTPError):
        headers = dict(exc.headers or {})
        if exc.code in (403, 429) and (str(headers.get("X-RateLimit-Remaining", "")) == "0" or exc.code == 429):
            return {"state": "error", "message": "GitHub 访问次数暂时用完，请一小时后再试"}
        if exc.code == 404:
            return {"state": "error", "message": "还没有发布版本"}
        if exc.code == 407:
            return {"state": "error", "message": "代理需要登录，请检查系统代理设置"}
        return {"state": "error", "message": f"GitHub 返回错误 {exc.code}"}
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return {"state": "error", "message": "连接 GitHub 超时，请检查网络或代理"}
    if isinstance(exc, urllib.error.URLError):
        reason = str(getattr(exc, "reason", exc)).lower()
        if "proxy" in reason or "tunnel" in reason:
            return {"state": "error", "message": "代理连接失败，请检查系统代理设置"}
        if "timed out" in reason or "timeout" in reason:
            return {"state": "error", "message": "连接 GitHub 超时，请检查网络或代理"}
        return {"state": "error", "message": "无法连接 GitHub，请检查网络"}
    if isinstance(exc, OSError):
        return {"state": "error", "message": "无法连接 GitHub，请检查网络"}
    return {"state": "error", "message": "无法读取更新信息"}


def _ok(current: str, body: bytes, via: str) -> dict[str, Any]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"state": "error", "message": "无法读取更新信息"}
    if not isinstance(data, dict) or not data.get("tag_name"):
        return {"state": "error", "message": "无法读取更新信息"}
    version = str(data["tag_name"]).lstrip("vV")
    asset = pick_asset(data.get("assets") or [])
    return {"state": "newer" if is_newer(version, current) else "latest", "version": version,
            "notes": str(data.get("body") or "").strip()[:4000], "url": str(data.get("html_url") or RELEASES),
            "asset_url": asset.get("browser_download_url", "") if asset else "",
            "asset_name": asset.get("name", "") if asset else "",
            "asset_size": int(asset.get("size", 0)) if asset else 0,
            "checked_at": time.time(), "via": via}


def check(current: str, fetch: Fetch | None = None, timeout: float = 6.0,
          direct_fetch: Fetch | None = None) -> dict[str, Any]:
    """{state: newer|latest|error, version, notes, url, asset_url, asset_name, asset_size, message, via}.

    Production uses the built-in fetcher (system proxy, then one direct retry). Tests inject
    `fetch` / `direct_fetch`: a connect/proxy/timeout failure on `fetch` retries once through
    `direct_fetch` when provided. HTTPError answers (rate-limit, 404, …) are never retried.
    """
    primary = fetch if fetch is not None else _default_fetch
    try:
        _status, _headers, body = primary(API, timeout)
        return _ok(current, body, "proxy")
    except Exception as first:
        if not is_proxy_connect_failure(first):
            return _error_from(first)
        # Built-in fetcher already retried direct inside _default_fetch; surface its final error.
        if fetch is None:
            return _error_from(first)
        if direct_fetch is None:
            return _error_from(first)
        try:
            _status, _headers, body = direct_fetch(API, timeout)
            return _ok(current, body, "direct")
        except Exception as second:
            # Prefer the direct answer when it is not another connect failure (e.g. rate-limit);
            # otherwise keep the original proxy-flavoured message.
            return _error_from(second if not is_proxy_connect_failure(second) else first)


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
