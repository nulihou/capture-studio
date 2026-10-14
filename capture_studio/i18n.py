"""Chinese / English UI text for Capture Studio.

Source strings stay Chinese (they double as the data values the backend expects);
only what is *displayed* goes through tr() / tr_opt() / tr_msg().
The language choice is a UI preference stored in ui_prefs.json, separate from studio settings.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LANGS = ("zh", "en")
_PREFS = (Path(sys.executable).parent if getattr(sys, "frozen", False)
          else Path(__file__).resolve().parent) / "ui_prefs.json"


def _load() -> str:
    try:
        value = json.loads(_PREFS.read_text(encoding="utf-8")).get("lang")
    except (OSError, ValueError, AttributeError):
        value = None
    return value if value in LANGS else "zh"


LANG = _load()


def set_lang(lang: str) -> None:
    global LANG
    if lang not in LANGS:
        return
    LANG = lang
    try:
        _PREFS.write_text(json.dumps({"lang": lang}, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    except OSError:
        pass


# ---- static UI text ------------------------------------------------------------
UI = {
    '版本': 'Revision',
    '外设': 'Peripherals',
    '扫描 I2C': 'Scan I2C',
    '搜索名称、VID:PID、驱动…': 'Search name, VID:PID, driver…',
    '全部': 'All',
    '没有匹配的外设': 'No matching peripherals',
    '暂无外设信息': 'No peripheral info yet',
    '复制': 'Copy',
    '导出 JSON': 'Export JSON',
    '视频': 'Video',
    '串口': 'Serial',
    '音频': 'Audio',
    '显示': 'Display',
    '设备': 'Device',
    '名称': 'Name',
    '驱动': 'Driver',
    '类型': 'Type',
    '接口': 'Interface',
    '产品': 'Product',
    '厂商': 'Vendor',
    '芯片': 'Chip',
    '速度': 'Speed',
    '型号': 'Model',
    '容量': 'Size',
    '方向': 'Direction',
    '声卡': 'Card',
    '标签': 'Label',
    '序列号': 'Serial no.',
    '能力': 'Capabilities',
    '路径': 'Path',
    '类别': 'Class',
    'USB 版本': 'USB version',
    '总线/设备': 'Bus/Device',
    '端口数': 'Ports',
    '总线': 'Bus',
    '驱动版本': 'Driver version',
    '更多模式': 'More modes',
    '稳定链接': 'Stable link',
    '适配器': 'Adapter',
    '扫描结果': 'Scan result',
    '速率': 'Speed',
    '文件系统': 'Filesystem',
    '挂载点': 'Mount point',
    '可移动': 'Removable',
    '上级': 'Parent',
    'ALSA 设备': 'ALSA device',
    '设备名': 'Device name',
    '引脚数': 'Lines',
    '启用': 'Enabled',
    '显示器': 'Monitor',
    '厂商代码': 'Vendor code',
    '首选模式': 'Preferred mode',
    '插槽': 'Slot',
    '子系统': 'Subsystem',
    '内核模块': 'Kernel modules',
    '是': 'yes',
    '无线': 'Wireless',
    '有线': 'Wired',
    '虚拟': 'Virtual',
    '播放': 'Playback',
    '录音': 'Capture',
    '无应答': 'No response',
    '按接口': 'Per interface',
    '通信': 'Communications',
    '图像': 'Imaging',
    '打印机': 'Printer',
    '大容量存储': 'Mass storage',
    '集线器': 'Hub',
    'CDC 数据': 'CDC data',
    '复合': 'Composite',
    '厂商自定义': 'Vendor specific',
    '元数据节点': 'Metadata node',
    '用户态 spidev': 'userspace spidev',
    '已复制外设清单': 'Peripheral list copied',
    '正在扫描外设…': 'Scanning peripherals…',
    '连接开发板后可扫描外设': 'Connect a board to scan peripherals',
    '无法读取外设列表': 'Could not read peripheral list',
    "开发板采集": "Board Capture", "连接后显示型号、系统和实时资源": "Connect to see model, system and live resources",
    "等待实时状态…": "Waiting for live status…", "系统": "System", "内核": "Kernel", "处理器": "CPU",
    "内存": "Memory", "存储": "Storage", "网络": "Network", "运行": "Uptime", "温度": "Temp",
    "磁盘": "Disk", "网速": "Net", "可用": "free", "核": "cores",
    "无画面": "No Signal",
    "大屏": "Full Screen",
    "滚轮放大    拖动平移    Esc 关闭": "Scroll to zoom    Drag to pan    Esc to close",
    "关闭": "Close",
    "连接": "Connect",
    "连接开发板": "Connect to Board",
    "地址": "Host",
    "用户": "User",
    "私钥": "Private Key",
    "板端目录": "Board Directory",
    "摄像头序号": "Camera Serial",
    "可留空": "Optional",
    "选择": "Browse",
    "仅新板第一次": "First time on a new board only",
    "密码": "Password",
    "查找": "Discover",
    "保存并连接": "Save & Connect",
    "摄像头测试": "Camera Test",
    "未连接": "Not Connected",
    "就绪": "Ready",
    "工作区": "Workspace",
    "测试": "Test",
    "电脑": "PC",
    "KV260": "KV260",
    "会话": "Sessions",
    "设置": "Settings",
    "时长": "Duration",
    "未发现摄像头": "No camera found",
    "识别并预览": "Detect & Preview",
    "画面": "Picture",
    "摄像头": "Camera",
    "宽": "Width",
    "高": "Height",
    "帧率": "Frame Rate",
    "格式": "Format",
    "应用并预览": "Apply & Preview",
    "曝光": "Exposure",
    "数字": "Value",
    "灯光": "Mains",
    "白平衡": "White Bal.",
    "对焦": "Focus",
    "室内日光灯": "Indoor Fluorescent",
    "图像": "Image",
    "读取参数": "Read",
    "填入当前": "Fill Current",
    "清空": "Clear",
    "采集": "Record",
    "录 60 秒": "Record 60 s",
    "停止并取回": "Stop & Fetch",
    "电脑采集": "PC Capture",
    "刷新": "Refresh",
    "预览一帧": "Preview Frame",
    "编码": "Codec",
    "开始采集": "Start Recording",
    "停止并校验": "Stop & Verify",
    "KV260 采集": "KV260 Capture",
    "实时": "Live",
    "预览": "Preview",
    "板端": "Board",
    "本机": "This PC",
    "取回": "Fetch",
    "校验": "Verify",
    "数据目录": "Data Folder",
    "采集人": "Operator",
    "场景备注": "Scene Notes",
    "镜头": "Lens",
    "光照": "Lighting",
    "距离": "Distance",
    "保存": "Save",
    "检查工具": "Check Tools",
    "更亮": "Brighter",
    "室内会变暗": "Darker indoors",
    "语言": "Language",
    "停止实时": "Stop Live", "录制中": "Recording", "实时预览中": "Live", "空闲": "Idle",
    "开发板": "Board", "画面参数": "Stream", "状态": "Status", "动态": "Activity",
    "暂无动态": "No activity yet", "识别摄像头并预览": "Detect the camera and preview",
    "调整画面后开始采集": "Tune the picture, then record",
    "模式": "Mode", "检测": "Detect", "自定义…": "Custom…", "常用预设": "common presets",
    "数据": "Data", "打开文件夹": "Open Folder", "列出本机会话": "List Local",
    "暂无会话": "No sessions yet", "尚未保存连接": "No saved connection",
    # camera_lab TUNING labels
    "增益": "Gain", "亮度": "Brightness", "对比度": "Contrast", "饱和度": "Saturation",
    "锐度": "Sharpness", "伽马": "Gamma", "色温": "Color Temp", "灯光频率": "Mains Freq.",
    "逆光补偿": "Backlight Comp.", "焦距": "Focus Position",
}

# ---- option labels (combo items / presets): value stays Chinese ------------------
OPTIONS = {
    "60 秒短检": "60 s quick check", "10 分钟关口": "10 min gate", "手动停止": "Stop manually",
    "看清画面": "Clarity", "看流畅": "Smoothness", "自己设置": "Custom",
    "自动": "Auto", "手动": "Manual", "快门优先": "Shutter priority",
    "不改": "Keep", "关闭": "Off",
}

# ---- runtime messages from the backend (display-only translation) ---------------
MESSAGES = {
    "无法读取开发板信息": "Could not read board info", "OpenSSH 不可用": "OpenSSH unavailable",
    "有操作正在进行": "Another operation is in progress",
    "未找到开发板": "Board not found",
    "正在查找": "Searching…",
    "填写开发板地址，或先查找": "Enter the board host, or run Discover first",
    "正在连接": "Connecting…",
    "未检测到摄像头": "No camera detected",
    "正在列出本机摄像头": "Listing local cameras…",
    "尚未连接开发板": "Board not connected",
    "实时预览": "Live preview",
    "正在打开画面": "Opening stream…",
    "画面已更新": "Frame updated",
    "正在取画面": "Grabbing frame…",
    "先连接开发板上的摄像头": "Connect the camera on the board first",
    "已读取参数": "Controls read",
    "未读到可调项": "No adjustable controls found",
    "正在读取参数": "Reading controls…",
    "磁盘剩余空间不足 100 MB": "Less than 100 MB of free disk space",
    "已修改图像参数，使用通用采集": "Image controls changed; using generic capture",
    "正在开始采集": "Starting recording…",
    "正在停止并取回": "Stopping and fetching…",
    "正在列出会话": "Listing sessions…",
    "正在取回": "Fetching…",
    "正在校验": "Verifying…",
    "先读取参数": "Read controls first",
    "正在检测模式": "Detecting modes…",
    "未检测到模式，显示常用预设": "No modes detected; showing common presets",
    "开发板未提供模式检测，显示常用预设": "Board does not report modes; showing common presets",
    "板上没有 v4l2-ctl，无法检测模式": "v4l2-ctl missing on the board; cannot detect modes",
    "数据目录尚不存在": "The data folder does not exist yet",
    "已保存": "Saved",
    "采集工具已就绪": "Capture tools are ready",
    "请等待当前操作完成": "Please wait for the current operation to finish",
    "请先停止电脑采集": "Stop the PC recording first",
    "开发板：还没连上": "Board: not connected",
    "开发板上还没有摄像头。把摄像头插到开发板的 USB 口，不要同时插在电脑上。":
        "No camera on the board yet. Plug it into the board's USB port, not into the PC.",
    "开发板上的摄像头已经拔掉。": "The camera on the board was unplugged.",
    "板上没有 v4l2-ctl，先用常用范围。安装 v4l-utils 后可以读出这只摄像头真正支持的项目。":
        "v4l2-ctl is missing on the board; using typical ranges. Install v4l-utils to read real limits.",
    "这是 USB 全速口，高分辨率可能会卡。可以先用 640×480。":
        "This is a USB full-speed port; high resolutions may stutter. Try 640×480 first.",
    "自动白平衡不要再填色温": "Leave color temperature empty with auto white balance",
    "自动对焦不要再填焦距": "Leave focus position empty with autofocus",
    "摄像头序号或 USB 速度无法保存": "Camera serial or USB speed could not be saved",
    "板端尚未编译 native_capture，不能确认画面": "native_capture is not built on the board; cannot verify the picture",
    "曝光预检未能恢复相机控制，已取消开始采集": "Exposure pre-check could not restore camera controls; recording cancelled",
    "录制未正常结束，此项未测": "Recording did not finish normally; not tested",
    "没有 FFmpeg，未从录像抽样": "FFmpeg missing; no samples taken from the recording",
    "没有录像可抽样": "No recording to sample",
    "录像样帧未能解码": "Recording sample frames could not be decoded",
    "录像短于 10 分钟，帧率关口未测": "Recording shorter than 10 min; frame-rate gate not tested",
    "没有 FFmpeg，未能做唯一图像帧率": "FFmpeg missing; unique-frame rate not measured",
    "停止后相机控制已恢复并读回": "Camera controls restored and read back after stop",
    "相机控制未恢复，或原生采集没有完成": "Camera controls not restored, or native capture did not finish",
    "录制进程没有正常结束": "Recording process did not exit normally",
    "本路径未改写相机控制，录制进程已结束": "This path did not change camera controls; recording process exited",
}

_PATTERNS = [
    (r"^已连接 (.+)$", "Connected · {0}"),
    (r"^本机摄像头 (\d+) 台$", "{0} local camera(s)"),
    (r"^电脑采集中 (.+)$", "Recording on PC {0}"),
    (r"^采集中 (.+)$", "Recording {0}"),
    (r"^电脑采集结束 ?(.*)$", "PC recording finished {0}"),
    (r"^已取回 (.+)$", "Fetched {0}"),
    (r"^会话 (\d+) 个$", "{0} session(s)"),
    (r"^已校验 (.+)$", "Verified {0}"),
    (r"^已填入 (\d+) 项$", "Filled {0} field(s)"),
    (r"^已检测到 (\d+) 种模式$", "{0} modes detected"),
    (r"^已选用 (.+)$", "Selected {0}"),
    (r"^外设 (\d+) 项$", "{0} peripherals"),
    (r"^共 (\d+) 项$", "{0} items"),
    (r"^外设扫描失败：(.*)$", "Peripheral scan failed: {0}"),
    (r"^新接入：(.*)$", "Connected: {0}"),
    (r"^已移除：(.*)$", "Removed: {0}"),
    (r"^已导出 (.+)$", "Exported {0}"),
    (r"^模式 (\d+)$", "Mode {0}"),
    (r"^(\d+) 种模式$", "{0} modes"),
    (r"^(.+) · (\d+) 种模式$", "{0} · {1} modes"),
    (r"^(.*) · (\d+) 个设备$", "{0} · {1} device(s)"),
    (r"^(\d+) 个设备$", "{0} device(s)"),
    (r"^(播放|录音) · (.+)$", "{0} · {1}"),
    (r"^(.+) \(驱动占用\)$", "{0} (in use by driver)"),
    (r"^未能读取开发板信息：(.*)$", "Could not read board info: {0}"),
    (r"^曝光预检失败：(.*)$", "Exposure pre-check failed: {0}"),
    (r"^无法取得录制路径样帧：?(.*)$", "Could not get a sample frame from the recording path {0}"),
]

# Substring phrases, longest first (gates summary, camera sentences, numbers in text).
_PHRASES = {
    "完整性": "Integrity", "帧率": "Frame rate", "画面": "Picture", "收尾": "Closeout",
    "通过": " pass", "未过": " fail", "未测": " untested",
    "不可入库": "Not dataset-ready", "可入库": "Dataset-ready",
    "开发板：": "Board: ", "开发板": "Board", "已认出摄像头：": " Camera recognised: ",
    "插着多只摄像头，请选一只。": " Several cameras plugged in; pick one.",
    "开发板上有多只摄像头，请选一只：": "Several cameras on the board; pick one: ",
    "插上了摄像头：": "Camera plugged in: ", "拔掉了摄像头：": "Camera unplugged: ",
    "摄像头重新编号，仍是 ": "Camera re-enumerated, still ",
    "记下的序号是 ": "Saved serial is ", "，现在只插着 ": "; only ",
    "，已改用这一只。": " is plugged in, switched to it.",
    "，这一只没有序号，已改用唯一的摄像头。": "; this one has no serial, using the only camera.",
    "序号 ": "S/N ", "无序号": "no serial", "这一只": "this one", "摄像头": "Camera",
    "USB 1.0 低速": "USB 1.0 low speed", "USB 1.1 全速": "USB 1.1 full speed",
    "USB 2.0 高速": "USB 2.0 high speed", "USB 3.0 超速": "USB 3.0 SuperSpeed",
    "(驱动占用)": "(in use by driver)", "无应答": "no response", "有线": "wired", "无线": "wireless",
    "虚拟": "virtual", "元数据节点": "metadata node", "用户态": "userspace",
    "。": ". ", "，": ", ", "：": ": ", "；": "; ", "（": " (", "）": ")",
}
_PHRASE_KEYS = sorted(_PHRASES, key=len, reverse=True)
_CJK = re.compile(r"[\u3400-\u9fff]")


def tr(text: str) -> str:
    return UI.get(text, text) if LANG == "en" else text


def tr_opt(value: str) -> str:
    return OPTIONS.get(value, value) if LANG == "en" else value


def tr_msg(text: str) -> str:
    """Best-effort English for a backend message; unknown text is shown unchanged."""
    if LANG != "en" or not text or not _CJK.search(text):
        return text
    if text in MESSAGES:
        return MESSAGES[text]
    if text in UI:
        return UI[text]
    if text in OPTIONS:
        return OPTIONS[text]
    for pattern, template in _PATTERNS:
        match = re.match(pattern, text)
        if match:
            return template.format(*(tr_msg(group) for group in match.groups())).strip()
    out = text
    for key in _PHRASE_KEYS:
        if key in out:
            out = out.replace(key, _PHRASES[key])
    return re.sub(r" {2,}", " ", out).strip()


# ---- v7 strings -------------------------------------------------------------------------
_V7 = {
    "开始 / 停止采集": "Start / stop capture", "大屏 / 全屏预览": "Large / full-screen preview", "实时预览开 / 关": "Live preview on / off",
    "预览一帧": "Preview one frame", "采集前体检": "Pre-capture check", "刷新外设 / 会话": "Refresh peripherals / sessions",
    "切换页面": "Switch page", "连接向导": "Connection wizard", "显示快捷键": "Show shortcuts", "关闭弹窗 / 退出大屏": "Close dialog / exit large view",
    "第 1 步 · 找到开发板": "Step 1 · Find the board", "第 2 步 · 登录方式": "Step 2 · Sign-in", "第 3 步 · 完成": "Step 3 · Done",
    "扫描局域网": "Scan LAN", "上一步": "Back", "跳过": "Skip", "下一步": "Next", "打开": "Open", "发送": "Send", "关闭": "Close",
    "跟随系统": "System", "自动": "Auto", "浅色": "Light", "深色": "Dark", "外观": "Appearance",
    "只对本机所在网段的 22 端口做一次快速连接测试，不登录、不扫其他端口。":
        "Only a quick connect test to port 22 on this PC's subnets — no login, no other ports.",
    "或手动填写地址": "Or enter an address", "密码（仅新板第一次，用来安装密钥）": "Password (first time on a new board, to install the key)",
    "记住密码（保存在 Windows 凭据管理器，不写入文件）": "Remember password (Windows Credential Manager, never written to a file)",
    "之后的登录都用本机 SSH 密钥，一般不需要密码。": "Later sign-ins use this PC's SSH key; normally no password is needed.",
    "下次启动时自动连接并打开实时预览（可取消）": "Auto-connect and start live preview on next launch (can cancel)",
    "正在扫描…": "Scanning…", "没有找到，可以手动填写地址": "Nothing found — enter the address manually",
    "请选择或填写开发板地址": "Pick or enter the board address", "一切就绪": "All good", "可以开始，但有几点建议": "Ready, with a few suggestions",
    "建议先处理以下问题": "Please fix these first", "先不录": "Not now", "好": "OK", "仍然开始": "Start anyway", "开始采集": "Start capture",
    "波特率": "Baud", "十六进制显示": "Hex view", "串口只在点“打开”后才会被占用。": "The port is only opened when you click Open.",
    "要发送的内容（回车发送）": "Text to send (Enter)", "按十六进制发送": "Send as hex", "无": "None", "已关闭": "Closed", "清空": "Clear",
    "串口终端": "Serial terminal", "先打开串口": "Open the port first", "重试": "Retry", "详情": "Details", "复制诊断包": "Copy diagnostics",
    "立即连接": "Connect now", "取消": "Cancel", "体检": "Check", "模板": "Templates", "自动连接": "Auto-connect", "已取消自动连接": "Auto-connect cancelled",
    "快捷键": "Shortcuts", "正在准备…": "Preparing…", "停止播放": "Stop", "播放": "Play", "打开文件夹": "Open folder",
    "删除模板": "Delete template", "保存模板": "Save template", "模板名称": "Template name", "场景（用于文件夹命名，可留空）": "Scene (used in folder name, optional)",
    "保存当前设置为模板…": "Save current settings as template…", "采集完成": "Capture finished", "终端": "Terminal", "导出": "Export",
    "无法播放：没有可用的画面（检查 ffmpeg）": "Cannot play: no frames (check ffmpeg)", "请先在列表里选一个串口": "Select a serial port in the list first",
    "自定义模式": "Custom mode", "宽×高@帧率 格式，例如 1280x720@30 mjpeg": "W×H@fps format, e.g. 1280x720@30 mjpeg",
    "格式不对，例如 1280x720@30 mjpeg": "Invalid format, e.g. 1280x720@30 mjpeg", "自定义": "Custom", "录制中": "Recording", "实时预览中": "Live",
    "预计大小": "Estimated size", "开发板 CPU 繁忙": "Board CPU busy", "关闭板上其他程序后再录": "Close other programs on the board first",
    "USB 带宽不够": "Not enough USB bandwidth", "改用 MJPEG，或降低分辨率/帧率，或接 USB 3.0 口": "Use MJPEG, lower resolution/fps, or a USB 3.0 port",
    "网络正忙": "Network busy", "暂停其他传输后再录": "Pause other transfers first", "电脑磁盘空间不足": "Not enough PC disk space",
    "换到空间更大的输出文件夹，或缩短时长、降低分辨率": "Choose a bigger output folder, or shorten duration / lower resolution",
    "开发板存储不足": "Not enough board storage", "清理板端旧会话（取回后删除）或插入更大的存储": "Clean old board sessions (after fetching) or add storage",
    "开发板存储": "Board storage", "开发板过热": "Board overheating", "加风扇或散热片，等降温后再录": "Add a fan/heatsink and wait for it to cool",
    "网络带宽可能不够": "Network may be too slow", "板端录制不受影响，但实时预览和取回会变慢；可用千兆网线": "Board recording is fine, but preview/fetch will be slow; use gigabit Ethernet",
    "网络带宽": "Network bandwidth", "上次录制有疑似掉帧": "Possible drops in last recording", "检查 USB 线和供电，尝试降低帧率或换 MJPEG": "Check USB cable and power; try lower fps or MJPEG",
    "电脑磁盘空间偏紧": "PC disk space is tight", "录完后及时取回并清理": "Fetch and clean up after recording", "电脑磁盘空间": "PC disk space",
    "开发板温度偏高": "Board running hot", "长时间录制可能降频掉帧，建议加强散热": "Long recordings may throttle and drop frames; improve cooling",
    "开发板温度": "Board temperature", "上次录制无掉帧": "No drops in last recording",
    "开发板拒绝登录": "Board refused login", "这台电脑的密钥还没装到开发板上。在连接窗口填一次登录密码，软件会自动安装密钥。":
        "This PC's key is not on the board yet. Enter the login password once in Connect and the key is installed automatically.",
    "开发板身份变了": "Board identity changed", "开发板重装过系统或换了一块板。确认无误后，在 known_hosts 里删除这台主机的旧记录再连。":
        "The board was reinstalled or replaced. If expected, remove its old entry from known_hosts and reconnect.",
    "找不到这个地址": "Address not found", "检查开发板地址是否填错，或用“查找”自动搜索局域网。": "Check the address, or use Find to search the LAN.",
    "开发板拒绝连接": "Board refused connection", "开发板开机了但 SSH 服务没开。等开机完成，或在板上启动 ssh 服务。": "The board is up but SSH isn't running. Wait for boot or start sshd.",
    "网络不通": "Network unreachable", "电脑和开发板不在同一网络。检查网线/Wi-Fi，以及两边的 IP 网段。": "PC and board are not on the same network. Check cable/Wi-Fi and subnets.",
    "连接超时": "Connection timed out", "开发板可能没开机、网线松了或 IP 变了。检查后点“重试”。": "The board may be off, unplugged, or on a new IP. Check, then Retry.",
    "磁盘满了": "Disk full", "清理输出文件夹或换一个空间更大的位置。": "Clean the output folder or choose a bigger location.",
    "摄像头被占用": "Camera busy", "关闭其他正在用摄像头的程序（含实时预览），再试一次。": "Close other programs using the camera (including live preview) and retry.",
    "找不到摄像头": "Camera not found", "重新插拔摄像头，换一个 USB 口，然后点“扫描”。": "Replug the camera, try another USB port, then Scan.",
    "缺少 ffmpeg": "ffmpeg missing", "在设置里指定 ffmpeg/ffprobe 的位置，或把它们放到软件的 bin 文件夹里。": "Set ffmpeg/ffprobe in Settings, or put them in the app's bin folder.",
    "开发板程序版本较旧": "Board agent is outdated", "重新连接一次，软件会自动同步板端程序。": "Reconnect once; the agent is synced automatically.",
    "缺少 OpenSSH": "OpenSSH missing", "在 Windows“可选功能”里安装“OpenSSH 客户端”。": "Install “OpenSSH Client” in Windows Optional Features.",
    "操作没有完成": "Operation did not complete", "可以重试；如果反复出现，请复制诊断包发给维护者。": "You can retry; if it keeps happening, copy the diagnostics and send them to support.",
    "串口或波特率无效": "Invalid port or baud rate", "十六进制格式不对，例如：55 AA 01": "Invalid hex, e.g. 55 AA 01", "模板名称不能为空": "Template name is required",
    "实例": "Instance", "回放": "Playback", "端口": "Port", "硬件 ID": "Hardware ID", "类别": "Class", "厂商": "Vendor", "名称": "Name", "序列号": "Serial", "芯片": "Chip",
}
UI.update({k: v for k, v in _V7.items() if k not in UI})
MESSAGES.update({k: v for k, v in _V7.items() if k not in MESSAGES})
_PATTERNS[:0] = [
    (r"^已打开 (\S+) @ (\d+)$", "Opened {0} @ {1}"), (r"^已保存模板 (.+)$", "Saved template {0}"), (r"^已套用模板 (.+)$", "Applied template {0}"),
    (r"^诊断包已复制：(.+)$", "Diagnostics copied: {0}"), (r"^(\d+) 秒后连接 (\S+) 并打开实时预览$", "Connecting to {1} in {0} s, then live preview"),
    (r"^预计 (.+) / (\d+) 秒 · (\d+) Mb/s$", "Estimated {0} / {1} s · {2} Mb/s"), (r"^已导出 (.+)$", "Exported {0}"),
    (r"^已选用 (.+)$", "Selected {0}"), (r"^找到 (\d+) 台可 SSH 的设备$", "Found {0} SSH-reachable devices"), (r"^会话 (\S+) 已结束$", "Session {0} finished"),
    (r"^约 (.+)（(\d+) Mb/s × (\d+) 秒）$", "About {0} ({1} Mb/s × {2} s)"), (r"^未压缩 (\d+) Mb/s 超过 USB 2.0 实际约 320 Mb/s$", "Uncompressed {0} Mb/s exceeds USB 2.0's ~320 Mb/s"),
    (r"^当前接收 (\d+) Mb/s$", "Receiving {0} Mb/s"), (r"^剩余 (.+)，需要约 (.+)$", "{0} free, needs ~{1}"), (r"^剩余 (.+)，本次约 (.+)$", "{0} free, this run ~{1}"),
    (r"^剩余 (.+)$", "{0} free"), (r"^码率 (\d+) Mb/s，链路 (\d+) Mb/s$", "Bitrate {0} Mb/s, link {1} Mb/s"), (r"^链路 (\d+) Mb/s$", "Link {0} Mb/s"),
    (r"^(\d+) 处间隔 / (\d+) 帧$", "{0} gaps / {1} frames"), (r"^(\d+) 帧$", "{0} frames"), (r"^(.+) 可能是 (.+)$", "{0} possibly {1}"),
    (r"^自定义 · (.+)$", "Custom · {0}"), (r"^电脑外设扫描失败：(.+)$", "PC peripheral scan failed: {0}"),
]
_PHRASES.update({"疑似掉帧": "possible drops", " 帧": " frames", "可能是": "possibly", "摄像头": "camera", "光照": "light", "温湿度": "temp/humidity",
                 "温湿压": "temp/humidity/pressure", "电流": "current", "温度": "temperature", "测距": "ranging", "磁力计": "magnetometer",
                 "加速度计": "accelerometer", "IO 扩展": "IO expander", "背板": "backpack", "电量计": "fuel gauge", "触摸": "touch", "手势": "gesture",
                 "显示器": "monitor", "模块": "module", "红外测温": "IR thermometer", "空气质量": "air quality", "时钟": "clock", "气压": "pressure",
                 "多路复用": "mux", "音频编解码": "audio codec", "驱动占用": "driver bound"})
_PHRASE_KEYS[:] = sorted(_PHRASES, key=len, reverse=True)

# ---- v9 ------------------------------------------------------------------------------------------
_V9 = {
    "快速连接": "Quick connect", "这台电脑": "This PC", "查看全部外设": "View all peripherals", "串口": "Serial",
    "USB 设备": "USB devices", "网卡": "Network", "连接": "Connect", "已保存": "Saved", "尚未保存开发板地址": "No board saved yet",
    "正在扫描本机外设…": "Scanning this PC…", "未发现摄像头或串口": "No cameras or serial ports found",
    "点“查看全部外设”扫描这台电脑": "Click “View all peripherals” to scan this PC",
    "还没有本机会话，采集后会列在这里": "No local sessions yet — recordings appear here",
    "自动选择：上次使用": "Auto: last used", "自动选择：同型号（VID:PID）": "Auto: same model (VID:PID)",
    "自动选择：唯一的 USB 摄像头": "Auto: the only USB camera", "自动选择：唯一的摄像头": "Auto: the only camera",
    "手动选择": "Manual choice", "有多只摄像头，请手动选择": "Several cameras — pick one", "未检测到摄像头": "No camera detected",
    "按格式计算": "computed from format", "按目标码率": "from target bitrate", "按最近会话实测": "measured from recent sessions",
    "上限（按未压缩计）": "upper bound (uncompressed)", "预计大小（估算）": "Estimated size",
    "通用阈值（未识别到该板的官方温度上限）": "generic limits (no published limit for this board)",
    "Raspberry Pi 官方文档：80 °C 开始降频，85 °C 进一步降频": "Raspberry Pi docs: throttles from 80 °C, more at 85 °C",
    "Kria K26 数据手册 DS987：商业级结温上限 100 °C": "Kria K26 data sheet DS987: commercial Tj max 100 °C",
    "有同名摄像头，已用设备路径分开": "Cameras with the same name were told apart by device path",
    "请先在列表里选择一只开发板上的摄像头。": "Pick a board camera in the list first.",
    "请先在列表里选择一只电脑上的摄像头。": "Pick a PC camera in the list first.",
}
UI.update({k: v for k, v in _V9.items() if k not in UI})
MESSAGES.update({k: v for k, v in _V9.items() if k not in MESSAGES})
_PATTERNS[:0] = [
    (r"^约 (.+)（(\d+) Mb/s × (\d+) 秒，(.+)）$", "About {0} ({1} Mb/s × {2} s, {3})"),
    (r"^(\d+) °C ≥ (\d+) °C · (.+)$", "{0} °C ≥ {1} °C · {2}"),
    (r"^(\d+) °C（上限 (\d+) °C · (.+)）$", "{0} °C (limit {1} °C · {2})"),
    (r"^开发板内核温控点（降频 (\d+) °C / 关机 (\d+) °C）$", "board kernel trip points (throttle {0} °C / critical {1} °C)"),
    (r"^开发板内核温控点（告警 (\d+) °C / 关机 (\d+) °C）$", "board kernel trip points (warn {0} °C / critical {1} °C)"),
    (r"^开发板未连接 · 显示这台电脑的 (\d+) 项外设$", "Board offline · showing this PC's {0} peripherals"),
    (r"^回放 · (.+)$", "Playback · {0}"),
]

_V10 = {
    "串口被占用": "Serial port in use",
    "这个串口正被其他程序（或另一个终端窗口）使用。关闭它后再打开。": "Another program (or another terminal window) is using this port. Close it, then open again.",
    "找不到这个串口": "Serial port not found",
    "串口可能已拔出或编号变了。重新插好后点“刷新”，再选一次端口。": "The port may be unplugged or renumbered. Reconnect it, click Refresh and pick the port again.",
}
UI.update({k: v for k, v in _V10.items() if k not in UI})
MESSAGES.update({k: v for k, v in _V10.items() if k not in MESSAGES})

_V11 = {"减少动态效果": "Reduce motion",
        "关闭页面淡入、状态渐变和折叠动画（Windows 关闭动画时自动生效）": "Turns off page fades, status cross-fades and collapse animations (automatic when Windows animations are off)"}
UI.update({k: v for k, v in _V11.items() if k not in UI})
MESSAGES.update({k: v for k, v in _V11.items() if k not in MESSAGES})

_V12 = {
    "扫描范围：每块真实网卡所在的 /24（最多 3 块），加上系统邻居表里已出现的地址和常见 .local 名称；只测 22 端口的 SSH 应答。不登录、不扫其他端口。":
        "Scope: the /24 around each real network adapter (up to 3), plus addresses already in the system neighbour table and common .local names; only port 22 is checked for an SSH reply. No login, no other ports.",
    "测试这个 IP": "Test this IP", "正在测试…": "Testing…", "开发板": "Board", "电脑 / 服务器": "PC / server",
    "Linux 设备": "Linux device", "随机 MAC": "random MAC", "Dropbear (嵌入式)": "Dropbear (embedded)", "地址格式不对": "Invalid address",
    "像是网线直连：打开“连接向导”查看直连提示，或填写开发板 IP 后点“测试这个 IP”。": "Looks like a direct cable: open the Connection wizard for direct-connect tips, or type the board IP and click Test this IP.",
    "没有找到开发板。请确认新板已联网，或直接填写它的 IP。": "No board found. Check that the new board is on the network, or type its IP.",
    "像是网线直连：打开“连接向导”查看直连提示，或填写开发板 IP 后点“测试这个 IP”。": "Looks like a direct cable: open the Connection wizard for direct-connect tips, or type the board IP and click Test this IP.",
}
UI.update({k: v for k, v in _V12.items() if k not in UI})
MESSAGES.update({k: v for k, v in _V12.items() if k not in MESSAGES})
_PATTERNS[:0] = [
    (r"^(\S+) 有 SSH 应答：(.*)$", "{0} answers SSH: {1}"),
    (r"^(\S+) 没有 SSH 应答（不在同一网段、没开机，或 SSH 没启动）$", "{0} gave no SSH reply (different subnet, powered off, or SSH not running)"),
    (r"^有线网卡“(.+)”只有 169\.254 自动地址（(\S+)），像是网线直连且没有 DHCP。.*$",
     "Wired adapter \"{0}\" has only a 169.254 auto address ({1}): looks like a direct cable without DHCP. A board that also uses 169.254 is found via the neighbour table and .local names; otherwise give this adapter a static IP in the board's subnet in Windows network settings (e.g. board 192.168.1.10 -> PC 192.168.1.20 / 255.255.255.0, no gateway), or type the board IP below and click Test this IP."),
    (r"^有线网卡“(.+)”（(\S+)）没有默认网关，可能是直连。.*$",
     "Wired adapter \"{0}\" ({1}) has no default gateway, probably a direct cable. Its /24 was scanned; if the board uses a static IP in another subnet, type it and click Test this IP."),
    (r"^已找到开发板 (.+)。$", "Found board {0}"),
    (r"^(.+。)(像是网线直连：.+)$", "{0} {1}"),
    (r"^只找到一台开着 SSH 的设备 (\S+)。若不是新开发板，请改地址。$", "Only one SSH device found: {0}. Change the address if it is not the new board."),
    (r"^找到多台开着 SSH 的设备：(.+)。请填写新板的地址。$", "Several SSH devices found: {0}. Enter the new board's address."),
    (r"^找到多块开发板：(.+)。请填写新板的地址。$", "Several boards found: {0}. Enter the new board's address."),
]

_V12U = {
    "启动时检查更新": "Check for updates at startup", "每天最多一次，在后台进行，不影响使用": "At most once a day, in the background",
    "检查更新": "Updates", "正在检查更新…": "Checking for updates…", "检查更新失败": "Update check failed",
    "下载": "Download", "关闭": "Close", "没有更新说明": "No release notes",
    "下载后解压到新文件夹即可，旧版本和设置不会被改动。": "Unzip the download into a new folder; the current version and settings stay untouched.",
    "GitHub 访问次数暂时用完，请一小时后再试": "GitHub rate limit reached, try again in an hour",
    "还没有发布版本": "No release published yet", "代理需要登录，请检查系统代理设置": "The proxy requires authentication; check the system proxy settings",
    "连接 GitHub 超时，请检查网络或代理": "Timed out reaching GitHub; check the network or proxy",
    "代理连接失败，请检查系统代理设置": "Proxy connection failed; check the system proxy settings",
    "无法连接 GitHub，请检查网络": "Cannot reach GitHub; check the network", "无法读取更新信息": "Could not read update information",
}
UI.update({k: v for k, v in _V12U.items() if k not in UI})
MESSAGES.update({k: v for k, v in _V12U.items() if k not in MESSAGES})
_PATTERNS[:0] = [
    (r"^有新版本 v(\S+)，可在设置页下载$", "Version {0} is available; download it from Settings"),
    (r"^有新版本 v(\S+)$", "New version {0}"), (r"^已是最新 v(\S+)$", "Up to date (v{0})"), (r"^当前 v(\S+)$", "Current v{0}"),
    (r"^GitHub 返回错误 (\d+)$", "GitHub returned error {0}"),
]

_V121 = {"Capture Studio": "Capture Studio", "开发板采集工作室": "Capture Studio"}
UI.update({k: v for k, v in _V121.items() if k not in UI})
MESSAGES.update({k: v for k, v in _V121.items() if k not in MESSAGES})
