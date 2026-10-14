"""PyInstaller entry point; source users can run ``python -m <package folder>`` (v9: package-name agnostic)."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

if __package__:
    PKG = __package__
elif not getattr(sys, "frozen", False):  # run as a script: the folder this file sits in is the package
    PKG = Path(__file__).resolve().parent.name
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
else:  # frozen: whichever capture_studio* package PyInstaller bundled (build_portable adds it as hidden import)
    import pkgutil
    names = sorted(m.name for m in pkgutil.iter_modules() if m.name.startswith("capture_studio") and m.ispkg)
    PKG = next((n for n in names if n != "capture_studio"), names[0] if names else "capture_studio")


def _mod(name: str):
    return importlib.import_module(f"{PKG}.{name}")


def self_test() -> int:
    report = {"ui": False, "ffmpeg": False, "ffprobe": False}
    app_root = _mod("desktop").app_root
    try:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        window = _mod("window")
        report["ui"] = hasattr(window, "StudioWindow") and app is not None
        portable_connect = _mod("portable_connect").main
        connect_main = _mod("connect_kv260").main
        report['portable_connection'] = callable(portable_connect) and callable(connect_main)
        resolve_tool = _mod("core").resolve_tool
        for name in ("ffmpeg", "ffprobe"):
            tool = resolve_tool(name, "", app_root())
            result = subprocess.run([str(tool), "-version"], capture_output=True, timeout=15)
            report[name] = result.returncode == 0
        report["ok"] = all(report.values())
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
    (app_root() / "self_test.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    app_root = _mod("desktop").app_root
    if sys.argv[1:2] == ['--connect-check']:
        check_connection = _mod("connect_kv260").main
        sys.argv = [sys.argv[0], '--check-only'] + sys.argv[2:]
        report = {'ok': False}
        try:
            check_connection()
            report['ok'] = True
        except Exception as error:
            report['error'] = str(error)
        (app_root()/'connection_self_test.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        raise SystemExit(0 if report['ok'] else 1)
    if sys.argv[1:] == ['--connect']:
        _mod("portable_connect").main()
        raise SystemExit(0)
    if sys.argv[1:] == ["--self-test"]:
        raise SystemExit(self_test())
    _mod("window").main()  # v9: the Qt studio window, same as python -m <package>
