"""OpenAI-compatible client for the council seats + safe JSON extraction.

Any provider that speaks the /chat/completions dialect works: OpenRouter,
Together, Groq, DeepSeek, Mistral, a local Ollama or a private vLLM box.
If a seat has no key (or the call fails) the caller falls back to the built-in
analyst engine, so the council never stops deliberating.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from .registry import PROVIDER_BASE_URLS, LLMSeat

_JSON_RE = re.compile(r"\{.*\}", re.S)


def extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            try:
                return json.loads(m.group(0).replace("'", '"'))
            except Exception:
                return None
    return None


class LLMClient:
    def __init__(self, timeout: float = 28.0) -> None:
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self.stats: Dict[str, Any] = dict(calls=0, failures=0, last_error="", last_latency_ms=0)

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=8.0),
                                             headers={"User-Agent": "soul-exter/1.0"})
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def base_url(self, seat: LLMSeat) -> str:
        return (seat.base_url or PROVIDER_BASE_URLS.get(seat.provider, "")).rstrip("/")

    async def chat(self, seat: LLMSeat, messages: List[Dict[str, str]],
                   json_mode: bool = True) -> Optional[str]:
        if not seat.live():
            return None
        base = self.base_url(seat)
        if not base:
            return None
        url = f"{base}/chat/completions"
        payload: Dict[str, Any] = dict(model=seat.model, messages=messages,
                                       temperature=seat.temperature, max_tokens=900)
        if json_mode and seat.provider in ("openai", "together", "groq", "deepseek", "mistral"):
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        key = seat.key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        t0 = time.time()
        try:
            client = await self._http()
            r = await client.post(url, json=payload, headers=headers)
            self.stats["calls"] += 1
            self.stats["last_latency_ms"] = int((time.time() - t0) * 1000)
            if r.status_code >= 400:
                self.stats["failures"] += 1
                self.stats["last_error"] = f"{seat.provider} {r.status_code}: {r.text[:180]}"
                return None
            data = r.json()
            msg = (data.get("choices") or [{}])[0].get("message", {})
            return msg.get("content") or ""
        except Exception as exc:  # network, DNS, timeout…
            self.stats["failures"] += 1
            self.stats["last_error"] = f"{type(exc).__name__}: {exc}"
            return None

    async def chat_json(self, seat: LLMSeat, messages: List[Dict[str, str]]) -> Optional[dict]:
        raw = await self.chat(seat, messages, json_mode=True)
        if raw is None:
            return None
        return extract_json(raw)


CLIENT = LLMClient()
