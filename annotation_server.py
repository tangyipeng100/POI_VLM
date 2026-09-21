#!/usr/bin/env python3
"""Local annotation server for POI VLM decision labels."""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "annotation_app"
DEFAULT_DATASET = ROOT / "vlm_dataset"


class AnnotationStore:
    def __init__(self, dataset_dir: Path):
        self.dataset_dir = dataset_dir
        self.manifest_path = dataset_dir / "samples.jsonl"
        self.annotations_json = dataset_dir / "annotations.json"
        self.annotations_jsonl = dataset_dir / "annotations.jsonl"
        self.annotations_csv = dataset_dir / "annotations.csv"
        self.samples = self._load_samples()
        self.annotations = self._load_annotations()

    def _load_samples(self) -> list[dict]:
        if not self.manifest_path.exists():
            raise FileNotFoundError(self.manifest_path)
        rows = []
        for line in self.manifest_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _load_annotations(self) -> dict[str, dict]:
        if self.annotations_json.exists():
            return json.loads(self.annotations_json.read_text(encoding="utf-8"))
        if self.annotations_jsonl.exists():
            out = {}
            for line in self.annotations_jsonl.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    out[row["sample_id"]] = row
            return out
        return {}

    @staticmethod
    def _normalize_poi_numbers(payload: dict) -> list[int]:
        raw = payload.get("poi_numbers")
        if not isinstance(raw, list):
            raw = (
                [payload.get("poi_number")]
                if payload.get("poi_number") is not None
                else []
            )
        numbers: list[int] = []
        for value in raw:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in numbers:
                numbers.append(number)
        return numbers

    def public_samples(self) -> list[dict]:
        out = []
        for index, sample in enumerate(self.samples):
            sample_id = sample["sample_id"]
            out.append(
                {
                    "index": index,
                    "sample_id": sample_id,
                    "frame_index": sample.get("frame_index"),
                    "question_image_url": f"/api/image?sample_id={sample_id}&kind=question",
                    "pois": sample.get("pois", []),
                    "route": sample.get("route", {}),
                    "gps": sample.get("gps", {}),
                    "annotation": self.annotations.get(sample_id),
                }
            )
        return out

    def stats(self) -> dict:
        total = len(self.samples)
        annotated_count = sum(1 for sample in self.samples if sample["sample_id"] in self.annotations)
        next_unlabeled = 0
        for idx, sample in enumerate(self.samples):
            if sample["sample_id"] not in self.annotations:
                next_unlabeled = idx
                break
        else:
            next_unlabeled = max(0, total - 1)
        return {
            "total": total,
            "annotated_count": annotated_count,
            "next_unlabeled_index": next_unlabeled,
        }

    def image_path(self, sample_id: str, kind: str) -> Path:
        sample = next((row for row in self.samples if row["sample_id"] == sample_id), None)
        if sample is None:
            raise KeyError(sample_id)
        key = "question_image" if kind == "question" else "map_image"
        return Path(sample[key])

    def save_annotation(self, payload: dict) -> dict:
        sample_id = str(payload.get("sample_id", ""))
        if not any(row["sample_id"] == sample_id for row in self.samples):
            raise ValueError(f"Unknown sample_id: {sample_id}")

        action = payload.get("action")
        if action not in {"go_to_poi", "rotate", "skip"}:
            raise ValueError("action must be go_to_poi, rotate, or skip")

        poi_numbers = self._normalize_poi_numbers(payload)
        row = {
            "sample_id": sample_id,
            "action": action,
            "poi_number": poi_numbers[0] if poi_numbers else None,
            "poi_numbers": poi_numbers,
            "rotate_direction": payload.get("rotate_direction"),
            "rotate_angle_deg": payload.get("rotate_angle_deg"),
            "confidence": payload.get("confidence") or "medium",
            "note": payload.get("note") or "",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        if action != "go_to_poi":
            row["poi_number"] = None
            row["poi_numbers"] = []
        if action != "rotate":
            row["rotate_direction"] = None
            row["rotate_angle_deg"] = None

        self.annotations[sample_id] = row
        self.flush()
        return row

    def flush(self) -> None:
        self.annotations_json.write_text(
            json.dumps(self.annotations, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ordered = [
            self.annotations[sample["sample_id"]]
            for sample in self.samples
            if sample["sample_id"] in self.annotations
        ]
        with self.annotations_jsonl.open("w", encoding="utf-8") as f:
            for row in ordered:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        with self.annotations_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "sample_id",
                    "action",
                    "poi_number",
                    "poi_numbers",
                    "rotate_direction",
                    "rotate_angle_deg",
                    "confidence",
                    "note",
                    "updated_at",
                ],
            )
            writer.writeheader()
            csv_rows = []
            for row in ordered:
                out = dict(row)
                poi_numbers = out.get("poi_numbers")
                if not poi_numbers and out.get("poi_number") is not None:
                    poi_numbers = [out["poi_number"]]
                out["poi_numbers"] = json.dumps(poi_numbers or [], ensure_ascii=False)
                csv_rows.append(out)
            writer.writerows(csv_rows)


def make_handler(store: AnnotationStore):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args):  # noqa: A002
            print(f"{self.address_string()} - {format % args}")

        def send_json(self, data: dict, status: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_text(self, text: str, status: int = 200) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self.send_text(f"Not found: {path}", 404)
                return
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/":
                self.send_file(APP_DIR / "index.html")
            elif path in {"/styles.css", "/app.js"}:
                self.send_file(APP_DIR / path.lstrip("/"))
            elif path == "/api/samples":
                self.send_json({"samples": store.public_samples(), **store.stats()})
            elif path == "/api/image":
                query = parse_qs(parsed.query)
                sample_id = query.get("sample_id", [""])[0]
                kind = query.get("kind", ["question"])[0]
                try:
                    self.send_file(store.image_path(sample_id, kind))
                except KeyError:
                    self.send_text(f"Unknown sample_id: {sample_id}", 404)
            elif path == "/api/annotations.csv":
                if not store.annotations_csv.exists():
                    store.flush()
                self.send_file(store.annotations_csv)
            else:
                self.send_text("Not found", 404)

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/annotations":
                self.send_text("Not found", 404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                annotation = store.save_annotation(payload)
            except Exception as exc:  # noqa: BLE001
                self.send_text(str(exc), 400)
                return
            self.send_json({"annotation": annotation, **store.stats()})

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local POI annotation server.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = AnnotationStore(args.dataset_dir)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"Annotation server: http://{args.host}:{args.port}")
    print(f"Dataset: {args.dataset_dir}")
    server.serve_forever()


if __name__ == "__main__":
    main()
