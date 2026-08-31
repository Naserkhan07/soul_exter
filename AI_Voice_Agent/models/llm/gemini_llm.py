"""Google Gemini chat completions (online API)."""

from __future__ import annotations

import requests

from ..base import LLMBase, LLMRequest


class GeminiLLM(LLMBase):
    name = "gemini"

    def __init__(self, cfg: dict, api_key: str) -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.model = cfg.get("gemini", {}).get("model", "gemini-1.5-flash")
        self.base_url = cfg.get("gemini", {}).get(
            "base_url", "https://generativelanguage.googleapis.com/v1beta/models")
        self.temperature = cfg.get("temperature", 0.6)
        self.max_tokens = cfg.get("max_tokens", 300)

    def complete(self, req: LLMRequest) -> str:
        contents = [{"role": "user", "parts": [{"text": req.system}]}]
        for m in req.messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": req.temperature or self.temperature,
                "maxOutputTokens": req.max_tokens or self.max_tokens,
            },
        }
        url = (f"{self.base_url}/{self.model}:generateContent?key={self.api_key}")
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        candidates = resp.json().get("candidates", [])
        if not candidates:
            return ""
        return candidates[0]["content"]["parts"][0]["text"].strip()
