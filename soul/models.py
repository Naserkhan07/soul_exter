"""Domain objects shared by the scanner, the council and the UI."""
from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


def _uid(prefix: str = "T") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


# --------------------------------------------------------------------------
# market
# --------------------------------------------------------------------------
@dataclass
class Tick:
    symbol: str
    price: float
    change_pct: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# trades
# --------------------------------------------------------------------------
@dataclass
class TradeCandidate:
    """One trader sitting at one desk."""

    symbol: str
    side: str                      # LONG | SHORT
    strategy: str
    entry: float
    stop: float
    target: float
    timeframe: str = "5m"
    score: float = 0.0
    features: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: _uid("T"))
    created_at: float = field(default_factory=time.time)
    desk: Optional[Dict[str, int]] = None

    # ---- derived -----------------------------------------------------
    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry)

    @property
    def rr(self) -> float:
        r = self.risk
        return (self.reward / r) if r > 0 else 0.0

    @property
    def risk_pct(self) -> float:
        return (self.risk / self.entry * 100.0) if self.entry else 0.0

    @property
    def target_pct(self) -> float:
        return (self.reward / self.entry * 100.0) if self.entry else 0.0

    def brief(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "strategy": self.strategy,
            "entry": round(self.entry, 6),
            "stop": round(self.stop, 6),
            "target": round(self.target, 6),
            "rr": round(self.rr, 2),
            "risk_pct": round(self.risk_pct, 2),
            "target_pct": round(self.target_pct, 2),
            "timeframe": self.timeframe,
            "score": round(self.score, 3),
            "features": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.features.items()},
            "notes": self.notes,
            "desk": self.desk,
            "created_at": self.created_at,
        }

    def as_dict(self) -> Dict[str, Any]:
        return self.brief()


@dataclass
class Verdict:
    """One cabin's opinion."""

    cabin: str
    model: str
    verdict: str                   # APPROVE | REJECT | ABSTAIN
    confidence: float              # 0..100
    reason: str = ""
    risk_flags: List[str] = field(default_factory=list)
    adjustment: Dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    raw: str = ""
    trade_id: str = ""
    stage: int = 0
    ts: float = field(default_factory=time.time)

    @property
    def approved(self) -> bool:
        return self.verdict == "APPROVE"

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d


@dataclass
class CouncilResult:
    trade: TradeCandidate
    verdicts: List[Verdict] = field(default_factory=list)
    ceo_verdict: Optional[Verdict] = None
    route: str = "ESCALATED"        # FINALIZED | ESCALATED | REJECTED
    decision: str = "PENDING"       # ENTER | SKIP
    approvals: int = 0
    rejections: int = 0
    confidence: float = 0.0
    wave_mode: bool = True
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.finished_at or time.time()) - self.started_at)

    def transcript(self) -> List[Dict[str, Any]]:
        return [v.as_dict() for v in self.verdicts]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "trade": self.trade.brief(),
            "verdicts": self.transcript(),
            "ceo": self.ceo_verdict.as_dict() if self.ceo_verdict else None,
            "route": self.route,
            "decision": self.decision,
            "approvals": self.approvals,
            "rejections": self.rejections,
            "confidence": round(self.confidence, 1),
            "duration_s": round(self.duration_s, 2),
            "stages_seen": [v.cabin for v in self.verdicts] + ([self.ceo_verdict.cabin] if self.ceo_verdict else []),
            "wave_mode": self.wave_mode,
        }


# --------------------------------------------------------------------------
# paper desk
# --------------------------------------------------------------------------
@dataclass
class Position:
    trade_id: str
    symbol: str
    side: str
    entry: float
    stop: float
    target: float
    size: float            # notional exposure  = qty * entry
    qty: float             # units
    risk: float = 0.0      # dollars at risk to the stop = |entry - stop| * qty
    opened_at: float = field(default_factory=time.time)
    status: str = "OPEN"           # OPEN | CLOSED
    exit_price: float = 0.0
    pnl: float = 0.0
    closed_at: float = 0.0
    confidence: float = 0.0
    strategy: str = ""
    reason: str = ""

    @property
    def notional(self) -> float:
        return self.size

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)

    def mark(self, price: float) -> float:
        direction = 1.0 if self.side == "LONG" else -1.0
        return (price - self.entry) * direction * self.qty

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def fmt_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def sigmoid(x: float, k: float = 1.0) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-k * x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0
