# Capture Studio (package)

This folder is the Python package `capture_studio`.

**User documentation:** see the repository root [`README.md`](../README.md).

```bash
git clone https://github.com/nulihou/capture-studio.git
cd capture-studio
pip install -r capture_studio/requirements.txt
python -m capture_studio
```

- Portable Windows build: `python capture_studio/build_portable.py --ffmpeg-bin <ffmpeg-bin-dir>`
  → `CaptureStudio_v<version>_windows_x64.zip`
- Portable user guide (Chinese): [使用说明.md](使用说明.md) / [PORTABLE_GUIDE.md](PORTABLE_GUIDE.md)
- Board agent install (developers): [docs/board_agent.md](docs/board_agent.md) — short pointer: [BOARD_README.md](BOARD_README.md)

The SSH private key file is still named `~/.ssh/id_ed25519_kv260` for compatibility with boards that already have this public key installed. The UI refers to it as the Capture Studio SSH key.
