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
sys.path.insert(0, str(REPOSITORY))
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
    parser.add_argument('--work-dir', type=Path, default=PACKAGE / 'build_tmp_portable')
    args = parser.parse_args()
    DIST = args.dist_dir.resolve()
    work = args.work_dir.resolve()
    if (DIST / 'CaptureStudio').exists() or work.exists():
        raise SystemExit('Use fresh dist/work directories; existing files will not be overwritten or cleaned')

    local_build_deps = PACKAGE / ".build_deps"
    if local_build_deps.is_dir():
        sys.path.insert(0, str(local_build_deps))

    try:
        from PyInstaller.__main__ import run
    except ImportError as exc:
        raise SystemExit("Install PyInstaller and pefile before building") from exc

    import importlib
    BOARD_FILES = importlib.import_module(f"{PACKAGE.name}.board_sync").BOARD_FILES
    pyinstaller_args = [
        str(PACKAGE / "launcher.py"),
        "--onedir", "--windowed",
        "--name", "CaptureStudio",
        "--paths", str(REPOSITORY),
        "--hidden-import", f"{PACKAGE.name}.portable_connect",
        "--hidden-import", f"{PACKAGE.name}.connect_kv260",
        "--hidden-import", f"{PACKAGE.name}.board_sync",
        "--hidden-import", f"{PACKAGE.name}.board_discover",
        "--hidden-import", f"{PACKAGE.name}.camera_lab",
        "--hidden-import", PACKAGE.name,
        "--hidden-import", f"{PACKAGE.name}.window",
        "--hidden-import", f"{PACKAGE.name}.v7_ui",
        "--hidden-import", f"{PACKAGE.name}.icons",
        "--hidden-import", f"{PACKAGE.name}.motion",
        "--hidden-import", f"{PACKAGE.name}.discovery",
        "--hidden-import", f"{PACKAGE.name}.updates",
        "--hidden-import", "PySide6.QtSvg",
        "--add-data", f"{PACKAGE / 'assets' / 'icons'}{os.pathsep}{PACKAGE.name}/assets/icons",
        "--icon", str(PACKAGE / "assets" / "app.ico"),
        "--distpath", str(DIST),
        "--workpath", str(work),
        "--specpath", str(work),
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
    if smoke.returncode != 0 or not report.get("ok"):
        raise SystemExit(f"portable bundle self-test failed: {report}")
    (bundle / "README.txt").write_text(
        "CaptureStudio.exe — Capture Studio (portable).\n"
        "Copy this entire folder to another Windows PC.\n"
        "ffmpeg.exe and ffprobe.exe are in bin; source DLLs are copied beside them.\n"
        "Connect a local USB camera or any SSH board (KV260, Jetson, Raspberry Pi, Rockchip, …).\n"
        "Keep the whole folder together. Settings and default captures stay beside the EXE.\n"
        "Chinese user guide: 使用说明.md\n"
        "Source: https://github.com/nulihou/capture-studio\n"
        "See the repository root README.md for full instructions.\n",
        encoding="utf-8",
    )
    # User-facing portable docs only. Do NOT re-introduce:
    # - BOARD_README.md at bundle root (developer essay; confuses end users)
    # - 换电脑使用说明.md copied from an outdated PORTABLE_GUIDE without rewrite
    # Chinese guide is 使用说明.md (kept in sync with PORTABLE_GUIDE.md in the package tree).
    user_guide = PACKAGE / "使用说明.md"
    if not user_guide.is_file():
        user_guide = PACKAGE / "PORTABLE_GUIDE.md"
    shutil.copy2(user_guide, bundle / "使用说明.md")
    # Optional short package pointer; full docs live at repo root README.
    shutil.copy2(PACKAGE / "README.md", bundle / "README.md")
    with ZipFile(DIST / "kv260_agent.zip", "w", compression=ZIP_DEFLATED) as archive:
        for name in BOARD_FILES:
            archive.write(PACKAGE / name, f"capture_studio/{name}")
        # Developer board notes under docs/, not a root BOARD_README that looks like a user manual.
        for name in ("board_agent.md", "inference_protocol.md"):
            doc = PACKAGE / "docs" / name
            if doc.is_file():
                archive.write(doc, f"docs/{name}")
    # Fresh builds contain no user data. Stop rather than deleting unexpected settings or captures.
    for personal in ('board_connection.json', 'studio_settings.json', 'ui_prefs.json', 'captures'):
        if (bundle / personal).exists():
            raise SystemExit(f'Unexpected user data in fresh bundle; preserved for inspection: {personal}')
    # Optional connect-mode launcher (users can also open CaptureStudio.exe directly).
    (bundle / "连接开发板.cmd").write_text(
        '@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0CaptureStudio.exe" --connect\r\n',
        encoding="utf-8",
    )
    version = importlib.import_module(PACKAGE.name).__version__
    with ZipFile(DIST / f"CaptureStudio_v{version}_windows_x64.zip", "w",
                 compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(DIST).as_posix())
    print(f"Built {bundle}; copied {len(copied)} FFmpeg executables/DLLs; self-test={report}")


if __name__ == "__main__":
    main()
