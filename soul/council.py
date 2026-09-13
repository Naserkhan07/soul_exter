"""The council: five cabins, then the CEO.

Flow for every trade:

    desk -> QUANT   -> cabin verdict, emitted as the trader walks
         -> RISK    -> sees QUANT's verdict
         -> NEWS    -> sees QUANT + RISK
         -> MACRO   -> sees the first three
         -> COMPLIANCE -> sees all four

    5/5 APPROVE  -> ENTRY DOOR  (finalised, no CEO needed)
    0/5 APPROVE  -> EXIT DOOR   (dead on arrival)
    1..4 approve -> CEO cabin (6th LLM) reads the whole transcript and decides

Cabins run in two *waves* by default so the floor moves at a watchable pace on
a T4 without breaking the "each cabin sees the desks before it" rule:
  wave 1: QUANT, RISK, NEWS  (parallel, independent reads)
  wave 2: MACRO, COMPLIANCE  (parallel, both see wave 1)
Everything is emitted on the bus as it happens, which is what the 3D floor
animates. Nothing else in the system knows how a verdict was produced.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from .brains import Brain
from .brains.base import CABINS, CEO_SPEC, CabinSpec
from .config import Config
from .models import CouncilResult, TradeCandidate, Verdict, clamp
from .scoreboard import Scoreboard

log = logging.getLogger("soul.council")

WAVES: List[List[str]] = [
    ["QUANT", "RISK", "NEWS"],
    ["MACRO", "COMPLIANCE"],
]
SERIAL_WAVES: List[List[str]] = [[c.key] for c in CABINS]


class Council:
    def __init__(self, cfg: Config, brains: Dict[str, Brain], bus) -> None:
        self.cfg = cfg
        self.brains = brains
        self.bus = bus
        self.sem = asyncio.Semaphore(max(1, cfg.llm_concurrency))
        self.stats = {
            "reviews": 0, "finalized": 0, "rejected": 0, "escalated": 0,
            "ceo_approved": 0, "ceo_rejected": 0, "total_cabin_calls": 0,
        }
        self.history: List[CouncilResult] = []
        # what each cabin's settled calls were actually worth (see scoreboard.py)
        self.scoreboard = Scoreboard()

    # ------------------------------------------------------------------
    def cabin_spec(self, key: str) -> CabinSpec:
        for c in CABINS:
            if c.key == key:
                return c
        return CEO_SPEC

    async def _ask(self, key: str, trade: TradeCandidate, ctx_fn: Callable[[], Dict[str, Any]],
                   prior: List[Verdict], stage: int) -> Verdict:
        brain = self.brains.get(key)
        if brain is None:                                   # pragma: no cover
            raise RuntimeError(f"no brain for cabin {key}")
        spec = self.cabin_spec(key)
        await self.bus.publish("trader_walks", trade_id=trade.id, symbol=trade.symbol,
                               **{"from": prior[-1].cabin if prior else "desk",
                                  "to": key, "stage": stage,
                                  "label": spec.label, "side": trade.side})
        async with self.sem:
            ctx = ctx_fn()
            ctx = dict(ctx)
            ctx["scoreboard"] = self.scoreboard.summary()
            verdict = await brain.judge(trade, ctx, prior, stage)
        self.stats["total_cabin_calls"] += 1
        return verdict

    # ------------------------------------------------------------------
    async def review(self, trade: TradeCandidate, ctx_fn: Callable[[], Dict[str, Any]],
                     source: str = "scanner") -> CouncilResult:
        t0 = time.time()
        result = CouncilResult(trade=trade)
        self.stats["reviews"] += 1

        await self.bus.publish("trader_spawned", trade=trade.brief(), source=source,
                               session_reviews=self.stats["reviews"])

        # Wave mode runs cabins in parallel within a wave. The cost: cabins in
        # the same wave cannot see each other (they only see earlier waves).
        # SOUL_WAVE_MODE=0 gives strict QUANT->RISK->NEWS->MACRO->COMPLIANCE
        # ordering where every cabin reads all of its predecessors.
        waves = WAVES if self.cfg.wave_mode else SERIAL_WAVES
        result.wave_mode = self.cfg.wave_mode
        prior: List[Verdict] = []
        stage = 0
        for wave in waves:
            stage += 1
            keys = [k for k in wave if k in self.brains]
            if not keys:
                continue
            verdicts = await asyncio.gather(*[self._ask(k, trade, ctx_fn, list(prior), stage) for k in keys])
            for v in verdicts:
                prior.append(v)
                result.verdicts.append(v)
                approvals = sum(1 for x in result.verdicts if x.verdict == "APPROVE")
                rejections = sum(1 for x in result.verdicts if x.verdict == "REJECT")
                await self.bus.publish(
                    "cabin_verdict", trade_id=trade.id, symbol=trade.symbol, side=trade.side,
                    cabin=v.cabin, label=self.cabin_spec(v.cabin).label, model=v.model,
                    verdict=v.verdict, confidence=v.confidence, reason=v.reason,
                    risk_flags=v.risk_flags, adjustment=v.adjustment,
                    latency_ms=v.latency_ms, stage=stage,
                    approvals=approvals, rejections=rejections,
                    remaining=len([k for k in self.brains if k != "CEO"]) - len(result.verdicts),
                )

        approvals = sum(1 for v in result.verdicts if v.verdict == "APPROVE")
        rejections = sum(1 for v in result.verdicts if v.verdict == "REJECT")
        answered = len(result.verdicts)
        route = self.cfg.rules.route(approvals, answered)
        result.approvals, result.rejections, result.route = approvals, rejections, route
        # The doors are decided by the route. A unanimous council never reaches
        # the CEO, so `decision` must be settled here rather than only there.
        if route == "FINALIZED":
            result.decision = "ENTER"
        elif route == "REJECTED":
            result.decision = "SKIP"
        else:
            result.decision = "PENDING"          # CEO decides in _escalate()

        base_conf = (sum(v.confidence for v in result.verdicts if v.verdict == "APPROVE") / approvals
                     if approvals else (sum(v.confidence for v in result.verdicts) / answered if answered else 0.0))
        result.confidence = base_conf

        await self.bus.publish("council_done", trade_id=trade.id, symbol=trade.symbol, side=trade.side,
                               approvals=approvals, rejections=rejections, answered=answered,
                               confidence=round(base_conf, 1), route=route,
                               verdicts=[v.as_dict() for v in result.verdicts])

        if route == "ESCALATED" and self.cfg.rules.ceo_enabled and "CEO" in self.brains:
            await self._escalate(result, ctx_fn, stage + 1)

        # ---- doors ---------------------------------------------------
        decision = "ENTER" if result.decision == "ENTER" else "SKIP"
        if decision == "ENTER":
            self.stats["finalized"] += 1
        else:
            self.stats["rejected"] += 1
        door = "entry_door" if decision == "ENTER" else "exit_door"
        await self.bus.publish(door, trade_id=trade.id, symbol=trade.symbol, side=trade.side,
                               decision=decision, approvals=result.approvals,
                               rejections=result.rejections, confidence=round(result.confidence, 1),
                               route=result.route,
                               reason=(result.ceo_verdict.reason if result.ceo_verdict
                                       else (result.verdicts[-1].reason if result.verdicts else "no verdicts")))
        result.finished_at = time.time()
        await self.bus.publish("council_result", **result.as_dict())
        log.info("council %s %s -> %s (%d/%d approve, %.0f%%, %.1fs)", trade.symbol, trade.side,
                 decision, approvals, answered, result.confidence, time.time() - t0)

        self.history.append(result)
        self.history = self.history[-200:]
        return result

    # ------------------------------------------------------------------
    async def _escalate(self, result: CouncilResult, ctx_fn: Callable[[], Dict[str, Any]],
                        stage: int) -> None:
        trade = result.trade
        self.stats["escalated"] += 1
        await self.bus.publish("escalated", trade_id=trade.id, symbol=trade.symbol, side=trade.side,
                               approvals=result.approvals, rejections=result.rejections,
                               council=[v.as_dict() for v in result.verdicts],
                               label=CEO_SPEC.label)
        verdict = await self._ask("CEO", trade, ctx_fn, list(result.verdicts), stage)
        if verdict.verdict == "ABSTAIN":       # CEO must decide
            majority_up = result.approvals >= 3
            verdict.verdict = "APPROVE" if majority_up else "REJECT"
            verdict.reason = verdict.reason or "CEO forced a decision on a split council"
        result.ceo_verdict = verdict

        if verdict.verdict == "APPROVE":
            result.decision = "ENTER"
            self.stats["ceo_approved"] += 1
            # the CEO's confidence blends the council's and its own read
            result.confidence = clamp(0.45 * result.confidence + 0.55 * verdict.confidence, 0, 100)
            # ...and the *size* answers to the record. On a split council whose
            # approvers have been wrong more often than right, the trade is
            # taken smaller rather than argued away: the book still gets the
            # idea, the account is charged less for it.
            approvers = [v.cabin for v in result.verdicts if v.verdict == "APPROVE"]
            weight = self.scoreboard.book_weight(approvers)
            if weight < 0.95:
                verdict.adjustment = dict(verdict.adjustment or {})
                current = float(verdict.adjustment.get("size_multiplier", 1.0) or 1.0)
                verdict.adjustment["size_multiplier"] = round(max(0.25, current * weight), 3)
                verdict.risk_flags = list(verdict.risk_flags) + [
                    f"record discount x{weight:.2f} on the desks carrying this"
                ]
        else:
            result.decision = "SKIP"
            self.stats["ceo_rejected"] += 1
            result.confidence = clamp(0.5 * result.confidence + 0.5 * verdict.confidence, 0, 100)

        await self.bus.publish("ceo_verdict", trade_id=trade.id, symbol=trade.symbol, side=trade.side,
                               verdict=verdict.verdict, confidence=verdict.confidence,
                               reason=verdict.reason, risk_flags=verdict.risk_flags,
                               adjustment=verdict.adjustment, latency_ms=verdict.latency_ms,
                               model=verdict.model, council=[v.as_dict() for v in result.verdicts])

    # ------------------------------------------------------------------
    def settle(self, trade_id: str, pnl: float, risk: float = 0.0) -> None:
        """A closed trade settles every desk that voted on it.

        Called by the engine when a position closes; the desk that was right on
        a loser (a REJECT) is credited the same way the desk that was right on a
        winner is, because refusing a bad trade is the job too.
        """
        rec = self.get(trade_id)
        if not rec:
            return
        for v in rec.get("verdicts", []) or []:
            self.scoreboard.settle(str(v.get("cabin", "")), str(v.get("verdict", "")),
                                   float(pnl or 0.0), float(risk or 0.0))
        ceo = rec.get("ceo") or {}
        if ceo.get("verdict"):
            self.scoreboard.settle("CEO", str(ceo["verdict"]), float(pnl or 0.0), float(risk or 0.0))

    def snapshot(self) -> Dict[str, Any]:
        return {**self.stats, "history_len": len(self.history),
                "scoreboard": self.scoreboard.snapshot(),
                "rules": {
                    "cabins": self.cfg.rules.cabins,
                    "unanimous_approve": self.cfg.rules.unanimous_approve,
                    "unanimous_reject": self.cfg.rules.unanimous_reject,
                    "escalate_range": [self.cfg.rules.escalate_min_approvals,
                                       self.cfg.rules.escalate_max_approvals],
                }}

    def recent(self, limit: int = 25) -> List[Dict[str, Any]]:
        return [r.as_dict() for r in self.history[-limit:]][::-1]

    def get(self, trade_id: str) -> Optional[Dict[str, Any]]:
        for r in reversed(self.history):
            if r.trade.id == trade_id:
                return r.as_dict()
        return None
