# KV260 数据采集 / KV260 Capture Studio

[中文](#中文) · [English](#english)

## 中文

Windows 程序，用来给一块新的 KV260 采集 USB 摄像头数据。连接时会把采集服务装到板上。每台电脑自己生成 SSH 密钥，每块板自己生成访问令牌。

### 准备

- Windows 10 或 11，已安装 Python 3.10 及以上，并且带 Tkinter。官方 Python 安装时勾选 tcl/tk。
- Windows 自带的 OpenSSH 客户端。在“可选功能”里确认有 OpenSSH Client。
- 电脑和开发板在同一网络。
- 开发板已烧录并完成第一次启动，能用 SSH 登录。Kria Ubuntu 的默认用户一般是 `ubuntu`。
- 板上需要 Python 3、GStreamer 和 gcc。采集服务在第一次连接时写入 `/home/ubuntu/capture_studio`。
- 电脑上若要做本机摄像头采集或取回后的校验，需要 FFmpeg 和 FFprobe，可放进系统 PATH，或在界面里指定路径。

### 使用

```powershell
git clone https://github.com/nulihou/kv260-capture-studio.git
cd kv260-capture-studio
python -m capture_studio.portable_connect
```

也可以双击 `capture_studio\Start-KV260-CaptureStudio.cmd`。

1. 这台电脑还没有私钥时，软件生成 `~/.ssh/id_ed25519_kv260`。
2. 同一网络只有一块 Xilinx 开发板时，IP 会自动填上。看到多块时列出地址，选中要用的那一块。板端目录保持 `/home/ubuntu/capture_studio`。摄像头序号留空；只接一只摄像头时会自动选用。
3. 新板第一次填写登录密码。软件只把本机公钥装到这块板，密码不保存。之后用密钥连接。
4. 保存并连接。软件在板上创建目录、放入当前采集程序并启动。
5. 在「摄像头测试」或「开发板」页点画面下方的「大屏看画面」，按采集分辨率查看画面。滚轮放大，按住拖动，Esc 关闭。640×480 原样显示；1920×1080 的预览长边收到 1280，画面仍能在网络上连续刷新。
6. 对准之后再录。开始录制时预览会停，录制期间大屏没有画面。

### 测试

```powershell
cd capture_studio\tests
$env:PYTHONPATH = (Resolve-Path ..\..).Path
python -m unittest discover -v
```

### 仓库里有什么

本仓库包含 Windows 采集程序和测试。SSH 密钥、板端令牌、已保存的开发板地址和已采集的录像在每台电脑、每块板上各自生成。SD 卡镜像、FPGA 镜像和模型另备；数据采集本身使用上面的程序即可。

## English

A Windows program for capturing USB camera data on a newly purchased KV260. Connecting installs the capture service on the board. Each computer creates its own SSH key, and each board creates its own access token.

### Requirements

- Windows 10 or 11 with Python 3.10 or newer, including Tkinter. Select tcl/tk in the official Python installer.
- The OpenSSH Client that ships with Windows. Confirm it under Optional Features.
- The computer and the board on the same network.
- A board that has been flashed, has completed first boot, and accepts SSH. The usual Kria Ubuntu user is `ubuntu`.
- Python 3, GStreamer, and gcc on the board. The first connection writes the capture service to `/home/ubuntu/capture_studio`.
- FFmpeg and FFprobe on the computer for local-camera capture and for checking files after retrieval. Put them on `PATH`, or set their paths in the interface.

### Use

```powershell
git clone https://github.com/nulihou/kv260-capture-studio.git
cd kv260-capture-studio
python -m capture_studio.portable_connect
```

Or double-click `capture_studio\Start-KV260-CaptureStudio.cmd`.

1. If this computer has no key yet, the program creates `~/.ssh/id_ed25519_kv260`.
2. When the network shows exactly one Xilinx board, its IP is filled in. When several boards appear, the program lists them and waits for a choice. Leave the board directory as `/home/ubuntu/capture_studio`. Leave the camera serial blank; a single connected camera is selected automatically.
3. On the first connection to a new board, enter its login password once. The program installs this computer’s public key and does not store the password. Later connections use the key.
4. Save and connect. The program creates the directory on the board, copies the current capture program, and starts it.
5. On the Camera Test or Board page, use **Large view** under the picture (`大屏看画面`) to inspect the frame at capture resolution. The mouse wheel zooms in, dragging pans, and Esc closes the window. A 640×480 frame is shown at full resolution. A 1920×1080 preview arrives with a 1280-pixel long edge so the live picture keeps moving over the network.
6. Start recording after the camera is aimed. Recording stops the preview, so the large view is blank while a recording is in progress.

### Tests

```powershell
cd capture_studio\tests
$env:PYTHONPATH = (Resolve-Path ..\..).Path
python -m unittest discover -v
```

### What this repository contains

This repository contains the Windows capture program and its tests. SSH keys, board tokens, saved board addresses, and recorded video are created on each computer and each board. SD card images, FPGA images, and models are kept separately; data collection uses the program above.
