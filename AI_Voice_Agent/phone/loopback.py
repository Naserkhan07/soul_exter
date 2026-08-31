"""Loopback audio bridge — route a live call into the agent (no VB-Cable needed).

This is the "you dial, the agent talks" free workflow with two audio paths:

    HEAR the person  (capture_mode = "system_loopback")
        The call's audio plays through your laptop's speakers/system output.
        We record the SYSTEM audio (WASAPI loopback) to capture the person's
        voice — no virtual cable required.

    SPEAK to the person  (output_device = USB audio device)
        The agent's reply plays out a USB audio device connected to your phone,
        so the person on the call hears it.

Alternatively you can keep capture_mode = "device" and use a virtual cable or
a specific input device id.

On Windows this needs:
    - pip install -r requirements-audio.txt   (sounddevice, numpy, soundfile,
                                               soundcard for system loopback)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

log = logging.getLogger("phone.loopback")

CHUNK = 512  # samples per block (~32ms @16k)


@dataclass
class LoopbackConfig:
    capture_mode: str = "system_loopback"   # "system_loopback" | "device"
    input_device: int | None = None         # used only when capture_mode == "device"
    output_device: int | None = None        # USB audio device the AGENT speaks into
    sample_rate: int = 16000                # capture sample rate
    output_sample_rate: int = 24000         # playback sample rate
    # VAD
    energy_threshold: float = 0.02
    min_speech_ms: int = 350
    min_silence_ms: int = 800
    # barge-in
    barge_in: bool = True
    barge_sensitivity: float = 0.55


def list_devices() -> list[str]:
    """Print available audio devices to help pick input/output device ids."""
    import sounddevice as sd
    rows = []
    for i, d in enumerate(sd.query_devices()):
        kind = []
        if d["max_input_channels"] > 0:
            kind.append("IN")
        if d["max_output_channels"] > 0:
            kind.append("OUT")
        rows.append(f"  [{i}] {d['name']}  ({'/'.join(kind)})")
    return rows


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if samples.size else 0.0


def decode_audio_to_float32(audio_bytes: bytes) -> tuple[np.ndarray, int]:
    """Decode TTS audio (mp3/wav/etc.) to (float32 mono samples, sample_rate)."""
    import io
    import soundfile as sf
    data, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


# ---------------------------------------------------------------------------
# Audio sources (both feed the same VAD/segment logic via feed(samples))
# ---------------------------------------------------------------------------
class _DeviceSource:
    """Read from a specific input device (virtual cable / USB in)."""

    def __init__(self, cfg: LoopbackConfig):
        self.cfg = cfg

    def start(self, feed: Callable[[np.ndarray], None]) -> None:
        import sounddevice as sd
        self.sd = sd
        self.feed = feed
        self.stream = sd.InputStream(
            samplerate=self.cfg.sample_rate, channels=1, dtype="float32",
            device=self.cfg.input_device, blocksize=CHUNK, callback=self._cb)
        self.stream.start()

    def _cb(self, indata, frames, time_info, status):
        arr = np.asarray(indata)
        samples = arr[:, 0].copy() if arr.ndim == 2 else arr.copy()
        self.feed(samples)

    def stop(self) -> None:
        if getattr(self, "stream", None):
            self.stream.stop()
            self.stream.close()


class _SystemLoopbackSource:
    """Capture what the SYSTEM is playing (WASAPI loopback) — the person's voice.

    Uses the `soundcard` library which supports WASAPI loopback on Windows.
    No virtual cable needed: we record the default speaker output.
    """

    def __init__(self, cfg: LoopbackConfig):
        self.cfg = cfg
        self._thread: threading.Thread | None = None

    def start(self, feed: Callable[[np.ndarray], None]) -> None:
        import soundcard as sc
        self.feed = feed
        speaker = sc.default_speaker()
        # A "microphone" that records the speaker's output (loopback).
        self.mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        self.recorder = self.mic.recorder(samplerate=self.cfg.sample_rate, channels=1)
        self.recorder.start()
        log.info("System loopback capture on speaker: %s", speaker.name)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while not getattr(self, "_stopped", False):
                data = self.recorder.record(numframes=CHUNK)
                if data is None or len(data) == 0:
                    continue
                samples = np.asarray(data)
                samples = samples[:, 0] if samples.ndim == 2 else samples
                self.feed(np.ascontiguousarray(samples.astype(np.float32)))
        except Exception as e:  # pragma: no cover
            log.warning("System loopback stopped: %s", e)

    def stop(self) -> None:
        self._stopped = True
        try:
            self.recorder.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# The bridge
# ---------------------------------------------------------------------------
class LoopbackBridge:
    """Streaming two-way audio bridge with VAD segmentation and barge-in."""

    def __init__(self, on_utterance: Callable[[np.ndarray], None],
                 on_transcript: Callable[[str], None] | None = None,
                 cfg: LoopbackConfig | None = None):
        self.cfg = cfg or LoopbackConfig()
        self.on_utterance = on_utterance   # gets a speech segment (float32 @16k)
        self.on_transcript = on_transcript or (lambda text: None)
        self._speaking = threading.Event()
        self._stop = threading.Event()
        self._buf: list[np.ndarray] = []
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self.min_speech_frames = int(self.cfg.min_speech_ms / 1000 * self.cfg.sample_rate / CHUNK + 1)
        self.min_silence_frames = int(self.cfg.min_silence_ms / 1000 * self.cfg.sample_rate / CHUNK + 1)
        self._source = None

    # ---------------- lifecycle ----------------
    def open(self) -> None:
        import sounddevice as sd
        self.sd = sd
        if self.cfg.capture_mode == "system_loopback":
            self._source = _SystemLoopbackSource(self.cfg)
        else:
            self._source = _DeviceSource(self.cfg)
        self._source.start(self._feed_chunk)
        log.info("Loopback open. capture_mode=%s input=%s output=%s",
                 self.cfg.capture_mode, self.cfg.input_device, self.cfg.output_device)

    def close(self) -> None:
        self._stop.set()
        if self._source:
            self._source.stop()

    # ---------------- shared chunk feed: VAD + segment detection ----
    def _feed_chunk(self, samples: np.ndarray) -> None:
        if self._stop.is_set():
            return
        loud = _rms(samples) >= self.cfg.energy_threshold
        if loud:
            self._speech_run += 1
            self._silence_run = 0
            self._buf.append(samples)
            if not self._in_speech and self._speech_run >= self.min_speech_frames:
                self._in_speech = True
        else:
            self._silence_run += 1
            if self._in_speech and self._silence_run >= self.min_silence_frames:
                self._in_speech = False
                self._flush_segment()
            elif not self._in_speech:
                self._buf = self._buf[-4:]  # small pre-roll

    def _flush_segment(self) -> None:
        if not self._buf:
            return
        seg = np.concatenate(self._buf)
        self._buf = []
        self._speech_run = 0
        threading.Thread(target=self._handle_segment, args=(seg,), daemon=True).start()

    def _handle_segment(self, seg: np.ndarray) -> None:
        try:
            self.on_utterance(seg)
        except Exception as e:  # pragma: no cover
            log.exception("Error handling utterance: %s", e)

    # ---------------- agent speak: with barge-in ----------------
    def speak(self, pcm_bytes: bytes, sample_rate: int) -> None:
        """Play the agent's reply on the output device; abort if person talks.

        `pcm_bytes` is raw float32 PCM. For decoded audio use play_samples().
        """
        if len(pcm_bytes) < 4:
            return
        data = np.frombuffer(pcm_bytes, dtype=np.float32)
        self.play_samples(data, sample_rate)

    def play_samples(self, samples: np.ndarray, sample_rate: int) -> None:
        """Play decoded float32 samples with barge-in on the output device."""
        if self.cfg.output_device is None:
            log.warning("No output device set — agent reply not played into call.")
            return
        data = np.ascontiguousarray(samples.astype(np.float32))
        self._speaking.set()
        try:
            chunk = max(1, int(sample_rate * 0.03))
            with self.sd.OutputStream(samplerate=sample_rate, channels=1,
                                      dtype="float32",
                                      device=self.cfg.output_device) as out:
                for i in range(0, len(data), chunk):
                    if self._stop.is_set() or self._barge_triggered():
                        log.info("Barge-in: agent stopped speaking.")
                        break
                    out.write(data[i:i + chunk])
        finally:
            self._speaking.clear()

    def _barge_triggered(self) -> bool:
        if not self.cfg.barge_in:
            return False
        # If capture energy is high while we're speaking, assume the person talked.
        buf = self._buf
        if not buf:
            return False
        recent = np.concatenate(buf[-4:])
        return _rms(recent) >= self.cfg.barge_sensitivity

    def is_speaking(self) -> bool:
        return self._speaking.is_set()
