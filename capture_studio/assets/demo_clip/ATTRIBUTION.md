# 演示片段

默认「演示片段」是从地面向上拍的天空，画面里有一群飞鸟。框按每只鸟的深色像素逐帧收紧。电脑播放时没有跑检测模型。界面上标为「演示数据 / 演示标注，不是识别结果」。

## 画面

- 来源：Pexels 视频 **14118342**，标题 *Flock of birds flying in the sky*
- 页面：https://www.pexels.com/video/flock-of-birds-flying-in-the-sky-14118342/
- 作者：Cesar A. Ramirez Vallejo Traphitho（Pexels 页面署名）
- 文件：`14118342-hd_1920_1080_30fps.mp4`
- 许可：[Pexels License](https://www.pexels.com/license/)
  - 可免费使用和修改，包括商业用途
  - 不要求署名；这里仍记录来源
  - 不得把未改动的原片当作素材库存再出售
- 本仓库只保留从第 3.2 秒起、约 3 秒、1280×720、8 fps 的 JPEG 序列（`frames/f_01.jpg` … `f_24.jpg`），不是原始文件。

## 标注

`demo.jsonl` 每一行是协议 `capture-studio.inference.v1`，`preview_only: true`，`model` 为 `demo-clip`，类别 `bird`。框是离线对照每一帧 JPEG 收紧到鸟体暗部的静态演示标注，每帧大约 7–12 只，贴着鸟的轮廓，画面里大部分可见的鸟都有框。这不是数据集 GT，也不是 Capture Studio 在电脑上跑出来的识别结果。接到板端模型后，来源改成「板端」，这些标注不再使用。

## 没有采用的素材

- Mixkit 44735、44645：可商用，但每段只有一架无人机，画面大半是空天。
- Pexels 4446463：可商用的单架无人机，机体贴在画面右缘。
- Envato / Adobe Stock 的无人机群：不是可再分发的免费许可，没有放进仓库。
