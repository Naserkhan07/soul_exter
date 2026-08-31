"""Model layer — pluggable STT / LLM / TTS interfaces.

Every model runs ONLINE (API-based) so no local GPU is required. Each family
has a "mock" provider that is fully offline and deterministic, which lets the
whole agent run and be tested in a sandbox with no audio hardware.

Factory helpers:
    build_stt(provider_cfg, keys)
    build_llm(provider_cfg, keys)
    build_tts(provider_cfg, keys)
"""

from .base import (
    STTBase, LLMBase, TTSBase, STSBase, STSResult,
    build_stt, build_llm, build_tts, build_sts,
)

__all__ = [
    "STTBase", "LLMBase", "TTSBase", "STSBase", "STSResult",
    "build_stt", "build_llm", "build_tts", "build_sts",
]
