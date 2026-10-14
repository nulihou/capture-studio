# Capture Studio v0.12.4

Docs and portable packaging cleanup (no feature change required for day-to-day capture).

## User-facing
- Rewrote portable Chinese guide: `使用说明.md` / `PORTABLE_GUIDE.md` (product name **Capture Studio**).
- Covers multi-board LAN discovery, check-for-updates, local USB + SSH boards, Capture Studio SSH key (disk file still `id_ed25519_kv260`), optional `连接开发板.cmd`.
- Developer KV260/tunnel/agent essay moved to `docs/board_agent.md`; root `BOARD_README.md` is a short pointer only.

## Packaging (`build_portable.py`)
- Ships `使用说明.md` (+ existing `README.txt`); does **not** copy `BOARD_README.md` into the portable folder root.
- Does **not** create outdated `换电脑使用说明.md` from the old guide name.
- `kv260_agent.zip` includes `docs/board_agent.md` instead of a root `BOARD_README.md` user-manual lookalike.

## Version
- `__version__ = 0.12.4`; portable zip name `CaptureStudio_v0.12.4_windows_x64.zip`.
- `ui_redesign/smoke_ui.py` version assertion updated. `tests/test_updates.py` still uses `0.12.3` as a historical comparison baseline (unchanged).
