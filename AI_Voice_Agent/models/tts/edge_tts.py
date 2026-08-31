"""Microsoft Edge text-to-speech — FREE, 100+ neural voices, many languages.

Uses the community `edge-tts` library (pip install edge-tts). Great default
for a fully free pipeline. Returns MP3 bytes.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from ..base import TTSBase

# Default neural voices per language (override in config `tts.edge.voice`).
_DEFAULT_VOICES = {
    "en": "en-US-AriaNeural", "en-IN": "en-IN-NeerjaNeural",
    "hi": "hi-IN-SwaraNeural", "ur": "ur-PK-UzmaNeural",
    "ar": "ar-SA-ZariyahNeural", "te": "te-IN-ShrutiNeural",
    "ta": "ta-IN-PallaviNeural", "bn": "bn-BD-NabanitaNeural",
    "es": "es-ES-ElviraNeural", "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural", "pt": "pt-BR-FranciscaNeural",
    "ru": "ru-RU-SvetlanaNeural", "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural", "zh": "zh-CN-XiaoxiaoNeural",
    "nl": "nl-NL-ColetteNeural", "it": "it-IT-ElsaNeural",
}


def _pick_voice(cfg_voice: str, language: str) -> str:
    if cfg_voice and cfg_voice.strip():
        return cfg_voice
    base = language.split("-")[0]
    if language in _DEFAULT_VOICES:
        return _DEFAULT_VOICES[language]
    return _DEFAULT_VOICES.get(base, "en-US-AriaNeural")


class EdgeTTS(TTSBase):
    name = "edge"

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.voice = cfg.get("voice", "")
        self.rate = cfg.get("rate", "+0%")

    def synthesize(self, text: str, language: str = "auto",
                   out_path: str | Path | None = None) -> bytes:
        import edge_tts  # imported lazily so mock mode needs no extra deps
        voice = _pick_voice(self.voice, language)
        communicate = edge_tts.Communicate(text, voice=voice, rate=self.rate)
        buf = io.BytesIO()

        async def _run() -> None:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])

        asyncio.run(_run())
        data = buf.getvalue()
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(data)
        return data

    def voices_for(self, language: str) -> list[str]:
        v = _pick_voice(self.voice, language)
        return [v]
