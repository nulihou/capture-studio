# Board agent install notes (developers)

> For **end users** of the Windows portable zip, see [`使用说明.md`](../使用说明.md) / [`PORTABLE_GUIDE.md`](../PORTABLE_GUIDE.md).  
> This page is for deploying the Linux-side agent (historically named `kv260_agent.zip`).

The board agent supports continuous preview and source FPS stats. Extra dependencies: Python GI/GStreamer bindings (`python3-gi`, `gir1.2-gstreamer-1.0`) and plugins such as jpegdec / videorate / pngenc / appsink. Current lab boards have these verified. The Windows portable app uses an editable SSH connect dialog so another PC does not depend on the original developer machine’s Python or key paths.

`/devices` lists USB primary image nodes and identity from sysfs, excluding metadata nodes for the same camera. Unplug/replug can change `/dev/videoN`. The Windows connect entry selects the image node by serial `HHW001` by default; `--device` or `--camera-serial` overrides. Prefer not to run a full `--list-ctrls-menus` scan on this camera; query only needed exposure controls.

Unpack from `kv260_agent.zip` into a working directory. Needs Python 3.10+, GStreamer 1.x, `v4l2src`, `splitmuxsink`, and `matroskamux`. Single-frame preview also needs `jpegdec`, `videoconvert`, `videoscale`, and `pngenc`. For `raw`, also `omxh264enc` and `h264parse`. Confirm plugins with `gst-inspect-1.0` on the board.

For HHW001 (VID/PID `1c45:6200`) with MJPEG 640×480 @ 30 fps, record and preview use the native V4L2 path. On first install, compile in the unpack directory (needs GCC, Python `gi`, GStreamer `appsrc`):

```bash
gcc -O2 -std=c11 -Wall -Wextra -Werror capture_studio/native_capture.c -o capture_studio/native_capture
```

Record path: S_FMT → S_PARM → 4 mmap buffers → STREAMON, then on the same FD set manual mode 1 → exposure 100 → shutter-priority mode 2, read back, warm up ~2 s, deliver JPEG. Live preview uses auto-exposure mode 0 for a visible scene; FPS shows measured values. Temporary exposure settings are restored on stop. Exposure 100 is nominally 10 ms at the API; fixed mode can look nearly black in some scenes—confirm image quality for formal capture. Other cameras/resolutions keep the previous capture path.

MKV stores native JPEG; PTS comes from V4L2 timestamps (first frame as zero). No fixed-FPS PTS synthesis or frame padding. `native_capture.json` keeps source counts/timestamps/restore results; `session.json` includes a summary. Record queues do not drop frames; preview is display-rate limited. Abnormal exit or failed control restore fails the recording; power loss / hard kill cannot guarantee restore—stop normally.

MJPEG recording muxes full V4L2 frames with `io-mode=mmap do-timestamp=false` to keep original PTS; non-dropping queue (256 frames or 32 MiB), async `splitmuxsink` finalize, Matroska `timecodescale=1000ns` (1 µs). Verified on board GStreamer 1.20.3; re-check attributes on other environments. Full queue still blocks. Do not reintroduce `jpegparse` PTS rewrite or `do-timestamp=true` arrival DTS for this path.

```bash
python3 -m capture_studio.board_agent --token-file ./capture_token.txt --init-token
python3 -m capture_studio.board_agent --token-file ./capture_token.txt \
  --output-root /data/captures --bind 127.0.0.1 --port 8765
```

Default bind is localhost on the board. Recommended approach from Windows: SSH tunnel:

```powershell
ssh -L 8765:127.0.0.1:8765 ubuntu@<BOARD-IP>
```

Keep the SSH session open; in the desktop app use `http://127.0.0.1:8765` and the token from `capture_token.txt`. On a trusted, isolated lab LAN only, bind to the board LAN IP and point the app at `http://<BOARD-IP>:8765`. Plain HTTP is not encrypted; do not expose the service to the public internet. Do not commit token files to the repo or shared datasets.

On the board, confirm camera and formats:

```bash
v4l2-ctl --list-devices
v4l2-ctl --device=/dev/video0 --list-formats-ext
gst-inspect-1.0 v4l2src
gst-inspect-1.0 splitmuxsink
gst-inspect-1.0 matroskamux
gst-inspect-1.0 omxh264enc
```

`/dev/video0` is an example—use the real device. Camera on the board USB host; negotiated speed via `lsusb -t` (USB2 camera stays USB2 even on a USB3 host port). Ensure enough free space on the board data disk. After capture, the desktop app downloads with SHA-256 verify; if the network drops, recording continues on the board—reconnect and enter the session ID under retrieve/verify.

Lab notes and historical FPS / hub-reset diaries live under `docs/` or dated `*_2026*.md` files in the tree; they are not portable end-user docs.
