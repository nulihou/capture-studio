# 演示片段

默认「演示片段」用的是一段真实航拍路口画面，外加一份**手工对齐**的 JSONL。电脑没有跑检测模型。框是演示标注，界面上标为「演示数据 / 演示标注，不是识别结果」。

## 画面

- 来源：Pexels 视频 **35467100**，标题 *Drone Aerial View of Urban Intersection*
- 页面：https://www.pexels.com/video/drone-aerial-view-of-urban-intersection-35467100/
- 文件：https://videos.pexels.com/video-files/35467100/15025977_3840_2160_30fps.mp4
- 许可：[Pexels License](https://www.pexels.com/license/) — 可免费使用、修改，包括商业用途。不要求署名；这里仍记录来源。
- 本仓库只保留从第 1 秒起、约 3 秒、1280×720、8 fps 的 JPEG 序列（`frames/f_01.jpg` …），不是原始 4K 文件。
- 文件内没有作者字段。Pexels 页面在抓取时被拦，未能写入贡献者姓名。ID 35467100 可以回到上面的页面核对。

## 标注

`demo.jsonl` 里每一行是协议 `capture-studio.inference.v1`，`preview_only: true`，`model` 为 `demo-clip`。框按画面里的车、巴士和行人手工标在 1280×720 上，并在 24 帧之间线性插值，方便演示时框跟着走。这不是数据集 GT，也不是模型输出。接到板端模型后，来源改成「板端」，这些标注不再使用。
