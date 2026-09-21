# Night-150 coordinate-free slice

This is the public, coordinate-free slice used for the continuous decision
trace. It contains 150 ordered frame records from the GPS-track route build,
the numbered POIs, route progress, and model-vs-label decisions. Eighteen
front-view POI images are included as a visual preview, including the audited
`frame_000258` sample. The remaining records are metadata-only so the release
stays small and avoids publishing raw locations or map tiles.

The values in `route` are directional progress signals, not a navigable map.
The release intentionally excludes raw camera paths, segmentation masks,
latitude/longitude, provider map imagery, prompts, API responses, and tracking
identifiers. Image consent and third-party image rights still need a final
human review before public hosting.

Files:

- `samples.jsonl`: ordered 150-frame metadata and POI candidates.
- `action_predictions.jsonl`: sanitized labels, predictions, and score flags.
- `preview/`: 18 front-view POI images for inspection and annotation demos.
- `release_summary.json`: machine-readable scope note.
