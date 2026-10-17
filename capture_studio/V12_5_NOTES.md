# Capture Studio v0.12.5

## Attended recording completion
- Timed recordings stop, fetch and verify on their own; a fetch interrupted by a transient error is retried up to twice, then shows the reason with "Retry" / "Stop and fetch" to resume the same session (`automation.py`).
- While a session is finishing ("收尾待完成") a new recording cannot start; a start request whose result is unknown is checked, never re-sent.
- Dataset acceptance needs all four gates to pass; the gate tooltip lists each reason.

## PC page fixes
- Switching to the PC page stops the board live preview and clears the picture; switching between PC and board never shows the other source's last frame. Live is not restarted automatically.
- Overview cards follow the page: on the PC page they show "本机", the selected PC camera (or "未检测到摄像头"), the PC capture mode and recording/idle state.
- With no PC camera the preview shows "本机未检测到摄像头" and "预览一帧" / "开始采集" are disabled.
- Board and PC keep separate capture modes. The board keeps `width/height/fps/format`; the PC uses `pc_width/pc_height/pc_fps/pc_format`. Settings from older versions load unchanged and seed the PC mode once from the old shared mode. Templates saved/started on the PC page use the PC mode.

## Layout
- Settings page fits 1280x800 again: the SSH key note shares the update row on one line (a word-wrapped label made the whole page height-for-width, forcing a scrollbar). Full text is in the tooltip.
- `smoke_ui.py` points the offscreen Qt platform at the Windows font folder; without it the offscreen font database is empty and every text width is measured about 2x too wide.

## Version
- `__version__ = 0.12.5`; portable zip `CaptureStudio_v0.12.5_windows_x64.zip`.
