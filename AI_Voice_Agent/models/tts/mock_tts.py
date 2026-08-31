"""Mock TTS — no audio; records what WOULD be spoken.

Used for offline testing of the full pipeline. The controller prints the
"spoken" text so you can verify the agent's language and content.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..base import TTSBase


class MockTTS(TTSBase):
    name = "mock"

    def synthesize(self, text: str, language: str = "auto",
                   out_path: str | Path | None = None) -> bytes:
        payload = {"language": language, "text": text}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(data)
        return data

    def voices_for(self, language: str) -> list[str]:
        return ["mock-default"]
