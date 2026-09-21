# POI-VLM

POI-VLM is a route-aware, point-of-interest-guided interface for evaluating
vision-language model decisions in outdoor local navigation. A drivable-area
mask is converted into numbered polygon candidates, a top-down route cue adds
directional context, and the model returns a constrained action that can be
inspected frame by frame.

## Public release

The self-contained release package is in [`open_source/`](open_source/):

- [`open_source/index.html`](open_source/index.html): visual project homepage.
- [`open_source/wiki.html`](open_source/wiki.html): research Wiki with method,
  evidence, runnable pieces, and release boundaries.
- [`open_source/README.md`](open_source/README.md): code, POI generation, VLM
  inference bridge, annotation, paper snapshot, and evaluation notes.
- [`open_source/media/`](open_source/media/): continuous two-panel decision
  trace and narrated paper presentation.
- [`open_source/paper/`](open_source/paper/): current author manuscript and
  selected figures.

The package deliberately excludes API keys, raw recordings, exact GPS traces,
provider-owned map tiles, raw model payloads, and private working records.
Review image consent, map-provider terms, and publication status before
redistributing the media or manuscript.

## Repository layout

The parent directories retain the reusable research scripts and editable paper
sources used to assemble the public package. The publishable boundary is the
`open_source/` directory; see [`OPEN_SOURCE_RELEASE.md`](OPEN_SOURCE_RELEASE.md)
for the release map and review checklist.

## License

Code is released under the MIT License. Media, figures, and manuscript content
remain subject to the terms described in
[`open_source/LICENSE_POLICY.md`](open_source/LICENSE_POLICY.md) until their
publication and image-rights review is complete.
