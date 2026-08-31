"""Audio bridge for a live phone conversation.

This module defines the interface the agent uses for two-way phone audio.
Implementations:

  NoneBridge     : mic + speaker (Stage 1).
  LoopbackBridge : route a manual phone call into the agent via virtual audio
                   cable (VB-Cable) on Windows. "You dial, the agent talks."
  TwilioBridge   : Twilio Media Streams (cloud) — config.sip/twilio.
  AudioIfBridge  : physical phone via a USB audio interface / hybrid.

The KEY point: the bridge hands the agent (a) incoming audio chunks that the
STT turns into text, and (b) receives the TTS audio to play into the call.
Everything above this layer is phone-agnostic.
"""

from __future__ import annotations

import logging

log = logging.getLogger("phone.bridge")


class AudioBridge:
    """Base class: streams person audio in, plays agent audio out."""

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def read_audio(self) -> bytes:
        """Next chunk of the person's speech (PCM 16k mono)."""
        raise NotImplementedError

    def write_audio(self, audio: bytes) -> None:
        """Send the agent's speech into the call."""
        raise NotImplementedError


class NoneBridge(AudioBridge):
    """No phone — uses the local mic/speaker. Stage 1."""

    def open(self) -> None:
        log.info("Phone bridge: none (using local microphone + speaker)")

    def close(self) -> None:
        pass

    def read_audio(self) -> bytes:
        raise RuntimeError("No phone bridge configured — run in microphone mode.")

    def write_audio(self, audio: bytes) -> None:
        pass


def build_bridge(cfg: dict) -> AudioBridge:
    bridge = cfg.get("phone", {}).get("bridge", "none")
    if bridge in ("none", "", None):
        return NoneBridge()
    if bridge == "loopback":
        # Returns a factory wrapper; the caller uses .open() then streams.
        from .loopback import LoopbackBridge
        return LoopbackBridge(on_utterance=lambda seg: None,
                              cfg=cfg.get("audio", {}).get("loopback", None))
    if bridge == "twilio":
        from .twilio_bridge import TwilioBridge
        return TwilioBridge(cfg["phone"].get("twilio", {}))
    if bridge == "audio":
        from .audio_interface import AudioIfBridge
        return AudioIfBridge(cfg.get("audio", {}))
    raise ValueError(f"Unknown phone bridge: {bridge}")
