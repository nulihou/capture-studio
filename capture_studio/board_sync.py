"""Copy the current board package over SSH and restart the agent when it changed."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

try:
    from .textcodec import safe_decode
except ImportError:  # loaded as a plain script
    from textcodec import safe_decode


BOARD_FILES = (
    "__init__.py",
    "core.py",
    "board_agent.py",
    "board_devices.py",
    "camera_lab.py",
    "gates.py",
    "live_preview.py",
    "preview_worker.py",
    "frame_rates.py",
    "native_source.py",
    "native_worker.py",
    "native_capture.c",
    "inference.py",
    "board_infer_push.py",
)


def package_directory() -> Path:
    """Directory that holds the board-side source shipped with this app."""
    here = Path(__file__).resolve().parent
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", "")) / "capture_studio")
        candidates.append(Path(sys.executable).resolve().parent / "capture_studio")
    candidates.append(here)
    for path in candidates:
        if (path / "board_agent.py").is_file() and (path / "camera_lab.py").is_file():
            return path
    raise RuntimeError("安装包里缺少板端采集程序文件。")


def file_hashes(root: Path) -> dict[str, str]:
    hashes = {}
    for name in BOARD_FILES:
        path = root / name
        if not path.is_file():
            raise RuntimeError(f"板端采集程序缺少 {name}")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def decide_sync(changed: bool, stamp_ok: bool, listening: bool, recording: bool) -> str:
    """Return keep, start, restart, or blocked."""
    if recording and (changed or not stamp_ok):
        return "blocked"
    if not listening:
        return "start"
    if changed or not stamp_ok:
        return "restart"
    return "keep"


def stamp_matches(package: Path, hashes: dict[str, str]) -> bool:
    path = package / ".package_stamp.json"
    if not path.is_file():
        return False
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("files") or {}
    except (OSError, ValueError):
        return False
    return saved == hashes


def changed_names(package: Path, hashes: dict[str, str]) -> list[str]:
    changed = []
    for name, digest in hashes.items():
        target = package / name
        current = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else ""
        if current != digest:
            changed.append(name)
    return changed


def write_changed(package: Path, encoded: dict[str, str], names: list[str]) -> None:
    package.mkdir(parents=True, exist_ok=True)
    for name in names:
        (package / name).write_bytes(base64.b64decode(encoded[name]))


def sync_note(result: dict) -> str:
    action = result.get("action")
    changed = result.get("changed") or []
    if action == "keep":
        text = "开发板上的采集程序已是当前版本。"
    elif action == "start":
        text = "已在开发板装上当前采集程序并启动。"
    else:
        text = "已把当前采集程序更新到开发板并重新启动。"
    if changed and action != "keep":
        text += f"更新了 {len(changed)} 个文件。" if len(changed) > 4 else "更新了 " + "、".join(changed) + "。"
    extra = result.get("compile_note") or ""
    if extra:
        text += extra
    return text


REMOTE_BODY = r"""
import base64, hashlib, json, os, re, signal, socket, subprocess, sys, time, urllib.request
from pathlib import Path

root = Path(PAYLOAD["root"])
package = root / "capture_studio"
hashes = PAYLOAD["hashes"]
encoded = PAYLOAD["files"]
package.mkdir(parents=True, exist_ok=True)
(root / "captures").mkdir(parents=True, exist_ok=True)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""

changed = [name for name, expect in hashes.items() if digest(package / name) != expect]
stamp_path = package / ".package_stamp.json"
stamp_ok = False
if stamp_path.is_file():
    try:
        stamp_ok = (json.loads(stamp_path.read_text(encoding="utf-8")).get("files") or {}) == hashes
    except (OSError, ValueError):
        stamp_ok = False

def listening():
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", 8765)) == 0

def agent_pids():
    found = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if b"capture_studio.board_agent" in command or b"capture_studio/board_agent.py" in command:
            found.append(int(entry.name))
    return found

token_path = root / "agent.token"
token = token_path.read_text(encoding="ascii").strip() if token_path.is_file() else ""
is_listening = listening()
recording = False
if is_listening and token:
    request = urllib.request.Request(
        "http://127.0.0.1:8765/status",
        headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            recording = bool(json.loads(response.read().decode()).get("recording"))
    except Exception as error:
        raise SystemExit("板上的采集服务没有正常响应，没有替换它。请先确认没有正在进行的录制，再重新连接。 " + str(error))
elif is_listening and not token:
    foreign = ""
    for pid in agent_pids():
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        found = re.search(r"--token-file(?:=|\s+)(\S+)", command)
        if found and Path(found.group(1)).is_file():
            foreign = Path(found.group(1)).read_text(encoding="ascii").strip()
            break
    if not foreign:
        raise SystemExit("板上的采集服务正在运行，但找不到令牌文件。请先停止该服务后再连接。")
    request = urllib.request.Request(
        "http://127.0.0.1:8765/status",
        headers={"Authorization": "Bearer " + foreign})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            recording = bool(json.loads(response.read().decode()).get("recording"))
    except Exception as error:
        raise SystemExit("板上的采集服务没有正常响应，没有替换它。请先确认没有正在进行的录制，再重新连接。 " + str(error))
    if recording:
        raise SystemExit("板上正在录制，这次没有替换正在运行的程序。停止录制后再连接，就会自动换上当前版本。")

needs_update = bool(changed) or not stamp_ok
if recording and needs_update:
    raise SystemExit("板上正在录制，这次没有替换正在运行的程序。停止录制后再连接，就会自动换上当前版本。")
if not is_listening:
    action = "start"
elif needs_update:
    action = "restart"
else:
    action = "keep"

compile_note = ""
if action != "keep":
    for name in changed:
        (package / name).write_bytes(base64.b64decode(encoded[name]))
binary = package / "native_capture"
if "native_capture.c" in changed or not binary.is_file():
    try:
        subprocess.run(
            ["gcc", "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror",
             str(package / "native_capture.c"), "-o", str(binary)],
            check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        compile_note = "原生采集程序没有编译成功，通用采集仍可使用。" + detail[-300:]
if action != "keep":
    if agent_pids():
        for pid in agent_pids():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for _ in range(50):
            if not agent_pids() and not listening():
                break
            time.sleep(0.1)
        for pid in agent_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        time.sleep(0.2)
    if not token_path.is_file():
        import secrets
        token_path.write_text(secrets.token_urlsafe(32) + "\n", encoding="ascii")
        token_path.chmod(0o600)
        token = token_path.read_text(encoding="ascii").strip()
    if len(token) < 32:
        raise SystemExit("板上的令牌文件太短，没有自动覆盖。")
    with (root / "agent.log").open("ab") as log:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "capture_studio.board_agent",
             "--bind", "127.0.0.1", "--port", "8765",
             "--output-root", str(root / "captures"),
             "--token-file", str(token_path)],
            cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
    (root / "agent.pid").write_text(str(proc.pid))
    ready = False
    for _ in range(50):
        if listening():
            ready = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if not ready:
        raise SystemExit("采集程序已拷到开发板，但服务没有启动。请查看板上的 agent.log。")
    stamp_path.write_text(json.dumps({"files": hashes}, sort_keys=True), encoding="utf-8")

sys.path.insert(0, str(root))
from capture_studio.board_devices import usb_image_devices
print(json.dumps({
    "token": token,
    "cameras": usb_image_devices(),
    "action": action,
    "changed": changed,
    "compile_note": compile_note,
}))
"""


def authentication_failed(message: str) -> bool:
    text = message.lower()
    return "permission denied" in text or "publickey" in text or "authentication failed" in text


def public_key_text(key: Path) -> str:
    public = Path(str(key) + ".pub")
    if public.is_file():
        return public.read_text(encoding="utf-8").strip()
    result = subprocess.run(["ssh-keygen", "-y", "-f", str(key)], capture_output=True,
                            text=True, errors="replace", timeout=15)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("无法从私钥得到公钥。")
    return result.stdout.strip()


def authorized_key_command(pubkey: str) -> str:
    quoted = shlex.quote(pubkey)
    return (
        "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; "
        "chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; "
        f"grep -qxF {quoted} ~/.ssh/authorized_keys || "
        f"printf '%s\\n' {quoted} >> ~/.ssh/authorized_keys"
    )


def install_authorized_key(ssh: str, key: Path, user: str, host: str, password: str) -> None:
    """Put this computer's public key on a new board. The password is not saved."""
    if not password:
        raise RuntimeError("没有开发板登录密码，无法为新板安装公钥。")
    pubkey = public_key_text(key)
    remote = authorized_key_command(pubkey)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "askpass.cs"
        program = Path(directory) / "askpass.exe"
        source.write_text(
            "class Ask { static void Main() { "
            "var value = System.Environment.GetEnvironmentVariable(\"CAPTURE_STUDIO_SSH_PASSWORD\"); "
            "System.Console.Write(value ?? \"\"); } }\n",
            encoding="ascii")
        compiler = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
        if os.name != "nt" or not compiler.is_file():
            raise RuntimeError("这台电脑缺少用于首次登录的组件，无法把公钥装到新开发板。")
        compiled = subprocess.run([str(compiler), "/nologo", "/t:exe",
                                   f"/out:{program}", str(source)],
                                  capture_output=True, text=True, errors="replace", timeout=30, creationflags=flags)
        if compiled.returncode != 0 or not program.is_file():
            raise RuntimeError("无法准备首次登录。")
        environment = os.environ.copy()
        environment["CAPTURE_STUDIO_SSH_PASSWORD"] = password
        environment["SSH_ASKPASS"] = str(program)
        environment["SSH_ASKPASS_REQUIRE"] = "force"
        environment["DISPLAY"] = "1"
        result = subprocess.run(
            [ssh, "-o", "BatchMode=no", "-o", "PreferredAuthentications=password",
             "-o", "NumberOfPasswordPrompts=1", "-o", "StrictHostKeyChecking=accept-new",
             "-o", "ConnectTimeout=15", f"{user}@{host}", remote],
            capture_output=True, text=True, errors="replace", timeout=30, creationflags=flags, env=environment)
    if result.returncode:
        detail = (result.stderr or result.stdout or "登录失败").strip()
        raise RuntimeError("没能把公钥装到新开发板。" + detail[-400:])


def build_remote_script(board_root: str, source: Path | None = None) -> str:
    if not board_root.startswith("/") or "\n" in board_root or "\x00" in board_root:
        raise RuntimeError("板端目录需是 Linux 绝对路径")
    source = source or package_directory()
    hashes = file_hashes(source)
    encoded = {
        name: base64.b64encode((source / name).read_bytes()).decode("ascii")
        for name in BOARD_FILES
    }
    payload = {"root": board_root, "hashes": hashes, "files": encoded}
    # The board reads this source as UTF-8. Windows would otherwise encode Chinese as GBK.
    return "# -*- coding: utf-8 -*-\nPAYLOAD = " + json.dumps(payload) + "\n" + REMOTE_BODY


def sync_board_package(ssh_args: list[str], board_root: str, source: Path | None = None) -> dict:
    script = build_remote_script(board_root, source).encode("utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    remote = subprocess.run(ssh_args + ["python3", "-"], input=script, capture_output=True,
                            timeout=90, creationflags=flags)
    stdout = safe_decode(remote.stdout)
    stderr = safe_decode(remote.stderr)
    if remote.returncode:
        detail = (stderr or stdout or "开发板没有返回结果").strip()
        raise RuntimeError(detail[-800:])
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("开发板没有返回采集程序状态。")
    try:
        result = json.loads(lines[-1])
    except ValueError as error:
        raise RuntimeError("开发板返回的内容无法识别。") from error
    if not result.get("token"):
        raise RuntimeError("开发板没有提供连接令牌。")
    result["sync_note"] = sync_note(result)
    return result
