import io
import json
import os
import socket
import unittest
import urllib.error

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from capture_studio import updates

REL = {"tag_name": "v0.13.0", "html_url": "https://github.com/nulihou/kv260-capture-studio/releases/tag/v0.13.0",
       "body": "## 新功能\n- faster", "assets": [{"name": "notes.txt", "browser_download_url": "x", "size": 1},
       {"name": "KV260CaptureStudio_v0.13.0_portable.zip", "size": 52428800,
        "browser_download_url": "https://github.com/nulihou/kv260-capture-studio/releases/download/v0.13.0/a.zip"}]}


def ok(data):
    return lambda url, timeout: (200, {}, json.dumps(data).encode())


def raising(exc):
    def fetch(url, timeout):
        raise exc
    return fetch


def http(code, headers=None):
    return raising(urllib.error.HTTPError(updates.API, code, "x", headers or {}, io.BytesIO(b"")))


class Versions(unittest.TestCase):
    def test_semver(self):
        self.assertTrue(updates.is_newer("0.13.0", "0.12.0"))
        self.assertTrue(updates.is_newer("v0.12.1", "0.12.0"))
        self.assertTrue(updates.is_newer("1.0", "0.99.9"))
        self.assertFalse(updates.is_newer("0.12.0", "0.12.0"))
        self.assertFalse(updates.is_newer("0.9.0", "0.12.0"))  # numeric, not string compare
        self.assertFalse(updates.is_newer("0.12.0-rc1", "0.12.0"))
        self.assertTrue(updates.is_newer("0.12.0", "0.12.0-rc1"))
        self.assertFalse(updates.is_newer("garbage", "0.12.0"))


class Check(unittest.TestCase):
    def test_newer_with_zip_asset(self):
        r = updates.check("0.12.0", ok(REL))
        self.assertEqual(r["state"], "newer")
        self.assertEqual(r["version"], "0.13.0")
        self.assertTrue(r["asset_name"].endswith(".zip"))
        self.assertEqual(r["asset_size"], 52428800)
        self.assertIn("新功能", r["notes"])

    def test_latest(self):
        self.assertEqual(updates.check("0.13.0", ok(REL))["state"], "latest")
        self.assertEqual(updates.check("0.13.0", ok(dict(REL, assets=[])))["asset_url"], "")

    def test_errors_are_friendly(self):
        cases = [
            (http(403, {"X-RateLimit-Remaining": "0"}), "访问次数"), (http(429), "访问次数"), (http(404), "还没有发布"),
            (http(407), "代理"), (http(500), "500"),
            (raising(urllib.error.URLError(ConnectionRefusedError("Tunnel connection failed: 502"))), "代理"),
            (raising(urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))), "无法连接"),
            (raising(socket.timeout("timed out")), "超时"), (raising(TimeoutError()), "超时"),
            (lambda u, t: (200, {}, b"<html>"), "无法读取"), (ok({"message": "x"}), "无法读取"), (ok([]), "无法读取"),
        ]
        for fetch, needle in cases:
            r = updates.check("0.12.0", fetch)
            self.assertEqual(r["state"], "error")
            self.assertIn(needle, r["message"])

    def test_error_messages_translated(self):
        from capture_studio import i18n
        i18n.LANG = "en"
        try:
            for fetch in (http(403, {"X-RateLimit-Remaining": "0"}), http(404), http(407), http(503), raising(TimeoutError()),
                          raising(urllib.error.URLError("proxy")), raising(urllib.error.URLError("x")), ok({})):
                text = i18n.tr_msg(updates.check("0.12.0", fetch)["message"])
                self.assertNotRegex(text, "[\u4e00-\u9fff]", text)
            for msg in ("有新版本 v0.13.0", "已是最新 v0.12.0", "有新版本 v0.13.0，可在设置页下载", "当前 v0.12.0", "检查更新失败"):
                self.assertNotRegex(i18n.tr_msg(msg), "[\u4e00-\u9fff]", msg)
        finally:
            i18n.LANG = "zh"

    def test_daily_cache_and_toggle(self):
        self.assertTrue(updates.due({}, 10**9))
        self.assertFalse(updates.due({"update_checked_at": str(10**9 - 3600)}, 10**9))
        self.assertTrue(updates.due({"update_checked_at": str(10**9 - updates.DAY)}, 10**9))
        self.assertFalse(updates.due({"update_check": "0"}, 10**9))
        self.assertTrue(updates.due({"update_checked_at": "junk"}, 10**9))

    def test_safe_url(self):
        self.assertTrue(updates.safe_url(REL["assets"][1]["browser_download_url"]))
        self.assertTrue(updates.safe_url(REL["html_url"]))
        self.assertFalse(updates.safe_url("https://evil.example/a.zip"))
        self.assertFalse(updates.safe_url("https://github.com/other/repo/releases"))
        self.assertFalse(updates.safe_url("file:///C:/x.exe"))

    def test_api_url(self):
        self.assertEqual(updates.API, "https://api.github.com/repos/nulihou/kv260-capture-studio/releases/latest")


class Dialog(unittest.TestCase):
    def test_dialog_targets_safe_url(self):
        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication.instance() or QApplication([])
        from capture_studio import window
        parent = QWidget()
        r = updates.check("0.12.0", ok(REL))
        dlg = window.UpdateDialog(parent, r)
        self.assertEqual(dlg.target_url(), REL["assets"][1]["browser_download_url"])
        self.assertIn("faster", dlg.notes.toPlainText())
        bad = dict(r, asset_url="https://evil.example/x.zip", url="javascript:x")
        self.assertEqual(window.UpdateDialog(parent, bad).target_url(), updates.RELEASES)
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
