"""Google Gemini speech-to-text using the free-tier API.

Sends the captured WAV chunk as inline audio and asks the multimodal model to
transcribe it. No extra dependencies beyond `requests`. A free API key works
(Google AI Studio -> https://aistudio.google.com/apikey). Models with audio
input (e.g. gemini-1.5-flash / gemini-2.0-flash) understand many languages, so
this is a good free "hearing" step for the three-stage pipeline.
"""

from __future__ import annotations

import base64
import requests

from ..base import STTBase


class GeminiSTT(STTBase):
    name = "gemini"

    def __init__(self, cfg: dict, api_key: str) -> None:
        self.cfg = cfg
        self.api_key = api_key
        self.model = cfg.get("model", "gemini-1.5-flash")
        self.mime_type = cfg.get("mime_type", "audio/wav")
        self.language = cfg.get("language", "")   # optional, e.g. "en" or "hi"
        self.base_url = cfg.get(
            "base_url",
            "https://generativelanguage.googleapis.com/v1beta/models",
        )

    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> str:
        lang = language or self.language or None
        instruction = (
            "Transcribe the spoken audio to text exactly as heard. "
            "Output ONLY the transcribed text with no preamble."
        )
        if lang and lang != "auto":
            instruction += f" The speech is in language: {lang}."

        parts = [{"text": instruction}]
        parts.append({
            "inline_data": {
                "mime_type": self.mime_type,
                "data": base64.b64encode(audio_bytes).decode("ascii"),
            },
        })

        payload = {"contents": [{"parts": parts}]}
        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        candidates = resp.json().get("candidates", [])
        if not candidates:
            return ""
        text = "".join(
            p.get("text", "")
            for p in candidates[0]["content"]["parts"]
            if p.get("text")
        )
        return text.strip()

    def supported_languages(self) -> list[str] | None:
        return None
