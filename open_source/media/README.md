# Release media

- `poi_vlm_continuous_decisions.mp4`: 18.75 seconds, 150 ordered frames at
  8 fps, 1280 x 720. Every frame keeps the actual two-panel input visible:
  front-view POIs plus the corresponding top-down route view. This file is
  review-required because the route panel contains rendered map context.
- `poi_vlm_presentation_narrated_subtitled.mp4`: 9:18, 1280 x 720 H.264 video,
  AAC audio, with the original narration and subtitles retained.

Posters are provided for fast page loading. The continuous renderer is
reproducible with `../tools/build_decision_video.py` when the full frame source
is available. Because the two-panel video includes rendered route/map context,
keep it in the review tier until image, privacy, and map-provider checks are
