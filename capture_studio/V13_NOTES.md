# Capture Studio v0.13.0

## 模型展示

新增「模型展示」页。模型只在开发板上跑，这台电脑只接收预览画面和协议 JSON，并画出框和指标。不在电脑上加载 torch、onnxruntime、ultralytics、openvino。

- 来源选 **板端** 时，沿用已有实时预览，按 `frame_id` 对齐 `POST /infer` 的结果。未连接时帧率、时延、计数和事件显示为「—」。
- 没有板子时播放可再分发的地对空鸟群（Pexels 14118342，许可见 `assets/demo_clip/ATTRIBUTION.md`），框是离线演示标注，画面标明 **演示数据**。
- 这一页自己记住浅色或深色，默认浅色，全屏跟随这一页，不改其他页面的主题。
- 检测框带深色描边，小目标有最小显示尺寸；小目标画廊是正方形，不拉伸。

协议和板端最小脚本：`capture_studio/docs/inference_protocol.md`。

## 推理帧率

- **演示片段**：帧率读演示数据里的 `infer_fps`（`demo.jsonl` 或 `assets/demo_clip/demo_meta.json`），在这个数附近轻微波动。当前片段是 30。这个读数与实际播放、抽帧速度无关，也不是写死在界面代码里的常数。
- **板端**：按结果到达电脑的时间间隔统计真实推理帧率，时延用每帧的 `latency_ms`。演示用的 `infer_fps` 不会带到板端。
- **本机视频、摄像头、回放**：按各自结果的到达间隔计算。

## 版本与安装包

- `__version__ = 0.13.0`
- Windows 便携包：`CaptureStudio_v0.13.0_windows_x64.zip`
- 设置里的「检查更新」比较 GitHub Release 的版本号。当前程序是 0.13.0 时，发布页上的 v0.13.0 会显示为已是最新。

## 构建

Windows 上：

```bash
python capture_studio/build_portable.py --ffmpeg-bin C:\path\to\ffmpeg\bin
```

推送 tag `v*` 时，GitHub Actions（`windows-latest`）会跑同一条命令，并把 zip 挂到对应 Release。
