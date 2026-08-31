"""Groq chat completions (online, very fast — good for low latency)."""

from __future__ import annotations

import requests

from ..base import LLMBase, LLMRequest


class GroqLLM(LLMBase):
    name = "groq"

    def __init__(self, cfg: dict, api_key: str) -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.model = cfg.get("groq", {}).get("model", "llama-3.3-70b-versatile")
        self.base_url = cfg.get("groq", {}).get("base_url", "https://api.groq.com/openai/v1").rstrip("/")
        self.temperature = cfg.get("temperature", 0.6)
        self.max_tokens = cfg.get("max_tokens", 300)

    def complete(self, req: LLMRequest) -> str:
        messages = [{"role": "system", "content": req.system}] + req.messages
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": req.temperature or self.temperature,
            "max_tokens": req.max_tokens or self.max_tokens,
        }
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
