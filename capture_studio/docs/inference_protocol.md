# 板端推理结果协议

Capture Studio 的「模型展示」页只负责显示。检测、跟踪、小目标模型都在开发板上运行（KV260 DPU、Jetson、RK3588、昇腾 NPU 或其他板端运行时）。Windows 电脑不加载模型，也不安装 torch、onnxruntime、ultralytics、openvino 等运行时。

数据流：

1. 板端采集服务继续输出预览画面（已有的 `/live/frame`、`/live/stream`）。
2. 板端模型进程把每一帧的结果 `POST` 到同一个采集服务的 `/infer`。
3. 电脑按 `frame_id`（优先）或 `timestamp_ns` 把结果贴到当前画面上。

维护中的发送脚本是 `capture_studio/board_infer_push.py`。下面的脚本与它相同，只使用 Python 标准库，可以单独拷到板上。

## 一条结果

`Content-Type: application/json`，对象字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema` | 建议 | 固定为 `capture-studio.inference.v1`。缺省时按此版本解析；其他值会被拒绝。 |
| `frame_id` | 是 | 非负整数。和预览帧同一个计数器时，电脑按它对齐。 |
| `timestamp_ns` | 否 | `time.time_ns()`，纳秒。模型自己取流、对不上 `frame_id` 时用来对齐。 |
| `width`, `height` | 是 | 框所在图像的宽高，像素，1–8192。 |
| `coord` | 否 | `pixel`（默认）或 `norm`（相对宽高的 0–1）。服务返回给电脑的框一律是像素。 |
| `model` | 否 | 模型名，最长 80 字符。还没接模型时请用 `not-configured`，界面会显示「模型未接入」，而不会当成真实识别。 |
| `backend` | 否 | 例如 `kv260-dpu`、`jetson-tensorrt`、`rk3588-rknn`、`ascend`。 |
| `latency_ms` | 否 | 这一帧推理耗时，毫秒，0–600000。 |
| `detections` | 是 | 数组，最多 400 个，可以是空数组。 |
| `preview_only` | 否 | 只能是 `true`。电脑端演示用的脚本框会带上它。板端真实模型不要设置。 |

每个检测：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `bbox` | 是 | `[x, y, w, h]`。原点在图像左上角，x 向右，y 向下。`w`、`h` 必须大于 0。 |
| `class` | 是 | 类别名，1–64 字符。 |
| `score` | 是 | 0 到 1。 |
| `class_id` | 否 | 整数。 |
| `track_id` | 否 | 整数或不超过 32 字符的字符串。界面用它保持框的淡入，并支持点选跟踪。 |

示例：

```json
{
  "schema": "capture-studio.inference.v1",
  "frame_id": 120,
  "timestamp_ns": 1700000000123456789,
  "width": 1920,
  "height": 1080,
  "model": "yolov8n-visdrone",
  "backend": "kv260-dpu",
  "latency_ms": 18.4,
  "detections": [
    {"bbox": [640, 360, 48, 32], "class": "person", "class_id": 0, "score": 0.91, "track_id": 3}
  ]
}
```

## 和画面帧对齐

预览进程每收到一张 PNG，就把 `frame_id` 加一，并记下 `time.time_ns()`。`GET /live/metrics` 和 `GET /infer` 的 `preview` 字段都会带上这两个值。

- 模型消费的就是这路预览：读 `GET /live/envelope`，用返回的 `frame_id` 原样填进结果。这是首选。
- 模型自己打开摄像头：填同一时钟的 `timestamp_ns`。电脑接受比当前画面早最多 80 ms、晚最多 40 ms 的结果。
- 模型比画面慢 1–3 帧：电脑仍贴上最近的那条，避免框闪没。更旧的结果丢掉，不拿去套新画面。

`/live/stream` 仍是纯 PNG，原有预览不受影响。`/live/envelope` 是新增的：每帧先写 4 字节大端头长度，再写 JSON（`frame_id`、`timestamp_ns`、`width`、`height`），再写 PNG。

## 采集服务接口

和原来的预览一样，需要 `Authorization: Bearer <token>`。默认只监听板子本机，经 SSH 隧道给电脑。

- `POST /infer`：正文是上面的对象，最大 256 KiB。成功返回 `{"accepted": true, "frame_id": N}`。
- `GET /infer`：按当前预览帧对齐后的结果。`result` 没有对上时为 `null`。可选查询 `frame_id`、`timestamp_ns`。
- `GET /live/envelope`：带头的预览流，给板端模型用。

电脑上的「模型展示」在来源选「板端」时，沿用已有实时预览取画面，并轮询 `GET /infer`。温度、CPU、内存来自原有的板端状态探针，不是模型上报的。

## 板端最小脚本

真实模型跑完后，把框填进 `adapt()` 能认的形状，再 POST。脚本本身不做推理。

把模型输出整理成下面任一形状即可：

- 已经是协议对象（含 `detections` 和 `frame_id`）
- 或 `boxes` 里用 `xywh` / `xyxy` / `bbox`，类别用 `class` / `label` / `name`，分数用 `score` / `conf`

```python
#!/usr/bin/env python3
"""Board-side sender. Stdlib only. Run on the board, not on the Windows PC."""
import json
import sys
import urllib.request
from pathlib import Path

SCHEMA = "capture-studio.inference.v1"
URL = "http://127.0.0.1:8765/infer"
TOKEN = Path("capture_token.txt").read_text(encoding="utf-8").strip()


def adapt(raw):
    if "detections" in raw and "frame_id" in raw:
        raw.setdefault("schema", SCHEMA)
        return raw
    detections = []
    for item in raw.get("boxes") or []:
        if "xyxy" in item:
            x1, y1, x2, y2 = item["xyxy"]
            bbox = [x1, y1, x2 - x1, y2 - y1]
        else:
            bbox = item.get("xywh") or item["bbox"]
        detections.append({
            "bbox": [float(v) for v in bbox],
            "class": str(item.get("class") or item.get("label") or item.get("name")),
            "score": float(item.get("score") if item.get("score") is not None else item["conf"]),
            **({"class_id": int(item["class_id"])} if "class_id" in item else {}),
            **({"track_id": item["track_id"]} if "track_id" in item else {}),
        })
    return {
        "schema": SCHEMA,
        "frame_id": int(raw["frame_id"]),
        "timestamp_ns": int(raw.get("timestamp_ns") or raw.get("time_ns") or 0),
        "width": int(raw["width"]),
        "height": int(raw["height"]),
        "model": str(raw.get("model") or "board-model"),
        "backend": str(raw.get("backend") or "board"),
        "latency_ms": float(raw.get("latency_ms") if raw.get("latency_ms") is not None else raw.get("ms") or 0),
        "detections": detections,
    }


def push(result):
    body = json.dumps(result).encode("utf-8")
    request = urllib.request.Request(
        URL, data=body, method="POST",
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2) as response:
        response.read()


if __name__ == "__main__":
    # One JSON object per line from the model process, for example:
    #   {"frame_id": 1, "width": 1920, "height": 1080, "ms": 12.0,
    #    "model": "yolov8n", "backend": "kv260-dpu",
    #    "boxes": [{"xyxy": [10, 20, 80, 60], "label": "car", "conf": 0.88}]}
    for line in sys.stdin:
        if line.strip():
            push(adapt(json.loads(line)))
```

模型若要和预览用同一张图，在板子上执行（先让电脑或脚本打开实时预览）：

```bash
python3 -m capture_studio.board_infer_push --envelope \
    --url http://127.0.0.1:8765 --token-file ./capture_token.txt
```

然后只改 `detections_from_frame`：用你的板端运行时处理 `png`，返回协议对象，并照抄 `meta["frame_id"]`。在接上模型之前，这个函数发送空列表且 `model` 为 `not-configured`，界面会标明还没有模型，不会画出假框。

接入时各平台只差运行时，协议不变：

- KV260 DPU / Vitis AI：在板上拿 `png`（或原始 NV12）跑 DPU，把 `bbox`、类别、分数填进 `detections`。
- Jetson：TensorRT / DeepStream 的框同样填进 `boxes`，`backend` 写 `jetson-tensorrt`。
- RK3588：RKNN 输出同样处理，`backend` 写 `rk3588-rknn`。
- 昇腾：ATC / ACL 推理在板上完成后 POST，`backend` 写 `ascend`。

不要把模型文件或上述运行时装到 Windows 电脑上。电脑只开「模型展示」，来源选「板端」。

## 电脑上的演示和回放

没有板子时，页面默认播放仓库里的航拍路口片段（Pexels 35467100，许可见 `assets/demo_clip/ATTRIBUTION.md`），并叠上与画面对齐的手工标注。标注写在 `assets/demo_clip/demo.jsonl`，`preview_only: true`，`model` 为 `demo-clip`。这不是数据集 GT，也不是在电脑上跑出来的检测结果。本地视频或本机摄像头仍只用脚本框，同样 `preview_only: true`，不看像素。画面上会一直显示「演示数据」，说明写在标题下方（「演示标注，不是识别结果」），全屏时也保留。旁边的温度、CPU、内存标为「示意读数，不是板端」，不会冒充板端探针。

「记录」把当前看到的协议对象存成 JSONL（一行一条）。「回放」再读出来，并标明这是回放，不是实时识别。回放不能代替板端模型。

## 桌面过滤

置信度滑块和类别开关只影响电脑上的绘制，不会改板端结果，也不会写回 JSONL 之外的过滤。JSONL 保存的是收到的整帧结果。
