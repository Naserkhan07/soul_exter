"""OpenAI Whisper speech-to-text (online API)."""

from __future__ import annotations

import base64
import requests

from ..base import STTBase


class OpenAISTT(STTBase):
    name = "openai"

    def __init__(self, cfg: dict, api_key: str) -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.model = cfg.get("model", "whisper-1")

    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> str:
        files = {"file": ("audio.webm", audio_bytes, "audio/webm")}
        data = {"model": self.model}
        if language:
            data["language"] = language
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files=files,
            data=data,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["text"]

    def supported_languages(self) -> list[str] | None:
        return None


class OpenAIWhisperAPI(OpenAISTT):
    """Same endpoint, convenience alias."""
