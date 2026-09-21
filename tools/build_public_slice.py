#!/usr/bin/env python3
"""Create a coordinate-free public slice from the night 150-frame run."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def public_route(route: dict) -> dict:
    allowed = ("total_m", "passed_m", "remaining_m", "heading_deg", "route_source")
    return {key: route[key] for key in allowed if key in route}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview-count", type=int, default=18)
    args = parser.parse_args()

    samples = rows(args.source / "samples.jsonl")
    predictions = {row.get("sample_id"): row for row in rows(args.source / "action_predictions.jsonl")}
    out = args.output
    preview = out / "preview"
    preview.mkdir(parents=True, exist_ok=True)
    for old in preview.glob("*.jpg"):
        old.unlink()

    # Keep the full 150-frame metadata sequence, while shipping a small visual subset.
    step = max(1, len(samples) // max(1, args.preview_count))
    selected = samples[::step][: args.preview_count]
    # Keep the frame discussed in the paper audit visible in the portable slice.
    highlighted = next((row for row in samples if row.get("frame_index") == 258), None)
    if highlighted and highlighted not in selected:
        selected[-1] = highlighted
    selected_ids = {row["sample_id"] for row in selected}
    for row in selected:
        source_image = Path(row.get("front_poi_image", ""))
        if not source_image.is_file():
            source_image = args.source / "generated_front_poi" / f"{row['sample_id']}_poi.jpg"
        if source_image.is_file():
            shutil.copy2(source_image, preview / f"{row['sample_id']}_poi.jpg")

    public_samples = []
    for row in samples:
        clean = {
            "sample_id": row["sample_id"],
            "frame_index": row.get("frame_index"),
            "pois": row.get("pois", []),
            "route": public_route(row.get("route", {})),
            "visual_status": "preview" if row["sample_id"] in selected_ids else "metadata_only",
        }
        if row["sample_id"] in selected_ids:
            clean["front_poi_image"] = f"preview/{row['sample_id']}_poi.jpg"
        public_samples.append(clean)

    public_predictions = []
    for sample in public_samples:
        pred = predictions.get(sample["sample_id"], {})
        public_predictions.append(
            {
                "sample_id": sample["sample_id"],
                "label_action": pred.get("label_action"),
                "label_poi_number": pred.get("label_poi_number"),
                "label_poi_numbers": pred.get("label_poi_numbers", []),
                "pred_action": pred.get("pred_action"),
                "pred_poi_number": pred.get("pred_poi_number"),
                "pred_poi_numbers": pred.get("pred_poi_numbers", []),
                "action_correct": pred.get("action_correct"),
                "target_correct": pred.get("target_correct"),
                "relaxed_action_correct": pred.get("relaxed_action_correct"),
                "relaxed_target_correct": pred.get("relaxed_target_correct"),
            }
        )

    out.mkdir(parents=True, exist_ok=True)
    (out / "samples.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in public_samples) + "\n", encoding="utf-8")
    (out / "action_predictions.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in public_predictions) + "\n", encoding="utf-8")
    summary = {
        "dataset": "night_150_coordinate_free",
        "samples": len(public_samples),
        "preview_images": len(selected),
        "route_source": "gps_track (progress only)",
        "excluded": ["raw_image", "mask_image", "GPS coordinates", "provider map tiles", "prompts", "raw model payloads"],
    }
    (out / "release_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(public_samples)} metadata rows and {len(selected)} preview images to {out}")


if __name__ == "__main__":
    main()
