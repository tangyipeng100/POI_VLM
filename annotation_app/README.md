# Annotation app

This is the browser-based labeler used to review POI decisions. It supports
single or multiple POI targets, rotate/skip labels, confidence, notes, sample
navigation, zoom, keyboard shortcuts, and CSV export.

From the release root, run:

```powershell
python annotation_server.py
```

Then open `http://127.0.0.1:8765/`. The default release dataset is the
coordinate-free night-150 preview slice. Pass `--dataset-dir` to review a
local dataset with the same `samples.jsonl` shape and image paths inside that
directory. Paths that escape the dataset directory are rejected deliberately.
The server writes annotation files next to that dataset; no network or API key
is required.
