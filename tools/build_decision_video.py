#!/usr/bin/env python3
"""Build a continuous POI decision trace video from a dataset slice.

When the source manifest has ``question_image`` records, the renderer keeps
the complete two-panel model input: front-view POIs on the left and the
corresponding top-down route view on the right. A coordinate-free abstract
fallback is used only for metadata-only public slices.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resolve_image(dataset_root: Path, row: dict) -> Path:
    candidate = Path(row.get("front_poi_image", ""))
    if candidate.is_file():
        return candidate
    if not candidate.is_absolute() and (dataset_root / candidate).is_file():
        return dataset_root / candidate
    return dataset_root / "generated_front_poi" / f"{row['sample_id']}_poi.jpg"


def resolve_question_image(dataset_root: Path, row: dict) -> Path:
    candidate = Path(row.get("question_image", ""))
    if candidate.is_file():
        return candidate
    if not candidate.is_absolute() and (dataset_root / candidate).is_file():
        return dataset_root / candidate
    return dataset_root / "question_images" / f"{row['sample_id']}_question.jpg"


def fit_image(image: np.ndarray, width: int, height: int) -> np.ndarray:
    canvas = np.full((height, width, 3), (20, 26, 36), dtype=np.uint8)
    if image is None:
        return canvas
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(image, (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    x = (width - resized.shape[1]) // 2
    y = (height - resized.shape[0]) // 2
    canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return canvas


def text(image: np.ndarray, value: str, origin: tuple[int, int], size: float = 0.7, color=(235, 241, 248), thickness=1) -> None:
    cv2.putText(image, value, origin, cv2.FONT_HERSHEY_SIMPLEX, size, color, thickness, cv2.LINE_AA)


def route_panel(row: dict, width: int, height: int) -> np.ndarray:
    panel = np.full((height, width, 3), (23, 31, 44), dtype=np.uint8)
    cv2.rectangle(panel, (0, 0), (width - 1, height - 1), (63, 83, 109), 1)
    text(panel, "ABSTRACT ROUTE STATE", (28, 46), 0.65, (130, 213, 220), 2)
    text(panel, "coordinates withheld", (28, 72), 0.48, (153, 166, 185), 1)

    route = row.get("route", {})
    total = float(route.get("total_m") or 1)
    passed = max(0.0, min(total, float(route.get("passed_m") or 0)))
    progress = passed / total
    # The same abstract path is used for every frame; only the progress marker moves.
    points = np.array([[54, 250], [140, 220], [208, 250], [275, 195], [346, 225], [width - 58, 154]], dtype=np.int32)
    for a, b in zip(points[:-1], points[1:]):
        cv2.line(panel, tuple(a), tuple(b), (69, 86, 106), 8, cv2.LINE_AA)
    cv2.polylines(panel, [points], False, (73, 150, 255), 4, cv2.LINE_AA)
    traveled = max(1, min(len(points) - 1, int(progress * (len(points) - 1))))
    cv2.polylines(panel, [points[: traveled + 1]], False, (112, 121, 135), 8, cv2.LINE_AA)
    cv2.polylines(panel, [points[: traveled + 1]], False, (180, 188, 198), 4, cv2.LINE_AA)
    seg = min(len(points) - 2, int(progress * (len(points) - 1)))
    local = progress * (len(points) - 1) - seg
    marker = (int(points[seg][0] * (1 - local) + points[seg + 1][0] * local), int(points[seg][1] * (1 - local) + points[seg + 1][1] * local))
    cv2.circle(panel, marker, 12, (37, 45, 58), -1)
    cv2.circle(panel, marker, 8, (244, 165, 62), -1)
    cv2.circle(panel, marker, 8, (255, 255, 255), 2)
    text(panel, "START", (38, 300), 0.45, (182, 193, 209), 1)
    text(panel, "GOAL", (width - 92, 120), 0.45, (255, 188, 94), 1)
    cv2.circle(panel, (47, 266), 5, (72, 210, 133), -1)
    cv2.circle(panel, (width - 49, 145), 5, (244, 93, 93), -1)

    text(panel, f"progress  {progress * 100:05.1f}%", (28, 370), 0.72, (238, 242, 248), 2)
    text(panel, f"passed    {passed:05.1f} m", (28, 405), 0.58, (170, 181, 198), 1)
    text(panel, f"remaining {max(0.0, total - passed):05.1f} m", (28, 434), 0.58, (170, 181, 198), 1)
    text(panel, f"heading   {float(route.get('heading_deg') or 0):05.1f} deg", (28, 463), 0.58, (170, 181, 198), 1)
    cv2.line(panel, (28, 500), (width - 28, 500), (58, 73, 93), 1)
    text(panel, "The route is a directional cue.", (28, 544), 0.55, (130, 213, 220), 1)
    text(panel, "The front view supplies feasible POIs.", (28, 572), 0.55, (170, 181, 198), 1)
    return panel


def render_frame(row: dict, prediction: dict | None, frame_number: int, total_frames: int, width: int, height: int) -> np.ndarray:
    canvas = np.full((height, width, 3), (12, 17, 25), dtype=np.uint8)
    text(canvas, "POI / VLM", (34, 42), 0.8, (244, 165, 62), 2)
    text(canvas, "continuous decision trace", (188, 42), 0.66, (232, 238, 246), 1)
    text(canvas, f"FRAME {frame_number:03d} / {total_frames:03d}", (width - 238, 42), 0.5, (157, 170, 189), 1)

    dataset_root = Path(row.get("_dataset_root", "."))
    question = cv2.imread(str(resolve_question_image(dataset_root, row)))
    if question is not None:
        # Keep both panels visible at their native aspect ratio. The source
        # question image is deliberately wide, so it is letterboxed rather
        # than cropped at the front/map boundary.
        image_area = fit_image(question, width - 56, height - 112)
        image_x = (width - image_area.shape[1]) // 2
        image_y = 68 + (height - 112 - image_area.shape[0]) // 2
        canvas[image_y : image_y + image_area.shape[0], image_x : image_x + image_area.shape[1]] = image_area
        cv2.rectangle(canvas, (image_x, image_y), (image_x + image_area.shape[1] - 1, image_y + image_area.shape[0] - 1), (80, 102, 129), 1)
        text(canvas, "MODEL INPUT / FRONT POIs + TOP-DOWN ROUTE", (34, 61), 0.47, (130, 213, 220), 1)
    else:
        left_w, panel_w = int(width * 0.67), width - int(width * 0.67) - 52
        image_path = resolve_image(dataset_root, row)
        image = cv2.imread(str(image_path))
        left = fit_image(image, left_w, height - 108)
        canvas[74 : 74 + left.shape[0], 28 : 28 + left.shape[1]] = left
        cv2.rectangle(canvas, (28, 74), (28 + left_w - 1, height - 35), (80, 102, 129), 1)
        panel = route_panel(row, panel_w, height - 108)
        canvas[74 : 74 + panel.shape[0], 28 + left_w + 24 : 28 + left_w + 24 + panel.shape[1]] = panel

    pred = prediction or {}
    action = pred.get("pred_action") or pred.get("action") or "unavailable"
    poi = pred.get("pred_poi_number") or pred.get("poi_number")
    target = f"POI {poi}" if poi not in (None, "", 0) else "none"
    correct = pred.get("action_correct")
    correctness = "match" if correct is True else "review" if correct is False else "not scored"
    color = (112, 210, 133) if correct is True else (244, 165, 62) if correct is False else (170, 181, 198)
    base_x = 28
    label_y = height - 20
    text(canvas, f"ACTION  {action}", (base_x, label_y), 0.6, (232, 238, 246), 2)
    text(canvas, f"TARGET  {target}", (base_x + 245, label_y), 0.6, (130, 213, 220), 2)
    text(canvas, f"LABEL  {correctness}", (base_x + 470, label_y), 0.6, color, 2)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--fps", type=float, default=8.0)
    args = parser.parse_args()

    rows = load_jsonl(args.dataset_root / "samples.jsonl")
    predictions = {}
    pred_path = args.dataset_root / "action_predictions.jsonl"
    if pred_path.exists():
        predictions = {row.get("sample_id"): row for row in load_jsonl(pred_path)}
    # A public metadata slice may contain only a visual preview subset. Keep
    # those rows usable instead of silently emitting black frames.
    visual_rows = [row for row in rows if resolve_image(args.dataset_root, row).is_file()]
    if visual_rows and len(visual_rows) < len(rows):
        rows = visual_rows
    rows = rows[args.start_index : args.start_index + args.count]
    if not rows:
        raise SystemExit("No samples selected")
    for row in rows:
        row["_dataset_root"] = str(args.dataset_root)

    width, height = 1280, 720
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer: {args.output}")
    try:
        for index, row in enumerate(rows):
            frame = render_frame(row, predictions.get(row.get("sample_id")), index + 1, len(rows), width, height)
            writer.write(frame)
    finally:
        writer.release()

    poster = args.output.with_name(args.output.stem + "_poster.jpg")
    cap = cv2.VideoCapture(str(args.output))
    ok, first = cap.read()
    cap.release()
    if ok:
        cv2.imwrite(str(poster), first, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"wrote {args.output} ({len(rows)} frames at {args.fps:g} fps)")
    print(f"poster {poster}")


if __name__ == "__main__":
    main()
