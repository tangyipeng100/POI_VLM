# POI-VLM open-source release

**[Open the POI-VLM project page](https://tangyipeng100.github.io/POI_VLM/)**

POI-VLM is a compact interface for route-aware local decisions in outdoor
robotics. A drivable-area mask becomes a small set of numbered polygon POIs;
a route-progress cue adds direction; a vision-language model returns one
structured action that can be inspected by a person and scored frame by frame.

## Contents

- [Research Wiki](open_source/wiki.html): method, evidence, limitations, and project summary.
- [Continuous decision trace](open_source/media/poi_vlm_continuous_decisions.mp4): 150 ordered night-route frames with the front POIs and top-down route view.
- [Narrated paper presentation](open_source/media/poi_vlm_presentation_narrated_subtitled.mp4): the 720p narrated and subtitled paper walkthrough.
- [Night-150 dataset note](open_source/dataset/night_150/README.md): the coordinate-free metadata slice and preview images.
- [Annotation tool guide](open_source/annotation_app/README.md): the local browser labeler.

## What is included

- `open_source/poi_core/`: polygon extraction, edge classification, vanishing-point and priority-aware candidate generation.
- `open_source/examples/`: an offline POI overlay example, bundled input assets, and a generated result image/JSON.
- `open_source/inference_bridge.py`: a provider-neutral bridge for sending a composed question image to an OpenAI-compatible VLM endpoint.
- `open_source/tests/`: focused tests for the reusable core and inference bridge.
- `open_source/dataset/night_150/`: 150 ordered metadata records, sanitized decisions, and 18 preview images. No coordinates or provider map tiles are included.
- `open_source/media/`: the two-panel continuous decision trace and narrated paper presentation.
- `open_source/annotation_app/` and `open_source/annotation_server.py`: a local-only browser labeler with POI, rotate, skip, confidence, notes, sample navigation, and CSV export.
- `open_source/paper_snapshot.md` and `open_source/paper/`: the current paper snapshot, manuscript, and selected figures.
- `open_source/tools/`: the public-slice builder, decision-video renderer, and metadata sanitizer used to assemble the package.
- `open_source/LICENSE`, `open_source/CITATION.cff`, `open_source/PUBLICATION.md`, and `open_source/LICENSE_POLICY.md`.

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

Code is released under the MIT License. Media, figures, and manuscript content
remain subject to the terms described in
[`open_source/LICENSE_POLICY.md`](open_source/LICENSE_POLICY.md) until their
publication and image-rights review is complete.
