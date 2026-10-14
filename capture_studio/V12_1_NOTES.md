# Board Capture Studio v0.12.1

产品显示名改为 **开发板采集工作室 / Board Capture Studio**（窗口标题、侧栏品牌、托盘标题、启动脚本、便携包名）。
Python 包名仍是 `capture_studio`，GitHub 仓库仍是 `nulihou/kv260-capture-studio`（仓库 slug 为历史名称，发布说明里会注明）。

## 检查更新：代理失败后直连重试
系统代理连不上、被拒绝、隧道失败或超时时，自动再用直连试一次。
- 代理成功 → 只请求一次。
- 代理返回限流 / 404 / 其他 HTTP 错误 → 不重试。
- 代理失败、直连成功 → 采用直连结果。
- 两边都连不上 → 保留代理侧友好提示；直连若返回限流等 HTTP 错误，则采用直连提示。

便携包：`BoardCaptureStudio_v0.12.1_windows_x64.zip`。
