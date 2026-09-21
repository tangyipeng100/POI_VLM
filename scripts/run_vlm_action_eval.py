#!/usr/bin/env python3
"""Evaluate action decisions against annotation_app labels."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "vlm_dataset" / "samples.jsonl"
DEFAULT_ANNOTATIONS = ROOT / "vlm_dataset" / "annotations.json"
DEFAULT_OUTPUT = ROOT / "vlm_dataset" / "action_predictions.jsonl"
DEFAULT_CONFIG: Path | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run action-level VLM evaluation.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument(
        "--unlabeled",
        action="store_true",
        help="Run prediction without requiring an annotations file or scoring.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Optional local provider config. Environment variables are preferred and no file is read by default.",
    )
    parser.add_argument("--api-url", default=os.environ.get("VLM_API_URL"))
    parser.add_argument(
        "--api-wire",
        choices=["auto", "chat", "responses"],
        default=os.environ.get("VLM_API_WIRE", "auto"),
    )
    parser.add_argument("--api-key-env", default="VLM_API_KEY")
    parser.add_argument("--model", default=os.environ.get("VLM_MODEL"))
    parser.add_argument(
        "--allow-midpoint",
        action="store_true",
        help="Allow the model to choose the midpoint between two candidate POIs.",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sample-ids", nargs="*", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="Optional system prompt for chat-completions providers.",
    )
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        help="Send chat_template_kwargs.enable_thinking=false for compatible vLLM/Qwen servers.",
    )
    return parser.parse_args()


def parse_config(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    def first(patterns: list[str]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.M)
            if match:
                return match.group(1).strip().strip('"').strip("'")
        return None

    config: dict[str, str] = {}
    for key in ("base_url", "model", "wire_api"):
        value = first([rf"^\s*{key}\s*=\s*\"([^\"]+)\""])
        if value:
            config[key] = value

    api_key = first(
        [
            r"^\s*(?:api_key|openai_api_key|vlm_api_key|key|token)\s*=\s*\"?([^\"\s]+)\"?\s*$",
            r"Bearer\s+([A-Za-z0-9_\.\-]{16,})",
            r"(sk-[A-Za-z0-9_\-]{16,})",
        ]
    )
    if not api_key:
        for line in text.splitlines():
            value = line.strip().strip('"').strip("'")
            if re.fullmatch(r"[A-Za-z0-9_\-]{32,}", value):
                api_key = value
                break
    if api_key:
        config["api_key"] = api_key
    return config


def endpoint_from_base(base_url: str | None, wire: str) -> str:
    if base_url:
        url = base_url.rstrip("/")
        if url.endswith("/chat/completions") or url.endswith("/responses"):
            return url
        suffix = "responses" if wire == "responses" else "chat/completions"
        if url.endswith("/v1"):
            return f"{url}/{suffix}"
        return f"{url}/v1/{suffix}"
    if wire == "responses":
        return "https://api.openai.com/v1/responses"
    return "https://api.openai.com/v1/chat/completions"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_existing(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                done.add(json.loads(line)["sample_id"])
    return done


def data_url(path: str | Path) -> str:
    image_path = Path(path)
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_prompt(sample: dict[str, Any], allow_midpoint: bool) -> str:
    candidates = "\n".join(
        f"- POI {p['number']}: color={p['color']}, pixel=({p['x']},{p['y']}), edge={p['edge_type']}"
        for p in sample.get("pois", [])
    )
    route = sample.get("route", {})
    passed = route.get("passed_m")
    remaining = route.get("remaining_m")
    progress = ""
    if passed is not None and remaining is not None:
        progress = f"\nRoute progress: passed={passed:.1f}m, remaining={remaining:.1f}m."

    midpoint_option = ""
    schema = (
        '{"action":"go_to_poi|rotate|skip","poi_number":number_or_null,'
        '"rotate_direction":"left|right|null","rotate_angle_deg":number_or_null,'
        '"reason":"short reason"}'
    )
    if allow_midpoint:
        midpoint_option = """
3. go_between_pois: choose this if the best target is clearly between two visible POIs rather than exactly on either point. Use poi_numbers [a,b] and interpolation 0.5 for the midpoint.
4. skip: choose only if the image is unusable or there are no usable candidates."""
        schema = (
            '{"action":"go_to_poi|go_between_pois|rotate|skip",'
            '"poi_number":number_or_null,"poi_numbers":[number,number]_or_null,'
            '"interpolation":0.5_or_null,'
            '"rotate_direction":"left|right|null","rotate_angle_deg":number_or_null,'
            '"reason":"short reason"}'
        )
    else:
        midpoint_option = """
3. skip: choose only if the image is unusable or there are no usable candidates."""

    return f"""You are the navigation decision module of an outdoor mobile robot.
You receive one composed image with two panels:
- Image 1: front camera view with numbered candidate POI points.
- Image 2: Amap top-down route. The orange circle is current GPS position, the green arrow is route-following heading, gray is passed route, blue is remaining route, S is start, and E is goal.{progress}

Choose the next action:
1. go_to_poi: choose one visible POI if it is feasible in the front view and consistent with the route direction.
2. rotate: choose this if the camera/robot should rotate before picking a POI because the view is misaligned with the next route direction or no visible POI is a good forward target. Use rotate_direction left or right and rotate_angle_deg 30.{midpoint_option}

Candidate POIs:
{candidates}

Return only JSON with this schema:
{schema}"""


def payload(
    sample: dict[str, Any],
    model: str,
    wire: str,
    allow_midpoint: bool,
    max_tokens: int,
    system_prompt: str | None = None,
    disable_thinking: bool = False,
) -> dict[str, Any]:
    prompt = build_prompt(sample, allow_midpoint)
    image = data_url(sample["question_image"])
    if wire == "responses":
        return {
            "model": model,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image},
                    ],
                }
            ],
            "max_output_tokens": max_tokens,
        }
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image}},
            ],
        }
    )
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if disable_thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def response_text(data: dict[str, Any], wire: str) -> str:
    if wire == "chat":
        return data["choices"][0]["message"]["content"]

    chunks: list[str] = []
    if data.get("output_text"):
        chunks.append(str(data["output_text"]))
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks).strip() or json.dumps(data, ensure_ascii=False)


def extract_json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def as_int_list(value: Any) -> list[int]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                value = parsed
            else:
                value = re.split(r"[,;/\s]+", text)
        except json.JSONDecodeError:
            value = re.split(r"[,;/\s]+", text)
    if not isinstance(value, list):
        return []
    numbers = []
    for item in value:
        number = as_int(item)
        if number is not None and number not in numbers:
            numbers.append(number)
    return numbers


def label_poi_numbers(row: dict[str, Any]) -> list[int]:
    numbers = as_int_list(row.get("label_poi_numbers"))
    if numbers:
        return numbers
    number = as_int(row.get("label_poi_number"))
    return [number] if number is not None else []


def as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def normalize_prediction(text: str) -> dict[str, Any]:
    data = extract_json(text)
    action = str(data.get("action") or "").strip().lower()
    if not action and data.get("answer") is not None:
        action = "go_to_poi"
        data["poi_number"] = data.get("answer")
    if action in {"poi", "go", "go_to"}:
        action = "go_to_poi"
    if action in {"midpoint", "between", "between_pois", "go_between"}:
        action = "go_between_pois"
    if action not in {"go_to_poi", "go_between_pois", "rotate", "skip"}:
        action = None
    direction = data.get("rotate_direction")
    if isinstance(direction, str):
        direction = direction.strip().lower()
        if direction not in {"left", "right"}:
            direction = None
    else:
        direction = None
    pred_poi_numbers = as_int_list(data.get("poi_numbers"))
    pred_poi_number = as_int(data.get("poi_number"))
    if pred_poi_number is None and pred_poi_numbers:
        pred_poi_number = pred_poi_numbers[0]
    return {
        "pred_action": action,
        "pred_poi_number": pred_poi_number,
        "pred_poi_numbers": pred_poi_numbers,
        "pred_interpolation": as_float(data.get("interpolation")),
        "pred_rotate_direction": direction,
        "pred_rotate_angle_deg": as_int(data.get("rotate_angle_deg")),
        "pred_reason": data.get("reason"),
    }


def call_vlm(
    api_url: str,
    api_key: str,
    sample: dict[str, Any],
    model: str,
    wire: str,
    allow_midpoint: bool,
    max_tokens: int,
    system_prompt: str | None,
    disable_thinking: bool,
    timeout: float,
    retries: int,
) -> tuple[str, dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = payload(
        sample,
        model,
        wire,
        allow_midpoint,
        max_tokens,
        system_prompt,
        disable_thinking,
    )
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            response = requests.post(api_url, headers=headers, json=body, timeout=timeout)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(min(45.0, 5.0 * (attempt + 1)))
                continue
            response.raise_for_status()
            data = response.json()
            return response_text(data, wire), data
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(45.0, 5.0 * (attempt + 1)))
    assert last_error is not None
    raise last_error


def score(row: dict[str, Any]) -> dict[str, bool]:
    label_action = row["label_action"]
    pred_action = row["pred_action"]
    action_correct = pred_action == label_action
    acceptable_pois = label_poi_numbers(row)
    target_correct = False
    if action_correct and label_action == "go_to_poi":
        target_correct = row["pred_poi_number"] in acceptable_pois
    elif action_correct and label_action == "rotate":
        target_correct = (
            row["pred_rotate_direction"] == row["label_rotate_direction"]
        )
    elif action_correct and label_action == "skip":
        target_correct = True

    relaxed_action_correct = action_correct
    relaxed_target_correct = target_correct
    if label_action == "go_to_poi" and pred_action == "go_between_pois":
        relaxed_action_correct = True
        relaxed_target_correct = bool(
            set(acceptable_pois) & set(row["pred_poi_numbers"])
        )
    return {
        "action_correct": action_correct,
        "target_correct": target_correct,
        "relaxed_action_correct": relaxed_action_correct,
        "relaxed_target_correct": relaxed_target_correct,
    }


def summarize(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No rows."
    latencies = [float(r["latency_s"]) for r in rows if r.get("latency_s") is not None]
    latency_part = ""
    if latencies:
        sorted_latencies = sorted(latencies)
        p50 = sorted_latencies[len(sorted_latencies) // 2]
        p95 = sorted_latencies[min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))]
        latency_part = (
            f", latency_avg={sum(latencies) / len(latencies):.2f}s"
            f", latency_p50={p50:.2f}s"
            f", latency_p95={p95:.2f}s"
        )
    if "label_action" not in rows[0] or rows[0].get("label_action") is None:
        counts = {}
        for row in rows:
            action = row.get("pred_action")
            counts[action] = counts.get(action, 0) + 1
        return f"rows={len(rows)}, predicted_actions={counts}{latency_part}"
    action_ok = sum(1 for r in rows if r["action_correct"])
    target_ok = sum(1 for r in rows if r["target_correct"])
    relaxed_action_ok = sum(1 for r in rows if r.get("relaxed_action_correct"))
    relaxed_target_ok = sum(1 for r in rows if r.get("relaxed_target_correct"))
    poi_rows = [r for r in rows if r["label_action"] == "go_to_poi"]
    rotate_rows = [r for r in rows if r["label_action"] == "rotate"]
    parts = [
        f"rows={len(rows)}",
        f"action_acc={action_ok}/{len(rows)}={action_ok / len(rows):.3f}",
        f"target_acc={target_ok}/{len(rows)}={target_ok / len(rows):.3f}",
        f"relaxed_action={relaxed_action_ok}/{len(rows)}={relaxed_action_ok / len(rows):.3f}",
        f"relaxed_target={relaxed_target_ok}/{len(rows)}={relaxed_target_ok / len(rows):.3f}",
    ]
    if poi_rows:
        ok = sum(1 for r in poi_rows if r["target_correct"])
        parts.append(f"poi_acc={ok}/{len(poi_rows)}={ok / len(poi_rows):.3f}")
    if rotate_rows:
        ok = sum(1 for r in rotate_rows if r["target_correct"])
        action = sum(1 for r in rotate_rows if r["action_correct"])
        parts.append(
            f"rotate_action={action}/{len(rotate_rows)}={action / len(rotate_rows):.3f}"
        )
        parts.append(f"rotate_dir={ok}/{len(rotate_rows)}={ok / len(rotate_rows):.3f}")
    return ", ".join(parts) + latency_part


def main() -> None:
    args = parse_args()
    config = parse_config(args.config)
    wire = args.api_wire
    if wire == "auto":
        wire = config.get("wire_api", "chat")
    if wire not in {"chat", "responses"}:
        raise SystemExit(f"Unsupported API wire: {wire}")

    model = args.model or config.get("model")
    if not model:
        raise SystemExit("Set --model, VLM_MODEL, or model in config.")
    api_key = (
        os.environ.get(args.api_key_env)
        or os.environ.get("OPENAI_API_KEY")
        or config.get("api_key")
    )
    if not api_key:
        config_hint = f", or pass --config {args.config}" if args.config else ""
        raise SystemExit(f"Set {args.api_key_env} or OPENAI_API_KEY{config_hint}.")
    api_url = args.api_url or endpoint_from_base(config.get("base_url"), wire)

    if args.unlabeled:
        annotations: dict[str, dict[str, Any]] = {}
        samples = load_jsonl(args.manifest)
    else:
        annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
        samples = [s for s in load_jsonl(args.manifest) if s["sample_id"] in annotations]
    if args.sample_ids:
        wanted = set(args.sample_ids)
        samples = [s for s in samples if s["sample_id"] in wanted]
    samples = samples[args.start :]
    if args.limit is not None:
        samples = samples[: args.limit]

    done = load_existing(args.output) if args.resume else set()
    mode = "a" if args.resume else "w"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    if args.resume and args.output.exists():
        with args.output.open("r", encoding="utf-8") as f:
            results = [json.loads(line) for line in f if line.strip()]

    with args.output.open(mode, encoding="utf-8") as f:
        run_started = time.perf_counter()
        for idx, sample in enumerate(samples, 1):
            sample_id = sample["sample_id"]
            if sample_id in done:
                print(f"[{idx}/{len(samples)}] {sample_id} skipped")
                continue
            print(f"[{idx}/{len(samples)}] {sample_id}")
            sample_started = time.perf_counter()
            text, raw = call_vlm(
                api_url,
                api_key,
                sample,
                model,
                wire,
                args.allow_midpoint,
                args.max_tokens,
                args.system_prompt,
                args.disable_thinking,
                args.timeout,
                args.retries,
            )
            latency_s = time.perf_counter() - sample_started
            pred = normalize_prediction(text)
            ann = annotations.get(sample_id, {})
            ann_poi_numbers = as_int_list(ann.get("poi_numbers"))
            if not ann_poi_numbers:
                ann_poi_number = as_int(ann.get("poi_number"))
                if ann_poi_number is not None:
                    ann_poi_numbers = [ann_poi_number]
            row = {
                "sample_id": sample_id,
                "label_action": ann.get("action"),
                "label_poi_number": ann.get("poi_number"),
                "label_poi_numbers": ann_poi_numbers,
                "label_rotate_direction": ann.get("rotate_direction"),
                "label_rotate_angle_deg": ann.get("rotate_angle_deg"),
                **pred,
                "model_content": text,
                "raw_response_id": raw.get("id"),
                "api_wire": wire,
                "allow_midpoint": args.allow_midpoint,
                "latency_s": latency_s,
            }
            if not args.unlabeled:
                row.update(score(row))
            results.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if args.sleep:
                time.sleep(args.sleep)

    elapsed_s = time.perf_counter() - run_started if "run_started" in locals() else 0.0
    print(summarize(results))
    if elapsed_s:
        print(f"Elapsed: {elapsed_s:.2f}s")
    print(f"Predictions: {args.output}")


if __name__ == "__main__":
    main()
