#!/usr/bin/env python3
"""Create an HTML report and contact sheet for VLM prediction results."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize VLM predictions.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--thumb-width", type=int, default=520)
    parser.add_argument("--cols", type=int, default=4)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pred_label(row: dict[str, Any]) -> str:
    action = row.get("pred_action")
    if action == "go_to_poi":
        return f"{row['sample_id']} | go_to_poi {row.get('pred_poi_number')}"
    if action == "go_between_pois":
        return (
            f"{row['sample_id']} | midpoint "
            f"{row.get('pred_poi_numbers')} @{row.get('pred_interpolation')}"
        )
    if action == "rotate":
        return (
            f"{row['sample_id']} | rotate {row.get('pred_rotate_direction')} "
            f"{row.get('pred_rotate_angle_deg')}deg"
        )
    return f"{row['sample_id']} | {action}"


def label_text(row: dict[str, Any]) -> str:
    action = row.get("label_action")
    if action == "go_to_poi":
        numbers = row.get("label_poi_numbers")
        if not numbers and row.get("label_poi_number") is not None:
            numbers = [row.get("label_poi_number")]
        return f"label go_to_poi {numbers or '-'}"
    if action == "rotate":
        return (
            f"label rotate {row.get('label_rotate_direction')} "
            f"{row.get('label_rotate_angle_deg')}deg"
        )
    if action == "skip":
        return "label skip"
    return "label -"


def score_class(row: dict[str, Any]) -> str:
    if row.get("target_correct") is True:
        return "ok"
    if row.get("relaxed_target_correct") is True:
        return "relaxed"
    if row.get("label_action") is not None:
        return "bad"
    return "unscored"


def score_text(row: dict[str, Any]) -> str:
    if row.get("target_correct") is True:
        return "strict correct"
    if row.get("relaxed_target_correct") is True:
        return "relaxed correct"
    if row.get("label_action") is not None:
        return "wrong"
    return "unscored"


def safe_acc(ok: int, total: int) -> str:
    return f"{ok}/{total}={ok / total:.3f}" if total else "0/0=-"


def summary_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    action_counts: dict[str, int] = {}
    for row in rows:
        action = str(row.get("pred_action"))
        action_counts[action] = action_counts.get(action, 0) + 1

    labeled = [row for row in rows if row.get("label_action") is not None]
    if not labeled:
        return {"action_counts": action_counts, "cards": [("samples", str(len(rows)))]}

    action_ok = sum(1 for row in labeled if row.get("action_correct"))
    target_ok = sum(1 for row in labeled if row.get("target_correct"))
    relaxed_action_ok = sum(1 for row in labeled if row.get("relaxed_action_correct"))
    relaxed_target_ok = sum(1 for row in labeled if row.get("relaxed_target_correct"))
    poi_rows = [row for row in labeled if row.get("label_action") == "go_to_poi"]
    rotate_rows = [row for row in labeled if row.get("label_action") == "rotate"]
    skip_rows = [row for row in labeled if row.get("label_action") == "skip"]
    cards = [
        ("samples", str(len(rows))),
        ("action_acc", safe_acc(action_ok, len(labeled))),
        ("target_acc", safe_acc(target_ok, len(labeled))),
        ("relaxed_action", safe_acc(relaxed_action_ok, len(labeled))),
        ("relaxed_target", safe_acc(relaxed_target_ok, len(labeled))),
    ]
    if poi_rows:
        cards.append(
            (
                "poi_target_acc",
                safe_acc(sum(1 for row in poi_rows if row.get("target_correct")), len(poi_rows)),
            )
        )
    if rotate_rows:
        cards.append(
            (
                "rotate_dir_acc",
                safe_acc(sum(1 for row in rotate_rows if row.get("target_correct")), len(rotate_rows)),
            )
        )
    if skip_rows:
        cards.append(
            (
                "skip_acc",
                safe_acc(sum(1 for row in skip_rows if row.get("target_correct")), len(skip_rows)),
            )
        )
    return {"action_counts": action_counts, "cards": cards}


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def add_banner(image: Image.Image, label: str) -> Image.Image:
    image = image.convert("RGB")
    w, h = image.size
    banner_h = 58
    out = Image.new("RGB", (w, h + banner_h), (255, 255, 255))
    out.paste(image, (0, banner_h))
    draw = ImageDraw.Draw(out)
    draw.rectangle((0, 0, w, banner_h), fill=(245, 247, 250))
    draw.text((18, 18), label[:120], fill=(20, 20, 20), font=load_font(24))
    return out


def resize_width(image: Image.Image, width: int) -> Image.Image:
    w, h = image.size
    scale = width / w
    return image.resize((width, int(round(h * scale))), Image.Resampling.LANCZOS)


def make_contact_sheet(
    rows: list[dict[str, Any]],
    sample_by_id: dict[str, dict[str, Any]],
    width: int,
    cols: int,
) -> Image.Image:
    thumbs: list[Image.Image] = []
    for row in rows:
        sample = sample_by_id[row["sample_id"]]
        try:
            image = Image.open(sample["question_image"]).convert("RGB")
        except OSError:
            continue
        thumbs.append(resize_width(add_banner(image, pred_label(row)), width))
    if not thumbs:
        return Image.new("RGB", (width, 200), (255, 255, 255))

    max_h = max(thumb.height for thumb in thumbs)
    padded = []
    for thumb in thumbs:
        canvas = Image.new("RGB", (width, max_h), (255, 255, 255))
        canvas.paste(thumb, (0, 0))
        padded.append(canvas)

    sheet_rows = (len(padded) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * width, sheet_rows * max_h), (255, 255, 255))
    for i in range(0, len(padded), cols):
        chunk = padded[i : i + cols]
        y = (i // cols) * max_h
        for x_idx, thumb in enumerate(chunk):
            sheet.paste(thumb, (x_idx * width, y))
    return sheet


def path_uri(path: str | Path) -> str:
    return Path(path).resolve().as_uri()


def make_html(rows: list[dict[str, Any]], sample_by_id: dict[str, dict[str, Any]], sheet_path: Path) -> str:
    stats = summary_stats(rows)
    stat_cards = "\n".join(
        f'<div class="stat"><strong>{html.escape(name)}</strong><span>{html.escape(value)}</span></div>'
        for name, value in stats["cards"]
    )
    cards = []
    for row in rows:
        sample = sample_by_id[row["sample_id"]]
        route = sample.get("route") or {}
        reason = html.escape(str(row.get("pred_reason") or ""))
        cls = score_class(row)
        cards.append(
            f"""
<section class="card {cls}">
  <h2>{html.escape(pred_label(row))}</h2>
  <p class="verdict">{html.escape(score_text(row))} | {html.escape(label_text(row))}</p>
  <p class="meta">passed={route.get('passed_m', '')}m | remaining={route.get('remaining_m', '')}m | gps_frame={(sample.get('gps') or {}).get('frame', '')}</p>
  <p>{reason}</p>
  <img src="{path_uri(sample['question_image'])}" alt="{html.escape(row['sample_id'])}">
</section>
"""
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Night VLM Prediction Report</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #f5f6f8; color: #111827; }}
    header {{ position: sticky; top: 0; background: #ffffff; border-bottom: 1px solid #d8dee8; padding: 14px 22px; z-index: 1; }}
    h1 {{ margin: 0 0 6px; font-size: 22px; }}
    .summary {{ color: #4b5563; }}
    main {{ padding: 18px 22px 40px; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0; }}
    .stat {{ min-width: 160px; background: #fff; border: 1px solid #d8dee8; border-radius: 8px; padding: 10px 12px; }}
    .stat strong {{ display: block; color: #4b5563; font-size: 12px; margin-bottom: 4px; }}
    .stat span {{ font-size: 18px; font-weight: 700; }}
    .sheet {{ display: block; width: 100%; max-width: 1800px; border: 1px solid #d8dee8; background: white; }}
    .card {{ margin: 18px 0; padding: 14px; background: white; border: 1px solid #d8dee8; border-radius: 8px; }}
    .card.ok {{ border-left: 8px solid #16a34a; }}
    .card.relaxed {{ border-left: 8px solid #f59e0b; }}
    .card.bad {{ border-left: 8px solid #dc2626; }}
    .card h2 {{ margin: 0 0 8px; font-size: 18px; }}
    .verdict {{ margin: 0 0 8px; font-weight: 700; }}
    .meta {{ color: #6b7280; }}
    .card img {{ width: 100%; max-width: 1600px; display: block; border: 1px solid #e5e7eb; }}
  </style>
</head>
<body>
  <header>
    <h1>Night VLM Prediction Report</h1>
    <div class="summary">action_counts={html.escape(str(stats["action_counts"]))}</div>
  </header>
  <main>
    <div class="stats">{stat_cards}</div>
    <h2>Contact Sheet</h2>
    <img class="sheet" src="{path_uri(sheet_path)}" alt="contact sheet">
    {''.join(cards)}
  </main>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    samples = load_jsonl(args.manifest)
    predictions = load_jsonl(args.predictions)
    sample_by_id = {row["sample_id"]: row for row in samples}
    predictions = [row for row in predictions if row["sample_id"] in sample_by_id]

    sheet = make_contact_sheet(predictions, sample_by_id, args.thumb_width, args.cols)
    sheet_path = args.output_dir / "vlm_prediction_contact_sheet.jpg"
    sheet.save(sheet_path, quality=92)

    html_path = args.output_dir / "vlm_prediction_report.html"
    html_path.write_text(make_html(predictions, sample_by_id, sheet_path), encoding="utf-8")
    print(f"Contact sheet: {sheet_path}")
    print(f"HTML report:   {html_path}")


if __name__ == "__main__":
    main()
