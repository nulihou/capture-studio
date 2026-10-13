import json
import unittest
from pathlib import Path
import tempfile

from capture_studio.board_sync import (BOARD_FILES, authentication_failed, authorized_key_command,
                                       build_remote_script, changed_names, decide_sync, file_hashes,
                                       package_directory, stamp_matches, sync_note, write_changed)
from capture_studio.board_discover import (choose_board_host, ensure_ssh_key, parse_arp,
                                           prefixes_from_ipconfig, xilinx_mac)
from capture_studio.portable_connect import FRESH_BOARD


class BoardSyncTests(unittest.TestCase):
    def test_shipped_package_includes_current_options(self):
        root = package_directory()
        source = (root / "core.py").read_text(encoding="utf-8")
        self.assertIn("gain: int | None = None", source)
        self.assertIn("camera_lab.py", BOARD_FILES)
        self.assertEqual(set(BOARD_FILES), set(file_hashes(root)))

    def test_restart_only_when_code_or_service_requires_it(self):
        self.assertEqual("keep", decide_sync(False, True, True, False))
        self.assertEqual("keep", decide_sync(False, True, True, True))
        self.assertEqual("restart", decide_sync(True, True, True, False))
        self.assertEqual("restart", decide_sync(False, False, True, False))
        self.assertEqual("start", decide_sync(True, False, False, False))
        self.assertEqual("blocked", decide_sync(True, False, True, True))

    def test_changed_files_and_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)
            write_changed(package, {"core.py": "aGVsbG8="}, ["core.py"])
            current = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
            self.assertEqual([], changed_names(package, {"core.py": current}))
            self.assertEqual(["core.py"], changed_names(package, {"core.py": "stale"}))
            self.assertFalse(stamp_matches(package, {"core.py": current}))
            (package / ".package_stamp.json").write_text(
                json.dumps({"files": {"core.py": current}}), encoding="utf-8")
            self.assertTrue(stamp_matches(package, {"core.py": current}))

    def test_notes_and_remote_script(self):
        self.assertIn("已是当前版本", sync_note({"action": "keep", "changed": []}))
        note = sync_note({"action": "restart", "changed": ["core.py"], "compile_note": ""})
        self.assertIn("重新启动", note)
        self.assertIn("core.py", note)
        many = sync_note({"action": "start", "changed": ["a.py", "b.py", "c.py", "d.py", "e.py"]})
        self.assertIn("5 个文件", many)
        script = build_remote_script("/home/ubuntu/capture_studio_platform_20261009")
        self.assertTrue(script.startswith("# -*- coding: utf-8 -*-"))
        script.encode("utf-8")
        compile(script, "<board-sync>", "exec")
        self.assertIn("camera_lab.py", script)
        self.assertIn("native_capture.c", script)
        with self.assertRaises(RuntimeError):
            build_remote_script("not-absolute")

    def test_new_board_defaults_are_not_the_lab_board(self):
        self.assertEqual("", FRESH_BOARD["host"])
        self.assertEqual("", FRESH_BOARD["serial"])
        self.assertEqual("/home/ubuntu/capture_studio", FRESH_BOARD["board_root"])
        self.assertNotIn("192.168.110.35", FRESH_BOARD.values())
        self.assertNotIn("HHW001", FRESH_BOARD.values())
        command = authorized_key_command("ssh-ed25519 AAAACORRECT comment")
        self.assertNotIn("secret-password", command)
        self.assertIn("authorized_keys", command)
        self.assertTrue(authentication_failed("ubuntu@board: Permission denied (publickey)."))
        self.assertFalse(authentication_failed("Connection timed out"))

    def test_board_address_is_chosen_only_when_unambiguous(self):
        self.assertTrue(xilinx_mac("00-0A-35-11-22-33"))
        self.assertFalse(xilinx_mac("00:1a:2b:3c:4d:5e"))
        one, note = choose_board_host({"192.168.1.20", "192.168.1.9"},
                                      {"192.168.1.20": "00-0a-35-aa-bb-cc"}, [])
        self.assertEqual("192.168.1.20", one)
        self.assertIn("已找到开发板", note)
        none, several = choose_board_host({"192.168.1.20", "192.168.1.21"},
                                          {"192.168.1.20": "00:0a:35:aa:bb:cc",
                                           "192.168.1.21": "00:0a:35:aa:bb:cd"}, [])
        self.assertEqual("", none)
        self.assertIn("多块", several)
        self.assertEqual("", choose_board_host(set(), {}, [])[0])
        text = """
Ethernet adapter Ethernet:

   IPv4 Address. . . . . . . . . . . : 192.168.110.8
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.110.1

Wireless LAN adapter Local Area Connection* 1:

   IPv4 Address. . . . . . . . . . . : 172.22.0.1
   Subnet Mask . . . . . . . . . . . : 255.255.240.0
"""
        self.assertEqual(["192.168.110."], prefixes_from_ipconfig(text))
        self.assertEqual({"192.168.110.35": "00-0a-35-01-02-03"},
                         parse_arp("  192.168.110.35        00-0a-35-01-02-03     dynamic"))

    def test_ssh_key_is_created_on_this_computer(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            target = home / ".ssh" / "id_ed25519_kv260"

            def runner(command, **_kwargs):
                Path(command[command.index("-f") + 1]).write_text("private\n", encoding="utf-8")

                class Result:
                    returncode = 0
                    stderr = ""

                return Result()

            created = ensure_ssh_key(home, runner)
            self.assertEqual(target, created)
            self.assertEqual(target, ensure_ssh_key(home, runner))
