"""Session review helpers (v7): stats from session.json, thumbnails and preview frames via ffmpeg."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
SESSION_RE = re.compile(r"^\d{8}T\d{6}Z_[0-9a-f]{8}$")


def find_sessions(root: Path, depth: int = 1, limit: int = 60) -> list[Path]:
    """Session folders in root and (for template sub-folders) one level below, newest first."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    levels = [root]
    for _ in range(depth):
        levels += [p for p in root.iterdir() if p.is_dir() and not SESSION_RE.match(p.name)]
    for folder in levels:
        try:
            for item in folder.iterdir():
                if item.is_dir() and SESSION_RE.match(item.name) and (item / "session.json").is_file():
                    found.append(item)
        except OSError:
            continue
    return sorted(found, key=lambda p: p.name, reverse=True)[:limit]


def summarize(session: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((session / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    options = manifest.get("options") or {}
    audit = manifest.get("audit") or {}
    files = [session / f["path"] for f in manifest.get("files") or [] if isinstance(f, dict) and f.get("path")]
    if not files:
        files = sorted((session / "segments").glob("*.mkv")) if (session / "segments").is_dir() else []
    size = sum(p.stat().st_size for p in files if p.is_file())
    fps = float(options.get("fps") or 0) or None
    frames = audit.get("frame_count")
    duration = manifest.get("duration_s") or (frames / fps if frames and fps else None)
    return {
        "session_id": manifest.get("session_id", session.name), "path": str(session),
        "status": manifest.get("status", ""), "created_utc": manifest.get("created_utc", ""),
        "mode": manifest.get("mode", ""), "width": options.get("width"), "height": options.get("height"),
        "fps": options.get("fps"), "format": options.get("source_format") or options.get("format", ""),
        "codec": options.get("codec", ""), "frames": frames,
        "dropped": audit.get("possible_gap_intervals"), "duration": duration, "size": size,
        "media": [str(p) for p in files if p.is_file()], "folder": session.parent.name,
    }


def probe_duration(ffprobe: Path, media: str, run: Callable[..., Any] = subprocess.run) -> float | None:
    result = run([str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", media],
                 capture_output=True, text=True, errors="replace", timeout=20, creationflags=_FLAGS)
    try:
        return float(str(result.stdout).strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def thumbnail_command(ffmpeg: Path, media: str, out: Path, at: float = 1.0, width: int = 160) -> list[str]:
    return [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", media,
            "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)]


def frames_command(ffmpeg: Path, media: str, out_dir: Path, fps: float = 5, width: int = 480, seconds: int = 20) -> list[str]:
    """Low-rate preview frames for inline playback (Qt Multimedia is not shipped)."""
    return [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-t", str(seconds), "-i", media,
            "-vf", f"fps={fps},scale={width}:-2", "-q:v", "5", str(out_dir / "f_%04d.jpg")]


def ensure_thumbnail(ffmpeg: Path, media: str, cache: Path, run: Callable[..., Any] = subprocess.run) -> Path | None:
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / (re.sub(r"[^0-9A-Za-z_]", "_", Path(media).parent.parent.name + "_" + Path(media).stem) + ".jpg")
    if out.is_file() and out.stat().st_size:
        return out
    try:
        run(thumbnail_command(ffmpeg, media, out), capture_output=True, timeout=30, creationflags=_FLAGS)
    except Exception:
        return None
    return out if out.is_file() and out.stat().st_size else None


def extract_frames(ffmpeg: Path, media: str, out_dir: Path, run: Callable[..., Any] = subprocess.run) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("f_*.jpg"))
    if existing:
        return existing
    try:
        run(frames_command(ffmpeg, media, out_dir), capture_output=True, timeout=120, creationflags=_FLAGS)
    except Exception:
        return []
    return sorted(out_dir.glob("f_*.jpg"))


def describe(summary: dict[str, Any]) -> str:
    parts = []
    if summary.get("width"):
        parts.append(f"{summary['width']}×{summary['height']} · {summary.get('fps')} fps")
    if summary.get("duration"):
        d = int(summary["duration"])
        parts.append(f"{d // 60}:{d % 60:02d}")
    if summary.get("frames") is not None:
        parts.append(f"{summary['frames']} 帧")
    if summary.get("dropped"):
        parts.append(f"疑似掉帧 {summary['dropped']}")
    if summary.get("size"):
        size = float(summary["size"])
        parts.append(f"{size / 2**20:.1f} MB" if size < 2**30 else f"{size / 2**30:.2f} GB")
    return " · ".join(parts)
