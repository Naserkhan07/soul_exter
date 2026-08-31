"""Speaker output (Windows). Requires sounddevice+numpy. Barge-in supported
by returning the player thread so the engine can stop it mid-playback.
"""

from __future__ import annotations

import threading
import numpy as np


class SpeakerOutput:
    def __init__(self, sample_rate: int = 24000, device: int | None = None):
        import sounddevice as sd
        self.sd = sd
        self.sample_rate = sample_rate
        self.device = device
        self._stop = threading.Event()

    def play(self, audio: bytes, sample_rate: int | None = None) -> None:
        """Play raw PCM float32 (or numpy array) audio; returns when done or barge."""
        sr = sample_rate or self.sample_rate
        data = audio if isinstance(audio, np.ndarray) else np.frombuffer(audio, dtype=np.float32)
        self._stop.clear()
        sd_sd = self.sd
        with sd_sd.OutputStream(samplerate=sr, device=self.device, channels=1) as stream:
            # chunked playback so we can abort on barge-in
            chunk = max(1, int(sr * 0.03))
            for i in range(0, len(data), chunk):
                if self._stop.is_set():
                    break
                stream.write(data[i:i + chunk])

    def stop(self) -> None:
        self._stop.set()
