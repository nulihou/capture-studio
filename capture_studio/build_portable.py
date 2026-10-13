"""Build a copyable Windows folder with Python and optional FFmpeg tools.

Usage from the repository root:
    python capture_studio/build_portable.py --ffmpeg-bin C:/path/to/ffmpeg/bin

PyInstaller and pefile must be importable. The --ffmpeg-bin folder must contain
ffmpeg.exe and ffprobe.exe. Their non-system DLL import closure is copied too,
which supports dynamic FFmpeg builds such as the local Conda installation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parent
DIST = PACKAGE / "dist"


def copy_ffmpeg_closure(source: Path, target: Path) -> list[str]:
    import pefile

    source = source.resolve()
    target.mkdir(parents=True, exist_ok=True)
    pending = [source / "ffmpeg.exe", source / "ffprobe.exe"]
    if any(not path.is_file() for path in pending):
        raise FileNotFoundError("--ffmpeg-bin needs ffmpeg.exe and ffprobe.exe")
    copied: set[str] = set()
    while pending:
        path = pending.pop()
        lower = path.name.lower()
        if lower in copied:
            continue
        shutil.copy2(path, target / path.name)
        copied.add(lower)
        binary = pefile.PE(str(path), fast_load=True)
        binary.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        for entry in getattr(binary, "DIRECTORY_ENTRY_IMPORT", []):
            name = entry.dll.decode("ascii", errors="replace")
            dependency = source / name
            if dependency.is_file() and dependency.name.lower() not in copied:
                pending.append(dependency)
    return sorted(copied)


def main() -> None:
    global DIST
    if sys.platform != "win32":
        raise SystemExit("Build the desktop application on Windows")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg-bin", type=Path, required=True)
    parser.add_argument('--dist-dir', type=Path, default=DIST)
    args = parser.parse_args()
    DIST = args.dist_dir.resolve()

    local_build_deps = PACKAGE / ".build_deps"
    if local_build_deps.is_dir():
        sys.path.insert(0, str(local_build_deps))

    try:
        from PyInstaller.__main__ import run
    except ImportError as exc:
        raise SystemExit("Install PyInstaller and pefile before building") from exc

    from capture_studio.board_sync import BOARD_FILES
    pyinstaller_args = [
        str(PACKAGE / "launcher.py"),
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "CaptureStudio",
        "--paths", str(REPOSITORY),
        "--hidden-import", "capture_studio.portable_connect",
        "--hidden-import", "capture_studio.connect_kv260",
        "--hidden-import", "capture_studio.board_sync",
        "--hidden-import", "capture_studio.board_discover",
        "--hidden-import", "capture_studio.camera_lab",
        "--distpath", str(DIST),
        "--workpath", str(PACKAGE / "build_tmp_portable"),
        "--specpath", str(PACKAGE / "build_tmp_portable"),
    ]
    for name in BOARD_FILES:
        pyinstaller_args.extend(["--add-data", f"{PACKAGE / name}{os.pathsep}capture_studio"])
    run(pyinstaller_args)
    bundle = DIST / "CaptureStudio"
    copied = copy_ffmpeg_closure(args.ffmpeg_bin, bundle / "bin")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    smoke = subprocess.run([str(bundle / "CaptureStudio.exe"), "--self-test"],
                           cwd=REPOSITORY, env=environment, timeout=45)
    report_path = bundle / "self_test.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    report_path.unlink(missing_ok=True)
    if smoke.returncode != 0 or not report.get("ok"):
        raise SystemExit(f"portable bundle self-test failed: {report}")
    (bundle / "README.txt").write_text(
        "CaptureStudio.exe: portable Windows desktop capture app.\n"
        "Copy this entire folder to another Windows PC.\n"
        "ffmpeg.exe and ffprobe.exe are in bin; source DLLs are copied beside them.\n"
        "Connect a local USB camera or configure a KV260 board agent.\n"
        "Keep the whole folder together. Settings and default captures stay beside the EXE.\n"
        "See capture_studio/README.md in the source tree for full instructions.\n",
        encoding="utf-8",
    )
    shutil.copy2(PACKAGE / "README.md", bundle / "README.md")
    with ZipFile(DIST / "kv260_agent.zip", "w", compression=ZIP_DEFLATED) as archive:
        for name in BOARD_FILES:
            archive.write(PACKAGE / name, f"capture_studio/{name}")
        archive.write(PACKAGE / "BOARD_README.md", "BOARD_README.md")
    for personal in ("board_connection.json", "capture_settings.json", "self_test.json",
                     "connection_self_test.json"):
        (bundle / personal).unlink(missing_ok=True)
    captured = bundle / "captures"
    if captured.exists():
        shutil.rmtree(captured)
    (bundle/'连接开发板.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0CaptureStudio.exe" --connect\r\n',encoding='utf-8')
    shutil.copy2(PACKAGE/'PORTABLE_GUIDE.md',bundle/'换电脑使用说明.md')
    for name in ['HUB_RESET_TRIGGER_20261011.md', 'LIVE_PREVIEW_20261011.md', 'BOARD_README.md', 'PREVIEW_PERFORMANCE_20261011.md', 'NATIVE_PLATFORM_30FPS_20261011.md', 'PREVIEW_30FPS_20261012.md']:
        shutil.copy2(PACKAGE/name,bundle/name)
    with ZipFile(DIST / "CaptureStudio_windows_x64.zip", "w",
                 compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(DIST).as_posix())
    print(f"Built {bundle}; copied {len(copied)} FFmpeg executables/DLLs; self-test={report}")


if __name__ == "__main__":
    main()
