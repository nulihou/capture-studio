"""PyInstaller entry point; source users can run ``python -m capture_studio``."""

import json
import subprocess
import sys

from capture_studio.core import resolve_tool
from capture_studio.desktop import CaptureDesktop, app_root, main


def self_test() -> int:
    report = {"ui": False, "ffmpeg": False, "ffprobe": False}
    try:
        window = CaptureDesktop()
        window.withdraw()
        window.update()
        window.destroy()
        report["ui"] = True
        from capture_studio.portable_connect import main as portable_connect
        from capture_studio.connect_kv260 import main as connect_main
        report['portable_connection'] = callable(portable_connect) and callable(connect_main)
        for name in ("ffmpeg", "ffprobe"):
            tool = resolve_tool(name, "", app_root())
            result = subprocess.run([str(tool), "-version"], capture_output=True,
                                    timeout=15)
            report[name] = result.returncode == 0
        report["ok"] = all(report.values())
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
    (app_root() / "self_test.json").write_text(json.dumps(report, indent=2) + "\n",
                                                encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ['--connect-check']:
        from capture_studio.connect_kv260 import main as check_connection
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
        from capture_studio.portable_connect import main as connect
        connect()
        raise SystemExit(0)
    if sys.argv[1:] == ["--self-test"]:
        raise SystemExit(self_test())
    main()
