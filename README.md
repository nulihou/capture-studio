[**中文**](README.md) | [English](README.en.md)

# Capture Studio

Windows 桌面程序（PySide6）：本机 USB 摄像头采集，以及通过 SSH 为 **KV260、Jetson、树莓派、RK3588** 和其他可 SSH 访问的 Linux 开发板做采集与调试。支持中文 / English、浅色 / 深色（截图为 125% 缩放、未接摄像头时）。

## 克隆

当前版本 **v0.12.6**，便携包见 [GitHub Release](https://github.com/nulihou/capture-studio/releases/tag/v0.12.6)。此版本修复退出时预览停止请求与 SSH 隧道关闭的竞争，并在切换页面时立即刷新对应来源的卡片和操作状态。

验证：227 项软件测试、229 项 Qt 界面检查通过；最终 Windows EXE 已在 KV260 / HHW001 上完成预览、60 秒录制、自动停止、取回、校验及实时预览中退出，退出码为 0。此验收不代表摄像头达到真实 30 fps，也不代替现场画质与长期稳定性测试。

```bash
git clone https://github.com/nulihou/capture-studio.git
cd capture-studio
pip install -r capture_studio/requirements.txt
python -m capture_studio
```

或双击 `capture_studio\Start-CaptureStudio.cmd`（旧名称 `Start-KV260-CaptureStudio.cmd` / `Start-BoardCaptureStudio.cmd` 仅转发到这里）。

运行：`python -m capture_studio`

## 界面（以下截图来自 v0.12.5）

左侧：测试、电脑、开发板、外设、会话、设置。

### 摄像头测试（深色）

![摄像头测试](docs/screenshots/v12/zh_dark_lab.png)

顶部四格为开发板、摄像头、画面参数和状态。左侧预览；右侧画面 / 曝光 / 图像。快捷键：Space 开始/停止，L 实时预览，P 预览一帧，F 大屏（Large view），H 采集前体检。

### 开发板（深色）

![开发板](docs/screenshots/v12/zh_dark_board.png)

未连接时用**连接向导**或快速扫描。发现规则（与向导内说明一致）：

- 每块真实网卡所在 **/24**（最多 3 块；更大网段也不扫整段）
- 系统**邻居表**（ARP / Get-NetNeighbor），含 **169.254** 链路本地（直连、无 DHCP 时），**不做** 169.254/16 全网扫描
- 常见 **`.local`** 名称（kria、ubuntu、raspberrypi、jetson、rockchip…）；可选 `zeroconf` 浏览 `_ssh._tcp`
- **只测 TCP 22** 的 `SSH-` 应答，不登录、不扫其他端口
- 按 MAC OUI / 名称标注厂商；开发板优先排序；普通 Linux / Windows PC 会标出
- 有线网卡只有 169.254 或无网关时，界面给出**直连文字指引**（不改系统网络）；可手填 IP 并 **测试这个 IP**

自动选用：若只发现一块开发板则选中；多块时请手选；没有开发板而只有一台 SSH 设备时提示核对。**不会**仅因「是 Xilinx」就在多设备时静默选定。

连接后显示型号、系统、CPU、内存、温度、磁盘等（KV260 / Zynq / Jetson / 树莓派 / RK3588 等可识别）。

### 外设（深色）

![外设](docs/screenshots/v12/zh_dark_periph.png)

USB、视频、串口、I2C、SPI、网络、存储、音频、GPIO、显示等；可搜索、筛选、串口终端与导出。

## 准备

- Windows 10/11，Python 3.10+：`pip install -r capture_studio/requirements.txt`（`keyring` 用于记住密码；可选 `zeroconf` 增强 mDNS）
- Windows OpenSSH 客户端
- 电脑与开发板网络可达（同网段、或直连后按指引设静态 IP、或手填 IP）
- 开发板已能 SSH；Kria 默认用户常为 `ubuntu`
- 板上需 Python 3、GStreamer、gcc（首次连接写入采集服务）
- 本机采集/校验需要 FFmpeg、FFprobe（PATH 或设置页指定）

## 使用

```powershell
git clone https://github.com/nulihou/capture-studio.git
cd capture-studio
pip install -r capture_studio/requirements.txt
python -m capture_studio
```

1. 若本机还没有密钥，会生成 **Capture Studio SSH 密钥**（文件仍为 `~/.ssh/id_ed25519_kv260`，兼容已装过公钥的板）。
2. 用连接向导扫描或手填地址；按上面的发现规则理解结果。
3. 新板第一次可填登录密码以安装公钥（可选「记住密码」→ Windows 凭据管理器）；之后用密钥。
4. 保存并连接；软件在板上部署/启动采集服务。
5. 在「摄像头测试」或「开发板采集」页用 **大屏** 看画面；对准后再录。
6. **设置**页可 **检查更新**（GitHub Releases；代理失败会直连重试；不自动替换本机文件）。

## 测试

```powershell
cd capture_studio\tests
$env:PYTHONPATH = (Resolve-Path ..\..).Path
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -v -p "test_[!u]*.py"
python ..\ui_redesign\smoke_ui.py capture_studio
```

（在仓库根克隆布局下执行；`test_ui.py` 会开 Tk 窗口，默认跳过。）

## 便携包

Release 资产：`CaptureStudio_v<version>_windows_x64.zip`。解压后运行 `CaptureStudio.exe`。
