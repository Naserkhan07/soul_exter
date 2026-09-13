"""Cabins, models and the brain factory. 100% local, 100% open weights.

NO API KEYS ANYWHERE. Only *ungated* Hugging Face models are used, so weights
download anonymously on a Kaggle box with no HF token:

    Qwen/Qwen2.5-7B-Instruct            Apache-2.0
    microsoft/Phi-3.5-mini-instruct     MIT
    mistralai/Mistral-7B-Instruct-v0.3  Apache-2.0
    Qwen/Qwen2.5-3B-Instruct            Apache-2.0
    HuggingFaceH4/zephyr-7b-beta        MIT
    Qwen/Qwen2.5-14B-Instruct           Apache-2.0   (CEO / Head of Desk)

Blocked-by-license models (Meta-Llama-3.x, Gemma) are deliberately NOT used
because they need an HF token + terms acceptance to download.

    backend       | when
    --------------|---------------------------------------------------------
    local-hf      | default on a GPU box (Kaggle 2x T4) — real open weights
    mock          | no GPU -> deterministic persona brains, same pipeline

Set SOUL_MOCK_LLM=0 to force the real weights even if detection is unsure.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Protocol

from ..config import Config
from .base import CABINS, CEO_SPEC, CabinSpec
from .local_hf import LocalHFBrain, ModelPool
from .mock import MockBrain

log = logging.getLogger("soul.brains")

# ---------------------------------------------------------------------------
# Model rosters (all ungated). Anything above ~9 GB in 4-bit lives on its own
# desk; the pool evicts LRU models when SOUL_MODEL_CACHE is exceeded.
# ---------------------------------------------------------------------------
PROFILE_STANDARD: Dict[str, str] = {
    "QUANT": "Qwen/Qwen2.5-7B-Instruct",
    "RISK": "mistralai/Mistral-7B-Instruct-v0.3",
    "NEWS": "HuggingFaceH4/zephyr-7b-beta",
    "MACRO": "Qwen/Qwen2.5-3B-Instruct",
    "COMPLIANCE": "microsoft/Phi-3.5-mini-instruct",
    "CEO": "Qwen/Qwen2.5-14B-Instruct",
}

PROFILE_LOW: Dict[str, str] = {
    "QUANT": "Qwen/Qwen2.5-3B-Instruct",
    "RISK": "microsoft/Phi-3.5-mini-instruct",
    "NEWS": "Qwen/Qwen2.5-3B-Instruct",
    "MACRO": "microsoft/Phi-3.5-mini-instruct",
    "COMPLIANCE": "microsoft/Phi-3.5-mini-instruct",
    "CEO": "Qwen/Qwen2.5-7B-Instruct",
}

#: Every cabin a *different* model, heaviest reasonable set for 2x T4 (32 GB).
PROFILE_VARIETY: Dict[str, str] = {
    "QUANT": "Qwen/Qwen2.5-7B-Instruct",
    "RISK": "mistralai/Mistral-7B-Instruct-v0.3",
    "NEWS": "HuggingFaceH4/zephyr-7b-beta",
    "MACRO": "Qwen/Qwen2.5-14B-Instruct",
    "COMPLIANCE": "microsoft/Phi-3.5-mini-instruct",
    "CEO": "Qwen/Qwen2.5-14B-Instruct",
}

PROFILES: Dict[str, Dict[str, str]] = {
    "low": PROFILE_LOW,
    "standard": PROFILE_STANDARD,
    "variety": PROFILE_VARIETY,
}

#: Rough 4-bit footprint in GB, used to warn about VRAM before loading.
APPROX_VRAM_4BIT_GB: Dict[str, float] = {
    "Qwen/Qwen2.5-3B-Instruct": 2.4,
    "microsoft/Phi-3.5-mini-instruct": 2.6,
    "Qwen/Qwen2.5-7B-Instruct": 5.0,
    "mistralai/Mistral-7B-Instruct-v0.3": 5.0,
    "HuggingFaceH4/zephyr-7b-beta": 5.0,
    "Qwen/Qwen2.5-14B-Instruct": 9.5,
}


class Brain(Protocol):
    kind: str
    spec: CabinSpec

    async def judge(self, trade, ctx: Dict, prior: Optional[List], stage: int): ...


def model_for(spec: CabinSpec, profile: str) -> str:
    roster = PROFILES.get(profile, PROFILE_STANDARD)
    return roster.get(spec.key) or spec.model_prefs[0]


def vram_estimate(profile: str) -> float:
    roster = PROFILES.get(profile, PROFILE_STANDARD)
    return round(sum(APPROX_VRAM_4BIT_GB.get(m, 5.0) for m in set(roster.values())), 1)


def build_brains(cfg: Config, cuda_available: bool) -> Dict[str, Brain]:
    """Return {cabin_key: brain}, CEO included."""
    brains: Dict[str, Brain] = {}

    if cfg.resolve_mock(cuda_available):
        log.warning("brains: MOCK mode (no GPU detected or SOUL_MOCK_LLM=1) — "
                    "the pipeline is real, the reasoning is synthetic personas")
        for spec in CABINS + [CEO_SPEC]:
            brains[spec.key] = MockBrain(spec, latency=cfg.mock_latency, jitter=cfg.mock_jitter)
        return brains

    pool = ModelPool(load_in_4bit=cfg.load_in_4bit and cuda_available,
                     max_cached=cfg.model_cache)
    est = vram_estimate(cfg.model_profile)
    log.info("brains: local open-weight models, profile=%s (~%.1f GB in 4-bit)", cfg.model_profile, est)
    for spec in CABINS + [CEO_SPEC]:
        brains[spec.key] = LocalHFBrain(spec, pool, model_for(spec, cfg.model_profile))
    return brains


def brain_registry(brains: Dict[str, Brain], profile: str = "standard") -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for i, spec in enumerate(CABINS + [CEO_SPEC]):
        b = brains.get(spec.key)
        if b is None:
            continue
        out[spec.key] = {
            "key": spec.key,
            "label": spec.label,
            "name": spec.name or spec.label,
            "title": spec.title or spec.role,
            "role": spec.role,
            "is_ceo": spec.is_ceo,
            "slot": i,
            "model": getattr(b, "model_name", "mock"),
            "backend": b.kind,
            "temperature": spec.temperature,
            "license": "open weights, ungated",
            # there is no key to show: that is the point of the roster
            "key_required": False,
            "auth": "none — local weights, ungated download",
            "expertise": list(spec.expertise),
            "style": spec.style,
        }
    return out
