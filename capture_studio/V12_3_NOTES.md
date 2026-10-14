# Capture Studio v0.12.3

Fixes from `USAGE_REVIEW_v12_2_zh.md` (B1/B2 + A-series docs/UI).

## Changes
- Root README: multi-board discovery (/24, neighbour/169.254, SSH:22), direct-connect guidance, update check, clone `capture-studio`; no KV260-only / Xilinx-only auto-IP claims.
- Package `capture_studio/README.md`: short pointer to root (dead acceptance-diary links removed).
- `requirements.txt`: PySide6, pyserial; keyring / zeroconf noted optional.
- `Start-CaptureStudio.cmd` primary; `Start-KV260-*.cmd` / `Start-Board*.cmd` thin legacy wrappers.
- UI/copy: `__version__ = 0.12.3`; English 大屏 → Large view; Tk tabs 「开发板采集」; `__init__` docstring Capture Studio; portable zip `CaptureStudio_v0.12.3_windows_x64.zip`.
- i18n: Capture Studio SSH key wording (file path unchanged).

## Compatibility (intentionally unchanged)
- SSH private key filename on disk: `~/.ssh/id_ed25519_kv260` (boards that already have the pubkey).
- Windows Credential Manager service: `CaptureStudio-board`.

## Layouts
- GitHub: `capture-studio/capture_studio/` → `python -m capture_studio`.
- Local flat trees (`capture_studio_ui_v12_3/`): run via junction pkgroot or `python -m` that folder name; do not delete older `v12*` trees.
