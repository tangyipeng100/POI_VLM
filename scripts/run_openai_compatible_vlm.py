#!/usr/bin/env python3
"""Run VLM decisions for samples produced by build_vlm_choice_dataset.py."""

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
DEFAULT_OUTPUT = ROOT / "vlm_dataset" / "predictions.jsonl"
DEFAULT_CONFIG: Path | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VLM POI choice evaluation.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
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
        help="API shape to use. 'auto' reads wire_api from --config when present.",
    )
    parser.add_argument("--api-key-env", default="VLM_API_KEY")
    parser.add_argument("--model", default=os.environ.get("VLM_MODEL"))
    parser.add_argument(
        "--image-mode",
        choices=["question", "separate"],
        default="question",
        help="Send the composed question image or send front/map images separately.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
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


def load_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def data_url(path: str | Path) -> str:
    image_path = Path(path)
    suffix = image_path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def chat_payload(sample: dict[str, Any], model: str, image_mode: str) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": sample["prompt"]}]
    if image_mode == "question":
        content.append(
            {"type": "image_url", "image_url": {"url": data_url(sample["question_image"])}}
        )
    else:
        content.extend(
            [
                {
                    "type": "image_url",
                    "image_url": {"url": data_url(sample["front_poi_image"])},
                },
                {"type": "image_url", "image_url": {"url": data_url(sample["map_image"])}},
            ]
        )
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 300,
    }


def responses_payload(
    sample: dict[str, Any], model: str, image_mode: str
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": sample["prompt"]}]
    if image_mode == "question":
        content.append(
            {"type": "input_image", "image_url": data_url(sample["question_image"])}
        )
    else:
        content.extend(
            [
                {
                    "type": "input_image",
                    "image_url": data_url(sample["front_poi_image"]),
                },
                {"type": "input_image", "image_url": data_url(sample["map_image"])},
            ]
        )
    return {
        "model": model,
        "store": False,
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": 300,
    }


def parse_answer(text: str) -> int | None:
    try:
        data = json.loads(text)
        answer = data.get("answer")
        if isinstance(answer, int):
            return answer
        if isinstance(answer, str) and answer.strip().isdigit():
            return int(answer.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r'"answer"\s*:\s*"?(\d+)"?', text)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(?:Answer|答案)\s*[:：]\s*(\d+)\b", text, re.I)
    if match:
        return int(match.group(1))
    return None


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
            value = parsed if isinstance(parsed, list) else re.split(r"[,;/\s]+", text)
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


def acceptable_answers(row: dict[str, Any]) -> list[int]:
    for key in ("ground_truth_answers", "acceptable_answers"):
        numbers = as_int_list(row.get(key))
        if numbers:
            return numbers
    answer = as_int(row.get("ground_truth_answer"))
    return [answer] if answer is not None else []


def response_text(data: dict[str, Any], wire: str) -> str:
    if wire == "chat":
        return data["choices"][0]["message"]["content"]

    chunks: list[str] = []
    if data.get("output_text"):
        chunks.append(str(data["output_text"]))
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if content.get("text"):
                chunks.append(str(content["text"]))
    if chunks:
        return "\n".join(chunks).strip()
    return json.dumps(data, ensure_ascii=False)


def call_vlm(
    api_url: str,
    api_key: str,
    sample: dict[str, Any],
    model: str,
    image_mode: str,
    wire: str,
    timeout: float,
) -> tuple[str, dict[str, Any]]:
    if wire == "responses":
        payload = responses_payload(sample, model, image_mode)
    else:
        payload = chat_payload(sample, model, image_mode)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    content = response_text(data, wire)
    return content, data


def summarize(rows: list[dict[str, Any]]) -> str:
    labeled = [r for r in rows if acceptable_answers(r)]
    parsed = [r for r in rows if r.get("predicted_answer") is not None]
    if labeled:
        correct = [
            r
            for r in labeled
            if r.get("predicted_answer") in acceptable_answers(r)
        ]
        accuracy = len(correct) / len(labeled)
        return (
            f"Parsed={len(parsed)}/{len(rows)}, "
            f"labeled={len(labeled)}, correct={len(correct)}, accuracy={accuracy:.3f}"
        )
    return f"Parsed={len(parsed)}/{len(rows)}. No ground-truth labels yet."


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
        raise SystemExit("Set --model or VLM_MODEL.")

    api_key = (
        os.environ.get(args.api_key_env)
        or os.environ.get("OPENAI_API_KEY")
        or config.get("api_key")
    )
    if not api_key:
        config_hint = f", or pass --config {args.config}" if args.config else ""
        raise SystemExit(f"Set {args.api_key_env} or OPENAI_API_KEY{config_hint}.")

    api_url = args.api_url or endpoint_from_base(config.get("base_url"), wire)

    samples = load_jsonl(args.manifest, args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    with args.output.open("w", encoding="utf-8") as f:
        for idx, sample in enumerate(samples, 1):
            print(f"[{idx}/{len(samples)}] {sample['sample_id']}")
            content, raw = call_vlm(
                api_url,
                api_key,
                sample,
                model,
                args.image_mode,
                wire,
                args.timeout,
            )
            predicted = parse_answer(content)
            row = {
                "sample_id": sample["sample_id"],
                "predicted_answer": predicted,
                "ground_truth_answer": sample.get("ground_truth_answer"),
                "ground_truth_answers": sample.get("ground_truth_answers")
                or sample.get("acceptable_answers"),
                "heuristic_answer": sample.get("heuristic_answer"),
                "model_content": content,
                "raw_response_id": raw.get("id"),
                "api_wire": wire,
            }
            results.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if args.sleep:
                time.sleep(args.sleep)

    print(summarize(results))
    print(f"Predictions: {args.output}")


if __name__ == "__main__":
    main()
