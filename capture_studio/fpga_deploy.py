"""Install one compiled Kria app over the existing SSH connection and load it.

The app directory (or a zip of that directory) contains shell.json, one .xclbin
and one .dtbo. Optional files: .bit, .bit.bin, .xmodel, vart.conf.
They are copied to /lib/firmware/xilinx/<app>/ and loaded with xmutil.
A vart.conf in the folder is also installed as /etc/vart.conf.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

from .textcodec import safe_decode

APP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ALLOWED_SUFFIXES = (".xclbin", ".dtbo", ".bit.bin", ".bit", ".xmodel", ".json", ".conf")
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
STAGING_PARENT = "/tmp/capture-studio-fpga"
_EXTRACTED = "unpacked"
_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_SUDO_NEEDS_PASSWORD = re.compile(r"a password is required|a terminal is required|需要密码", re.I)
_SUDO_WRONG = re.compile(r"sorry, try again|sorry, user|不正确|密码不对", re.I)


class SudoPasswordRequired(RuntimeError):
    pass


class Prepared:
    def __init__(self, name: str, directory: Path, temp: tempfile.TemporaryDirectory[str] | None) -> None:
        self.name = name
        self.directory = directory
        self._temp = temp

    def cleanup(self) -> None:
        if self._temp is not None:
            self._temp.cleanup()
            self._temp = None


def prepare(source: Path) -> Prepared:
    """Copy the app's firmware files into a clean directory named after the app."""
    source = Path(source)
    temp = tempfile.TemporaryDirectory(prefix="capture-studio-fpga-")
    try:
        root, name = _locate(source, Path(temp.name), "")
        _check_name(name)
        staged = Path(temp.name) / "stage" / name
        staged.mkdir(parents=True)
        copied = _copy_allowed(root, staged)
        missing = [kind for kind, ok in (
            ("shell.json", (staged / "shell.json").is_file()),
            (".xclbin", any(path.suffix.lower() == ".xclbin" for path in copied)),
            (".dtbo", any(path.suffix.lower() == ".dtbo" for path in copied)),
        ) if not ok]
        if missing:
            raise ValueError("应用目录里需要 shell.json、一个 .xclbin 和一个 .dtbo")
        _check_shell(staged / "shell.json")
        return Prepared(name, staged, temp)
    except Exception:
        temp.cleanup()
        raise


def root_script(name: str) -> str:
    """Shell script that installs and loads the staged app. It runs as root."""
    _check_name(name)
    quoted = shlex.quote(name)
    return f"""set -euo pipefail
name={quoted}
stage={STAGING_PARENT}/$name
dest=/lib/firmware/xilinx/$name
command -v xmutil >/dev/null 2>&1 || {{ echo "这块板没有 xmutil" >&2; exit 2; }}
test -f "$stage/shell.json"
rm -rf "$dest"
mkdir -p "$dest"
cp -a "$stage"/. "$dest"/
chmod -R a+rX "$dest"
if [ -f "$dest/vart.conf" ]; then
  cp "$dest/vart.conf" /etc/vart.conf
fi
xmutil unloadapp || true
xmutil loadapp "$name"
xmutil listapps
"""


def deploy(ssh_args: list[str], source: Path, password: str = "",
           run: Callable[..., Any] = subprocess.run) -> str:
    """Upload source and load it. ssh_args is the connected board's ssh command plus user@host."""
    if password and any(char in password for char in "\r\n"):
        raise ValueError("sudo 密码里不能换行")
    prepared = prepare(source)
    try:
        host = ssh_args[-1]
        parent = _run(run, [*ssh_args, "mkdir", "-p", STAGING_PARENT], timeout=30)
        if parent.returncode != 0:
            raise RuntimeError("上传失败：" + _tail(parent))
        cleared = _run(run, [*ssh_args, "rm", "-rf", f"{STAGING_PARENT}/{prepared.name}"], timeout=30)
        if cleared.returncode != 0:
            raise RuntimeError("上传失败：" + _tail(cleared))
        remote_dir = f"{host}:{STAGING_PARENT}/"
        upload = _run(run, [*_scp_prefix(ssh_args), "-r", str(prepared.directory), remote_dir], timeout=300)
        if upload.returncode != 0:
            raise RuntimeError("上传失败：" + _tail(upload))
        remote, stdin = _sudo_invocation(password, root_script(prepared.name))
        loaded = _run(run, [*ssh_args, remote], input=stdin, timeout=180)
        text = safe_decode(loaded.stderr) + safe_decode(loaded.stdout)
        if loaded.returncode != 0:
            if not password and _SUDO_NEEDS_PASSWORD.search(text):
                raise SudoPasswordRequired("sudo 需要密码")
            if password and _SUDO_WRONG.search(text):
                raise RuntimeError("sudo 密码不对")
            if "没有 xmutil" in text:
                raise RuntimeError("这块板没有 xmutil")
            raise RuntimeError("xmutil loadapp 失败：" + _tail(loaded))
        if prepared.name not in text.split():
            raise RuntimeError(f"加载后的应用列表里没有 {prepared.name}")
        return f"已加载 {prepared.name}"
    finally:
        prepared.cleanup()


def _locate(source: Path, scratch: Path, fallback_name: str) -> tuple[Path, str]:
    if source.is_file() and source.suffix.lower() == ".zip":
        extracted = _extract(source, scratch / _EXTRACTED)
        return _locate(extracted, scratch, source.stem)
    if not source.is_dir():
        raise ValueError("选择 FPGA 应用目录或 zip")
    if (source / "shell.json").is_file():
        name = fallback_name if source.name == _EXTRACTED and fallback_name else source.name
        if not APP_NAME.fullmatch(name):
            raise ValueError("应用名只能用字母、数字、点、下划线和短横线")
        return source, name
    children = [path for path in source.iterdir() if path.is_dir() and (path / "shell.json").is_file()]
    zips = [path for path in source.iterdir() if path.is_file() and path.suffix.lower() == ".zip"]
    if len(children) == 1 and not zips:
        return children[0], children[0].name
    if len(zips) == 1 and not children:
        return _locate(zips[0], scratch, zips[0].stem)
    raise ValueError("这个目录里没有 FPGA 应用")


def _extract(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            parts = Path(info.filename).parts
            if not parts or info.filename.startswith("/") or ".." in parts or parts[0] in ("", "/"):
                raise ValueError("压缩包路径不安全")
            total += info.file_size
            if total > MAX_TOTAL_BYTES or info.file_size > MAX_FILE_BYTES:
                raise ValueError("FPGA 应用太大")
        archive.extractall(dest)
    tops = [path for path in dest.iterdir()]
    if len(tops) == 1 and tops[0].is_dir():
        return tops[0]
    return dest


def _copy_allowed(root: Path, dest: Path) -> list[Path]:
    copied: list[Path] = []
    total = 0
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        if not _allowed(path.name):
            continue
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("FPGA 应用太大")
        target = dest / path.name
        shutil.copyfile(path, target)
        copied.append(target)
    return copied


def _allowed(name: str) -> bool:
    if name in ("shell.json", "vart.conf"):
        return True
    lower = name.lower()
    return any(lower.endswith(suffix) for suffix in ALLOWED_SUFFIXES if suffix not in (".json", ".conf"))


def _check_shell(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("shell.json 无法读取") from exc
    if not isinstance(data, dict):
        raise ValueError("shell.json 无法读取")


def _check_name(name: str) -> None:
    if not APP_NAME.fullmatch(name):
        raise ValueError("应用名只能用字母、数字、点、下划线和短横线")


def _scp_prefix(ssh_args: list[str]) -> list[str]:
    ssh = Path(ssh_args[0])
    candidate = ssh.with_name("scp.exe" if ssh.suffix.lower() == ".exe" else "scp")
    scp = str(candidate if candidate.is_file() else "") or shutil.which("scp") or ""
    if not scp:
        raise RuntimeError("OpenSSH 不可用")
    return [scp, *ssh_args[1:-1]]


def _sudo_invocation(password: str, script: str) -> tuple[str, bytes]:
    if password:
        return "sudo -S -p '' bash -s", (password + "\n" + script).encode("utf-8")
    return "sudo -n bash -s", script.encode("utf-8")


def _run(run: Callable[..., Any], argv: list[str], input: bytes | None = None, timeout: int = 60) -> Any:
    return run(argv, input=input, timeout=timeout, capture_output=True, creationflags=_FLAGS)


def _tail(result: Any) -> str:
    text = (safe_decode(getattr(result, "stderr", b"")) + "\n" + safe_decode(getattr(result, "stdout", b""))).strip()
    return text[-400:] or f"退出码 {getattr(result, 'returncode', '')}"
