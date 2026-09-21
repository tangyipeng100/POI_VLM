#!/usr/bin/env python3
"""
Build VLM multiple-choice samples from front-view POI outputs and an Amap route.

The script keeps the original POI project untouched. It re-runs the polygon POI
generator to recover structured POI metadata, pairs that metadata with the
existing annotated front image and Amap overview image, and writes a JSONL
manifest that can be sent to a VLM later.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests


DEFAULT_DATA_ROOT = Path(os.environ.get("POI_VLM_DATA_ROOT", "data"))
DEFAULT_POI_GEN_ROOT = Path(os.environ.get("POI_VLM_POI_GEN_ROOT", "poi_gen"))
DEFAULT_MAP_IMAGE = Path(os.environ.get("POI_VLM_MAP_IMAGE", "assets/route.png"))
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("POI_VLM_OUTPUT_ROOT", "vlm_dataset"))
# Amap coordinates are intentionally not bundled. Pass --route-start/--route-end
# when using the optional Amap adapter; GPS-track mode does not need them.
DEFAULT_ROUTE_START_GCJ = (0.0, 0.0)
DEFAULT_ROUTE_END_GCJ = (0.0, 0.0)

POI_PARAMS = {
    "epsilon_ratio": 0.005,
    "min_edges": 6,
    "max_edges": 12,
    "edge_margin": 50,
    "bottom_y_ratio": 0.92,
    "skip_bottom": True,
    "nms_dist": 80,
    "min_edge_len": 120,
    "max_pois": 7,
    "min_pois": 6,
}

COLOR_NAMES = {
    "vanishing": "cyan",
    "top": "yellow",
    "left": "red",
    "right": "purple",
    "bottom": "gray",
}

WGS84_A = 6378245.0
WGS84_EE = 0.00669342162296594323
WGS84_PI = math.pi


def parse_lnglat(text: str) -> tuple[float, float]:
    lng, lat = text.split(",", 1)
    return float(lng), float(lat)


def out_of_china(lng: float, lat: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def transform_lat(lng: float, lat: float) -> float:
    ret = (
        -100.0
        + 2.0 * lng
        + 3.0 * lat
        + 0.2 * lat * lat
        + 0.1 * lng * lat
        + 0.2 * math.sqrt(abs(lng))
    )
    ret += (
        20.0 * math.sin(6.0 * lng * WGS84_PI)
        + 20.0 * math.sin(2.0 * lng * WGS84_PI)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(lat * WGS84_PI)
        + 40.0 * math.sin(lat / 3.0 * WGS84_PI)
    ) * 2.0 / 3.0
    ret += (
        160.0 * math.sin(lat / 12.0 * WGS84_PI)
        + 320 * math.sin(lat * WGS84_PI / 30.0)
    ) * 2.0 / 3.0
    return ret


def transform_lng(lng: float, lat: float) -> float:
    ret = (
        300.0
        + lng
        + 2.0 * lat
        + 0.1 * lng * lng
        + 0.1 * lng * lat
        + 0.1 * math.sqrt(abs(lng))
    )
    ret += (
        20.0 * math.sin(6.0 * lng * WGS84_PI)
        + 20.0 * math.sin(2.0 * lng * WGS84_PI)
    ) * 2.0 / 3.0
    ret += (
        20.0 * math.sin(lng * WGS84_PI)
        + 40.0 * math.sin(lng / 3.0 * WGS84_PI)
    ) * 2.0 / 3.0
    ret += (
        150.0 * math.sin(lng / 12.0 * WGS84_PI)
        + 300.0 * math.sin(lng / 30.0 * WGS84_PI)
    ) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    if out_of_china(lng, lat):
        return lng, lat
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * WGS84_PI
    magic = math.sin(radlat)
    magic = 1 - WGS84_EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / (
        (WGS84_A * (1 - WGS84_EE)) / (magic * sqrtmagic) * WGS84_PI
    )
    dlng = (dlng * 180.0) / (
        WGS84_A / sqrtmagic * math.cos(radlat) * WGS84_PI
    )
    return lng + dlng, lat + dlat


def lonlat_to_xy_m(
    lng: float, lat: float, ref_lng: float, ref_lat: float
) -> tuple[float, float]:
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lng = meters_per_deg_lat * math.cos(math.radians(ref_lat))
    return (lng - ref_lng) * meters_per_deg_lng, (lat - ref_lat) * meters_per_deg_lat


def xy_m_to_lonlat(
    x: float, y: float, ref_lng: float, ref_lat: float
) -> tuple[float, float]:
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lng = meters_per_deg_lat * math.cos(math.radians(ref_lat))
    return ref_lng + x / meters_per_deg_lng, ref_lat + y / meters_per_deg_lat


def lonlat_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    ref_lng = (a[0] + b[0]) / 2.0
    ref_lat = (a[1] + b[1]) / 2.0
    ax, ay = lonlat_to_xy_m(a[0], a[1], ref_lng, ref_lat)
    bx, by = lonlat_to_xy_m(b[0], b[1], ref_lng, ref_lat)
    return math.hypot(ax - bx, ay - by)


def path_distance_m(points: list[tuple[float, float]]) -> float:
    return sum(lonlat_distance_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def mercator_xy(lng: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, 85.0511287798), -85.0511287798)
    x = lng * 20037508.34 / 180.0
    y = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)) * 20037508.34 / math.pi
    return x, y


def lonlat_to_pixel(
    lng: float,
    lat: float,
    center_lng: float,
    center_lat: float,
    zoom: int,
    width: int,
    height: int,
) -> tuple[int, int]:
    center_x, center_y = mercator_xy(center_lng, center_lat)
    point_x, point_y = mercator_xy(lng, lat)
    resolution = 40075016.68 / (256 * (2**zoom))
    px = width / 2.0 + (point_x - center_x) / resolution
    py = height / 2.0 - (point_y - center_y) / resolution
    return int(round(px)), int(round(py))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    ref_lng = (a[0] + b[0]) / 2.0
    ref_lat = (a[1] + b[1]) / 2.0
    ax, ay = lonlat_to_xy_m(a[0], a[1], ref_lng, ref_lat)
    bx, by = lonlat_to_xy_m(b[0], b[1], ref_lng, ref_lat)
    dx = bx - ax
    dy = by - ay
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


@dataclass(frozen=True)
class DataPaths:
    data_root: Path
    input_dir: Path
    poi_image_dir: Path
    map_image: Path
    gps_csv: Path
    output_root: Path
    question_dir: Path
    route_map_dir: Path
    manifest_path: Path
    review_html_path: Path
    labels_template_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build front-view POI + Amap VLM decision samples."
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--poi-gen-root", type=Path, default=DEFAULT_POI_GEN_ROOT)
    parser.add_argument("--map-image", type=Path, default=DEFAULT_MAP_IMAGE)
    parser.add_argument("--gps-csv", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--amap-key-env",
        default="AMAP_KEY",
        help="Environment variable containing the Gaode/Amap web service key.",
    )
    parser.add_argument(
        "--route-start",
        default=f"{DEFAULT_ROUTE_START_GCJ[0]},{DEFAULT_ROUTE_START_GCJ[1]}",
        help="Route start in GCJ-02 as lng,lat.",
    )
    parser.add_argument(
        "--route-end",
        default=f"{DEFAULT_ROUTE_END_GCJ[0]},{DEFAULT_ROUTE_END_GCJ[1]}",
        help="Route end in GCJ-02 as lng,lat.",
    )
    parser.add_argument("--map-zoom", type=int, default=18)
    parser.add_argument("--map-lookahead-m", type=float, default=15.0)
    parser.add_argument(
        "--route-source",
        choices=["amap", "gps_track"],
        default="amap",
        help="Use Amap planning or the recorded GPS track as the overview route.",
    )
    parser.add_argument(
        "--dynamic-route-map",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Draw per-frame route maps with current GPS position and heading. "
            "Requires the Gaode/Amap key env var; otherwise falls back to --map-image."
        ),
    )
    parser.add_argument(
        "--gps-frame-scale",
        type=float,
        default=4.0,
        help=(
            "Map debug_raw_N to the GPS/video frame as N * scale + offset. "
            "Current extraction matches video frame = debug_raw index * 4."
        ),
    )
    parser.add_argument("--gps-frame-offset", type=float, default=0.0)
    parser.add_argument("--start-frame", type=int, default=None)
    parser.add_argument("--end-frame", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--stride",
        type=int,
        default=1,
        help="Use every Nth frame after range filtering.",
    )
    parser.add_argument(
        "--sample-count",
        type=int,
        default=None,
        help="Evenly sample this many frames after range filtering, including endpoints when possible.",
    )
    parser.add_argument(
        "--include-frames",
        type=int,
        nargs="*",
        default=[],
        help="Force specific frame indices into the sampled set, replacing nearby non-forced samples if needed.",
    )
    parser.add_argument(
        "--desired-direction",
        choices=["left", "straight", "right"],
        default="straight",
        help=(
            "Only used to create a weak heuristic answer for quick smoke tests. "
            "Do not treat it as ground truth."
        ),
    )
    parser.add_argument(
        "--navigation-instruction",
        default=(
            "Follow the blue route on the Amap overview from marker A/current "
            "location to marker B/goal. Select the next feasible POI in the "
            "front camera view."
        ),
    )
    parser.add_argument(
        "--reuse-existing-poi-images",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Use out_frames/output/*_poi.jpg when available. The default "
            "regenerates POI images with padding so edge candidates are visible."
        ),
    )
    parser.add_argument(
        "--labels-csv",
        type=Path,
        default=None,
        help="Optional CSV with columns sample_id,answer for ground truth labels.",
    )
    return parser.parse_args()


def make_paths(args: argparse.Namespace) -> DataPaths:
    output_root = args.output_root
    gps_csv = args.gps_csv
    if gps_csv is None:
        gps_files = sorted(args.data_root.glob("gps_*.csv"))
        gps_csv = gps_files[0] if gps_files else args.data_root / "gps.csv"
    return DataPaths(
        data_root=args.data_root,
        input_dir=args.data_root / "out_frames" / "input",
        poi_image_dir=args.data_root / "out_frames" / "output",
        map_image=args.map_image,
        gps_csv=gps_csv,
        output_root=output_root,
        question_dir=output_root / "question_images",
        route_map_dir=output_root / "route_maps",
        manifest_path=output_root / "samples.jsonl",
        review_html_path=output_root / "review.html",
        labels_template_path=output_root / "labels_template.csv",
    )


def load_poi_tools(poi_gen_root: Path):
    sys.path.insert(0, str(poi_gen_root))
    from poi_polygon import PolygonPOIGenerator, cv_imread, cv_imwrite  # type: ignore

    return PolygonPOIGenerator, cv_imread, cv_imwrite


def frame_number(path: Path) -> int:
    for pattern in (r"debug_raw_(\d+)", r"frame_(\d+)", r"(\d+)"):
        match = re.search(pattern, path.stem)
        if match:
            return int(match.group(1))
    raise ValueError(f"Cannot parse frame number from {path.name}")


def iter_image_paths(
    input_dir: Path,
    start_frame: int | None,
    end_frame: int | None,
    stride: int,
    limit: int | None,
    sample_count: int | None,
    include_frames: list[int] | None = None,
) -> list[Path]:
    paths = sorted(
        [p for p in input_dir.glob("*.jpg") if not p.stem.endswith("_poi")],
        key=frame_number,
    )
    filtered: list[Path] = []
    for path in paths:
        frame = frame_number(path)
        if start_frame is not None and frame < start_frame:
            continue
        if end_frame is not None and frame > end_frame:
            continue
        filtered.append(path)

    forced_frames = set(include_frames or [])
    forced_paths = [path for path in filtered if frame_number(path) in forced_frames]

    if sample_count is not None and sample_count > 0 and filtered:
        if sample_count >= len(filtered):
            filtered = filtered[:]
        elif sample_count == 1:
            filtered = [filtered[0]]
        else:
            last = len(filtered) - 1
            indices = [round(i * last / (sample_count - 1)) for i in range(sample_count)]
            # round can theoretically duplicate for tiny lists; preserve order and uniqueness.
            seen = set()
            filtered = [filtered[i] for i in indices if not (i in seen or seen.add(i))]
    else:
        filtered = filtered[:: max(stride, 1)]

    if forced_paths:
        by_frame = {frame_number(path): path for path in filtered}
        for path in forced_paths:
            by_frame[frame_number(path)] = path
        filtered = sorted(by_frame.values(), key=frame_number)
        if sample_count is not None and len(filtered) > sample_count:
            forced_path_frames = {frame_number(path) for path in forced_paths}
            while len(filtered) > sample_count:
                removable = [
                    path for path in filtered if frame_number(path) not in forced_path_frames
                ]
                if not removable:
                    break
                victim = min(
                    removable,
                    key=lambda path: min(
                        abs(frame_number(path) - forced_frame)
                        for forced_frame in forced_path_frames
                    ),
                )
                filtered.remove(victim)

    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def extract_drivable_mask(mask_color: np.ndarray) -> np.ndarray:
    return (
        (mask_color[:, :, 1] > 200)
        & (mask_color[:, :, 0] < 100)
        & (mask_color[:, :, 2] < 100)
    ).astype(np.uint8)


def load_gps_by_frame(gps_csv: Path) -> list[dict[str, Any]]:
    if not gps_csv.exists():
        return []
    rows: list[dict[str, Any]] = []
    with gps_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                frame = int(float(row["frame"]))
                lat_wgs = float(row["latitude"])
                lng_wgs = float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            lng_gcj, lat_gcj = wgs84_to_gcj02(lng_wgs, lat_wgs)
            rows.append(
                {
                    "frame": frame,
                    "latitude_wgs84": lat_wgs,
                    "longitude_wgs84": lng_wgs,
                    "latitude_gcj02": lat_gcj,
                    "longitude_gcj02": lng_gcj,
                }
            )
    rows.sort(key=lambda item: item["frame"])
    return rows


def nearest_gps(rows: list[dict[str, Any]], frame: int) -> dict[str, Any] | None:
    if not rows:
        return None
    lo = 0
    hi = len(rows) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid]["frame"] < frame:
            lo = mid + 1
        else:
            hi = mid
    candidates = [rows[lo]]
    if lo > 0:
        candidates.append(rows[lo - 1])
    return min(candidates, key=lambda item: abs(item["frame"] - frame))


def gps_track_points(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for row in rows:
        point = (float(row["longitude_gcj02"]), float(row["latitude_gcj02"]))
        if not points or point != points[-1]:
            points.append(point)
    return points


def fetch_amap_route(
    start: tuple[float, float],
    end: tuple[float, float],
    amap_key: str,
) -> list[tuple[float, float]]:
    url = "https://restapi.amap.com/v4/direction/bicycling"
    params = {
        "origin": f"{start[0]},{start[1]}",
        "destination": f"{end[0]},{end[1]}",
        "key": amap_key,
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"Amap route failed: {data}")

    points: list[tuple[float, float]] = []
    for step in data["data"]["paths"][0]["steps"]:
        for pair in step.get("polyline", "").split(";"):
            if not pair:
                continue
            lng, lat = pair.split(",", 1)
            point = (float(lng), float(lat))
            if not points or point != points[-1]:
                points.append(point)
    if len(points) < 2:
        raise RuntimeError("Amap route returned fewer than two points.")
    return points


def project_point_to_path(
    point: tuple[float, float],
    path: list[tuple[float, float]],
) -> dict[str, Any]:
    ref_lng, ref_lat = point
    point_xy = lonlat_to_xy_m(point[0], point[1], ref_lng, ref_lat)
    best: dict[str, Any] | None = None
    cumulative = 0.0

    for idx in range(len(path) - 1):
        a = path[idx]
        b = path[idx + 1]
        ax, ay = lonlat_to_xy_m(a[0], a[1], ref_lng, ref_lat)
        bx, by = lonlat_to_xy_m(b[0], b[1], ref_lng, ref_lat)
        vx = bx - ax
        vy = by - ay
        seg_len2 = vx * vx + vy * vy
        seg_len = math.sqrt(seg_len2)
        if seg_len2 == 0:
            t = 0.0
            proj_x, proj_y = ax, ay
        else:
            t = ((point_xy[0] - ax) * vx + (point_xy[1] - ay) * vy) / seg_len2
            t = max(0.0, min(1.0, t))
            proj_x = ax + t * vx
            proj_y = ay + t * vy
        dist = math.hypot(point_xy[0] - proj_x, point_xy[1] - proj_y)
        along = cumulative + seg_len * t
        projected = xy_m_to_lonlat(proj_x, proj_y, ref_lng, ref_lat)
        candidate = {
            "distance_to_route_m": dist,
            "segment_index": idx,
            "segment_t": t,
            "along_m": along,
            "projected": projected,
        }
        if best is None or dist < best["distance_to_route_m"]:
            best = candidate
        cumulative += seg_len

    if best is None:
        raise ValueError("Cannot project to an empty route.")
    return best


def point_at_distance(
    path: list[tuple[float, float]], target_m: float
) -> tuple[float, float]:
    if not path:
        raise ValueError("Empty path.")
    if len(path) == 1 or target_m <= 0:
        return path[0]
    cumulative = 0.0
    for idx in range(len(path) - 1):
        a = path[idx]
        b = path[idx + 1]
        seg_len = lonlat_distance_m(a, b)
        if cumulative + seg_len >= target_m:
            ratio = 0.0 if seg_len == 0 else (target_m - cumulative) / seg_len
            lng = a[0] + (b[0] - a[0]) * ratio
            lat = a[1] + (b[1] - a[1]) * ratio
            return lng, lat
        cumulative += seg_len
    return path[-1]


def split_route_at_projection(
    path: list[tuple[float, float]], projection: dict[str, Any]
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    idx = int(projection["segment_index"])
    projected = projection["projected"]
    passed = path[: idx + 1] + [projected]
    remaining = [projected] + path[idx + 1 :]
    return passed, remaining


def amap_static_map(
    paths: list[tuple[int, str, float, list[tuple[float, float]]]],
    markers: list[tuple[str, str, str, tuple[float, float]]],
    center: tuple[float, float],
    zoom: int,
    amap_key: str,
) -> np.ndarray:
    path_specs = []
    for width, color, transparency, points in paths:
        if len(points) < 2:
            continue
        coords = ";".join(f"{lng:.6f},{lat:.6f}" for lng, lat in points)
        path_specs.append(f"{width},{color},{transparency},,:{coords}")

    marker_specs = [
        f"{size},{color},{label}:{point[0]:.6f},{point[1]:.6f}"
        for size, color, label, point in markers
    ]
    params = {
        "location": f"{center[0]:.6f},{center[1]:.6f}",
        "zoom": zoom,
        "size": "1024*1024",
        "key": amap_key,
    }
    if path_specs:
        params["paths"] = "|".join(path_specs)
    if marker_specs:
        params["markers"] = "|".join(marker_specs)

    def fallback_map(reason: str) -> np.ndarray:
        print(f"[WARN] Amap static map unavailable ({reason}); using local blank map.")
        image = np.full((1024, 1024, 3), (248, 246, 240), dtype=np.uint8)
        for x in range(0, 1024, 128):
            cv2.line(image, (x, 0), (x, 1023), (232, 228, 220), 1, cv2.LINE_AA)
        for y in range(0, 1024, 128):
            cv2.line(image, (0, y), (1023, y), (232, 228, 220), 1, cv2.LINE_AA)
        cv2.putText(
            image,
            "Amap basemap fallback",
            (26, 990),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (120, 120, 120),
            2,
            cv2.LINE_AA,
        )
        return image

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                "https://restapi.amap.com/v3/staticmap", params=params, timeout=20
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 2:
                return fallback_map(str(exc))
            time.sleep(2.0 * (attempt + 1))
    else:
        assert last_error is not None
        return fallback_map(str(last_error))
    content_type = response.headers.get("Content-Type", "")
    if "image" not in content_type.lower():
        return fallback_map(f"non-image response: {response.text[:120]}")
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return fallback_map("decode failed")
    return image


def draw_heading_arrow(
    image: np.ndarray,
    center_px: tuple[int, int],
    heading_deg: float,
    length: int = 44,
) -> None:
    theta = math.radians(heading_deg)
    end_x = int(round(center_px[0] + math.sin(theta) * length))
    end_y = int(round(center_px[1] - math.cos(theta) * length))
    cv2.arrowedLine(
        image,
        center_px,
        (end_x, end_y),
        (0, 220, 0),
        5,
        cv2.LINE_AA,
        tipLength=0.32,
    )


def draw_polyline_on_map(
    image: np.ndarray,
    points: list[tuple[float, float]],
    center: tuple[float, float],
    zoom: int,
    color: tuple[int, int, int],
    thickness: int,
) -> None:
    if len(points) < 2:
        return
    h, w = image.shape[:2]
    pixels = np.array(
        [
            lonlat_to_pixel(point[0], point[1], center[0], center[1], zoom, w, h)
            for point in points
        ],
        dtype=np.int32,
    )
    cv2.polylines(image, [pixels.reshape((-1, 1, 2))], False, color, thickness, cv2.LINE_AA)


def draw_labeled_marker(
    image: np.ndarray,
    point: tuple[float, float],
    center: tuple[float, float],
    zoom: int,
    label: str,
    color: tuple[int, int, int],
) -> None:
    h, w = image.shape[:2]
    px = lonlat_to_pixel(point[0], point[1], center[0], center[1], zoom, w, h)
    cv2.circle(image, px, 15, color, -1, cv2.LINE_AA)
    cv2.circle(image, px, 15, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(
        image,
        label,
        (px[0] - 6, px[1] + 7),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )


def build_route_map(
    route_points: list[tuple[float, float]],
    current: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    amap_key: str,
    zoom: int,
    lookahead_m: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    projection = project_point_to_path(current, route_points)
    passed, remaining = split_route_at_projection(route_points, projection)
    total_m = path_distance_m(route_points)
    passed_m = projection["along_m"]
    remaining_m = max(0.0, total_m - passed_m)
    lookahead = point_at_distance(route_points, min(total_m, passed_m + lookahead_m))
    heading = bearing_deg(current, lookahead)
    center = (
        (start[0] + end[0] + current[0]) / 3.0,
        (start[1] + end[1] + current[1]) / 3.0,
    )

    image = amap_static_map([], [], center, zoom, amap_key)
    h, w = image.shape[:2]
    current_px = lonlat_to_pixel(current[0], current[1], center[0], center[1], zoom, w, h)

    draw_polyline_on_map(image, passed, center, zoom, (128, 128, 128), 5)
    draw_polyline_on_map(image, remaining, center, zoom, (255, 100, 0), 6)
    draw_labeled_marker(image, start, center, zoom, "S", (0, 255, 0))
    draw_labeled_marker(image, end, center, zoom, "E", (0, 0, 255))

    cv2.rectangle(image, (10, 10), (800, 52), (255, 255, 255), -1)
    info_text = f"Total: {total_m:.0f}m | Passed: {passed_m:.0f}m | Remaining: {remaining_m:.0f}m"
    cv2.putText(image, info_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 0, 0), 2)

    cv2.circle(image, current_px, 19, (0, 165, 255), -1)
    cv2.circle(image, current_px, 19, (0, 0, 0), 3)
    draw_heading_arrow(image, current_px, heading)

    meta = {
        "current_lng_gcj02": current[0],
        "current_lat_gcj02": current[1],
        "route_projected_lng_gcj02": projection["projected"][0],
        "route_projected_lat_gcj02": projection["projected"][1],
        "distance_to_route_m": projection["distance_to_route_m"],
        "heading_deg": heading,
        "lookahead_lng_gcj02": lookahead[0],
        "lookahead_lat_gcj02": lookahead[1],
        "total_m": total_m,
        "passed_m": passed_m,
        "remaining_m": remaining_m,
    }
    return image, meta


def silence_stdout():
    return contextlib.redirect_stdout(io.StringIO())


def make_combined_image(
    image: np.ndarray,
    clean_mask: np.ndarray,
    polygon: np.ndarray,
    pois: list[dict[str, Any]],
    ego: tuple[int, int],
    pad: int = 32,
) -> np.ndarray:
    poi_colors = {
        "top": (0, 200, 255),
        "left": (0, 0, 255),
        "right": (255, 0, 180),
        "bottom": (128, 128, 128),
        "vanishing": (255, 255, 0),
    }
    image_pad = cv2.copyMakeBorder(
        image,
        pad,
        pad,
        pad,
        pad,
        cv2.BORDER_CONSTANT,
        value=(245, 245, 245),
    )
    mask_bgr = cv2.cvtColor((clean_mask * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    mask_pad = cv2.copyMakeBorder(
        mask_bgr,
        pad,
        pad,
        pad,
        pad,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )
    combined = cv2.addWeighted(image_pad, 0.6, mask_pad, 0.4, 0)

    if len(polygon) > 0:
        pts = polygon.reshape((-1, 1, 2)).astype(np.int32) + np.array(
            [[[pad, pad]]], dtype=np.int32
        )
        cv2.polylines(combined, [pts], True, (255, 255, 255), 2)

    for idx, poi in enumerate(pois, 1):
        color = poi_colors.get(poi["edge_type"], (255, 255, 255))
        center = (int(poi["x"]) + pad, int(poi["y"]) + pad)
        cv2.circle(combined, center, 14, color, 4)
        cv2.circle(combined, center, 5, (255, 255, 255), -1)
        cv2.putText(
            combined,
            str(idx),
            (center[0] + 18, center[1] + 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    cv2.circle(combined, (ego[0] + pad, ego[1] + pad), 10, (0, 0, 255), 3)
    return combined


def resize_to_height(image: np.ndarray, target_h: int) -> np.ndarray:
    h, w = image.shape[:2]
    scale = target_h / h
    target_w = int(round(w * scale))
    return cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)


def add_title(image: np.ndarray, title: str) -> np.ndarray:
    h, w = image.shape[:2]
    title_h = 44
    out = np.full((h + title_h, w, 3), 255, dtype=np.uint8)
    out[title_h:, :] = image
    cv2.putText(
        out,
        title,
        (16, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.78,
        (30, 30, 30),
        2,
        cv2.LINE_AA,
    )
    return out


def compose_question_image(front_poi: np.ndarray, amap: np.ndarray) -> np.ndarray:
    target_h = 900
    front = add_title(resize_to_height(front_poi, target_h), "Image 1: front POI choices")
    map_img = add_title(resize_to_height(amap, target_h), "Image 2: Amap route")
    gap = 24
    h = max(front.shape[0], map_img.shape[0])
    w = front.shape[1] + gap + map_img.shape[1]
    canvas = np.full((h, w, 3), 245, dtype=np.uint8)
    canvas[: front.shape[0], : front.shape[1]] = front
    x0 = front.shape[1] + gap
    canvas[: map_img.shape[0], x0 : x0 + map_img.shape[1]] = map_img
    return canvas


def clean_poi(poi: dict[str, Any], number: int) -> dict[str, Any]:
    out = {
        "number": number,
        "x": int(poi["x"]),
        "y": int(poi["y"]),
        "edge_type": str(poi.get("edge_type", "")),
        "color": COLOR_NAMES.get(str(poi.get("edge_type", "")), "white"),
        "length": float(poi.get("length", 0.0)),
    }
    if "vertex_index" in poi:
        out["vertex_index"] = int(poi["vertex_index"])
    return out


def heuristic_answer(
    pois: list[dict[str, Any]], width: int, height: int, desired_direction: str
) -> int | None:
    if not pois:
        return None
    targets = {"left": 0.25, "straight": 0.50, "right": 0.75}
    target_x = targets[desired_direction]

    best_num: int | None = None
    best_score = math.inf
    for poi in pois:
        x_norm = poi["x"] / width
        y_norm = poi["y"] / height
        edge_bonus = -0.08 if poi["edge_type"] == "vanishing" else 0.0
        score = abs(x_norm - target_x) + 0.24 * y_norm + edge_bonus
        if score < best_score:
            best_score = score
            best_num = int(poi["number"])
    return best_num


def make_prompt(
    instruction: str,
    pois: list[dict[str, Any]],
) -> str:
    poi_lines = "\n".join(
        [
            (
                f"- POI {p['number']}: color={p['color']}, "
                f"pixel=({p['x']},{p['y']})"
            )
            for p in pois
        ]
    )
    return (
        "You are the navigation decision module of an outdoor mobile robot.\n"
        "You receive two images. Image 1 is the front camera view with numbered "
        "candidate POI points. Image 2 is an Amap overview route. In Image 2, "
        "the orange circle is the current GPS position, the green arrow is the "
        "route-following heading, gray is the passed route, blue is the remaining "
        "route, S is the start, and E is the goal.\n\n"
        f"Navigation instruction: {instruction}\n\n"
        "Choose exactly one POI number as the next navigation target. The chosen "
        "point must be both feasible in Image 1 and consistent with the route "
        "direction in Image 2.\n\n"
        "Candidate POIs:\n"
        f"{poi_lines}\n"
        "\n"
        "Return only JSON with this schema:\n"
        "{\"answer\": <poi_number>, \"reason\": \"short reason\"}"
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_labels(path: Path | None) -> dict[str, int]:
    if path is None:
        return {}
    labels: dict[str, int] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sample_id = (row.get("sample_id") or "").strip()
            answer = (row.get("answer") or row.get("ground_truth_answer") or "").strip()
            if not sample_id or not answer:
                continue
            labels[sample_id] = int(answer)
    return labels


def write_labels_template(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sample_id",
                "answer",
                "heuristic_answer",
                "num_pois",
                "question_image",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "sample_id": row["sample_id"],
                    "answer": row.get("ground_truth_answer") or "",
                    "heuristic_answer": row.get("heuristic_answer") or "",
                    "num_pois": len(row.get("pois", [])),
                    "question_image": row["question_image"],
                }
            )


def path_uri(path: Path) -> str:
    return path.resolve().as_uri()


def write_review_html(path: Path, rows: list[dict[str, Any]]) -> None:
    cards: list[str] = []
    for row in rows:
        poi_lines = "".join(
            [
                (
                    "<li>"
                    f"POI {p['number']}: {p['color']} "
                    f"({p['x']}, {p['y']}), type={p['edge_type']}"
                    "</li>"
                )
                for p in row["pois"]
            ]
        )
        cards.append(
            f"""
<section class="sample">
  <h2>{row['sample_id']}</h2>
  <p><strong>Instruction:</strong> {row['navigation_instruction']}</p>
  <p><strong>Weak heuristic:</strong> {row.get('heuristic_answer')}</p>
  <img src="{path_uri(Path(row['question_image']))}" alt="{row['sample_id']}">
  <ul>{poi_lines}</ul>
</section>
"""
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>POI VLM Decision Review</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
    .sample {{ margin-bottom: 40px; border-top: 1px solid #ddd; padding-top: 20px; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
    li {{ margin: 4px 0; }}
  </style>
</head>
<body>
  <h1>POI VLM Decision Review</h1>
  <p>Use this page for quick visual inspection. Ground-truth labels should be
  stored separately and merged before accuracy evaluation.</p>
  {''.join(cards)}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_dataset(args: argparse.Namespace) -> list[dict[str, Any]]:
    paths = make_paths(args)
    for must_exist in [paths.input_dir, args.poi_gen_root]:
        if not must_exist.exists():
            raise FileNotFoundError(must_exist)
    if not args.dynamic_route_map and not paths.map_image.exists():
        raise FileNotFoundError(paths.map_image)

    paths.output_root.mkdir(parents=True, exist_ok=True)
    paths.question_dir.mkdir(parents=True, exist_ok=True)
    paths.route_map_dir.mkdir(parents=True, exist_ok=True)

    PolygonPOIGenerator, cv_imread, cv_imwrite = load_poi_tools(args.poi_gen_root)
    labels = load_labels(args.labels_csv)
    fallback_map = cv_imread(str(paths.map_image)) if paths.map_image.exists() else None
    if fallback_map is None and not args.dynamic_route_map:
        raise RuntimeError(f"Failed to read map image: {paths.map_image}")

    amap_key = os.environ.get(args.amap_key_env, "")
    start_gcj = parse_lnglat(args.route_start)
    end_gcj = parse_lnglat(args.route_end)
    gps_rows = load_gps_by_frame(paths.gps_csv)
    route_points: list[tuple[float, float]] = []
    use_dynamic_maps = bool(args.dynamic_route_map and amap_key and gps_rows)
    if args.dynamic_route_map and not amap_key:
        print(f"[WARN] {args.amap_key_env} is not set; falling back to static map image.")
    if args.dynamic_route_map and not gps_rows:
        print(f"[WARN] No GPS rows loaded from {paths.gps_csv}; falling back to static map image.")
    if use_dynamic_maps:
        if args.route_source == "gps_track":
            route_points = gps_track_points(gps_rows)
            if len(route_points) < 2:
                print(f"[WARN] GPS track has fewer than two points; falling back to static map image.")
                use_dynamic_maps = False
            else:
                start_gcj = route_points[0]
                end_gcj = route_points[-1]
        else:
            route_points = fetch_amap_route(start_gcj, end_gcj, amap_key)

    image_paths = iter_image_paths(
        paths.input_dir,
        args.start_frame,
        args.end_frame,
        args.stride,
        args.limit,
        args.sample_count,
        args.include_frames,
    )
    rows: list[dict[str, Any]] = []

    for idx, image_path in enumerate(image_paths, 1):
        stem = image_path.stem
        frame = frame_number(image_path)
        gps_lookup_frame = int(round(frame * args.gps_frame_scale + args.gps_frame_offset))
        mask_path = image_path.parent / f"{stem}_mask.png"
        existing_poi_path = paths.poi_image_dir / f"{stem}_poi.jpg"
        question_path = paths.question_dir / f"{stem}_question.jpg"
        map_for_sample_path = paths.route_map_dir / f"{stem}_route.jpg"

        if not mask_path.exists():
            print(f"[{idx}/{len(image_paths)}] skip, missing mask: {mask_path.name}")
            continue

        image = cv_imread(str(image_path))
        mask_color = cv_imread(str(mask_path))
        if image is None or mask_color is None:
            print(f"[{idx}/{len(image_paths)}] skip, failed to read: {stem}")
            continue

        h, w = image.shape[:2]
        generator = PolygonPOIGenerator(h, w)
        mask = extract_drivable_mask(mask_color)
        with silence_stdout():
            result = generator.generate_pois(mask, **POI_PARAMS)

        pois = [clean_poi(poi, i) for i, poi in enumerate(result["pois"], 1)]

        if args.reuse_existing_poi_images and existing_poi_path.exists():
            front_poi = cv_imread(str(existing_poi_path))
            front_poi_path = existing_poi_path
        else:
            front_poi = make_combined_image(
                image,
                result["clean_mask"],
                result["polygon"],
                result["pois"],
                generator.ego,
            )
            front_poi_path = paths.output_root / "generated_front_poi" / f"{stem}_poi.jpg"
            front_poi_path.parent.mkdir(parents=True, exist_ok=True)
            cv_imwrite(str(front_poi_path), front_poi)

        if front_poi is None:
            print(f"[{idx}/{len(image_paths)}] skip, missing front POI image: {stem}")
            continue

        route_meta: dict[str, Any] = {}
        gps_match = nearest_gps(gps_rows, gps_lookup_frame)
        if use_dynamic_maps and gps_match is not None:
            current_gcj = (
                float(gps_match["longitude_gcj02"]),
                float(gps_match["latitude_gcj02"]),
            )
            route_map, route_meta = build_route_map(
                route_points,
                current_gcj,
                start_gcj,
                end_gcj,
                amap_key,
                args.map_zoom,
                args.map_lookahead_m,
            )
            route_meta.update(
                {
                    "gps_frame": gps_match["frame"],
                    "gps_lookup_frame": gps_lookup_frame,
                    "debug_frame_to_gps_scale": args.gps_frame_scale,
                    "debug_frame_to_gps_offset": args.gps_frame_offset,
                    "route_source": args.route_source,
                    "current_lng_wgs84": gps_match["longitude_wgs84"],
                    "current_lat_wgs84": gps_match["latitude_wgs84"],
                }
            )
            cv_imwrite(str(map_for_sample_path), route_map)
            map_for_sample = route_map
        else:
            map_for_sample_path = paths.map_image
            map_for_sample = fallback_map

        if map_for_sample is None:
            print(f"[{idx}/{len(image_paths)}] skip, missing map image")
            continue

        question = compose_question_image(front_poi, map_for_sample)
        cv_imwrite(str(question_path), question)

        heuristic = heuristic_answer(pois, w, h, args.desired_direction)
        prompt = make_prompt(args.navigation_instruction, pois)

        row = {
            "sample_id": stem,
            "frame_index": frame,
            "raw_image": str(image_path.resolve()),
            "mask_image": str(mask_path.resolve()),
            "front_poi_image": str(front_poi_path.resolve()),
            "map_image": str(Path(map_for_sample_path).resolve()),
            "question_image": str(question_path.resolve()),
            "image_width": w,
            "image_height": h,
            "gps": gps_match,
            "route": route_meta,
            "navigation_instruction": args.navigation_instruction,
            "pois": pois,
            "heuristic_answer": heuristic,
            "ground_truth_answer": labels.get(stem),
            "prompt": prompt,
        }
        rows.append(row)
        write_jsonl(paths.manifest_path, rows)
        print(f"[{idx}/{len(image_paths)}] wrote {stem}: {len(pois)} POIs")

    write_jsonl(paths.manifest_path, rows)
    write_labels_template(paths.labels_template_path, rows)
    write_review_html(paths.review_html_path, rows)
    print(f"Manifest: {paths.manifest_path}")
    print(f"Labels:   {paths.labels_template_path}")
    print(f"Review:   {paths.review_html_path}")
    return rows


def main() -> None:
    args = parse_args()
    build_dataset(args)


if __name__ == "__main__":
    main()
