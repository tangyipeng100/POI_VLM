#!/usr/bin/env python3
"""Create a contact sheet from generated question images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a question-image contact sheet.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--thumb-width", type=int, default=520)
    parser.add_argument("--cols", type=int, default=4)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resize_width(image: np.ndarray, width: int) -> np.ndarray:
    h, w = image.shape[:2]
    return cv2.resize(image, (width, int(round(h * width / w))), interpolation=cv2.INTER_AREA)


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.manifest)
    thumbs: list[np.ndarray] = []
    for row in rows:
        image = cv2.imread(row["question_image"])
        if image is None:
            continue
        image = resize_width(image, args.thumb_width)
        banner = np.full((54, args.thumb_width, 3), 255, dtype=np.uint8)
        gps_frame = (row.get("gps") or {}).get("frame", "")
        label = f"{row['sample_id']} | POIs={len(row.get('pois', []))} | gps={gps_frame}"
        cv2.putText(
            banner,
            label[:95],
            (12, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (20, 20, 20),
            2,
            cv2.LINE_AA,
        )
        thumbs.append(np.vstack([banner, image]))

    if not thumbs:
        raise SystemExit("No question images loaded.")

    max_h = max(t.shape[0] for t in thumbs)
    padded: list[np.ndarray] = []
    for thumb in thumbs:
        canvas = np.full((max_h, args.thumb_width, 3), 255, dtype=np.uint8)
        canvas[: thumb.shape[0], :] = thumb
        padded.append(canvas)

    sheet_rows: list[np.ndarray] = []
    for i in range(0, len(padded), args.cols):
        chunk = padded[i : i + args.cols]
        while len(chunk) < args.cols:
            chunk.append(np.full_like(padded[0], 255))
        sheet_rows.append(np.hstack(chunk))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), np.vstack(sheet_rows))
    print(args.output)


if __name__ == "__main__":
    main()
