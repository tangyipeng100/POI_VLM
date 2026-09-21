# POI-VLM

POI-VLM is a compact interface for route-aware local decisions in outdoor
robotics. A drivable-area mask becomes a small set of numbered polygon POIs;
a route-progress cue adds direction; a vision-language model returns one
structured action that can be inspected by a person and scored frame by frame.

## Project page

**[Open the POI-VLM project page](https://tangyipeng100.github.io/POI_VLM/)**

The page presents the method, continuous two-panel decision trace, narrated
paper presentation, selected figures, dataset slice, annotation tool, and
runnable examples in one visual overview.

## Release package

The canonical open-source documentation is
[`open_source/README.md`](open_source/README.md). It contains the same release
scope shown on the project page, including:

- polygon POI generation and the bundled offline example;
- the OpenAI-compatible VLM inference bridge and dry-run commands;
- the coordinate-free Night-150 metadata slice;
- the local annotation application;
- the current paper snapshot, figures, evaluation metrics, and release boundary.

The visual source pages are [`open_source/index.html`](open_source/index.html)
and [`open_source/wiki.html`](open_source/wiki.html). The `open_source/`
directory is the self-contained publishable boundary for this repository.

## Repository layout

- `open_source/`: public release package and GitHub Pages source.
- `paper/`: editable paper sources retained for research work.
- `scripts/`: dataset preparation and evaluation utilities.
- `annotation_app/`: local annotation application source.

The package deliberately excludes API keys, raw recordings, exact GPS traces,
provider-owned map tiles, raw model payloads, and private working records.
Review image consent, map-provider terms, and publication status before
redistributing the media or manuscript. See
[`OPEN_SOURCE_RELEASE.md`](OPEN_SOURCE_RELEASE.md) for the release map.

## License

Code is released under the MIT License. Media, figures, and manuscript content
remain subject to the terms described in
[`open_source/LICENSE_POLICY.md`](open_source/LICENSE_POLICY.md) until their
publication and image-rights review is complete.
