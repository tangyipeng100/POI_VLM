# POI-Guided Vision-Language Decision Making for Outdoor Robot Local Navigation

An interpretable perception-to-decision interface that turns drivable-area
geometry and route context into visual, structured VLM actions.

**[Open the POI-VLM project page](https://tangyipeng100.github.io/POI_VLM/)**

Videos, the narrated PPT presentation, and other visual demonstrations are
available on the [Project Page](https://tangyipeng100.github.io/POI_VLM/).

POI-VLM is a compact interface for route-aware local decisions in outdoor
robotics. A drivable-area mask becomes a small set of numbered polygon POIs;
a route-progress cue adds direction; a vision-language model returns one
structured action that can be inspected by a person and scored frame by frame.

## Visual overview

<p align="center">
  <img src="open_source/assets/framework.jpg" alt="POI-VLM framework overview" width="860">
</p>

<p align="center">
  <img src="open_source/assets/question.png" alt="Composed front-view and route-view question" width="430">
  <img src="open_source/assets/accuracy.png" alt="Offline action accuracy comparison" width="430">
</p>

## Contents

- [Night-150 dataset note](open_source/dataset/night_150/README.md): the coordinate-free metadata slice and preview images.
- [Annotation tool guide](open_source/annotation_app/README.md): the local browser labeler.

## What is included

- `open_source/poi_core/`: polygon extraction, edge classification, vanishing-point and priority-aware candidate generation.
- `open_source/examples/`: an offline POI overlay example, bundled input assets, and a generated result image/JSON.
- `open_source/inference_bridge.py`: a provider-neutral bridge for sending a composed question image to an OpenAI-compatible VLM endpoint.
- `open_source/tests/`: focused tests for the reusable core and inference bridge.
- `open_source/dataset/night_150/`: 150 ordered metadata records, sanitized decisions, and 18 preview images. No coordinates or provider map tiles are included.
- `open_source/annotation_app/` and `open_source/annotation_server.py`: a local-only browser labeler with POI, rotate, skip, confidence, notes, sample navigation, and CSV export.

## Runnable examples

Install the small Python package first if OpenCV/NumPy are not already
available:

```powershell
cd open_source
python -m pip install -e .
```

### 1. Generate numbered POIs

The bundled example uses a front frame and drivable-area mask. It is offline
and needs no API key:

```powershell
python examples/generate_poi_example.py
```

Outputs:

- `examples/output/poi_overlay.jpg`: the front frame with the polygon and numbered POIs.
- `examples/output/poi_result.json`: the polygon, edge classes, and POI pixel coordinates.

### 2. VLM inference bridge

`inference_bridge.py` sends one composed front/map image, or two separate
front/map images, to an OpenAI-compatible endpoint. It supports Chat
Completions and Responses-shaped APIs, retries transient failures, and only
reads credentials from an environment variable. The bridge returns only the
normalized `action`, `poi_number`, and `reason` fields; raw provider responses
are not written.

Inspect the request without making a network call:

```powershell
python inference_bridge.py `
  --image assets/question.png `
  --model your-vision-model `
  --dry-run
```

Run a real request by setting `VLM_API_KEY`, `VLM_MODEL`, and optionally
`VLM_BASE_URL` in the environment. The complete command set is in
[`open_source/README.md`](open_source/README.md#runnable-examples).

## Annotation quick start

From `open_source/`, run the local labeler:

```powershell
python annotation_server.py
```

Open `http://127.0.0.1:8765/`. The default dataset is the bundled preview
slice. No network or API key is required.

## Evaluation snapshot

The current paper snapshot reports 150 night frames: GPT-5.5 action accuracy
`138/150` and Qwen-H800 action accuracy `137/150`. Strict target agreement is
`97/150` and `118/150`, respectively. These are offline frame-level results,
not closed-loop navigation or a safety guarantee.

## Release boundary

The package does not publish API keys, raw recordings, exact GPS or route
coordinates, provider-owned map imagery, raw VLM payloads, internal chats,
patent material, or the original segmentation training set. The included
images and videos are reviewable evidence; confirm consent and third-party
image rights before hosting them publicly. The paper link is intentionally a
living placeholder until the final publication is available.

## License

Code is released under the MIT License. Media, figures, and publication
materials remain subject to the terms described in
[`open_source/LICENSE_POLICY.md`](open_source/LICENSE_POLICY.md) until their
publication and image-rights review is complete.
