"""Microphone input (Windows). Thin wrapper so it can be swapped for a phone
bridge later without touching the agent. Requires sounddevice+numpy.
"""

from __future__ import annotations

import numpy as np


class MicInput:
    def __init__(self, sample_rate: int = 16000, channels: int = 1,
                 device: int | None = None, chunk_ms: int = 30):
        import sounddevice as sd
        self.sd = sd
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.chunk = max(1, int(sample_rate * chunk_ms / 1000))
        self._stream = None

    def __enter__(self):
        self._stream = self.sd.InputStream(
            samplerate=self.sample_rate, channels=self.channels,
            device=self.device, blocksize=self.chunk,
            dtype="float32", callback=self._cb)
        self._stream.start()
        return self

    def __exit__(self, *a):
        if self._stream:
            self._stream.stop()
            self._stream.close()

    def _cb(self, indata, frames, time_info, status):
        # push to a queue the engine consumes
        self.buffer.append(indata[:, 0].copy())

    def chunks(self):
        self.buffer = []
        return self
