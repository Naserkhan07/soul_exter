"""ElevenLabs text-to-speech (online API) — best multilingual voice quality."""

from __future__ import annotations

from pathlib import Path
import requests

from ..base import TTSBase


class ElevenLabsTTS(TTSBase):
    name = "elevenlabs"

    def __init__(self, cfg: dict, api_key: str) -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.voice = cfg.get("voice", "Rachel")
        self.model = cfg.get("model", "eleven_multilingual_v2")

    def synthesize(self, text: str, language: str = "auto",
                   out_path: str | Path | None = None) -> bytes:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice}"
        resp = requests.post(
            url,
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": self.model,
                "voice_settings": {"stability": 0.6, "similarity_boost": 0.7},
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.content
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(data)
        return data

    def voices_for(self, language: str) -> list[str]:
        return [self.voice]
