"""Runtime settings — market selection, thresholds, pacing, LLM seats."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..llm.registry import LLMSeat, default_seats
from ..market.universe import UNIVERSE, default_enabled

SETTINGS_PATH = os.environ.get("SOUL_EXTER_SETTINGS", "soul_exter_settings.json")


@dataclass
class Settings:
    enabled_symbols: List[str] = field(default_factory=default_enabled)
    scan_interval: float = 1.6           # seconds between scan bursts
    scan_batch: int = 12                 # symbols inspected per burst
    strike_score: float = 0.62           # fly-brain threshold
    cooldown_s: float = 40.0             # per-symbol strike cooldown
    min_efficiency: float = 0.32         # only trade efficient (directional) tape
    min_trend: float = 0.30              # only trade a real trend composite
    use_correlation: bool = True         # correlation-brain finder (bloc-lag, corr-break)
    use_orderbook: bool = True           # live L2 book + microstructure channels (crypto)
    corr_overlap_max: float = 0.85       # refuse new tickets too correlated with open ones
    micro_refresh_s: float = 12.0        # seconds between L2 book refreshes per symbol
    sl_atr: float = 1.00                 # stop distance in ATR
    tp_atr: float = 2.20                 # target distance in ATR
    outcome_horizon_s: float = 600.0     # paper-evaluation window
    max_trades_in_pipe: int = 9
    speed: float = 1.0                   # floor clock multiplier
    paused: bool = False
    live_venues: bool = True             # merge real venue prices when reachable
    live_symbols_max: int = 10           # how many symbols to poll from the venue
    auto_trade_eval: bool = True         # paper-evaluate accepted trades
    ambient_traders: int = 12            # NPC floor traders
    cabin_dwell_scale: float = 1.0       # hearing length multiplier
    seats: List[dict] = field(default_factory=lambda: [s.dict() for s in default_seats()])
    # --- execution / broker -------------------------------------------------
    broker_mode: str = "paper"           # paper | mt5
    mt5_login: int = 0                   # your MT5 account number
    mt5_password: str = ""               # stored locally only (never committed)
    mt5_server: str = ""                 # e.g. MetaQuotes-Demo / ICMarkets-Live
    mt5_path: str = ""                   # optional path to terminal64.exe
    mt5_symbol_suffix: str = ""          # brokers that quote EURUSD.m etc.
    lots: float = 0.10                   # clip size sent to the broker
    auto_place: bool = False             # send accepted trades to the broker automatically

    # ------------------------------------------------------------------ io
    def to_seats(self) -> List[LLMSeat]:
        out: List[LLMSeat] = []
        for raw in self.seats:
            data = {k: v for k, v in raw.items()
                    if k in LLMSeat.__dataclass_fields__}
            # migrate the legacy head-of-council name: NAVEED runs the executive floor
            if data.get("id") == "ceo" and data.get("name") in ("SOVEREIGN", "", None):
                data["name"] = "NAVEED"
            out.append(LLMSeat(**data))
        return out

    def set_seats(self, seats: List[LLMSeat]) -> None:
        self.seats = [s.dict() for s in seats]

    def dict(self) -> dict:
        d = asdict(self)
        d["universe_size"] = len(UNIVERSE)
        return d

    def save(self, path: str = SETTINGS_PATH) -> None:
        try:
            with open(path, "w") as fh:
                json.dump(asdict(self), fh, indent=2)
        except Exception:
            pass

    @classmethod
    def load(cls, path: str = SETTINGS_PATH) -> "Settings":
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    data = json.load(fh)
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except Exception:
                pass
        return cls()

    def apply_patch(self, patch: Dict[str, Any]) -> None:
        for k, v in (patch or {}).items():
            if k == "seats":
                continue
            if hasattr(self, k):
                setattr(self, k, v)
        self.enabled_symbols = [s for s in self.enabled_symbols if s in UNIVERSE]
        if not self.enabled_symbols:
            self.enabled_symbols = default_enabled()
