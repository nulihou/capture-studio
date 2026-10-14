"""Named capture templates (v7): mode + exposure + duration + output + scene, stored as JSON."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

FIELDS = ("width", "height", "fps", "format", "codec", "bitrate", "preset", "exposure_mode", "exposure_absolute",
          "power", "wb", "focus", "duration", "output", "lens", "lighting", "distance")


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip()[:40]


def safe_scene(scene: str) -> str:
    """Folder-safe scene text; keeps Chinese, drops path and reserved characters."""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(scene)).strip(" ._")
    return re.sub(r"\s+", "_", text)[:40]


_DATED = re.compile(r"^\d{8}(?:_.*)?$")


def base_output(value: str) -> str:
    """Strip auto-named <YYYYMMDD>[_scene] folders so a template never nests or sticks to an old date (v9)."""
    path = Path(str(value or "captures"))
    while path.name and _DATED.match(path.name) and str(path.parent) not in ("", "."):
        path = path.parent
    if path.name and _DATED.match(path.name):
        return "captures"
    return str(path)


def capture(settings: dict[str, Any], scene: str = "") -> dict[str, Any]:
    tpl = {key: str(settings.get(key, "")) for key in FIELDS if key in settings}
    if "output" in tpl:
        tpl["output"] = base_output(tpl["output"])
    tpl["scene"] = scene
    return tpl


def load_all(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def save(path: Path, name: str, tpl: dict[str, Any]) -> dict[str, dict[str, Any]]:
    name = _clean(name)
    if not name:
        raise ValueError("模板名称不能为空")
    data = load_all(path)
    data[name] = dict(tpl)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def delete(path: Path, name: str) -> dict[str, dict[str, Any]]:
    data = load_all(path)
    data.pop(name, None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def output_for(base: str, scene: str, now: datetime | None = None) -> str:
    """Auto naming: <base>/<YYYYMMDD>_<scene> (session folders inside keep their own ids)."""
    now = now or datetime.now()
    folder = now.strftime("%Y%m%d") + (f"_{safe_scene(scene)}" if safe_scene(scene) else "")
    return str(Path(base or "captures") / folder)


def apply(settings: dict[str, Any], tpl: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Payload to send to Studio.update_settings / start_record; never mutates the input."""
    payload = {key: tpl[key] for key in FIELDS if key in tpl and key != "output"}
    base = base_output(str(tpl.get("output") or settings.get("output") or "captures"))
    payload["output"] = output_for(base, str(tpl.get("scene") or ""), now)
    return payload
