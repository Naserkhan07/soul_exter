"""Central configuration.

Everything is overridable through environment variables so the same code runs
in three places:

* a Kaggle notebook on a free GPU (real 4-bit LLMs, see kaggle/)
* a small CPU box (mock brains, identical UI/flow)
* tests / CI
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_list(key: str, default: List[str]) -> List[str]:
    raw = os.environ.get(key)
    if not raw:
        return list(default)
    return [p.strip() for p in raw.split(",") if p.strip()]


#: The desk universe. Crypto majors + high-beta alts, matching the reference
#: art (ADA, SOL, XRP, DOGE, TAO, INJ, HYPE, ZEC, SUI, NEAR, LINK, UNI, AAVE,
#: DOT, XLM, PAXG, ETH, BTC).
DEFAULT_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT",
    "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "MATIC/USDT", "LTC/USDT", "NEAR/USDT", "UNI/USDT", "AAVE/USDT",
    "ATOM/USDT", "FIL/USDT", "INJ/USDT", "SUI/USDT", "APT/USDT",
    "ARB/USDT", "OP/USDT", "TIA/USDT", "SEI/USDT", "TON/USDT",
    "XLM/USDT", "ETC/USDT", "HBAR/USDT", "ALGO/USDT", "VET/USDT",
    "ZEC/USDT", "PAXG/USDT", "TAO/USDT", "RNDR/USDT", "FET/USDT",
    "HYPE/USDT",
]


@dataclass
class CouncilRules:
    """Vote maths for the floor.

    * ``unanimous_approve`` -> trade is FINALISED and walks to the ENTRY door.
    * ``unanimous_reject``  -> trade is REJECTED and walks to the EXIT door.
    * anything in between   -> ESCALATED to the CEO (the 6th brain).
    """

    cabins: int = 5
    unanimous_approve: int = 5
    unanimous_reject: int = 0
    escalate_min_approvals: int = 1   # 1..4 approvals => CEO decides
    escalate_max_approvals: int = 4
    ceo_enabled: bool = True
    quorum: int = 5                   # how many cabins must answer to count

    def route(self, approvals: int, answered: int) -> str:
        """Return one of FINALIZED | ESCALATED | REJECTED."""
        if answered == 0:
            return "ESCALATED"
        if approvals >= self.unanimous_approve:
            return "FINALIZED"
        if approvals <= self.unanimous_reject:
            return "REJECTED"
        if self.ceo_enabled and self.escalate_min_approvals <= approvals <= self.escalate_max_approvals:
            return "ESCALATED"
        return "REJECTED"


@dataclass
class Config:
    # ---- server -------------------------------------------------------
    host: str = _env("SOUL_HOST", "0.0.0.0")
    port: int = _env_int("SOUL_PORT", 8000)
    web_dir: str = _env("SOUL_WEB_DIR", "web")

    # ---- market -------------------------------------------------------
    venue: str = _env("SOUL_VENUE", "binance")
    universe: List[str] = field(default_factory=lambda: _env_list("SOUL_UNIVERSE", DEFAULT_UNIVERSE))
    market_source: str = _env("SOUL_MARKET_SOURCE", "auto")   # auto | ccxt | sim
    poll_seconds: float = _env_float("SOUL_POLL_SECONDS", 3.0)
    candle_timeframe: str = _env("SOUL_TIMEFRAME", "5m")
    candle_limit: int = _env_int("SOUL_CANDLE_LIMIT", 200)
    # The offline simulator runs time-compressed so setups actually form while
    # you watch: one simulated 5m bar every sim_bar_seconds of wall clock.
    sim_bar_seconds: float = _env_float("SOUL_SIM_BAR_SECONDS", 8.0)

    # ---- scanner ------------------------------------------------------
    scan_seconds: float = _env_float("SOUL_SCAN_SECONDS", 25.0)
    max_candidates_per_scan: int = _env_int("SOUL_MAX_CANDIDATES", 3)
    min_score: float = _env_float("SOUL_MIN_SCORE", 0.28)
    #: don't re-review the same symbol+side+strategy for this long (seconds)
    trade_cooldown_s: float = _env_float("SOUL_TRADE_COOLDOWN", 420.0)
    desks: int = _env_int("SOUL_DESKS", 64)

    # ---- council ------------------------------------------------------
    rules: CouncilRules = field(default_factory=CouncilRules)
    llm_concurrency: int = _env_int("SOUL_LLM_CONCURRENCY", 3)
    max_trades_in_flight: int = _env_int("SOUL_MAX_IN_FLIGHT", 6)
    cabin_timeout_s: float = _env_float("SOUL_CABIN_TIMEOUT", 90.0)
    seed_demo_trades: int = _env_int("SOUL_SEED_TRADES", 5)

    # ---- brains -------------------------------------------------------
    mock_llm: bool = _env_bool("SOUL_MOCK_LLM", False)
    force_real_llm: bool = _env_bool("SOUL_FORCE_REAL_LLM", False)
    model_profile: str = _env("SOUL_MODEL_PROFILE", "standard")  # low | standard | variety
    load_in_4bit: bool = _env_bool("SOUL_LOAD_4BIT", True)
    model_cache: int = _env_int("SOUL_MODEL_CACHE", 6)     # how many models stay resident
    wave_mode: bool = _env_bool("SOUL_WAVE_MODE", True)    # 2 waves instead of 5 serial calls
    hf_home: Optional[str] = os.environ.get("HF_HOME")
    mock_latency: float = _env_float("SOUL_MOCK_LATENCY", 0.55)   # seconds per cabin
    mock_jitter: float = _env_float("SOUL_MOCK_JITTER", 0.35)

    # ---- paper desk ---------------------------------------------------
    starting_cash: float = _env_float("SOUL_STARTING_CASH", 15000.0)
    #: risked per trade, as a % of equity (the classic 0.5-1% rule)
    risk_per_trade_pct: float = _env_float("SOUL_RISK_PCT", 0.75)
    #: cap on TOTAL open risk across the book at any moment
    max_session_risk_pct: float = _env_float("SOUL_SESSION_RISK_PCT", 3.0)
    max_open_positions: int = _env_int("SOUL_MAX_OPEN", 8)
    max_leverage: float = _env_float("SOUL_MAX_LEVERAGE", 1.0)   # 1.0 = spot, no leverage

    # ---- misc ---------------------------------------------------------
    log_level: str = _env("SOUL_LOG_LEVEL", "info")
    demo_turbo: bool = _env_bool("SOUL_TURBO", False)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("hf_home", None)
        return d

    def resolve_mock(self, cuda_available: bool) -> bool:
        if self.force_real_llm:
            return False
        if self.mock_llm:
            return True
        # auto: no GPU => mock brains, unless the operator forced real ones.
        return not cuda_available

    def universe_slice(self, n: int) -> List[str]:
        return self.universe[:n] if n > 0 else list(self.universe)


def load_config() -> Config:
    return Config()
