"""OpenAI text-to-speech (online API)."""

from __future__ import annotations

from pathlib import Path
import requests

from ..base import TTSBase


class OpenAITTS(TTSBase):
    name = "openai"

    def __init__(self, cfg: dict, api_key: str) -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.model = cfg.get("model", "gpt-4o-mini-tts")
        self.voice = cfg.get("voice", "alloy")
        self.fmt = cfg.get("output_format", "mp3")

    def synthesize(self, text: str, language: str = "auto",
                   out_path: str | Path | None = None) -> bytes:
        resp = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "voice": self.voice,
                  "input": text, "response_format": self.fmt},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.content
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(data)
        return data

    def voices_for(self, language: str) -> list[str]:
        return ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
