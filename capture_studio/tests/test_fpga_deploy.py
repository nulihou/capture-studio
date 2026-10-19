import json
import subprocess
import unittest
import zipfile
from pathlib import Path
import tempfile

from capture_studio.fpga_deploy import SudoPasswordRequired, deploy, prepare, root_script


def _app(root: Path, name: str = "demo-app") -> Path:
    folder = root / name
    folder.mkdir()
    (folder / "shell.json").write_text(json.dumps({"shell_type": "XRT_FLAT", "accel_name": name}), encoding="utf-8")
    (folder / f"{name}.xclbin").write_bytes(b"xclbin")
    (folder / f"{name}.dtbo").write_bytes(b"dtbo")
    (folder / "notes.txt").write_text("skip", encoding="utf-8")
    return folder


class FpgaPackageTests(unittest.TestCase):
    def test_directory_keeps_firmware_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _app(Path(tmp))
            (folder / "vart.conf").write_text("firmware=demo\n", encoding="utf-8")
            prepared = prepare(folder)
            try:
                names = sorted(path.name for path in prepared.directory.iterdir())
                self.assertEqual(prepared.name, "demo-app")
                self.assertEqual(names, ["demo-app.dtbo", "demo-app.xclbin", "shell.json", "vart.conf"])
            finally:
                prepared.cleanup()

    def test_parent_directory_and_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _app(root, "kv260-demo")
            prepared = prepare(root)
            try:
                self.assertEqual(prepared.name, "kv260-demo")
            finally:
                prepared.cleanup()
            archive = root / "kv260-demo.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("kv260-demo/shell.json", '{"shell_type":"XRT_FLAT"}')
                zf.writestr("kv260-demo/kv260-demo.xclbin", b"x")
                zf.writestr("kv260-demo/kv260-demo.dtbo", b"d")
            prepared = prepare(archive)
            try:
                self.assertEqual(prepared.name, "kv260-demo")
                self.assertTrue((prepared.directory / "shell.json").is_file())
            finally:
                prepared.cleanup()

    def test_flat_zip_uses_the_archive_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "flat-app.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("shell.json", '{"shell_type":"XRT_FLAT"}')
                zf.writestr("flat-app.xclbin", b"x")
                zf.writestr("flat-app.dtbo", b"d")
            prepared = prepare(archive)
            try:
                self.assertEqual(prepared.name, "flat-app")
            finally:
                prepared.cleanup()

    def test_rejects_incomplete_unsafe_and_odd_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "demo-app"
            folder.mkdir()
            (folder / "shell.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare(folder)
            archive = root / "slip.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../evil.xclbin", b"x")
            with self.assertRaisesRegex(ValueError, "不安全"):
                prepare(archive)
            odd = root / "my app"
            odd.mkdir()
            (odd / "shell.json").write_text("{}", encoding="utf-8")
            (odd / "a.xclbin").write_bytes(b"x")
            (odd / "a.dtbo").write_bytes(b"d")
            with self.assertRaisesRegex(ValueError, "应用名"):
                prepare(odd)

    def test_script_loads_the_named_app(self):
        script = root_script("demo-app")
        self.assertIn("xmutil loadapp", script)
        self.assertIn("/lib/firmware/xilinx/$name", script)
        self.assertIn("/etc/vart.conf", script)
        self.assertNotIn("secret", script)


class FpgaDeployTests(unittest.TestCase):
    def _runner(self, sudo_code=0, sudo_out=b"demo-app XRT_FLAT 0\n", sudo_err=b""):
        calls = []

        def run(argv, input=None, timeout=None, capture_output=True, creationflags=0):
            calls.append((list(argv), input))
            if argv[-1:] == ["sudo -n bash -s"] or argv[-1:] == ["sudo -S -p '' bash -s"]:
                return subprocess.CompletedProcess(argv, sudo_code, sudo_out, sudo_err)
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        return calls, run

    def test_upload_then_load_without_putting_the_password_on_the_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _app(Path(tmp))
            calls, run = self._runner()
            note = deploy(["ssh", "-i", "key", "-o", "BatchMode=yes", "ubuntu@10.0.0.8"], folder, "secret", run)
        self.assertEqual(note, "已加载 demo-app")
        upload = next(argv for argv, _ in calls if "scp" in Path(argv[0]).name.lower())
        self.assertIn("ubuntu@10.0.0.8:/tmp/capture-studio-fpga/", upload)
        remote, stdin = calls[-1]
        self.assertEqual(remote[-1], "sudo -S -p '' bash -s")
        self.assertTrue(stdin.startswith(b"secret\n"))
        self.assertNotIn("secret", " ".join(remote))

    def test_passwordless_sudo_and_password_errors(self):
        ssh = ["ssh", "-i", "key", "ubuntu@10.0.0.8"]
        with tempfile.TemporaryDirectory() as tmp:
            folder = _app(Path(tmp))
            _, run = self._runner()
            self.assertEqual(deploy(ssh, folder, "", run), "已加载 demo-app")
            _, needs = self._runner(1, b"", b"sudo: a password is required\n")
            with self.assertRaises(SudoPasswordRequired):
                deploy(ssh, folder, "", needs)
            _, wrong = self._runner(1, b"", b"Sorry, try again")
            with self.assertRaisesRegex(RuntimeError, "密码不对"):
                deploy(ssh, folder, "nope", wrong)
            _, missing = self._runner(0, b"other-app\n", b"")
            with self.assertRaisesRegex(RuntimeError, "应用列表里没有 demo-app"):
                deploy(ssh, folder, "", missing)


if __name__ == "__main__":
    unittest.main()
