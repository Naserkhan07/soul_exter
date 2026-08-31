"""Speech-to-Speech model layer (one-model architecture).

This is the native "voice in -> voice out" path (e.g. Qwen Omni). It replaces
the three separate STT + LLM + TTS calls with a single model that understands
the person's audio and speaks its reply directly.

Providers:
  mock         : offline deterministic (for testing)
  qwen_omni    : a local Qwen Omni server (your own GPU / PC)
  qwen_kaggle  : a Qwen Omni server you host on a free Kaggle GPU
"""

from .mock_sts import MockSTS
from .qwen_omni_sts import QwenOmniSTS
from .qwen_kaggle_sts import QwenKaggleSTS

__all__ = ["MockSTS", "QwenOmniSTS", "QwenKaggleSTS"]
