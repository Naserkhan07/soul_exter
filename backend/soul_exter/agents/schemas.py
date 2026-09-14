"""Domain model shared by every stage of the council pipeline."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class AssetClass(str, Enum):
    FOREX = "forex"
    STOCKS = "stocks"
    INDICES = "indices"
    FUTURES = "futures"
    OPTIONS = "options"
    CRYPTO = "crypto"


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class Verdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


class TradeState(str, Enum):
    DISCOVERED = "discovered"          # fly brain found it, still at the gate
    ENTERING = "entering"              # walking in from the welcome gate
    SEATED = "seated"                  # sitting at its desk
    WALKING_TO_CABIN = "walking_to_cabin"
    IN_CABIN = "in_cabin"
    DELIBERATING = "deliberating"      # council voting in progress
    TO_EXECUTIVE = "to_executive"
    IN_EXECUTIVE = "in_executive"
    FINAL_REVIEW = "final_review"
    ACCEPTED = "accepted"              # CEO approved -> walks out through the entry door (goes live)
    REJECTED = "rejected"              # walks to the exit door
    EXITING = "exiting"
    EXITED = "exited"
    PARKED = "parked"                  # WAIT_FOR_SETUP -> roams the floor


@dataclass
class Instrument:
    symbol: str
    asset_class: str
    name: str
    venue: str
    price: float
    tick: float
    vol: float          # annualised vol used by the synthetic feed
    pip: float          # smallest sensible price increment
    spread: float
    meta: Dict[str, Any] = field(default_factory=dict)

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Signal:
    """Raw output of the fly-brain scanner for one instrument."""
    symbol: str
    asset_class: str
    direction: str
    score: float                 # 0..1 fly brain conviction
    entry: float
    stop_loss: float
    take_profit: float
    atr: float
    horizon: str                 # scalp | intraday | swing
    features: Dict[str, float] = field(default_factory=dict)
    neural: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop_loss)

    @property
    def reward(self) -> float:
        return abs(self.take_profit - self.entry)

    @property
    def rr(self) -> float:
        return self.reward / self.risk if self.risk else 0.0

    def dict(self) -> dict:
        d = asdict(self)
        d["rr"] = round(self.rr, 2)
        return d


@dataclass
class Verdict_:
    judge_id: str
    judge_name: str
    verdict: str                    # approve | reject | abstain
    confidence: float               # 0..1
    score: float                    # -1..1 signed conviction
    reasoning: str
    key_points: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    engine: str = "deterministic"
    model: str = "soul-exter-analyst"
    latency_ms: int = 0
    ts: float = field(default_factory=time.time)

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Stage:
    """One cabin hearing (or the executive review)."""
    id: str
    kind: str                        # cabin | executive
    cabin_index: int
    judge_id: str
    judge_name: str
    stage_index: int
    state: str = "pending"           # pending | hearing | voted
    verdict: Optional[Verdict_] = None
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None

    def dict(self) -> dict:
        return dict(id=self.id, kind=self.kind, cabin_index=self.cabin_index,
                    judge_id=self.judge_id, judge_name=self.judge_name,
                    stage_index=self.stage_index, state=self.state,
                    verdict=self.verdict.dict() if self.verdict else None,
                    transcript=self.transcript, started_at=self.started_at,
                    ended_at=self.ended_at)


@dataclass
class Trade:
    id: str
    symbol: str
    asset_class: str
    direction: str
    desk_id: str
    desk_index: int
    confidence: float
    signal: Dict[str, Any]
    stages: List[Stage] = field(default_factory=list)
    state: str = TradeState.DISCOVERED.value
    outcome: str = "pending"          # pending | accepted | rejected
    created_at: float = field(default_factory=time.time)
    finalized_at: Optional[float] = None
    votes_for: int = 0
    votes_against: int = 0
    avg_confidence: float = 0.0
    thesis: str = ""
    exec_note: str = ""
    pnl_r: float = 0.0
    cf_r: float = 0.0
    broker_ticket: Optional[str] = None      # venue order id (MT5 ticket / paper id)
    broker_mode: str = ""                    # paper | mt5
    broker_message: str = ""                 # venue confirmation / rejection text
    broker_account: str = ""                 # MT5 login the order went to
    lots: float = 0.0                        # size actually sent
    place_price: Optional[float] = None      # fill price at placement
    book_price: Optional[float] = None       # price the position was closed at
    placed_at: Optional[float] = None
    booked_at: Optional[float] = None
    pnl_usd: float = 0.0                     # venue-level P&L of the closed position
    exec_id: Optional[str] = None            # bridge execution id (remote MT5 executor)
    exec_state: str = ""                     # "" | queued | filled | failed | book_queued
    manual: bool = False                     # operator cleared it by hand
    closed_manual: bool = False              # operator booked it out by hand                  # counterfactual R for vetoed tickets
    trajectory: List[Dict[str, Any]] = field(default_factory=list)
    position: Dict[str, float] = field(default_factory=lambda: dict(x=0.0, z=0.0, yaw=0.0))

    @property
    def label(self) -> str:
        return f"{self.id} · {self.symbol} {self.direction.upper()}"

    def dict(self, with_transcript: bool = False) -> dict:
        d = dict(
            id=self.id, symbol=self.symbol, asset_class=self.asset_class,
            direction=self.direction, desk_id=self.desk_id, desk_index=self.desk_index,
            confidence=round(self.confidence, 3), signal=self.signal, state=self.state,
            outcome=self.outcome, created_at=self.created_at, finalized_at=self.finalized_at,
            votes_for=self.votes_for, votes_against=self.votes_against,
            avg_confidence=round(self.avg_confidence, 3), thesis=self.thesis,
            exec_note=self.exec_note, pnl_r=round(self.pnl_r, 2), cf_r=round(self.cf_r, 2),
            broker_ticket=self.broker_ticket, broker_mode=self.broker_mode,
            broker_message=self.broker_message, broker_account=self.broker_account,
            lots=round(self.lots, 4), place_price=self.place_price,
            book_price=self.book_price, placed_at=self.placed_at, booked_at=self.booked_at,
            pnl_usd=round(self.pnl_usd, 2),
            exec_id=self.exec_id, exec_state=self.exec_state,
            manual=self.manual, closed_manual=self.closed_manual,
            position=self.position,
            label=self.label, rr=self.signal.get("rr", 0.0),
            verdicts=[s.verdict.dict() for s in self.stages if s.verdict],
        )
        if with_transcript:
            d["stages"] = [s.dict() for s in self.stages]
        else:
            d["stages"] = [dict(id=s.id, kind=s.kind, cabin_index=s.cabin_index,
                                judge_name=s.judge_name, stage_index=s.stage_index,
                                state=s.state,
                                verdict=(s.verdict.verdict if s.verdict else None),
                                confidence=(round(s.verdict.confidence, 2) if s.verdict else None),
                                summary=(s.verdict.reasoning[:280] if s.verdict else ""))
                           for s in self.stages]
        return d


def new_id(prefix: str = "TRD") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:5].upper()}"


@dataclass
class Outcome:
    """Result of finalising a trade — fills the dashboard + learning loop."""
    trade_id: str
    symbol: str
    accepted: bool
    votes_for: int
    votes_against: int
    avg_confidence: float
    eval_pnl_r: float
    note: str
    ts: float = field(default_factory=time.time)

    def dict(self) -> dict:
        return asdict(self)
