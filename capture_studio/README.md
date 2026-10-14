# Capture Studio：USB 摄像头双模式数据采集

产品规格见 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。入库资格、关口和下一版范围以该规格为准。本文件保留操作说明与历史验收记录。

2026-10-12黑屏复核：此前30fps固定曝光输出近乎黑图，帧率通过不等于画面质量通过。预览现改为自动曝光，画面可见，当前约10.6fps；正常亮度和30fps尚未同时通过。见[BLACK_PREVIEW_FIX_20261012.md](BLACK_PREVIEW_FIX_20261012.md)。

2026-10-12实时预览也已修复：持续流传输，板端输出约30fps，75秒桌面验收六个10秒窗口均29.9–30.0fps；程序与ZIP已重建。详见[PREVIEW_30FPS_20261012.md](PREVIEW_30FPS_20261012.md)。以下保留历史记录。

2026-10-11原生流程已接入平台：当前HHW001、MJPEG640×480/30的620秒长录严格解码、唯一帧及十个60秒窗口验收通过；24项测试通过。详见[NATIVE_PLATFORM_30FPS_20261011.md](NATIVE_PLATFORM_30FPS_20261011.md)。下面保留此前各轮失败与历史记录。

换电脑请使用最新版`release/CaptureStudio_windows_x64.zip`，完整解压后双击`连接开发板.cmd`，可编辑IP、用户、SSH密钥、板端目录和相机序号。自带Python/FFmpeg，含连续预览及实际FPS；包内不含密钥/令牌/数据。新路径、清洁PATH及实际开发板连接自检通过，未在第二台实体电脑验收。详见[PORTABLE_GUIDE.md](PORTABLE_GUIDE.md)。旧`dist/`包保留为历史版本。

实时预览右侧现显示实际取流FPS与预览输出FPS（最近3秒、每秒更新）。实际取流按v4l2src源buffer到达计数，位于预览限速前；实板约10.7fps/5.0fps，数值不会采用请求30fps。重新打开源码启动入口获得新显示，仅在KV260实时预览期间统计。

KV260连续画面：重新打开`Start-KV260-CaptureStudio.cmd`后，在“KV260采集”点击“实时预览”，同一画面区会连续更新（最多5帧/秒）；再次点击“停止预览”。开始采集自动释放预览摄像头。本次支持录制前调镜头，录制期间不提供同步画面；电脑端仍为单帧预览。实板20次画面读取、停止释放及预览切换短录通过，详见[LIVE_PREVIEW_20261011.md](LIVE_PREVIEW_20261011.md)。

2026-10-11移到亮处复测：相同手动曝光100条件三轮均106/10秒、10.6fps，与移动前最近两轮一致，未观察到帧率改善；本轮无新增内核异常。画面和照度比较限制见[BRIGHT_SCENE_RETEST_20261011.md](BRIGHT_SCENE_RETEST_20261011.md)。

2026-10-11复位触发链：捕获PipeWire打开视频节点经USB运行时恢复触发设备/hub复位；临时将根hub、父hub及相机电源策略设on后，三轮完成且短测无新增复位，仍13.2/10.6/10.6fps，未恢复30fps。证据、回滚及边界：[HUB_RESET_TRIGGER_20261011.md](HUB_RESET_TRIGGER_20261011.md)。

2026-10-11增益及枚举核查：同流gain0→32→0画面亮度出现可逆变化，三个稳定段均15.05fps；收尾再次出现hub复位、无效USB描述符和视频节点消失，实时健康未通过，连接稳定性仍有问题。详情：[GAIN_AND_ENUMERATION_20261011.md](GAIN_AND_ENUMERATION_20261011.md)。

2026-10-10源状态复测：90秒2352个buffer、26.13fps；驱动入口FID/PTS约26.1/s，与用户态26.2fps接近。分辨率及显式动态帧率控制未改善，另一开流曝光阶跃约21fps，跨开流变化未解释，仍未恢复30fps。原控制与跟踪清理已核查，详细复现和原始记录见[SOURCE_STATE_AND_CONTROLS_20261010.md](SOURCE_STATE_AND_CONTROLS_20261010.md)。以下保留各轮历史结果。

最新实际内核跟踪：17处序号缺口逐处对应EAGAIN帧边界处理，116对相邻buffer全部匹配，跟踪无漏记；前/中/后三轮仍11.70fps，未修复30fps。详见[UVC_RETURN_TRACE_20261010.md](UVC_RETURN_TRACE_20261010.md)。

最新确认：auto→on→on→auto为13.20/14.50/15.05/15.05fps，未确认自动挂起的稳定改善；已有USB包重建89个不同可解码JPEG，其中12组缺UVC EOF，序号缺口不能直接计作源丢帧。步骤和边界：[PM_AND_FRAME_BOUNDARY_CONFIRM_20261010.md](PM_AND_FRAME_BOUNDARY_CONFIRM_20261010.md)。

直接板端核查：CPU未持续饱和；相机启用自动挂起且此前有复位记录。auto→on→auto短测为17.70/20.95/17.50fps，仍有序号缺口、未恢复30fps，设置全部恢复；候选线索及混杂详见[BOARD_DIRECT_AUDIT_20261010.md](BOARD_DIRECT_AUDIT_20261010.md)。

板端曝光时序最新复测：开流后→开流前→开流后为17.55/15.05/15.05fps，设置读回和恢复均通过，未恢复30fps；详细步骤及原始证据：[CONTROL_TIMING_RETEST_20261010.md](CONTROL_TIMING_RETEST_20261010.md)。

移除MIPI最新复测：USB相机仍13.2–15.05fps，标准快门优先有效条件也13.2fps，未恢复30fps；当前连接和原控制恢复通过：[MIPI_REMOVAL_RETEST_20261010.md](MIPI_REMOVAL_RETEST_20261010.md)。

2026-10-10 USB二进制核查：内存抓包4174事件、0捕获丢失/0截断，观察到的FID/PTS节奏约10.5/s，与该轮原生10.6/s接近；仍未定位固件/主机根因或恢复30fps。当前连接和原控制恢复通过：[USB_SOURCE_CADENCE_20261010.md](USB_SOURCE_CADENCE_20261010.md)。

固定场景电脑基线：四轮20秒均600完整图像、30fps，4477帧全解码/边界通过，原设置恢复；板端录制亦已取回校验，但样图场景不同，公平跨主机对照仍未完成：[FIXED_SCENE_HOST_COMPARISON_20261009.md](FIXED_SCENE_HOST_COMPARISON_20261009.md)。

电脑最新曝光对照：7.8/15.6/31.25ms及短档重复，四轮固定20秒均600完整帧/30fps；原设置恢复通过。样图仍偏暗且与板端场景不同，公平主机对照尚未完成：[EXPOSURE_RESPONSE_DIAGNOSIS_20261009.md](EXPOSURE_RESPONSE_DIAGNOSIS_20261009.md)。

Linux/UVC映射核查：实际手动100及640×480 MJPEG/30fps协商的USB请求核实，仍11.75–13.2fps；YUYV短测序号无缺口但未恢复30fps。无人工拔动时发生断连，原端口断电后恢复，20秒复测仍13.2fps；连接长期稳定性未解决。详见[UVC_MAPPING_AUDIT_20261009.md](UVC_MAPPING_AUDIT_20261009.md)。

最新回接开发板：7段885帧全部解码、大小/哈希/PTS顺序通过；有效手动10ms仍13.2fps，Linux7.8ms请求读回10ms。电脑30fps尚未在板端复现：[RETURN_BOARD_RETEST_20261009.md](RETURN_BOARD_RETEST_20261009.md)。

电脑直连新证据：开流后手动短曝光，60秒1800完整帧、实测30fps；自动曝光约10.6fps。画面偏暗，开发板迁移与长录尚未验收。详细流程：[PC_DIRECT_RETEST_20261009.md](PC_DIRECT_RETEST_20261009.md)。

最新换口复测与重复执行步骤：[PORT_CHANGE_RETEST_20261009.md](PORT_CHANGE_RETEST_20261009.md)。新口录制完整性通过，实际仍约15fps，未恢复30fps。

连接入口现按相机序号自动选择USB主图像节点，避免拔插后编号变化及误选元数据节点。源端低帧率诊断、已验证修复和当前限制见 [SOURCE_FPS_DIAGNOSIS_20261009.md](SOURCE_FPS_DIAGNOSIS_20261009.md)。

本工具提供一个 Windows 桌面界面，支持两种连接方式：

| 模式 | 摄像头连接位置 | 录制位置 | 桌面程序的工作 |
| --- | --- | --- | --- |
| 电脑直连 USB | Windows 电脑 | 电脑 | 列设备、单帧预览、录制、停止、校验 |
| KV260 直连 USB | KV260 | KV260，随后取回电脑 | 连接板端、单帧预览、远程开始/停止、校验下载 |

两种模式产生相同结构的会话目录：

```text
captures/<session_id>/
  session.json       模式、请求参数、状态、分段文件 SHA-256、校验摘要
  capture.log        FFmpeg 或 GStreamer 输出
  segments/part_00000.mkv ...
  frames.jsonl       录制文件逐帧清单；校验后生成
```

`frames.jsonl` 的 `recorded_frame_id` 只给录制文件中的帧编号，`container_pts_s` 是封装/解码得到的 PTS。它们不是相机曝光时间或相机源帧序号。`possible_gap_intervals` 是 PTS 间隔启发式检查，不能直接当作真实丢帧数。视频元数据不一致、无 PTS、PTS 倒退或异常间隔会标为 `needs_review`。

界面顶部填写数据目录、采集人和场景备注；“电脑采集”与“KV260 采集”各自显示设备、单帧预览、录制按钮和会话状态。“会话与校验”负责板端取回与本地校验；不常改动的 FFmpeg 路径放在“工具设置”。

## 在 Windows 电脑使用

如果已有 `dist/CaptureStudio/`，把**整个文件夹**复制到测试电脑，运行 `CaptureStudio.exe`。也可复制 `dist/CaptureStudio_windows_x64.zip` 并完整解压。应用会优先使用文件夹内 `bin/ffmpeg.exe`、`bin/ffprobe.exe`。界面中的工具路径也可手动设置，程序不依赖开发电脑的路径。换电脑后重新选择摄像头名称和保存目录；默认 `captures` 位于 EXE 同目录。需要 Windows x64、能正常工作的相机驱动和可写数据盘。当前构建只在本机 Windows 11 上做过启动和合成视频测试，跨机器兼容性仍需实测。

从源码启动：

```powershell
python -m capture_studio
```

源码模式需要 Python 3.10+、Tkinter、FFmpeg、FFprobe。将 `ffmpeg.exe` 和 `ffprobe.exe` 连同其依赖 DLL 放在 `capture_studio/bin/`，或在界面指定路径，或放入系统 `PATH`。单独复制 Conda 的两个 EXE 通常不够，它们可能依赖旁边的 DLL。

电脑模式启动后自动检测摄像头；若只找到一台会自动选中，多台时请从列表选择。设备栏会显示检测数量，画面区会显示当前设备或未检测到的原因。新插入摄像头后点击“刷新设备”。然后填写分辨率和帧率，再“预览一帧”确认视场。默认 `ffv1` 保存解码帧，无再次有损压缩，但文件可能很大；它不能恢复摄像头内部已经发生的压缩。`copy` 仅适用于相机输出可直接封装的压缩视频流。录制完成请点“停止并校验”，不要直接关闭程序。

## 在 KV260 上使用

将 `dist/kv260_agent.zip` 解压到 KV260，按 [BOARD_README.md](BOARD_README.md) 启动服务。桌面程序输入地址、令牌、`/dev/videoN`、分辨率、帧率和格式。`mjpeg` 模式直接封装 V4L2 的完整 JPEG 帧，不再次编码；`raw` 模式在板端编码成 H.264，因此是有损数据。令牌只保留在本次界面内，不写入设置文件。板端运行的 GStreamer 插件和具体 USB 摄像头格式需要在实板确认。

当前开发电脑可双击 `Start-KV260-CaptureStudio.cmd`，自动建立 SSH 连接、读取令牌到内存并打开已连接的源码版桌面平台。板端包需已安装；此入口的 IP、密钥及 Python 路径按本机配置，换电脑需调整。详细连接、录制、停止、取回与严格逐帧复测见 [PLATFORM_REPRODUCE_20261009.md](PLATFORM_REPRODUCE_20261009.md)。

2026-10-09基线长录有7处重复PTS和最长1.293秒间隔。已通过受控阻塞复现机制，部署原始PTS、非丢弃队列、微秒封装及异步分段修复；新的30分钟复测31,543帧全部解码、6段哈希匹配，重复/倒退PTS均0，最长173.975ms（启动后60.156ms）。但实际只有17.53fps，低于基线21.73fps，30fps质量关口仍失败，保留`needs_review`。不能声称FPS提升或零传感器丢帧。原因与完整结果见 [OPTIMIZATION_20261009.md](OPTIMIZATION_20261009.md)。

板端录制在 KV260 本地进行，电脑失去连接不会直接中断它。填写地址和令牌后点击“连接并查设备”，界面会同时显示连接状态和板端摄像头；新插入摄像头可点击“刷新设备”。恢复连接后也可按此步骤查询活动会话和正在录制的设备，再停止或重新取回；此状态需要配套本版本的板端代理。下载核对大小和 SHA-256，失败可重试；桌面端随后用 FFprobe 建立逐帧清单。

## 建议的采集口径

1. 每次会话记录摄像头型号、镜头/焦距、光照、场景、距离、曝光/增益、分辨率、帧率、操作者和异常；当前界面提供操作者与场景备注，自由文本需要人工填写完整。
2. 比较电脑直连和 KV260 直连时，固定同一摄像头、分辨率、帧率、曝光、增益和视场；两个域分开统计。不要把 KV260 验证集直接混入训练集后仍称其为独立部署验证。
3. 按会话或场景切分训练/验证/测试，避免同一连续片段的邻近帧跨集合。对微小目标额外记录原始图像中的目标像素尺寸、遮挡、离开/重入视场等情况。
4. 正式采集前每种模式分别做短录和长录，核对 `session.json` 的状态、`capture.log`、逐帧清单和实际磁盘写入速度。实板验收按摄像头、格式与分辨率分别判断；某一配置通过不能替代其他配置的测试。

## 构建便携 Windows 文件夹

在 Windows 构建机安装 PyInstaller 和 pefile 后，从仓库根目录运行：

```powershell
python capture_studio/build_portable.py --ffmpeg-bin C:/path/to/ffmpeg/bin
```

输出为 `capture_studio/dist/CaptureStudio/`、`capture_studio/dist/CaptureStudio_windows_x64.zip` 和 `capture_studio/dist/kv260_agent.zip`。构建器会复制 FFmpeg/FFprobe 及其在指定目录可找到的非系统 DLL。若改用其他 FFmpeg 发行版，先在一台干净测试电脑验证运行，并核对该发行版的再分发许可。不要把包含私密令牌或已采集数据的设置/数据目录复制到其他测试电脑。

## 当前边界

本版本做采集、取回、校验和元数据归档。KV260 推理结果尚未与视频帧建立经过验证的一一对应关系，因此界面没有把模型输出写成真值标签，也没有声称板端实时推理或真实传感器丢帧统计。电脑预览为单帧快照；KV260支持录制前连续预览，不提供录制中的实时画面。若后续需要叠加推理结果，先为模型结果与录制帧建立可验证的共同帧 ID 或时钟映射，再导入独立 sidecar 文件。

参考：[FFmpeg DirectShow 输入](https://ffmpeg.org/ffmpeg-devices.html#dshow)、[GStreamer splitmuxsink](https://gstreamer.freedesktop.org/documentation/multifile/splitmuxsink.html)、[AMD KV260 SmartCam 文档](https://xilinx.github.io/kria-apps-docs/kv260/2022.1/build/html/docs/smartcamera/docs/introduction.html)。
