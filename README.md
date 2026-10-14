# Capture Studio

USB camera capture and board debug for **KV260, Jetson, Raspberry Pi, RK3588**, and other SSH-reachable Linux boards - plus local USB cameras on Windows.

## Clone

```bash
git clone https://github.com/nulihou/capture-studio.git
cd capture-studio
pip install -r capture_studio/requirements.txt
python -m capture_studio
```

Or double-click `capture_studio\Start-CaptureStudio.cmd` (legacy names `Start-KV260-CaptureStudio.cmd` / `Start-BoardCaptureStudio.cmd` only forward here).

Run: `python -m capture_studio`

## 中文

Windows 桌面程序（PySide6）：本机 USB 摄像头采集，或通过 SSH 连接开发板采集。支持中文 / English、浅色 / 深色（截图为 125% 缩放、未接摄像头时）。

### 界面（v0.12）

左侧：测试、电脑、开发板、外设、会话、设置。

#### 摄像头测试

![摄像头测试](docs/screenshots/v11/zh_light_lab.png)

顶部四格为开发板、摄像头、画面参数和状态。左侧预览；右侧画面 / 曝光 / 图像。快捷键：Space 开始/停止，L 实时预览，P 预览一帧，F 大屏（Large view），H 采集前体检。

#### 开发板

![开发板](docs/screenshots/v11/zh_light_board.png)

未连接时用**连接向导**或快速扫描。发现规则（与向导内说明一致）：

- 每块真实网卡所在 **/24**（最多 3 块；更大网段也不扫整段）
- 系统**邻居表**（ARP / Get-NetNeighbor），含 **169.254** 链路本地（直连、无 DHCP 时），**不做** 169.254/16 全网扫描
- 常见 **`.local`** 名称（kria、ubuntu、raspberrypi、jetson、rockchip…）；可选 `zeroconf` 浏览 `_ssh._tcp`
- **只测 TCP 22** 的 `SSH-` 应答，不登录、不扫其他端口
- 按 MAC OUI / 名称标注厂商；开发板优先排序；普通 Linux / Windows PC 会标出
- 有线网卡只有 169.254 或无网关时，界面给出**直连文字指引**（不改系统网络）；可手填 IP 并 **测试这个 IP**

自动选用：若只发现一块开发板则选中；多块时请手选；没有开发板而只有一台 SSH 设备时提示核对。**不会**仅因「是 Xilinx」就在多设备时静默选定。

连接后显示型号、系统、CPU、内存、温度、磁盘等（KV260 / Zynq / Jetson / 树莓派 / RK3588 等可识别）。

#### 外设

![外设](docs/screenshots/v11/zh_light_periph.png)

USB、视频、串口、I2C、SPI、网络、存储、音频、GPIO、显示等；可搜索、筛选、串口终端与导出。

### 准备

- Windows 10/11，Python 3.10+：`pip install -r capture_studio/requirements.txt`（`keyring` 用于记住密码；可选 `zeroconf` 增强 mDNS）
- Windows OpenSSH 客户端
- 电脑与开发板网络可达（同网段、或直连后按指引设静态 IP、或手填 IP）
- 开发板已能 SSH；Kria 默认用户常为 `ubuntu`
- 板上需 Python 3、GStreamer、gcc（首次连接写入采集服务）
- 本机采集/校验需要 FFmpeg、FFprobe（PATH 或设置页指定）

### 使用

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

### 测试

```powershell
cd capture_studio\tests
$env:PYTHONPATH = (Resolve-Path ..\..).Path
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -v -p "test_[!u]*.py"
python ..\ui_redesign\smoke_ui.py capture_studio
```

（在仓库根克隆布局下执行；`test_ui.py` 会开 Tk 窗口，默认跳过。）

### 便携包

Release 资产：`CaptureStudio_v<version>_windows_x64.zip`。解压后运行 `CaptureStudio.exe`。

## English

Windows app (PySide6) for local USB cameras and SSH boards (KV260, Jetson, Raspberry Pi, RK3588, …). Chinese / English, light / dark. Screenshots at 125% scaling with no camera attached.

### Interface (v0.12)

Sidebar: Test, PC, Board, Peripherals, Sessions, Settings.

#### Camera test

![Camera test](docs/screenshots/v11/en_light_lab.png)

Shortcuts: Space record, L live preview, P one frame, F **Large view**, H health check.

#### Board

![Board](docs/screenshots/v11/en_light_board.png)

Discovery (also explained in the connection wizard):

- **/24** around each real adapter (up to 3; never sweeps a wider mask as a whole)
- System **neighbour table**, including **169.254** link-local (direct cable); **no** /16 link-local sweep
- Common **`.local`** names; optional `zeroconf` for `_ssh._tcp`
- **TCP 22** SSH banner only - no login
- Vendor tags; boards ranked first; guidance when the NIC has only 169.254 or no gateway (**text only**, no OS network changes); **Test this IP** for a single address

Auto-select: one board → select it; several → pick manually; a single non-board SSH host → select with a warning. Multi-device networks are never silently forced to an Xilinx address.

#### Peripherals

![Peripherals](docs/screenshots/v11/en_light_periph.png)

### Requirements

- Windows 10/11, Python 3.10+: `pip install -r capture_studio/requirements.txt`
- OpenSSH Client; reachable board (same subnet, direct-link static IP, or typed IP)
- FFmpeg / FFprobe for local capture and checks

### Use

```powershell
git clone https://github.com/nulihou/capture-studio.git
cd capture-studio
pip install -r capture_studio/requirements.txt
python -m capture_studio
```

The **Capture Studio SSH key** is stored as `~/.ssh/id_ed25519_kv260` for compatibility with boards that already trust that key. **Settings → Check for updates** uses GitHub Releases (proxy failure retries direct; never self-replaces files).

### Tests

Same commands as the Chinese section (repo-root layout).

### Portable zip

`CaptureStudio_v<version>_windows_x64.zip` → run `CaptureStudio.exe`.
