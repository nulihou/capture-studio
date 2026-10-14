# KV260 端安装

新版板端包含连续预览及源FPS统计；额外需要Python GI/GStreamer绑定（`python3-gi`、`gir1.2-gstreamer-1.0`）与jpegdec/videorate/pngenc/appsink等插件。当前实板环境已验证可用。Windows新版便携包使用可编辑SSH连接窗口，避免换电脑继续依赖原开发机Python或密钥路径。

当前`/devices`按sysfs列USB主图像节点及身份信息，排除本相机的元数据节点。拔插会改变`/dev/videoN`编号；Windows连接入口默认按序号`HHW001`选择图像节点，显式`--device`或`--camera-serial`可覆盖。2026-10-09的源低帧率失败记录保留在`SOURCE_FPS_DIAGNOSIS_20261009.md`；2026-10-11已加入下面的原生采集流程，验收结果见`NATIVE_PLATFORM_30FPS_20261011.md`。避免本相机的完整`--list-ctrls-menus`扫描，曝光信息仅查询必要控制。

本目录从 `kv260_agent.zip` 解压后使用。需要 Python 3.10+、GStreamer 1.x、`v4l2src`、`splitmuxsink` 和 `matroskamux`；单帧预览还需要 `jpegdec`、`videoconvert`、`videoscale` 和 `pngenc`。选择 `raw` 时还需要 `omxh264enc` 和 `h264parse`。实际可用插件以板端 `gst-inspect-1.0` 为准。

HHW001（VID/PID `1c45:6200`）选择 MJPEG 640×480、30fps 时，录制与预览自动使用原生 V4L2 路径。首次安装在解压目录编译采集程序，需要 GCC、Python `gi` 和 GStreamer `appsrc`：

```bash
gcc -O2 -std=c11 -Wall -Wextra -Werror capture_studio/native_capture.c -o capture_studio/native_capture
```

录制路径依次执行 S_FMT、S_PARM、4 个 mmap 缓冲、STREAMON，随后在同一摄像头文件描述符上设置手动模式1→曝光100→快门优先模式2，读回并预热2秒后交付 JPEG。实时预览使用自动曝光模式0以恢复当前场景可见画面，帧率显示实测值，当前约10.6fps；见BLACK_PREVIEW_FIX_20261012.md。临时曝光设置在停止时恢复原值。曝光100是接口名义10ms，当前场景下固定模式近乎黑图，正式录制需重新确认图像质量；其他摄像头/分辨率继续使用原有采集路径。

MKV直接保存原生 JPEG，PTS来自V4L2时间戳（减首帧时间作为零点），不生成固定帧率PTS、不补帧。`native_capture.json`保留源端计数、时间戳与恢复结果，`session.json`包含其摘要。录制队列不丢帧，预览只限速显示。异常退出或控制恢复失败会使录制失败；掉电/强制kill不能保证恢复，请正常停止。

MJPEG录制直接封装V4L2完整帧，使用`io-mode=mmap do-timestamp=false`保留原始PTS；加入非丢弃队列（256帧或32MiB），`splitmuxsink`异步收尾，Matroska `timecodescale=1000ns`（1μs精度）。当前板端GStreamer 1.20.3已验证这些参数；换环境先确认属性可用。队列满仍阻塞。`jpegparse`会将本相机PTS按请求FPS重排，已移除；`do-timestamp=true`生成到达DTS也会干扰封装时钟，因此已纠正。时间戳仍属于驱动/管线，不能声称已验证传感器曝光时间。

```bash
python3 -m capture_studio.board_agent --token-file ./capture_token.txt --init-token
python3 -m capture_studio.board_agent --token-file ./capture_token.txt \
  --output-root /data/captures --bind 127.0.0.1 --port 8765
```

默认仅监听板端本机。推荐从 Windows 电脑建立 SSH 隧道：

```powershell
ssh -L 8765:127.0.0.1:8765 ubuntu@<KV260-IP>
```

保持 SSH 窗口打开，桌面程序中填 `http://127.0.0.1:8765` 和 `capture_token.txt` 内的令牌。如果在可信、隔离的实验局域网内直连，则将 `--bind` 改为板端局域网 IP，并在桌面程序填写 `http://<KV260-IP>:8765`。直连 HTTP 不加密，令牌会随请求传输；不要把服务暴露到公网。令牌文件不要提交到代码仓库或共享数据集。

先在板端确认摄像头和格式：

```bash
v4l2-ctl --list-devices
v4l2-ctl --device=/dev/video0 --list-formats-ext
gst-inspect-1.0 v4l2src
gst-inspect-1.0 splitmuxsink
gst-inspect-1.0 matroskamux
gst-inspect-1.0 omxh264enc
```

`/dev/video0` 只是示例，按实际设备填写。摄像头接到 KV260 的 USB 主机口，协商速度以 `lsusb -t` 为准；USB2 摄像头接到 USB3 主机口也仍是 USB2 速度。板端数据盘需有足够空间。板端采集完成后，桌面程序会按 SHA-256 校验下载；网络中断时录制继续在板端进行，可重新连接并在“取回与校验”中输入会话 ID 取回。

2026-10-09在本项目KV260完成当前`1c45:6200`、MJPEG 640×480配置的优化后1分钟和30分钟复测。30分钟6段、31,543帧全部严格解码及SHA-256下载核对通过，重复/倒退PTS均0，最长间隔173.975ms，启动2秒后最大60.156ms。原基线有7处重复PTS、最长1.293秒间隔；原始失败证据保留。本轮实际17.53fps，低于原基线21.73fps，不能宣称FPS提升；30fps质量关口仍失败，状态`needs_review`。原因、边界和复现步骤见源码目录`OPTIMIZATION_20261009.md`及`PLATFORM_REPRODUCE_20261009.md`。换摄像头、格式或曝光后重新做短录与长录。
