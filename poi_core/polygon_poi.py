"""Polygon-based candidate point generation.

The public implementation is a small, dependency-light extraction of the POI
stage used in the paper. It accepts a binary drivable-area mask and returns a
stable, inspectable set of candidates. The segmentation model is intentionally
not coupled to this module: a PP-LiteSeg mask, a hand-labelled mask, or any
other binary traversability front end can be used.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def normalize_mask(mask: np.ndarray) -> np.ndarray:
    """Convert grayscale or green pseudo-colour masks to ``uint8`` 0/1."""

    array = np.asarray(mask)
    if array.ndim == 3:
        # The source project stores pseudo masks as green foreground on black.
        b, g, r = cv2.split(array[..., :3])
        green_foreground = (g > 100) & (g >= r * 1.15) & (g >= b * 1.15)
        gray = cv2.cvtColor(array[..., :3], cv2.COLOR_BGR2GRAY)
        array = np.where(green_foreground, 255, gray)
    threshold = 127 if int(array.max(initial=0)) > 1 else 0
    return (array > threshold).astype(np.uint8)


def _read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    return image


def _write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix or ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        raise ValueError(f"Could not encode image: {path}")
    encoded.tofile(str(path))


class PolygonPOIGenerator:
    """Generate candidate targets from the boundary of a drivable mask.

    The generator follows the method used by the paper: clean the largest
    traversable component, approximate it by a polygon, classify boundary
    edges, add the farthest/vanishing vertex, then apply priority-aware NMS.
    """

    def __init__(self, image_height: int, image_width: int, ego_margin: int = 10):
        if image_height < 2 or image_width < 2:
            raise ValueError("image_height and image_width must be at least 2")
        self.h = int(image_height)
        self.w = int(image_width)
        self.ego = (self.w // 2, self.h - 1 - int(ego_margin))

    def preprocess_mask(
        self,
        mask: np.ndarray,
        close_ksize: int = 9,
        open_ksize: int = 5,
        min_area: int = 500,
    ) -> np.ndarray:
        """Fill small holes, remove speckles, and keep connected regions."""

        clean = normalize_mask(mask)
        if close_ksize > 0:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (close_ksize, close_ksize)
            )
            clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel)
        if open_ksize > 0:
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (open_ksize, open_ksize)
            )
            clean = cv2.morphologyEx(clean, cv2.MORPH_OPEN, kernel)

        count, labels, stats, _ = cv2.connectedComponentsWithStats(clean, 8)
        output = np.zeros_like(clean)
        threshold = max(1, min(int(min_area), self.h * self.w))
        for label in range(1, count):
            if int(stats[label, cv2.CC_STAT_AREA]) >= threshold:
                output[labels == label] = 1
        return output

    def extract_polygon(
        self,
        clean_mask: np.ndarray,
        epsilon_ratio: float = 0.012,
        min_edges: int = 4,
        max_edges: int = 8,
    ) -> np.ndarray:
        contours, _ = cv2.findContours(
            clean_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return np.empty((0, 2), dtype=np.int32)
        contour = max(contours, key=cv2.contourArea)
        perimeter = cv2.arcLength(contour, True)
        epsilon = max(float(epsilon_ratio), 1e-5)
        approximation = None
        for _ in range(24):
            approximation = cv2.approxPolyDP(contour, epsilon * perimeter, True)
            edge_count = len(approximation)
            if min_edges <= edge_count <= max_edges:
                break
            epsilon *= 0.7 if edge_count < min_edges else 1.3
        assert approximation is not None
        return approximation.reshape(-1, 2).astype(np.int32)

    def classify_edges(
        self,
        polygon: np.ndarray,
        edge_margin: int = 30,
        bottom_y_ratio: float = 0.92,
        top_y_ratio: float = 0.75,
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for index, vertex in enumerate(polygon):
            other = polygon[(index + 1) % len(polygon)]
            x1, y1 = map(int, vertex)
            x2, y2 = map(int, other)
            midpoint = ((x1 + x2) // 2, (y1 + y2) // 2)
            length = math.hypot(x2 - x1, y2 - y1)
            if y1 > bottom_y_ratio * self.h and y2 > bottom_y_ratio * self.h:
                edge_type = "bottom"
            elif midpoint[1] < top_y_ratio * self.h:
                edge_type = "top"
            elif x1 < edge_margin or x2 < edge_margin:
                edge_type = "left"
            elif x1 > self.w - edge_margin or x2 > self.w - edge_margin:
                edge_type = "right"
            else:
                edge_type = "top"
            edges.append(
                {
                    "index": index,
                    "v1": [x1, y1],
                    "v2": [x2, y2],
                    "midpoint": list(midpoint),
                    "edge_type": edge_type,
                    "length": round(length, 3),
                }
            )
        return edges

    @staticmethod
    def _nms(points: list[dict[str, Any]], radius: float) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        radius_sq = float(radius) ** 2
        for point in points:
            if all(
                (point["x"] - other["x"]) ** 2
                + (point["y"] - other["y"]) ** 2
                >= radius_sq
                for other in kept
            ):
                kept.append(point)
        return kept

    def generate_pois(
        self,
        mask: np.ndarray,
        *,
        epsilon_ratio: float = 0.012,
        min_edges: int = 4,
        max_edges: int = 8,
        edge_margin: int = 30,
        bottom_y_ratio: float = 0.92,
        skip_bottom: bool = True,
        nms_dist: int = 80,
        min_edge_len: int = 120,
        max_pois: int = 7,
        min_pois: int = 1,
    ) -> dict[str, Any]:
        """Return ``pois``, ``polygon``, ``edges`` and the cleaned mask."""

        clean_mask = self.preprocess_mask(mask)
        polygon = self.extract_polygon(clean_mask, epsilon_ratio, min_edges, max_edges)
        if len(polygon) == 0:
            return {"pois": [], "polygon": [], "edges": [], "clean_mask": clean_mask}

        edges = self.classify_edges(
            polygon, edge_margin=edge_margin, bottom_y_ratio=bottom_y_ratio
        )
        pois: list[dict[str, Any]] = []
        for edge in edges:
            if skip_bottom and edge["edge_type"] == "bottom":
                continue
            if edge["length"] < min_edge_len:
                continue
            x, y = edge["midpoint"]
            pois.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "edge_type": edge["edge_type"],
                    "length": edge["length"],
                    "source": "edge_midpoint",
                }
            )

        farthest_index = int(np.argmin(polygon[:, 1]))
        farthest = polygon[farthest_index]
        pois.append(
            {
                "x": int(farthest[0]),
                "y": int(farthest[1]),
                "edge_type": "vanishing",
                "length": 0.0,
                "source": "farthest_vertex",
            }
        )

        priority = {"vanishing": 0, "left": 1, "right": 1, "top": 2}
        pois.sort(key=lambda item: (priority.get(item["edge_type"], 9), item["y"]))
        pois = self._nms(pois, nms_dist)

        if len(pois) > max_pois:
            # Preserve semantic priority while enforcing a stable display size.
            radius = float(nms_dist)
            candidate = pois
            for _ in range(20):
                radius *= 1.15
                reduced = self._nms(pois, radius)
                if min_pois <= len(reduced) <= max_pois:
                    candidate = reduced
                    break
            pois = candidate[:max_pois]

        for number, point in enumerate(pois, start=1):
            point["number"] = number
        return {
            "pois": pois,
            "polygon": polygon.astype(int).tolist(),
            "edges": edges,
            "clean_mask": clean_mask,
        }


def draw_poi_overlay(
    image: np.ndarray,
    result: dict[str, Any],
    *,
    show_polygon: bool = True,
) -> np.ndarray:
    """Draw the polygon and numbered POIs on a BGR image."""

    overlay = image.copy()
    polygon = np.asarray(result.get("polygon", []), dtype=np.int32)
    if show_polygon and len(polygon) >= 3:
        cv2.polylines(overlay, [polygon.reshape(-1, 1, 2)], True, (255, 255, 255), 3)

    colors = {
        "vanishing": (255, 255, 0),
        "left": (0, 0, 255),
        "right": (255, 0, 180),
        "top": (0, 180, 255),
        "bottom": (128, 128, 128),
    }
    for point in result.get("pois", []):
        center = (int(point["x"]), int(point["y"]))
        color = colors.get(point.get("edge_type"), (255, 255, 255))
        cv2.circle(overlay, center, 15, color, 4, cv2.LINE_AA)
        cv2.circle(overlay, center, 4, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.putText(
            overlay,
            str(point.get("number", "?")),
            (center[0] + 18, center[1] - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
            cv2.LINE_AA,
        )
    return overlay


__all__ = ["PolygonPOIGenerator", "draw_poi_overlay", "normalize_mask"]
