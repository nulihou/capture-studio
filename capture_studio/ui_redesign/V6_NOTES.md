# capture_studio_ui_v6 说明

## 采集模式自动检测
- 开发板：`v4l2-ctl --list-formats-ext`（板端 agent 新增 `/formats`），电脑：ffmpeg dshow `-list_options`（safe_decode 解码）。
- 下拉框显示“1920×1080 · 30 fps · MJPEG”。如果之前保存的模式仍受支持就保留，否则选最高分辨率且 ≥30 fps 的模式，同等条件优先 MJPEG。检测不到时显示常用预设，可选“自定义…”。
- 设置文件格式不变（width/height/fps/format 存为字符串）。

## 通用开发板（board_probe.py）
- 用现有 SSH 登录，把一段 POSIX sh 脚本经 stdin 发给 `sh -s` 执行，开发板上不需要安装任何东西。
- 型号识别依次读取：/proc/device-tree/model、/sys/firmware/devicetree、compatible、/etc/nv_tegra_release、/proc/cpuinfo、DMI（会过滤 "To Be Filled" 之类的占位值）。
- 能识别的板型：KV260、Zynq/PYNQ、Jetson、Raspberry Pi、Rockchip、通用 Linux。
- 显示的信息：系统、内核/架构、CPU/核数、内存、存储、主机名/IP、运行时间、FPGA（fpga_manager 状态和 xmutil 当前应用）。
- 实时状态：保持一条长连接的 ssh，每 2 秒输出一次，在后台线程解析，不占用 UI 线程。内容包括 CPU%、负载、内存、最高温度（thermal_zone*）、磁盘、网速（不计 lo），以及 Jetson GPU 和 RKNPU 负载。没有的探针对应的行会自动隐藏。断线后约 5 秒重连。
- FPGA/xmutil 信息只在开发板支持时显示。原有的 KV260 采集流程不变。
- UI 文案统一改为“开发板”，型号显示为检测结果。

## 测试
- tests/test_board_probe.py：19 项，样例覆盖 KV260、Jetson、树莓派、RK3588、x86、PYNQ、BusyBox、CRLF、GBK 和中文主机名。
- tests/test_camera_modes.py：13 项。
- ui_redesign/smoke_ui.py：82 项。
- render_ui.py：1280×800、1600×900、1920×1080 三种尺寸下中英文都没有截字，也没有竖向滚动（各 28 项）。

## 需要真机验证
- 真实的 v4l2/dshow 输出。
- 板端 agent 同步后 `/formats` 是否可用。
- 各板 sysfs 路径差异，例如 Jetson GPU load 路径、RKNPU debugfs 需要 root。
- xmutil listapps 的实际格式。
- Windows OpenSSH 下长连接 ssh 的稳定性。

## 外设页（peripherals.py）
- 页面入口：导航中的“外设”。连接开发板后自动扫描，热插拔时也会自动扫描：2 秒一次的状态流会比较 /sys/bus/usb/devices 和 /dev 的签名，变化后重新扫描，并记录“新接入 / 已移除”。
- 识别范围：
  - USB：VID:PID、厂商、产品、类别、速度、驱动。
  - 视频：v4l2 能力和全部模式。
  - 串口：CH340、CP210x、FTDI、PL2303、CDC-ACM、PS UART 等。
  - I2C：总线和已绑定设备。
  - SPI、网络（状态、速率、MAC、IP）、存储（lsblk）、音频（aplay/arecord -l）、GPIO（gpiodetect 或 sysfs）、显示（DRM 和 EDID 名称）、PCIe（lspci -nnk）。
- 全部只读，每条命令都有 timeout 限制，在后台线程运行，输出用 safe_decode 解码，没有的工具会被跳过。
- I2C 扫描（i2cdetect -y -r）只在点击“扫描 I2C”时运行，避免在推流时探测摄像头 I2C 总线。
- 操作：搜索、分类筛选、详情、复制为文本、导出 JSON（保存到输出目录，文件名 peripherals_时间.json）、刷新。
- 电脑端外设未做，只有已有的 dshow 摄像头列表。
