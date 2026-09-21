#!/usr/bin/env python3
"""Create metadata-only JSONL artifacts for a public release.

The input files may contain exact GPS coordinates, absolute image paths, API
response identifiers, and raw model payloads. This helper keeps only the
decision metadata needed to reproduce a table or a metric.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_annotations(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and "annotations" in payload:
        payload = payload["annotations"]
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def numbers(value: Any) -> list[int]:
    if isinstance(value, list):
        source = value
    elif value is None:
        source = []
    else:
        source = [value]
    result: list[int] = []
    for item in source:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number not in result:
            result.append(number)
    return sorted(result)


def decision_from_annotation(annotation: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": annotation.get("action", "unreleased"),
        "poi_numbers": numbers(annotation.get("poi_numbers") or annotation.get("poi_number")),
        "rotate_direction": annotation.get("rotate_direction"),
        "rotate_angle_deg": annotation.get("rotate_angle_deg"),
    }


def decision_from_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": prediction.get("pred_action", "unreleased"),
        "poi_numbers": numbers(
            prediction.get("pred_poi_numbers") or prediction.get("pred_poi_number")
        ),
        "rotate_direction": prediction.get("pred_rotate_direction"),
        "rotate_angle_deg": prediction.get("pred_rotate_angle_deg"),
    }


def public_manifest_row(
    row: dict[str, Any],
    annotation: dict[str, Any] | None,
    prediction: dict[str, Any] | None,
) -> dict[str, Any]:
    width = max(float(row.get("image_width") or 1), 1.0)
    height = max(float(row.get("image_height") or 1), 1.0)
    pois = []
    for poi in row.get("pois") or []:
        try:
            number = int(poi["number"])
            x = float(poi["x"])
            y = float(poi["y"])
        except (KeyError, TypeError, ValueError):
            continue
        pois.append(
            {
                "number": number,
                "x_norm": round(max(0.0, min(1.0, x / width)), 5),
                "y_norm": round(max(0.0, min(1.0, y / height)), 5),
                "edge_type": str(poi.get("edge_type", "unknown")),
                "color": str(poi.get("color", "unknown")),
            }
        )

    route = row.get("route") or {}
    label = decision_from_annotation(annotation) if annotation else None
    pred = decision_from_prediction(prediction) if prediction else None
    public_row: dict[str, Any] = {
        "sample_id": str(row.get("sample_id", "")),
        "frame_index": int(row.get("frame_index", 0)),
        "pois": pois,
        "route_summary": {
            "passed_m": round(float(row.get("passed_m", route.get("passed_m", 0.0))), 2),
            "remaining_m": round(float(row.get("remaining_m", route.get("remaining_m", 0.0))), 2),
            "heading_deg": round(float(row.get("heading_deg", route.get("heading_deg", 0.0))), 2),
        },
        "label": label or {"action": "unreleased", "poi_numbers": [], "rotate_direction": None, "rotate_angle_deg": None},
        "prediction": pred or {"action": "unreleased", "poi_numbers": [], "rotate_direction": None, "rotate_angle_deg": None},
    }
    if prediction:
        public_row["metrics"] = {
            "action_correct": bool(prediction.get("action_correct", False)),
            "target_correct": bool(prediction.get("target_correct", False)),
            "relaxed_action_correct": bool(prediction.get("relaxed_action_correct", False)),
            "relaxed_target_correct": bool(prediction.get("relaxed_target_correct", False)),
        }
    return public_row


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strip private fields from POI-VLM JSONL artifacts.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, default=None)
    parser.add_argument("--predictions", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_rows = load_jsonl(args.manifest)
    prediction_rows = {str(row.get("sample_id")): row for row in load_jsonl(args.predictions)}
    annotations = load_annotations(args.annotations)

    public_rows = [
        public_manifest_row(
            row,
            annotations.get(str(row.get("sample_id"))),
            prediction_rows.get(str(row.get("sample_id"))),
        )
        for row in manifest_rows
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "manifest_public.jsonl", public_rows)
    report = {
        "input_manifest_rows": len(manifest_rows),
        "output_rows": len(public_rows),
        "annotations_joined": sum(1 for row in public_rows if row["label"]["action"] != "unreleased"),
        "predictions_joined": sum(1 for row in public_rows if row["prediction"]["action"] != "unreleased"),
        "removed_fields": [
            "gps coordinates",
            "absolute image paths",
            "raw prompts",
            "provider response IDs",
            "raw model payloads",
        ],
    }
    (args.output_dir / "sanitization_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
