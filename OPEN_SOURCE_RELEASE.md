# Open-source release map

This workspace is a research archive, not yet a single ready-to-publish
repository. The release candidate is intentionally split into three tiers so
the useful parts can be shared without publishing credentials, private
recordings, exact GPS traces, provider-owned map tiles, or internal patent
material. `open_source/` is the self-contained release root; the parent tree is
the working archive.

## Publish now

The publish-now tier is self-contained under `open_source/`. It includes the
clean polygon POI core, tests, the evaluation snapshot, citation/license metadata,
the visual homepage, the Research Wiki, the local annotation app, and the
portable release scripts. There is no one-command demo in this package; the
maintained first-look artifacts are the continuous decision trace and narrated
paper video.

The HTML pages and packaged videos are ready for a visual review. Use
`open_source/serve.py` when previewing locally so browser video controls can
request byte ranges. Keep the
dataset preview images and paper figures in the review tier until the
corresponding rights and privacy checks pass.

The runnable public surface includes `open_source/examples/` for offline POI
generation and `open_source/inference_bridge.py` for optional
OpenAI-compatible VLM calls. Both examples use relative paths and contain no
credentials.

The manuscript and editable paper source directories are intentionally omitted
from this repository. The release keeps only the compact evaluation snapshot,
selected public-facing assets, and publication placeholder.

## Publish after preprocessing

- Dataset records can be released only after removing WGS84/GCJ-02 coordinates,
  absolute Windows paths, provider map tiles, and any scene-identifying detail
  that the data owner does not want public.
- Prediction logs should keep actions, labels, and aggregate metrics, but drop
  API response IDs, raw provider payloads, and private endpoint metadata.
- The current 50-frame daytime and 150-frame nighttime collections are useful
  evidence, but they are not automatically redistributable just because they
  exist locally. A public version should be a consented, redacted subset or a
  metadata-only benchmark.
- `open_source/dataset/night_150/` is the selected coordinate-free metadata
  slice. It contains 150 ordered rows and 18 preview images; the preview
  images remain review-required.
- `open_source/media/` contains the continuous two-panel decision trace and the
  compressed narrated PPT presentation. The trace keeps the front POI panel
  and the corresponding top-down route panel used at decision time; because it
  includes rendered route/map context, both video files remain review-required.
- `open_source/annotation_app/` and `open_source/annotation_server.py` are a
  local-only labeler and portable server for the preview slice.
- `open_source/assets/` contains visual assets used by the homepage and Wiki;
  review those files together with the paper figures before enabling the pages
  in a public deployment.

## Keep private

- `api_key.txt`, tunnel commands, SSH host details, and all `*.log` files.
- `vlm_dataset/`, `vlm_dataset_night/`, and `vlm_dataset_night_150/` until a
  privacy and map-license review is complete.
- `open_source/examples/` contains the maintained offline POI example and its
  small bundled assets. The old one-command demo remains removed.
- `chats/`, `tmp/`, `patent/`, generated submission archives, and raw video or
  GPS source directories outside this workspace.
- Python bytecode, screenshot smoke tests, and other generated verification
  artifacts are not release inputs (for example `open_source/**/__pycache__/`,
  `open_source/*_desktop.png`, and `tmp_chrome_verify/`).

## Evidence snapshot

The paper can report the existing results without shipping the raw recordings:

| Split / model | Samples | Action accuracy | Strict target | Relaxed target |
|---|---:|---:|---:|---:|
| Night / GPT-5.5 | 150 | 138/150 (92.0%) | 97/150 (64.7%) | 100/150 (66.7%) |
| Night / Qwen-H800 | 150 | 137/150 (91.3%) | 118/150 (78.7%) | 118/150 (78.7%) |

These are offline frame-level decision metrics. They are not closed-loop robot
success rates, route completion rates, or a claim of superiority over a
traditional navigation stack.

## Before a public push

1. Confirm the MIT code license and the intended CC BY content license.
2. Clear the redacted demo image, homepage/Wiki visual assets, and any future
   figure/data assets.
3. Run `open_source/tools/sanitize_release.py` on any candidate JSONL files.
4. Run a secret scan and verify that no API key, endpoint credential, raw GPS,
   or absolute user path remains in the staged tree.
5. Add the final publication URL in `open_source/PUBLICATION.md`.

The static release pages are [open_source/index.html](open_source/index.html)
and [open_source/wiki.html](open_source/wiki.html). The exact path lists are
kept in [open_source/release_manifest.json](open_source/release_manifest.json).
