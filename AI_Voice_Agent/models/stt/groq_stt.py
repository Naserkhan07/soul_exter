"""Groq speech-to-text — FREE tier, fast Whisper-large-v3.

Groq offers a free developer tier that includes Whisper for transcription.
Endpoint mirrors OpenAI's, but model names differ:
  whisper-large-v3 / whisper-large-v3-turbo
"""

from __future__ import annotations

import requests

from ..base import STTBase


class GroqSTT(STTBase):
    name = "groq"

    def __init__(self, cfg: dict, api_key: str) -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.model = cfg.get("model", "whisper-large-v3")
        self.base_url = cfg.get("base_url", "https://api.groq.com/openai/v1").rstrip("/")

    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> str:
        files = {"file": ("audio.webm", audio_bytes, "audio/webm")}
        data = {"model": self.model}
        if language:
            data["language"] = language
        resp = requests.post(
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files=files,
            data=data,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["text"]

    def supported_languages(self) -> list[str] | None:
        return None
