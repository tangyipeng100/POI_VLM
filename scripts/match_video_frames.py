#!/usr/bin/env python3
"""Find approximate source video frames for extracted debug_raw images."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

DEFAULT_DATA_ROOT = Path(r"C:\working_document\2025\录制户外视频gps")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Match extracted images to video frames.")
    parser.add_argument(
        "--video",
        type=Path,
        default=DEFAULT_DATA_ROOT / "video_20251229_115727.mp4",
    )
    parser.add_argument("images", type=Path, nargs="*")
    return parser.parse_args()


def imread_unicode(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def signature(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (96, 54), interpolation=cv2.INTER_AREA).astype(np.int16)


def main() -> None:
    args = parse_args()
    image_paths = args.images
    if not image_paths:
        image_paths = [
            DEFAULT_DATA_ROOT / "out_frames" / "input" / "debug_raw_0055.jpg",
            DEFAULT_DATA_ROOT / "out_frames" / "input" / "debug_raw_0683.jpg",
            DEFAULT_DATA_ROOT / "out_frames" / "input" / "debug_raw_0865.jpg",
        ]

    targets = []
    for image_path in image_paths:
        image = imread_unicode(image_path)
        if image is None:
            raise RuntimeError(f"Failed to read {image_path}")
        targets.append((image_path.stem, signature(image)))

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open {args.video}")

    print(
        "video_frames",
        int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "fps",
        cap.get(cv2.CAP_PROP_FPS),
    )
    best = {name: (float("inf"), None) for name, _ in targets}
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_sig = signature(frame)
        for name, target_sig in targets:
            score = float(np.mean(np.abs(frame_sig - target_sig)))
            if score < best[name][0]:
                best[name] = (score, frame_idx)
        frame_idx += 1
    cap.release()

    for name, (score, frame_idx) in best.items():
        print(f"{name},best_video_frame={frame_idx},score={score:.4f}")


if __name__ == "__main__":
    main()
