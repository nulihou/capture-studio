# Capture Studio v0.12.0 说明

## 1. 开发板发现（统一为 `discovery.py`）
以前有两条路径：向导用 `lan_scan`，“查找开发板”用 `board_discover.find_board`。现在两者都走 `discovery.discover()`，这条路径不再要求有默认网关。

候选地址只测 TCP 22 端口：读到 `SSH-` 应答就关闭，不登录，也不测其他端口。

| 来源 | 规则 |
|---|---|
| 网段 | 每块真实、已连接网卡所在的 /24，最多 3 块。/22、/16 这类大网段也只扫本机所在的 /24。虚拟网卡（VMware、Hyper-V、WSL、Clash/Meta、TUN/TAP、VPN、ZeroTier、Tailscale…）、198.18/15 和 169.254 不参与网段扫描 |
| 邻居表 | 合并 `Get-NetNeighbor` 和 `arp -a`（中英文 Windows 输出都能解析）。私网和 169.254 邻居都会单独探测，所以能找到直连且用链路本地地址或其他网段静态 IP 的开发板，不做 /16 扫描。广播、组播、未完成的条目会过滤掉 |
| mDNS | 解析 kria / kv260 / ubuntu / raspberrypi / jetson / nano / orin / rockchip / orangepi5 / rock-5b / radxa / petalinux 等常见名称的 `.local` 地址，2.5 s 超时，保留 169.254 结果。装了 `zeroconf` 时再浏览 DNS-SD `_ssh._tcp`；没装时自动跳过 |

结果按 MAC OUI 标注厂商：Xilinx、Raspberry Pi、NVIDIA、Rockchip/Radxa 标为开发板；Dell、Lenovo、Intel、Realtek、VMware 等标为电脑。随机 MAC 会注明。没有 OUI 时，再看 mDNS 名和 SSH banner（PetaLinux、Dropbear、Windows）。排序：开发板 → Linux 设备 → 电脑。探测会填充 ARP 缓存，所以探测后会再读一次邻居表，给 /24 命中的地址补上 MAC。

自动选择规则：只有一块开发板时直接选中；有多块时不选。没有开发板而只有一台 SSH 设备时，选中它并提示核对。

## 2. 直连指引（只给文字，不改任何网络设置）
- 有线网卡只有 169.254 地址：说明可能是直连且没有 DHCP。会给出给网卡设同网段静态 IP 的示例，或者让用户手动填 IP 后点“测试这个 IP”。
- 有线网卡没有网关：提示可能是直连；如果开发板在其他网段，请手动填写。
- 向导第 1 步写明了扫描范围（/24 规则）。手动填写保留，并新增“测试这个 IP”（只测一个地址的 SSH banner）。

## 3. 检查更新（`updates.py`）
- 设置页新增“检查更新”按钮和版本状态 pill。有新版本时显示黄色，已是最新显示绿色，失败显示红色，悬停可看原因。
- “启动时检查更新”默认开启：启动 3 s 后在后台检查，一天最多一次，失败时不弹窗。
- 数据来源是 GitHub Releases API（`nulihou/kv260-capture-studio`），版本按 semver 比较，预发布版排在正式版之前。
- 发现新版本时弹窗显示更新说明和 zip 大小。点“下载”用浏览器打开 GitHub 上的 zip 或发布页，只放行本仓库的地址；程序不会自己替换文件。
- 离线、超时、代理错误/407、限流（403/429）、404、数据异常都有中英文提示。

## 4. 便携包
`build_portable.py` 改动：
- 加入 discovery/updates/motion 的 hidden import；
- 包名改为 `KV260CaptureStudio_v<版本>_windows_x64.zip`；
- 删除的个人文件新增 studio_settings / ui_prefs / capture_templates；
- 不再打包实验诊断 md。

## 5. 测试
- `tests/test_v12.py`：ipconfig（中/英、169.254、网关续行）、arp（中/英）、Get-NetNeighbor JSON、mDNS（含超时）、OUI、端到端排序、不做 /16 扫描、自动选择、单 IP 测试、向导 UI。
- `tests/test_updates.py`：semver、各类错误、中英文、每日缓存、URL 白名单、更新弹窗。
- smoke 新增更新流程和设置页无滚动检查（zh/en × 浅/深）。
