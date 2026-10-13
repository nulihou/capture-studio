# KV260 数据采集

Windows 程序，用来给一块新的 KV260 采集 USB 摄像头数据。连接时会把采集服务装到板上。每台电脑自己生成 SSH 密钥，每块板自己生成访问令牌。

## 准备

- Windows 10 或 11，已安装 Python 3.10 及以上，并且带 Tkinter。官方 Python 安装时勾选 tcl/tk。
- Windows 自带的 OpenSSH 客户端。在“可选功能”里确认有 OpenSSH Client。
- 电脑和开发板在同一网络。
- 开发板已烧录并完成第一次启动，能用 SSH 登录。Kria Ubuntu 的默认用户一般是 `ubuntu`。
- 板上需要 Python 3、GStreamer 和 gcc。采集服务在第一次连接时写入 `/home/ubuntu/capture_studio`。
- 电脑上若要做本机摄像头采集或取回后的校验，需要 FFmpeg 和 FFprobe，可放进系统 PATH，或在界面里指定路径。

## 使用

```powershell
git clone https://github.com/REPLACE/kv260-capture-studio.git
cd kv260-capture-studio
python -m capture_studio.portable_connect
```

也可以双击 `capture_studio\Start-KV260-CaptureStudio.cmd`。

1. 这台电脑还没有私钥时，软件生成 `~/.ssh/id_ed25519_kv260`。
2. 同一网络只有一块 Xilinx 开发板时，IP 会自动填上。看到多块时列出地址，选中要用的那一块。板端目录保持 `/home/ubuntu/capture_studio`。摄像头序号留空；只接一只摄像头时会自动选用。
3. 新板第一次填写登录密码。软件只把本机公钥装到这块板，密码不保存。之后用密钥连接。
4. 保存并连接。软件在板上创建目录、放入当前采集程序并启动。
5. 在「摄像头测试」或「开发板」页点画面下方的「大屏看画面」，按采集分辨率查看画面。滚轮放大，按住拖动，Esc 关闭。640×480 原样显示；1920×1080 的预览长边收到 1280，避免把连接堵死。
6. 对准之后再录。开始录制时预览会停，录制期间大屏没有画面。

## 测试

```powershell
cd capture_studio\tests
$env:PYTHONPATH = (Resolve-Path ..\..).Path
python -m unittest discover -v
```

## 不包含的内容

- SSH 私钥、板端令牌、连接里保存的地址。
- 已采集的录像。
- SD 卡镜像、FPGA 镜像和模型。数据采集本身不需要它们。
