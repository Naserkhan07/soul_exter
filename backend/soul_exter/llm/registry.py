"""The council roster: 5 cabin judges (open-source models), the CEO, and the fly scout.

Every desk is configurable at runtime from the Settings panel — name, provider,
model id, base url and API key. With no key configured the seat still reasons
through the built-in analyst engine, so the floor is fully functional offline.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class LLMSeat:
    id: str
    name: str
    role: str
    specialty: str
    model: str
    provider: str = "builtin"          # builtin | openrouter | together | groq | ollama | openai|custom
    base_url: str = ""
    api_key_env: str = ""
    api_key: str = ""
    cabin: Optional[int] = None
    accent: str = "#38bdf8"
    temperature: float = 0.25
    enabled: bool = True
    open_source_family: str = ""
    avatar: Dict[str, str] = field(default_factory=dict)

    def engine_token(self) -> str:
        """Deterministic local credential for the built-in analyst engine.

        The keyless engine still authenticates its own seats (order signing, chat
        sessions), so there is always a key to show and copy in the settings
        panel — it is just generated on this host instead of pasted by you.
        """
        seed = f"{self.id}|{os.environ.get('SOUL_EXTER_SECRET', 'soul-exter-local')}"
        digest = hashlib.sha256(seed.encode()).hexdigest()[:16].upper()
        return f"SOULX-{self.name}-{digest[:8]}-{digest[8:16]}"

    def key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env, "")
        return ""

    def live(self) -> bool:
        return self.provider != "builtin" and bool(self.key() or self.provider == "ollama")

    def key_source(self) -> str:
        """Where the key this seat is running with comes from."""
        if self.api_key:
            return "seat"
        if self.api_key_env and os.environ.get(self.api_key_env):
            return f"env:{self.api_key_env}"
        return "none"

    def dict(self, expose_key: bool = True) -> dict:
        d = asdict(self)
        if not expose_key:
            d["api_key"] = "***" if self.api_key else ""
        active = self.key()
        d["has_key"] = bool(active)
        d["live"] = self.live()
        d["engine_token"] = self.engine_token()
        # what the desk is *actually* running with, so the operator never has to
        # guess whether a key is in play
        shown = active or self.engine_token()
        d["active_key"] = shown
        d["active_key_masked"] = (shown[:7] + "…" + shown[-4:]) if len(shown) > 14 else shown
        d["key_source"] = self.key_source() if active else "local-engine"
        d["engine"] = (f"{self.provider}:{self.model}" if self.live()
                       else "soul-exter-analyst (built-in)")
        return d


DEFAULT_SEATS: List[LLMSeat] = [
    LLMSeat(
        id="judge_trend", name="ATLAS", role="Cabin Judge 01",
        specialty="Trend structure & market regime", model="meta-llama/llama-3.1-70b-instruct",
        provider="builtin", api_key_env="OPENROUTER_API_KEY", cabin=1, accent="#38bdf8",
        open_source_family="Llama 3.1 70B · Meta",
        avatar=dict(style="tall, grey suit, wireframe glasses", chair="premium mesh"),
    ),
    LLMSeat(
        id="judge_quant", name="QUANTA", role="Cabin Judge 02",
        specialty="Quant risk, expectancy & position sizing", model="Qwen/Qwen2.5-72B-Instruct",
        provider="builtin", api_key_env="TOGETHER_API_KEY", cabin=2, accent="#a78bfa",
        open_source_family="Qwen2.5 72B · Alibaba",
        avatar=dict(style="navy blazer, tablet in hand", chair="leather executive"),
    ),
    LLMSeat(
        id="judge_macro", name="MERIDIAN", role="Cabin Judge 03",
        specialty="Macro liquidity, rates & cross-asset flow", model="deepseek-ai/DeepSeek-V3",
        provider="builtin", api_key_env="DEEPSEEK_API_KEY", cabin=3, accent="#f59e0b",
        open_source_family="DeepSeek V3 · DeepSeek AI",
        avatar=dict(style="charcoal three-piece, pocket square", chair="wingback"),
    ),
    LLMSeat(
        id="judge_vol", name="VOLTA", role="Cabin Judge 04",
        specialty="Volatility, options surface & tail risk", model="mistralai/Mixtral-8x22B-Instruct",
        provider="builtin", api_key_env="MISTRAL_API_KEY", cabin=4, accent="#f472b6",
        open_source_family="Mixtral 8x22B · Mistral AI",
        avatar=dict(style="pink shirt, rolled sleeves", chair="standing desk bar-stool"),
    ),
    LLMSeat(
        id="judge_exec", name="VECTOR", role="Cabin Judge 05",
        specialty="Execution, microstructure & slippage", model="microsoft/phi-4",
        provider="builtin", api_key_env="GROQ_API_KEY", cabin=5, accent="#22d3ee",
        open_source_family="Phi-4 · Microsoft",
        avatar=dict(style="dark turtleneck, headset", chair="ergonomic task chair"),
    ),
    LLMSeat(
        id="ceo", name="NAVEED", role="Head of Council · CEO",
        specialty="Capital allocation & final mandate", model="NousResearch/Hermes-3-Llama-3.1-405B",
        provider="builtin", api_key_env="OPENROUTER_API_KEY", cabin=None, accent="#c084fc",
        temperature=0.2, open_source_family="Hermes 3 · 405B Llama 3.1",
        avatar=dict(style="black suit, gold tie pin", chair="leather high-back"),
    ),
    LLMSeat(
        id="hunter", name="DROSOPHILA", role="Fly Scout · Market Hunter",
        specialty="Tick-level pattern hunting off the fly brain", model="Qwen/Qwen2.5-32B-Instruct",
        provider="builtin", api_key_env="TOGETHER_API_KEY", cabin=None, accent="#34d399",
        temperature=0.35, open_source_family="Qwen2.5 32B · Alibaba",
        avatar=dict(style="utility vest, headset", chair="drone rig"),
    ),
]

PROVIDER_BASE_URLS: Dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    "openai": "https://api.openai.com/v1",
    "custom": "",
}


def default_seats() -> List[LLMSeat]:
    return [LLMSeat(**asdict(s)) for s in DEFAULT_SEATS]


def seat_index(seats: List[LLMSeat]) -> Dict[str, LLMSeat]:
    return {s.id: s for s in seats}
