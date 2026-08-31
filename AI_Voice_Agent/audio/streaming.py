"""Streaming voice engine (real audio path — Windows).

This is the Stage-1 hardware loop:

    mic -> VAD -> (speech segment) -> on_utterance(text) -> tts -> speaker

with a barge-in thread that stops playback when the mic hears speech.

Requires: sounddevice + numpy (see requirements-audio.txt). The `_MockEngine`
below is used when no audio hardware is present so the app still starts.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

CHUNK = 512  # samples (~32ms @16k)


@dataclass
class VoiceEngineConfig:
    sample_rate: int = 16000
    energy_threshold: float = 0.03
    min_silence_ms: int = 700
    barge_in: bool = True
    barge_sensitivity: float = 0.55


class StreamingVoiceEngine:
    def __init__(self, on_utterance: Callable[[str], None],
                 on_start: Callable[[], None] | None = None,
                 on_end: Callable[[], None] | None = None,
                 cfg: VoiceEngineConfig | None = None):
        self.cfg = cfg or VoiceEngineConfig()
        self.on_utterance = on_utterance
        self.on_start = on_start or (lambda: None)
        self.on_end = on_end or (lambda: None)
        self._speaking = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- public API ----
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.interrupt_playback()

    def speak(self, audio_bytes: bytes) -> None:
        """Play generated audio on the speaker (with barge-in)."""
        self._speaking.set()
        try:
            self._play(audio_bytes)
        finally:
            self._speaking.clear()

    def interrupt_playback(self) -> None:
        self._barge()

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    # ---- implement in a real audio backend ----
    def _run(self) -> None:
        """Continuously read mic chunks, run VAD, fire on_utterance."""
        raise NotImplementedError("Real audio requires sounddevice (see requirements-audio.txt)")

    def _play(self, audio_bytes: bytes) -> None:
        raise NotImplementedError

    def _barge(self) -> None:
        pass


class _MockEngine(StreamingVoiceEngine):
    """Used when sounddevice is unavailable — engine exists but no audio."""

    def start(self) -> None:
        self.on_start()

    def _run(self) -> None:
        pass

    def _play(self, audio_bytes: bytes) -> None:
        pass


def build_engine(on_utterance: Callable[[str], None], cfg: dict) -> StreamingVoiceEngine:
    """Return a real or mock voice engine depending on installed deps."""
    try:
        import sounddevice  # noqa: F401
        return StreamingVoiceEngine(on_utterance, cfg=VoiceEngineConfig(**{
            k: v for k, v in cfg.items()
            if k in VoiceEngineConfig.__dataclass_fields__}))
    except ImportError:
        return _MockEngine(on_utterance)
