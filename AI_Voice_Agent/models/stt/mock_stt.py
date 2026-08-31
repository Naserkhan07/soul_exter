"""Mock STT — offline, used for testing the pipeline with no audio hardware.

In text mode the controller injects the typed text as the recognised
transcript via `set_transcript`. This keeps the agent pipeline identical to a
real mic: STT produces text -> LLM -> TTS.
"""

from __future__ import annotations

from ..base import STTBase


class MockSTT(STTBase):
    name = "mock"

    def __init__(self) -> None:
        self._transcript = ""

    def set_transcript(self, text: str) -> None:
        """Simulate that the microphone heard this speech."""
        self._transcript = text

    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> str:
        return self._transcript

    def supported_languages(self) -> list[str] | None:
        return None  # any
