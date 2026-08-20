#!/usr/bin/env python3
"""Verify the configured Qwen endpoint without printing its bearer token."""

import json
import os
import sys
import httpx
from dotenv import load_dotenv


def main() -> int:
    load_dotenv(override=False)
    base_url = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-3B-Instruct").strip()

    placeholder_fragments = ("random-name", "private-random-token", "<", ">", "&lt;", "[", "]", "(", ")")
    if not base_url or not api_key:
        print("LLM_BASE_URL and LLM_API_KEY are missing from .env.", file=sys.stderr)
        return 2
    if any(fragment in base_url or fragment in api_key for fragment in placeholder_fragments):
        print("The .env file contains example/Markdown placeholders. Copy the exact plain-text values printed by Kaggle.", file=sys.stderr)
        return 2
    if not base_url.startswith("https://") or not base_url.endswith("/v1"):
        print("LLM_BASE_URL must look like https://actual-name.trycloudflare.com/v1", file=sys.stderr)
        return 2

    try:
        with httpx.Client(timeout=120) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0.1,
                    "max_tokens": 80,
                    "messages": [{"role": "user", "content": "Reply with exactly: AUTOMATON_LLM_OK"}],
                },
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        print(f"Qwen endpoint test failed: {type(exc).__name__}", file=sys.stderr)
        print("Keep the Kaggle inference notebook running and check that its tunnel URL has not changed.", file=sys.stderr)
        return 1

    print("Qwen endpoint authenticated successfully.")
    print(f"Model response: {content[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
