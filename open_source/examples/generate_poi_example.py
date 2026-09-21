#!/usr/bin/env python3
"""Run the public POI generator on the bundled mask and save a visual result.

This example deliberately uses only the small assets shipped in this release:
one front-view image and one binary drivable-area mask. It does not need a
camera model, GPS, map provider, or network connection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2


EXAMPLES_ROOT = Path(__file__).resolve().parent
RELEASE_ROOT = EXAMPLES_ROOT.parent
if str(RELEASE_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_ROOT))

from poi_core import PolygonPOIGenerator, draw_poi_overlay  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=EXAMPLES_ROOT / "assets" / "sample_front_frame.jpg")
    parser.add_argument("--mask", type=Path, default=EXAMPLES_ROOT / "assets" / "sample_drivable_mask.png")
    parser.add_argument("--output", type=Path, default=EXAMPLES_ROOT / "output" / "poi_overlay.jpg")
    parser.add_argument("--result-json", type=Path, default=EXAMPLES_ROOT / "output" / "poi_result.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    mask = cv2.imread(str(args.mask), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise SystemExit(f"Could not read image: {args.image}")
    if mask is None:
        raise SystemExit(f"Could not read mask: {args.mask}")

    height, width = image.shape[:2]
    if mask.shape[:2] != (height, width):
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)

    result = PolygonPOIGenerator(height, width).generate_pois(
        mask,
        epsilon_ratio=0.005,
        min_edges=4,
        max_edges=12,
        edge_margin=50,
        bottom_y_ratio=0.92,
        skip_bottom=True,
        nms_dist=80,
        min_edge_len=40,
        max_pois=7,
        min_pois=1,
    )
    overlay = draw_poi_overlay(image, result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.result_json.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), overlay):
        raise SystemExit(f"Could not write output: {args.output}")
    def public_path(path: Path) -> str:
        try:
            return path.resolve().relative_to(RELEASE_ROOT.resolve()).as_posix()
        except ValueError:
            return path.name

    serializable = {
        "image": public_path(args.image),
        "mask": public_path(args.mask),
        "image_size": {"width": width, "height": height},
        "pois": result["pois"],
        "polygon": result["polygon"],
        "edges": result["edges"],
    }
    args.result_json.write_text(json.dumps(serializable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"POIs: {len(result['pois'])}")
    for point in result["pois"]:
        print(f"  POI {point['number']}: ({point['x']}, {point['y']}) {point['edge_type']}")
    print(f"Overlay: {args.output}")
    print(f"Result:  {args.result_json}")


if __name__ == "__main__":
    main()
