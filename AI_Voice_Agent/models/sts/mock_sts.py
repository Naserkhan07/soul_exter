"""Mock Speech-to-Speech — offline, deterministic.

For text-mode testing with no audio/GPU: set the "recognised" transcript via
set_transcript(), and it returns the MockLLM reply text. Audio bytes are empty
(or a small marker) because there is no real TTS in mock mode.
"""

from __future__ import annotations

from ..base import STSBase, STSResult
from ..llm.mock_llm import MockLLM


class MockSTS(STSBase):
    name = "mock"

    def __init__(self) -> None:
        self._llm = MockLLM()
        self._transcript = ""

    def set_transcript(self, text: str) -> None:
        """Simulate that the model heard this speech."""
        self._transcript = text

    def converse(self, audio_bytes: bytes, system_prompt: str,
                 history: list[dict]) -> STSResult:
        from ..base import LLMRequest
        user_text = self._transcript
        reply = self._llm.complete(LLMRequest(
            system=system_prompt,
            messages=history + [{"role": "user", "content": user_text}],
            language="auto",
        ))
        return STSResult(text=user_text, reply_text=reply,
                         audio=b"<mock-audio>", language="auto")
