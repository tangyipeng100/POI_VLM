# POI VLM Decision Prototype

> Public release staging: open [the release page](open_source/index.html) and
> read [the release map](OPEN_SOURCE_RELEASE.md) before publishing this tree.

这个工作区用于把现有 POI 结果做成 VLM 选择题评测样本。它不改动原来的
`C:\working_document\code_project\poi_gen`，只读取数据并在本目录下生成新的
manifest、合成问答图和后续 VLM 预测结果。

## 开源发布入口

如果只想快速了解论文和结果，直接打开 [`open_source/index.html`](open_source/index.html)。
里面有连续 150 帧 POI 决策视频、压缩后的 PPT 讲解视频、双语 README、夜间
150 帧无坐标数据切片和本地标注工具。可复用代码集中在 `open_source/poi_core/`；
原始 GPS、地图底图、API key 和内部记录仍留在工作区之外的私有边界内。

## 1. 构建样本

默认读取：

- 数据：`C:\working_document\2025\录制户外视频gps`
- POI 代码：`C:\working_document\code_project\poi_gen`
- 高德备用图：`C:\working_document\code_project\gaode_map_revise\gaode_path_with_markers.jpg`
- GPS：`C:\working_document\2025\录制户外视频gps\gps_20251229_115727.csv`
- 输出：`C:\Users\51745\Documents\poi plan\vlm_dataset`

如果设置了 `AMAP_KEY`，脚本会为每帧生成动态俯视图：

- WGS84 GPS 转高德 GCJ-02。
- 橙色圆点表示当前 GPS 位置。
- 绿色箭头朝向规划路线前方的 lookahead 点。
- 灰色表示已走路线，蓝色表示剩余路线。
- 顶部显示 total / passed / remaining。

先跑少量样例：

```powershell
conda run -n segment python scripts\build_vlm_choice_dataset.py --limit 5
```

跑完整 811 帧：

```powershell
conda run -n segment python scripts\build_vlm_choice_dataset.py
```

常用抽样参数：

```powershell
conda run -n segment python scripts\build_vlm_choice_dataset.py --start-frame 55 --end-frame 200 --stride 5
```

输出文件：

- `vlm_dataset\samples.jsonl`：每行一个样本，含原图、mask、POI 图、高德图、合成图、候选 POI 坐标、prompt。
- `vlm_dataset\question_images\*_question.jpg`：左侧前视 POI，右侧高德路线图。
- `vlm_dataset\route_maps\*_route.jpg`：每帧动态俯视图，需要 `AMAP_KEY`。
- `vlm_dataset\labels_template.csv`：人工标注模板，填写 `answer` 列即可。
- `vlm_dataset\review.html`：人工快速浏览页面。

`heuristic_answer` 只是按左/中/右方向生成的弱参考，不能当准确率真值。
真正评测需要把 `ground_truth_answer` 补成标注答案，或者另建一个 labels 文件再合并。

用人工标签重建 manifest：

```powershell
conda run -n segment python scripts\build_vlm_choice_dataset.py --labels-csv vlm_dataset\labels_template.csv
```

## 2. 调 VLM

脚本使用常见的 OpenAI-compatible Chat Completions 图片消息格式。等有 key 后：

```powershell
$env:VLM_API_KEY="你的key"
$env:VLM_MODEL="你的vlm模型名"
conda run -n segment python scripts\run_openai_compatible_vlm.py --limit 5
```

如果供应商 API URL 不是 OpenAI 默认地址：

```powershell
$env:VLM_API_URL="https://your-provider.example/v1/chat/completions"
conda run -n segment python scripts\run_openai_compatible_vlm.py --model your-model
```

默认发送合成后的单张 `question_image`。如果模型支持多图，建议对比：

```powershell
conda run -n segment python scripts\run_openai_compatible_vlm.py --image-mode separate --model your-model
```

预测会写入 `vlm_dataset\predictions.jsonl`。当 manifest 里有
`ground_truth_answer` 时，脚本会直接统计 accuracy。

## 3. 当前第一版评测思路

第一版先验证 VLM 是否能稳定读懂三件事：

- 前视图里每个编号 POI 的可行性和相对方向。
- 高德俯视图中 A 到 B 的路线走向。
- 指令约束下，选择一个最合适的下一步 POI。

准确率要靠谱，关键是补一层真值。建议先人工标 30 到 50 个关键帧，覆盖直行、
转弯、路口、遮挡和 POI 截断场景；如果这批效果不错，再扩大到整段视频。

## 4. 标注系统

启动本地标注服务：

```powershell
python annotation_server.py --port 8765
```

然后用 Chrome 打开：

```text
http://127.0.0.1:8765
```

支持三种标签：

- `go_to_poi`：选择一个 POI 编号。
- `rotate`：标注左转/右转和旋转角度。
- `skip`：坏帧、空 POI 或暂时不参与评测。

标注会实时写入：

- `vlm_dataset\annotations.json`
- `vlm_dataset\annotations.jsonl`
- `vlm_dataset\annotations.csv`
