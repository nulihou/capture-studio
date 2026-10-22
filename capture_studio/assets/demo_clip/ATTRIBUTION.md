# 演示片段

默认「演示片段」是一段从地面向上拍的天空，画面里有一架小尺寸四旋翼无人机。框按机体和旋翼的真实像素位置逐帧贴合，并跟着它移动。电脑没有跑检测模型。界面上标为「演示数据 / 演示标注，不是识别结果」。

## 画面

- 来源：Mixkit 免费视频 **44735**，标题 *Small drone flying with the sky in the background*
- 页面：https://mixkit.co/free-stock-video/small-drone-flying-with-the-sky-in-the-background-44735/
- 文件：https://assets.mixkit.co/videos/44735/44735-720.mp4
- 许可：[Mixkit Stock Video Free License](https://mixkit.co/license/)
  - 可用于商业和非商业项目
  - 允许下载、复制、修改、分发、公开展示
  - 不要求署名；这里仍记录来源
  - 不得把未改动的原片当作素材库存再出售
- 本仓库只保留从第 0.55 秒起、约 3 秒、1280×720、8 fps 的 JPEG 序列（`frames/f_01.jpg` … `f_24.jpg`），不是原始文件。
- 页面没有单独的作者姓名，素材属于 Mixkit / Envato 免费片库。

## 标注

`demo.jsonl` 每一行是协议 `capture-studio.inference.v1`，`preview_only: true`，`model` 为 `demo-clip`，类别 `drone`。框是离线对照画面标出的静态演示标注，只覆盖这一架无人机，尺寸贴着机体和旋翼。这不是数据集 GT，也不是 Capture Studio 在电脑上跑出来的识别结果。接到板端模型后，来源改成「板端」，这些标注不再使用。
