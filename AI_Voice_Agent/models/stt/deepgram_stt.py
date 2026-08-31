"""Deepgram speech-to-text (online API)."""

from __future__ import annotations

import requests

from ..base import STTBase


class DeepgramSTT(STTBase):
    name = "deepgram"

    def __init__(self, cfg: dict, api_key: str) -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.model = cfg.get("model", "nova-3")

    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> str:
        url = f"https://api.deepgram.com/v1/listen?model={self.model}"
        if self.cfg.get("smart_format"):
            url += "&smart_format=true"
        if language:
            url += f"&language={language}"
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Token {self.api_key}",
                "Content-Type": "audio/webm",
            },
            data=audio_bytes,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", {}).get("channels", [{}])[0].get(
            "alternatives", [{}])[0].get("transcript", "")

    def supported_languages(self) -> list[str] | None:
        return None
