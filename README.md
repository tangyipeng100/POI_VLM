# POI-VLM

**[Open the POI-VLM project page](https://tangyipeng100.github.io/POI_VLM/)**

POI-VLM is a compact interface for route-aware local decisions in outdoor
robotics. A drivable-area mask becomes a small set of numbered polygon POIs;
a route-progress cue adds direction; a vision-language model returns one
structured action that can be inspected by a person and scored frame by frame.

The complete release documentation is [`open_source/README.md`](open_source/README.md).
The visual homepage is [`open_source/index.html`](open_source/index.html), and
the research Wiki is [`open_source/wiki.html`](open_source/wiki.html).

## Release contents

- [`open_source/poi_core/`](open_source/poi_core/): reusable polygon POI generation.
- [`open_source/examples/`](open_source/examples/): offline POI overlay example and bundled assets.
- [`open_source/inference_bridge.py`](open_source/inference_bridge.py): OpenAI-compatible VLM inference bridge.
- [`open_source/dataset/night_150/`](open_source/dataset/night_150/): coordinate-free 150-frame metadata slice.
- [`open_source/annotation_app/`](open_source/annotation_app/): local browser labeler.
- [`open_source/paper/`](open_source/paper/): current paper snapshot and selected figures.
- [`open_source/media/`](open_source/media/): continuous decision trace and narrated paper presentation.

## Runnable examples

Install the package from the release directory if OpenCV/NumPy are not already
available:

```powershell
cd open_source
python -m pip install -e .
```

Generate numbered POIs from the bundled frame and drivable-area mask:

```powershell
python examples/generate_poi_example.py
```

Inspect a VLM request without making a network call:

```powershell
python inference_bridge.py `
  --image assets/question.png `
  --model your-vision-model `
  --dry-run
```

Run a real OpenAI-compatible request with credentials kept in the environment:

```powershell
$env:VLM_API_KEY = "your-key"
$env:VLM_MODEL = "your-vision-model"
$env:VLM_BASE_URL = "https://api.openai.com/v1"
python inference_bridge.py --image assets/question.png --output output\decision.json
```

For the full POI and inference examples, see
[`open_source/README.md`](open_source/README.md#runnable-examples).

## Annotation

```powershell
cd open_source
python annotation_server.py
```

Open `http://127.0.0.1:8765/` to review the bundled coordinate-free preview
slice. No network or API key is required for local annotation.

## Evaluation snapshot

The current paper snapshot reports 150 night frames: GPT-5.5 action accuracy
`138/150` and Qwen-H800 action accuracy `137/150`. Strict target agreement is
`97/150` and `118/150`, respectively. These are offline frame-level results,
not closed-loop navigation or a safety guarantee.

## Release boundary

The package deliberately excludes API keys, raw recordings, exact GPS or route
coordinates, provider-owned map imagery, raw VLM payloads, internal chats,
patent material, and the original segmentation training set. Review image
consent, map-provider terms, and publication status before redistributing the
media or manuscript. See [`OPEN_SOURCE_RELEASE.md`](OPEN_SOURCE_RELEASE.md) and
[`open_source/LICENSE_POLICY.md`](open_source/LICENSE_POLICY.md).

## License

Code is released under the MIT License. Media, figures, and manuscript content
remain subject to the terms in
[`open_source/LICENSE_POLICY.md`](open_source/LICENSE_POLICY.md) until their
publication and image-rights review is complete.
