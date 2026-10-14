[中文](README.md) | [**English**](README.en.md)

# Capture Studio

USB camera capture and board debug for **KV260, Jetson, Raspberry Pi, RK3588**, and other SSH-reachable Linux boards - plus local USB cameras on Windows.

Windows app (PySide6) for local USB cameras and SSH boards (KV260, Jetson, Raspberry Pi, RK3588, …). Chinese / English, light / dark. Screenshots at 125% scaling with no camera attached.

## Clone

```bash
git clone https://github.com/nulihou/capture-studio.git
cd capture-studio
pip install -r capture_studio/requirements.txt
python -m capture_studio
```

Or double-click `capture_studio\Start-CaptureStudio.cmd` (legacy names `Start-KV260-CaptureStudio.cmd` / `Start-BoardCaptureStudio.cmd` only forward here).

Run: `python -m capture_studio`

## Interface (v0.12.4)

Sidebar: Test, PC, Board, Peripherals, Sessions, Settings.

### Camera test (dark)

![Camera test](docs/screenshots/v12/en_dark_lab.png)

Shortcuts: Space record, L live preview, P one frame, F **Large view**, H health check.

### Board (dark)

![Board](docs/screenshots/v12/en_dark_board.png)

Discovery (also explained in the connection wizard):

- **/24** around each real adapter (up to 3; never sweeps a wider mask as a whole)
- System **neighbour table**, including **169.254** link-local (direct cable); **no** /16 link-local sweep
- Common **`.local`** names; optional `zeroconf` for `_ssh._tcp`
- **TCP 22** SSH banner only - no login
- Vendor tags; boards ranked first; guidance when the NIC has only 169.254 or no gateway (**text only**, no OS network changes); **Test this IP** for a single address

Auto-select: one board → select it; several → pick manually; a single non-board SSH host → select with a warning. Multi-device networks are never silently forced to an Xilinx address.

### Peripherals (dark)

![Peripherals](docs/screenshots/v12/en_dark_periph.png)

## Requirements

- Windows 10/11, Python 3.10+: `pip install -r capture_studio/requirements.txt`
- OpenSSH Client; reachable board (same subnet, direct-link static IP, or typed IP)
- FFmpeg / FFprobe for local capture and checks

## Use

```powershell
git clone https://github.com/nulihou/capture-studio.git
cd capture-studio
pip install -r capture_studio/requirements.txt
python -m capture_studio
```

The **Capture Studio SSH key** is stored as `~/.ssh/id_ed25519_kv260` for compatibility with boards that already trust that key. **Settings → Check for updates** uses GitHub Releases (proxy failure retries direct; never self-replaces files).

## Tests

Run from a repo-root clone layout (`test_ui.py` opens a Tk window and is skipped by default):

```powershell
cd capture_studio\tests
$env:PYTHONPATH = (Resolve-Path ..\..).Path
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -v -p "test_[!u]*.py"
python ..\ui_redesign\smoke_ui.py capture_studio
```

## Portable zip

`CaptureStudio_v<version>_windows_x64.zip` → run `CaptureStudio.exe`.
