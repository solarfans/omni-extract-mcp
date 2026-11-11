#!/usr/bin/env python3
"""
OmniExtract Apify Actor Entrypoint (Pay-Per-Event & x402 Agent Ready)
Supports both local Apify storage directories and Apify Cloud REST APIs without heavy SDK overhead.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.request
from typing import Any

from omni_extract.engine import OmniExtractEngine


def _load_apify_input() -> dict[str, Any]:
    # 1. Explicit JSON string in env
    raw_env = os.environ.get("APIFY_INPUT_JSON", "").strip()
    if raw_env:
        return json.loads(raw_env)

    # 2. Local Apify key-value store file
    storage_dir = Path(os.environ.get("APIFY_LOCAL_STORAGE_DIR", "./storage"))
    input_key = os.environ.get("APIFY_INPUT_KEY", "INPUT")
    for candidate in (
        storage_dir / "key_value_stores" / "default" / f"{input_key}.json",
        storage_dir / "key_value_stores" / "default" / input_key,
        Path("/apify_input/INPUT.json"),
    ):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))

    # 3. Apify Cloud API Key-Value Store
    kv_store_id = os.environ.get("APIFY_DEFAULT_KEY_VALUE_STORE_ID", "").strip()
    token = os.environ.get("APIFY_TOKEN", "").strip()
    api_base = os.environ.get("APIFY_API_PUBLIC_BASE_URL", "https://api.apify.com").rstrip("/")
    if kv_store_id and token:
        url = f"{api_base}/v2/key-value-stores/{kv_store_id}/records/{input_key}?token={token}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    return {}


def _push_apify_dataset_items(items: list[dict[str, Any]]) -> Path:
    """Save output items to local Apify default dataset AND push to Apify Cloud Dataset if running on Apify."""
    storage_dir = Path(os.environ.get("APIFY_LOCAL_STORAGE_DIR", "./storage"))
    ds_dir = storage_dir / "datasets" / "default"
    ds_dir.mkdir(parents=True, exist_ok=True)

    for idx, item in enumerate(items, start=1):
        out_path = ds_dir / f"{idx:09d}.json"
        out_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")

    dataset_id = os.environ.get("APIFY_DEFAULT_DATASET_ID", "").strip()
    token = os.environ.get("APIFY_TOKEN", "").strip()
    api_base = os.environ.get("APIFY_API_PUBLIC_BASE_URL", "https://api.apify.com").rstrip("/")
    if dataset_id and token:
        url = f"{api_base}/v2/datasets/{dataset_id}/items?token={token}"
        payload = json.dumps(items, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20):
            pass

    return ds_dir


def _charge_apify_ppe_event(event_name: str, count: int = 1) -> bool:
    """Trigger Apify Pay-Per-Event (PPE) charging API when running inside Apify Cloud."""
    run_id = os.environ.get("APIFY_ACTOR_RUN_ID", "").strip()
    token = os.environ.get("APIFY_TOKEN", "").strip()
    api_base = os.environ.get("APIFY_API_PUBLIC_BASE_URL", "https://api.apify.com").rstrip("/")
    if not (run_id and token):
        return False
    try:
        url = f"{api_base}/v2/actor-runs/{run_id}/charge?token={token}"
        payload = json.dumps({"eventName": event_name, "count": count}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def run_actor(custom_input: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    actor_input = custom_input if custom_input is not None else _load_apify_input()

    urls: list[str] = []
    if isinstance(actor_input.get("url"), str) and actor_input["url"].strip():
        urls.append(actor_input["url"].strip())
    if isinstance(actor_input.get("urls"), list):
        for item in actor_input["urls"]:
            if isinstance(item, str) and item.strip():
                urls.append(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"].strip():
                urls.append(item["url"].strip())

    if not urls:
        raise ValueError("Actor input must provide 'url' (string) or 'urls' (array of URLs).")

    include_transcript = bool(actor_input.get("include_transcript", True))
    use_cache = bool(actor_input.get("use_cache", True))

    engine = OmniExtractEngine(enforce_billing=False)
    results = engine.extract_batch(
        urls=urls,
        include_transcript=include_transcript,
        use_cache=use_cache,
        client_id="apify_actor",
    )

    # Trigger Pay-Per-Event billing for each successful item
    for item in results:
        if item.get("ok"):
            event_name = (
                "video_transcript_extracted"
                if item.get("transcript")
                else "content_item_extracted"
            )
            charged = _charge_apify_ppe_event(event_name=event_name, count=1)
            item["apify_ppe_event"] = event_name
            item["apify_ppe_charged"] = charged

    _push_apify_dataset_items(results)
    return results


def main() -> int:
    try:
        results = run_actor()
        ok_count = sum(1 for r in results if r.get("ok"))
        print(
            json.dumps(
                {
                    "status": "SUCCEEDED",
                    "total_requested": len(results),
                    "succeeded": ok_count,
                    "failed": len(results) - ok_count,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as e:
        print(json.dumps({"status": "FAILED", "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
