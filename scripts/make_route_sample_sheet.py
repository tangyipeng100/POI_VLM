#!/usr/bin/env python3
"""Create a contact sheet and coordinate CSV from a samples.jsonl manifest."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np


DEFAULT_MANIFEST = Path(r"C:\Users\51745\Documents\poi plan\vlm_dataset\samples.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Make route-map sample overview.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--thumb-size", type=int, default=360)
    parser.add_argument("--cols", type=int, default=4)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_coordinate_csv(rows: list[dict], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sample_id",
                "frame_index",
                "gps_frame",
                "longitude_wgs84",
                "latitude_wgs84",
                "longitude_gcj02",
                "latitude_gcj02",
                "passed_m",
                "remaining_m",
                "heading_deg",
                "distance_to_route_m",
                "map_image",
            ],
        )
        writer.writeheader()
        for row in rows:
            gps = row.get("gps") or {}
            route = row.get("route") or {}
            writer.writerow(
                {
                    "sample_id": row["sample_id"],
                    "frame_index": row["frame_index"],
                    "gps_frame": gps.get("frame"),
                    "longitude_wgs84": gps.get("longitude_wgs84"),
                    "latitude_wgs84": gps.get("latitude_wgs84"),
                    "longitude_gcj02": route.get("current_lng_gcj02")
                    or gps.get("longitude_gcj02"),
                    "latitude_gcj02": route.get("current_lat_gcj02")
                    or gps.get("latitude_gcj02"),
                    "passed_m": route.get("passed_m"),
                    "remaining_m": route.get("remaining_m"),
                    "heading_deg": route.get("heading_deg"),
                    "distance_to_route_m": route.get("distance_to_route_m"),
                    "map_image": row.get("map_image"),
                }
            )


def make_card(row: dict, thumb_size: int) -> np.ndarray | None:
    image = cv2.imread(row["map_image"])
    if image is None:
        return None

    label_h = 58
    image = cv2.resize(image, (thumb_size, thumb_size), interpolation=cv2.INTER_AREA)
    card = np.full((thumb_size + label_h, thumb_size, 3), 255, np.uint8)
    route = row.get("route") or {}
    gps = row.get("gps") or {}

    title = f"{row['sample_id']}  gps={gps.get('frame')}"
    stats = (
        f"pass {route.get('passed_m', 0):.0f}m "
        f"rem {route.get('remaining_m', 0):.0f}m "
        f"hdg {route.get('heading_deg', 0):.1f}"
    )
    cv2.putText(
        card,
        title,
        (8, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        card,
        stats,
        (8, 47),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (20, 20, 20),
        1,
        cv2.LINE_AA,
    )
    card[label_h:, :] = image
    return card


def write_sheet(rows: list[dict], output_path: Path, thumb_size: int, cols: int) -> None:
    cards = [card for row in rows if (card := make_card(row, thumb_size)) is not None]
    if not cards:
        raise RuntimeError("No map images could be loaded.")

    gap = 12
    rows_count = math.ceil(len(cards) / cols)
    card_h, card_w = cards[0].shape[:2]
    sheet_h = rows_count * card_h + (rows_count - 1) * gap
    sheet_w = cols * card_w + (cols - 1) * gap
    sheet = np.full((sheet_h, sheet_w, 3), 238, np.uint8)

    for idx, card in enumerate(cards):
        y = (idx // cols) * (card_h + gap)
        x = (idx % cols) * (card_w + gap)
        sheet[y : y + card_h, x : x + card_w] = card

    cv2.imwrite(str(output_path), sheet)


def main() -> None:
    args = parse_args()
    rows = load_rows(args.manifest)
    output_root = args.manifest.parent
    csv_path = output_root / "route_coordinate_samples.csv"
    sheet_path = output_root / "route_map_samples_sheet.jpg"

    write_coordinate_csv(rows, csv_path)
    write_sheet(rows, sheet_path, args.thumb_size, args.cols)

    print(f"CSV:   {csv_path}")
    print(f"Sheet: {sheet_path}")


if __name__ == "__main__":
    main()
