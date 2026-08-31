"""Base classes and factory for model interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Speech-to-Text
# --------------------------------------------------------------------------
class STTBase(ABC):
    """Converts speech audio bytes -> transcript text."""

    name = "base-stt"

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, language: str | None = None) -> str:
        """Transcribe a WAV/FLAC/MP3 chunk of speech to text."""

    @abstractmethod
    def supported_languages(self) -> list[str] | None:
        """List of supported BCP-47 language codes, or None if all."""


# --------------------------------------------------------------------------
# Language model
# --------------------------------------------------------------------------
@dataclass
class LLMRequest:
    system: str
    messages: list[dict]
    language: str = "auto"
    max_tokens: int = 300
    temperature: float = 0.6


class LLMBase(ABC):
    """Given a system prompt + conversation, produces the agent's reply text."""

    name = "base-llm"

    @abstractmethod
    def complete(self, req: LLMRequest) -> str:
        """Return the assistant reply as plain text."""


# --------------------------------------------------------------------------
# Text-to-Speech
# --------------------------------------------------------------------------
class TTSBase(ABC):
    """Converts reply text -> audio file bytes for playback."""

    name = "base-tts"

    @abstractmethod
    def synthesize(self, text: str, language: str = "auto",
                   out_path: str | Path | None = None) -> bytes:
        """Return audio bytes (format depends on provider). Optionally write to out_path."""

    @abstractmethod
    def voices_for(self, language: str) -> list[str]:
        """Voices available for a language code (for mapping)."""


# --------------------------------------------------------------------------
# Speech-to-Speech (one-model architecture)
# --------------------------------------------------------------------------
@dataclass
class STSResult:
    """Result of a speech-to-speech turn.

    text      : the speech the model understood (person's words), if returned
    reply_text: the agent's reply as text (for logging/transcript)
    audio     : the agent's spoken audio bytes
    language  : detected language
    """
    text: str = ""
    reply_text: str = ""
    audio: bytes = b""
    language: str = "auto"


class STSBase(ABC):
    """A single model that takes speech in and produces speech out.

    This is the "speech-to-speech" architecture you asked for (e.g. a Qwen
    Omni model). It replaces the three-stage STT + LLM + TTS pipeline with one
    call: person audio -> (understood text, agent speech audio).
    """

    name = "base-sts"

    @abstractmethod
    def converse(self, audio_bytes: bytes, system_prompt: str,
                 history: list[dict]) -> STSResult:
        """Send one person utterance; returns the agent's reply (text + audio)."""


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------
def _require_keys(keys: dict[str, str]) -> str:
    missing = [k for k, v in keys.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing API key(s): {', '.join(missing)}. "
            "Add them to config.yaml 'keys' or a .env file."
        )
    return keys[list(keys)[0]]


def build_stt(cfg: dict, keys: dict[str, str]) -> STTBase:
    provider = cfg.get("provider", "mock").lower()
    if provider == "mock":
        from .stt.mock_stt import MockSTT
        return MockSTT()
    if provider == "openai":
        from .stt.openai_stt import OpenAISTT
        _require_keys({"openai": keys.get("openai", "")})
        return OpenAISTT(cfg.get("openai", {}), keys["openai"])
    if provider == "deepgram":
        from .stt.deepgram_stt import DeepgramSTT
        _require_keys({"deepgram": keys.get("deepgram", "")})
        return DeepgramSTT(cfg.get("deepgram", {}), keys["deepgram"])
    if provider == "groq":
        from .stt.groq_stt import GroqSTT
        _require_keys({"groq": keys.get("groq", "")})
        return GroqSTT(cfg.get("groq", {}), keys["groq"])
    if provider == "whisper_api":
        from .stt.openai_stt import OpenAIWhisperAPI
        _require_keys({"openai": keys.get("openai", "")})
        return OpenAIWhisperAPI(cfg.get("openai", {}), keys["openai"])
    raise ValueError(f"Unknown STT provider: {provider}")


def build_llm(cfg: dict, keys: dict[str, str]) -> LLMBase:
    provider = cfg.get("provider", "mock").lower()
    if provider == "mock":
        from .llm.mock_llm import MockLLM
        return MockLLM()
    if provider == "openai":
        from .llm.openai_llm import OpenAILLM
        _require_keys({"openai": keys.get("openai", "")})
        return OpenAILLM(cfg, keys["openai"])
    if provider == "groq":
        from .llm.groq_llm import GroqLLM
        _require_keys({"groq": keys.get("groq", "")})
        return GroqLLM(cfg, keys["groq"])
    if provider == "gemini":
        from .llm.gemini_llm import GeminiLLM
        _require_keys({"gemini": keys.get("gemini", "")})
        return GeminiLLM(cfg, keys["gemini"])
    raise ValueError(f"Unknown LLM provider: {provider}")


def build_tts(cfg: dict, keys: dict[str, str]) -> TTSBase:
    provider = cfg.get("provider", "mock").lower()
    if provider == "mock":
        from .tts.mock_tts import MockTTS
        return MockTTS()
    if provider == "openai":
        from .tts.openai_tts import OpenAITTS
        _require_keys({"openai": keys.get("openai", "")})
        return OpenAITTS(cfg.get("openai", {}), keys["openai"])
    if provider == "edge":
        from .tts.edge_tts import EdgeTTS
        return EdgeTTS(cfg.get("edge", {}))
    if provider == "elevenlabs":
        from .tts.elevenlabs_tts import ElevenLabsTTS
        _require_keys({"elevenlabs": keys.get("elevenlabs", "")})
        return ElevenLabsTTS(cfg.get("elevenlabs", {}), keys["elevenlabs"])
    raise ValueError(f"Unknown TTS provider: {provider}")


def build_sts(cfg: dict, keys: dict[str, str]) -> STSBase:
    provider = cfg.get("provider", "mock").lower()
    if provider == "mock":
        from .sts.mock_sts import MockSTS
        return MockSTS()
    if provider == "qwen_omni":
        from .sts.qwen_omni_sts import QwenOmniSTS
        return QwenOmniSTS(cfg.get("qwen_omni", {}), keys.get("qwen_url", ""))
    if provider == "qwen_kaggle":
        from .sts.qwen_kaggle_sts import QwenKaggleSTS
        return QwenKaggleSTS(cfg.get("qwen_kaggle", {}), keys.get("qwen_url", ""))
    raise ValueError(f"Unknown STS provider: {provider}")
