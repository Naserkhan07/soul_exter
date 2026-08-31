"""Voice Activity Detection.

`energy`   : built-in RMS-based, no extra deps (default).
`silero`   : more accurate neural VAD — needs torch + silero package.

Energy VAD here is a pure-python reference for testing. On Windows, the
streaming engine uses real samples from the mic; in text mode it is unused.
"""

from __future__ import annotations

import math


def _rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class EnergyVAD:
    """Detects speech-vs-silence from a stream of float samples [-1, 1]."""

    def __init__(self, threshold: float = 0.03,
                 min_speech_ms: int = 350, min_silence_ms: int = 700,
                 sample_rate: int = 16000):
        self.threshold = threshold
        self.min_speech_frames = int(min_speech_ms / 1000 * sample_rate / 512 + 1)
        self.min_silence_frames = int(min_silence_ms / 1000 * sample_rate / 512 + 1)
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0

    def push_chunk(self, samples: list[float]) -> str:
        """Feed a ~512-sample chunk; returns 'speech' | 'silence' | 'segment_end'."""
        loud = _rms(samples) >= self.threshold
        if loud:
            self._speech_run += 1
            self._silence_run = 0
            if not self._in_speech and self._speech_run >= self.min_speech_frames:
                self._in_speech = True
            return "speech"
        else:
            self._silence_run += 1
            if self._in_speech and self._silence_run >= self.min_silence_frames:
                self._in_speech = False
                self._speech_run = 0
                self._silence_run = 0
                return "segment_end"
            return "silence"
