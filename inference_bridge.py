#!/usr/bin/env python3
"""Provider-neutral bridge for structured POI-VLM inference.

The bridge sends one composed question image to an OpenAI-compatible endpoint.
It supports Chat Completions and Responses-shaped APIs, keeps credentials in
environment variables, retries transient failures, and extracts a structured
action without writing raw provider payloads to disk.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_PROMPT = """You are the local navigation decision module of an outdoor robot.
The image contains two panels: numbered front-view POI candidates on the left
and a top-down route cue on the right. Choose a feasible action consistent with
the route direction.

Return only JSON using this schema:
{"action":"go_to_poi|rotate|skip","poi_number":1,"rotate_direction":"left|right|null","rotate_angle_deg":30,"reason":"short reason"}
"""


def endpoint_from_base(base_url: str, wire: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions") or url.endswith("/responses"):
        return url
    suffix = "responses" if wire == "responses" else "chat/completions"
    return f"{url}/{suffix}" if url.endswith("/v1") else f"{url}/v1/{suffix}"


def image_data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_payload(image_urls: str | list[str], prompt: str, model: str, wire: str, max_tokens: int) -> dict[str, Any]:
    urls = [image_urls] if isinstance(image_urls, str) else image_urls
    image_items = [
        {"type": "input_image", "image_url": url} if wire == "responses"
        else {"type": "image_url", "image_url": {"url": url}}
        for url in urls
    ]
    if wire == "responses":
        return {
            "model": model,
            "store": False,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                *image_items,
            ]}],
            "max_output_tokens": max_tokens,
        }
    return {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
                *image_items,
        ]}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }


def response_text(data: dict[str, Any], wire: str) -> str:
    if wire == "chat":
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        return str(content)
    if data.get("output_text"):
        return str(data["output_text"])
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks).strip()


def parse_decision(text: str) -> dict[str, Any]:
    """Parse a small action object, tolerating markdown JSON fences."""
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.I | re.S)
    if fenced:
        cleaned = fenced.group(1).strip()
    candidates = [cleaned]
    object_match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if object_match:
        candidates.append(object_match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            action = str(value.get("action", "")).strip()
            poi = value.get("poi_number")
            if isinstance(poi, str) and poi.strip().isdigit():
                poi = int(poi.strip())
            decision = {"action": action or "unparsed", "poi_number": poi, "reason": str(value.get("reason", "")).strip()}
            if "rotate_direction" in value:
                decision["rotate_direction"] = value.get("rotate_direction")
            if "rotate_angle_deg" in value:
                decision["rotate_angle_deg"] = value.get("rotate_angle_deg")
            if "poi_numbers" in value:
                decision["poi_numbers"] = value.get("poi_numbers")
            return decision
    return {"action": "unparsed", "poi_number": None, "reason": cleaned[:500]}


def request_json(endpoint: str, api_key: str, payload: dict[str, Any], timeout: float, retries: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(2.0 ** attempt, 8.0))
    raise RuntimeError(f"VLM request failed after {retries + 1} attempt(s): {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, nargs="+", help="One composed image, or front POI and map images in order.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--model", default=os.environ.get("VLM_MODEL"))
    parser.add_argument("--base-url", default=os.environ.get("VLM_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--api-url", default=os.environ.get("VLM_API_URL"))
    parser.add_argument("--wire", choices=["chat", "responses"], default=os.environ.get("VLM_API_WIRE", "chat"))
    parser.add_argument("--api-key-env", default="VLM_API_KEY")
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", help="Print request metadata without calling a provider.")
    parser.add_argument("--output", type=Path, help="Optional path for the parsed decision JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    missing = [path for path in args.image if not path.is_file()]
    if missing:
        raise SystemExit("Image does not exist: " + ", ".join(str(path) for path in missing))
    if not args.model:
        raise SystemExit("Set --model or VLM_MODEL.")
    endpoint = args.api_url or endpoint_from_base(args.base_url, args.wire)
    payload = build_payload([image_data_url(path) for path in args.image], args.prompt, args.model, args.wire, args.max_tokens)
    if args.dry_run:
        content = payload["messages"][0]["content"] if args.wire == "chat" else payload["input"][0]["content"]
        print(json.dumps({"endpoint": endpoint, "wire": args.wire, "model": args.model, "image_count": len(args.image), "image_bytes": sum(path.stat().st_size for path in args.image), "content_items": [item.get("type") for item in content]}, indent=2))
        return

    api_key = os.environ.get(args.api_key_env) or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(f"Set {args.api_key_env} or OPENAI_API_KEY, or use --dry-run.")
    raw = request_json(endpoint, api_key, payload, args.timeout, args.retries)
    decision = parse_decision(response_text(raw, args.wire))
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
