"""The debate room: the six desks teaching each other how to trade.

A council vote is not a conversation. Five models answer the same packet in
parallel(ish), a sixth reads the transcript and rules — and then everyone forgets
it ever happened. That is not how a desk works.

In a real room the review *is* the training: someone makes a claim, someone else
attacks it, a question gets asked that nobody had asked, an answer gets given, and
the head of desk closes the round with the rule the table will carry forward.
The rule is the whole point — it is what the next trade gets judged against.

That is what this module is:

* a **round** is a topic, a lead speaker, two or three challenges or questions,
  an answer, and a closing lesson from the head of desk;
* a topic is either something the desk just lived through (the trade the council
  has on the table, with its numbers) or a standing question about the craft;
* every closing lesson is written into **desk memory**, and desk memory is read
  back into the council prompt for every following trade.

So the floors learns across trades, in public, where it can be watched: the
transcript is published on the event bus and the lessons are visible in the UI.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .brains.base import CABINS, CEO_SPEC, CabinSpec
from .config import Config
from .models import CouncilResult, TradeCandidate

log = logging.getLogger("soul.debate")

#: The standing curriculum. These are the arguments that actually decide trading
#: accounts, and every desk has an angle on all of them.
CURRICULUM: List[str] = [
    "When does a breakout into a stretched tape deserve a seat, and when is it a trap?",
    "How much of the account should one setup get — and what has to be true to raise it?",
    "A stop that is hit by noise is worse than no stop: how wide is wide enough?",
    "When is a losing trade a bad decision, and when is it just a bad outcome?",
    "We keep taking the same bet in five tickers. How should the desk count that risk?",
    "What is the difference between a setup with no catalyst and a setup with no story yet?",
    "When the regime turns, do we cut the book or hedge it? What does the desk actually do?",
    "Which is more expensive for this desk: a missed winner or an avoided loser?",
    "How do we tell signal decay from a normal drawdown?",
    "What evidence would make us stop trading a strategy that has worked for a month?",
]

#: Turn shapes per round: a lead claim, then the challenge/answer rhythm, then the close.
ROUND_SHAPE = ["claim", "challenge", "question", "answer", "ack", "lesson"]


@dataclass
class DebateMessage:
    room: str
    topic: str
    speaker: str
    name: str
    label: str
    model: str
    turn: str
    text: str
    round: int
    trade_id: Optional[str] = None
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DebateRoom:
    """Turns + transcript + written rules, driven by the same six brains."""

    def __init__(self, cfg: Config, brains: Dict[str, Any], bus, registry: Dict[str, dict]) -> None:
        self.cfg = cfg
        self.brains = {k: b for k, b in brains.items() if k != "CEO"}
        self.ceo = brains.get("CEO")
        self.bus = bus
        self.registry = registry
        self.transcript: List[Dict[str, Any]] = []
        self.lessons: List[Dict[str, Any]] = []
        self.rounds = 0
        self.current_topic: Optional[str] = None
        self._queued: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._rng = random.Random(getattr(cfg, "debate_seed", 20240914))

    # ------------------------------------------------------------------
    def queue_trade(self, trade: TradeCandidate, result: CouncilResult,
                    extra: Optional[Dict[str, Any]] = None) -> None:
        """Put the trade the council just decided on the debate agenda."""
        inner = {
            "symbol": trade.symbol, "side": trade.side, "strategy": trade.strategy,
            "rr": round(trade.rr, 2), "risk": round(trade.risk_pct, 2),
            "atr": round(float(trade.features.get("atr_pct", 1.0)), 2),
            "rsi": round(float(trade.features.get("rsi", 50.0)), 1),
            "regime": ("risk-on" if float(trade.features.get("regime", 0)) > 0 else
                       "risk-off" if float(trade.features.get("regime", 0)) < 0 else "mixed"),
            "btc": round(float(trade.features.get("btc_ret_12", 0.0)), 2),
            "corr": round(float(trade.features.get("corr_proxy", 1.3)), 2),
            "stop": trade.stop,
            "size": round(float(getattr(result, "size_multiplier", 1.0) or 1.0), 2),
            "decision": result.decision,
            "approvals": result.approvals,
            "rejections": result.rejections,
        }
        inner.update(extra or {})
        topic = (f"{trade.symbol} {trade.side} ({trade.strategy}) — the council "
                 f"{'passed' if result.decision == 'ENTER' else 'refused'} it "
                 f"{result.approvals}-{result.rejections}. Is that the right call?")
        self._queued.append({"topic": topic, "inner": inner, "trade_id": trade.id})
        self._queued = self._queued[-6:]

    def _next_topic(self) -> Dict[str, Any]:
        if self._queued:
            return self._queued.pop(0)
        text = CURRICULUM[self._rng.randrange(len(CURRICULUM))]
        return {"topic": text, "inner": {}, "trade_id": None}

    # ------------------------------------------------------------------
    async def _say(self, key: str, kind: str, topic: str, inner: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        brain = self.brains.get(key) or self.ceo
        if brain is None:
            return None
        spec: CabinSpec = brain.spec
        reg = self.registry.get(key, {})
        # note: `turn`, not `kind` — publish() already owns that keyword
        await self.bus.publish("debate_thinking", room="desk", speaker=key,
                               name=spec.name or spec.label, turn=kind, topic=topic,
                               round=self.rounds + 1)
        text = await brain.debate(topic, self.transcript, kind, inner)
        text = " ".join(str(text).split())
        if not text:
            return None
        msg = DebateMessage(
            room="desk", topic=topic, speaker=key, name=spec.name or spec.label,
            label=spec.label, model=reg.get("model", getattr(brain, "model_name", "mock")),
            turn=kind, text=text[:600], round=self.rounds + 1,
            trade_id=inner.get("trade_id"),
        ).as_dict()
        self.transcript.append(msg)
        self.transcript = self.transcript[-160:]
        if kind == "lesson":
            self.lessons.append({
                "topic": topic, "speaker": key,
                "speaker_label": f"{spec.name or spec.label}, {spec.title or spec.role}",
                "text": text[:400], "ts": msg["ts"], "round": msg["round"],
            })
            self.lessons = self.lessons[-40:]
        await self.bus.publish("debate_message", **msg)
        return msg

    async def run_round(self, topic: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """One full debate round: claim -> challenge -> question -> answer -> lesson."""
        if self._lock.locked():
            return []
        async with self._lock:
            agenda = topic or self._next_topic()
            text, inner = agenda["topic"], dict(agenda.get("inner") or {})
            inner.setdefault("trade_id", agenda.get("trade_id"))
            self.rounds += 1
            self.current_topic = text
            await self.bus.publish("debate_round", room="desk", round=self.rounds,
                                   topic=text, trade_id=agenda.get("trade_id"))
            keys = list(self.brains.keys())
            # the head of desk closes; everyone else rotates through the turns
            mode = inner.get("decision", "")
            if mode == "SKIP":
                # a refused trade: the desks that voted no lead the post-mortem
                order = [k for k in ("RISK", "COMPLIANCE") if k in keys] + \
                        [k for k in keys if k not in ("RISK", "COMPLIANCE")]
            else:
                order = keys
            lead = order[self._rng.randrange(len(order))]
            order = [lead] + [k for k in order if k != lead]

            said: List[Dict[str, Any]] = []
            for i, kind in enumerate(ROUND_SHAPE):
                speaker = self.ceo_key() if kind == "lesson" else order[min(i, len(order) - 1)]
                if kind == "ack" and len(order) > 4:
                    speaker = order[3]
                msg = await self._say(speaker, kind, text, inner)
                if msg:
                    said.append(msg)
            log.info("debate round %d on %r: %d turns, %d lessons on file",
                     self.rounds, text[:48], len(said), len(self.lessons))
            return said

    def ceo_key(self) -> str:
        return "CEO"

    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        return {
            "room": "desk",
            "rounds": self.rounds,
            "topic": self.current_topic,
            "transcript": self.transcript[-40:],
            "lessons": self.lessons[-12:],
            "speakers": [
                {"key": k, "name": (self.brains.get(k) or self.ceo).spec.name
                 if (self.brains.get(k) or self.ceo) else k,
                 "title": (self.brains.get(k) or self.ceo).spec.title
                 if (self.brains.get(k) or self.ceo) else ""}
                for k in list(self.brains.keys()) + ["CEO"]
                if (self.brains.get(k) or self.ceo) is not None
            ],
            "queued": len(self._queued),
        }
