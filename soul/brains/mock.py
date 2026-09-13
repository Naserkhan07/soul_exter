"""Mock brains.

Purpose: exercise the *entire* pipeline (scanner -> 5 cabins -> CEO -> doors ->
paper desk -> websocket UI) on a machine with no GPU, deterministically enough
to be testable. Each cabin has its own quantitative persona, so the mock council
produces the same qualitative spread of outcomes a real council does:
unanimous approvals, unanimous rejections and genuine 3-2 / 4-1 splits.

On a GPU box, SOUL_MOCK_LLM=0 swaps these for real open-weight models. Nothing
else in the system changes — the council only ever sees Verdict objects.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import time
from typing import Any, Dict, List, Optional

from ..models import TradeCandidate, Verdict, clamp
from .base import CabinSpec, make_verdict

PERSONA_LATENCY = {"QUANT": 1.0, "RISK": 0.75, "NEWS": 1.2, "MACRO": 1.05, "COMPLIANCE": 0.6, "CEO": 1.5}

#: Weights per persona. Tuned so the mock council reproduces a realistic mix of
#: unanimous approvals, unanimous rejections and splits (see tools/tune_mock.py).
PERSONA: Dict[str, Dict[str, float]] = {
    #          bias   rr   vol  align  stretch  volrank  chase  noise
    "QUANT": {"bias": 0.30, "rr": 0.90, "vol": 0.50, "align": 0.30, "stretch": 0.30, "volrank": 0.15, "chase": 0.25, "noise": 0.68},
    "RISK": {"bias": 0.15, "rr": 0.75, "vol": 0.15, "align": 0.20, "stretch": 0.55, "volrank": 0.35, "chase": 0.10, "noise": 0.66},
    "NEWS": {"bias": 0.30, "rr": 0.30, "vol": 0.45, "align": 0.15, "stretch": 0.10, "volrank": 0.10, "chase": 0.85, "noise": 0.80},
    "MACRO": {"bias": 0.45, "rr": 0.30, "vol": 0.10, "align": 0.25, "stretch": 0.15, "volrank": 0.30, "chase": 0.10, "noise": 0.72},
    "COMPLIANCE": {"bias": 0.15, "rr": 0.25, "vol": 0.05, "align": 0.05, "stretch": 0.05, "volrank": 0.05, "chase": 0.00, "noise": 0.62},
    "CEO": {"bias": 0.00, "rr": 0.45, "vol": 0.15, "align": 0.30, "stretch": 0.20, "volrank": 0.10, "chase": 0.10, "noise": 0.42},
}


class MockBrain:
    """A deterministic, opinionated stand-in for an open-source LLM."""

    kind = "mock"

    def __init__(self, spec: CabinSpec, latency: float = 0.55, jitter: float = 0.35) -> None:
        self.spec = spec
        self.base_latency = latency * PERSONA_LATENCY.get(spec.key, 1.0)
        self.jitter = jitter

    # ------------------------------------------------------------------
    def _seed(self, trade: TradeCandidate) -> random.Random:
        h = hashlib.sha256(f"{trade.id}|{self.spec.key}|{trade.symbol}|{trade.side}".encode()).digest()
        return random.Random(int.from_bytes(h[:8], "big"))

    def _terms(self, t: TradeCandidate, ctx: Dict[str, Any]) -> Dict[str, float]:
        """The shared evidence every persona reasons over."""
        f = t.features
        mkt = ctx.get("market", {})
        long = t.side == "LONG"
        rr = t.rr or 0.0
        risk_pct = t.risk_pct or 0.0
        rsi = float(f.get("rsi", 50.0))
        vol_z = float(f.get("vol_z", 0.0))
        ema_stack = float(f.get("ema_stack", 1.0))
        regime = float(f.get("regime", 0.0))
        atr_rank = float(f.get("atr_rank", 50.0))
        if not f.get("atr_rank") and mkt.get("vol_rank") is not None:
            atr_rank = float(mkt.get("vol_rank", 50.0))
        return {
            "rr_edge": clamp((rr - 1.5) / 1.5, -1.0, 1.0),
            "vol_edge": clamp((vol_z - 0.8) / 2.2, -1.0, 1.0),
            "align": 1.0 if ((long and ema_stack > 0) or (not long and ema_stack < 0)) else -1.0,
            "stretch": clamp((risk_pct - 1.3) / 1.4, -0.5, 2.0),
            "volrank": clamp((atr_rank - 45.0) / 40.0, -1.0, 1.5),
            "regime_align": (1.0 if long else -1.0) * regime if regime else 0.0,
            "chase": (1.0 if (long and rsi > 78) or (not long and rsi < 22) else 0.0),
            "rsi_extreme": clamp(abs(rsi - 50.0) / 35.0, 0.0, 1.4),
            "rsi": rsi, "vol_z": vol_z, "atr_rank": atr_rank, "risk_pct": risk_pct, "rr": rr,
        }

    def _book_penalties(self, t: TradeCandidate, ctx: Dict[str, Any], key: str) -> tuple[float, List[str]]:
        """Rule breaches (compliance cares most, risk cares somewhat)."""
        book = ctx.get("portfolio", {})
        flags: List[str] = []
        pen = 0.0
        equity = float(book.get("equity", 15000.0)) or 15000.0
        planned = float(book.get("planned_risk_pct", 0.0))
        cap = float(book.get("risk_budget_pct", 0.75))
        positions = book.get("positions", [])
        weight = 1.0 if key == "COMPLIANCE" else (0.35 if key == "RISK" else 0.0)

        if positions and any(p.get("symbol") == t.symbol for p in positions):
            flags.append(f"already holding {t.symbol}")
            pen -= 1.0 * weight
        if len(positions) >= int(book.get("max_positions", 8)):
            flags.append("at the position-count limit")
            pen -= 1.1 * weight
        if planned + 0.6 > cap:
            flags.append(f"session risk {planned:.2f}% vs {cap:.2f}% cap")
            pen -= 0.8 * weight
        same_side = [p for p in positions if p.get("side") == t.side]
        if len(same_side) >= 4:
            flags.append(f"{len(same_side)} positions already {t.side}")
            pen -= 0.5 * weight
        if t.entry <= 0 or t.risk <= 0:
            flags.append("malformed packet (zero risk)")
            pen -= 2.0
        return pen, flags

    # ------------------------------------------------------------------
    def _score(self, t: TradeCandidate, ctx: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
        w = PERSONA[self.spec.key]
        key = self.spec.key
        f = t.features
        terms = self._terms(t, ctx)
        flags: List[str] = []
        notes: List[str] = []

        if key == "CEO":
            council = ctx.get("_council") or []
            votes = [v for v in council]
            approvals = sum(1 for v in votes if v.verdict == "APPROVE")
            total = max(1, len(votes))
            majority = approvals / total
            score = (w["bias"] + 1.15 * (majority - 0.5) * 2.0
                     + w["rr"] * terms["rr_edge"] + w["align"] * terms["regime_align"]
                     - w["stretch"] * max(0.0, terms["stretch"]) + rng.gauss(0, w["noise"]))
            flags = [f"{v.cabin}: {v.reason.split('.')[0]}" for v in votes if v.verdict == "REJECT"][:2]
            notes.append(f"council {approvals}/{total} in favour, avg conf "
                         f"{sum(v.confidence for v in votes) / total:.0f}%")
            hard = [v for v in votes if v.verdict == "REJECT" and v.confidence > 75
                    and (v.cabin in ("RISK", "COMPLIANCE"))]
            if hard and approvals <= 3:
                flags.append(f"{hard[0].cabin} veto at {hard[0].confidence:.0f}% confidence")
                score -= 0.55
            conf = clamp(50 + abs(score) * 28 + rng.gauss(0, 4), 22, 96)
            verdict = "APPROVE" if score > 0 else "REJECT"
            return {"verdict": verdict, "confidence": round(conf, 1), "flags": flags,
                    "notes": notes, "adjustment": {"size_multiplier": 1.0 if verdict == "APPROVE" else 0.0,
                                                   "stop_pct": round(terms["risk_pct"], 2)}}

        # ---- the five cabins ------------------------------------------
        score = (w["bias"]
                 + w["rr"] * terms["rr_edge"]
                 + w["vol"] * terms["vol_edge"]
                 + w["align"] * terms["align"]
                 - w["stretch"] * max(0.0, terms["stretch"])
                 - w["volrank"] * max(0.0, terms["volrank"])
                 - w["chase"] * terms["chase"])

        book_pen, book_flags = self._book_penalties(t, ctx, key)
        score += book_pen
        flags += book_flags

        if key == "QUANT":
            if terms["rr"] < 1.4:
                flags.append(f"R:R {terms['rr']:.2f} is below the 1.4 desk minimum")
                score -= 0.5
            if terms["vol_z"] > 3.8:
                flags.append("volume spike could be exhaustion, not confirmation")
                score -= 0.25
            if terms["rsi_extreme"] > 1.1:
                flags.append(f"RSI {terms['rsi']:.0f} is stretched for a fresh entry")
                score -= 0.3
            notes.append(f"R:R {terms['rr']:.2f}, rs {f.get('rel_strength', 0):+.2f}%, "
                         f"vol z {terms['vol_z']:+.2f}, ATR {f.get('atr_pct', 0):.2f}%")
        elif key == "RISK":
            score -= 0.5 * clamp((terms["risk_pct"] - 1.8) / 1.2, 0.0, 2.0)
            if terms["risk_pct"] > 2.2:
                flags.append(f"stop {terms['risk_pct']:.2f}% wide for a 5m entry")
            if terms["atr_rank"] > 70:
                flags.append("entering while volatility is in the top quartile")
            if terms["vol_z"] < 0:
                flags.append("no volume confirmation behind the move")
            notes.append(f"stop {terms['risk_pct']:.2f}%, ATR rank {terms['atr_rank']:.0f}, "
                         f"reward {t.target_pct:.2f}%")
        elif key == "NEWS":
            if terms["regime_align"] < 0:
                flags.append("price is moving against the prevailing narrative")
            if f.get("bb_width_rank", 50) < 20:
                flags.append("no narrative energy — range is compressed")
            notes.append(f"tape {f.get('regime', 0):+.0f}, rel strength {f.get('rel_strength', 0):+.2f}%, "
                         f"RSI {terms['rsi']:.0f}")
        elif key == "MACRO":
            if terms["regime_align"] < 0:
                flags.append(f"fighting the {('risk-on' if f.get('regime', 0) > 0 else 'risk-off')} tape")
            if f.get("corr_proxy", 1.3) and float(f.get("corr_proxy", 1.3)) > 1.8:
                flags.append("high beta: this is a BTC directional bet in disguise")
            notes.append(f"BTC 12-bar {f.get('btc_ret_12', 0):+.2f}%, beta proxy "
                         f"{float(f.get('corr_proxy', 1.3)):.2f}, range pos {f.get('range_pos', 0.5):.2f}")
        else:  # COMPLIANCE
            if not flags:
                notes.append("no rule breaches found: sizing and exposure within mandate")
            notes.append(f"{len(ctx.get('portfolio', {}).get('positions', []))} open, "
                         f"planned risk {ctx.get('portfolio', {}).get('planned_risk_pct', 0):.2f}%")

        score += rng.gauss(0, w["noise"])
        verdict = "APPROVE" if score > 0 else "REJECT"
        conf = clamp(46 + abs(score) * 30 + rng.gauss(0, 5), 18, 95)
        if abs(score) < 0.16:
            conf = min(conf, 57)                     # a genuine coin flip, say so
        mult = 1.0 if verdict == "APPROVE" else 0.0
        if verdict == "APPROVE" and conf < 62:
            mult = round(clamp(0.35 + conf / 200.0, 0.3, 0.8), 2)
            notes.append(f"clears at reduced size x{mult}")
        return {"verdict": verdict, "confidence": round(conf, 1), "flags": flags,
                "notes": notes, "adjustment": {"size_multiplier": mult,
                                               "stop_pct": round(terms["risk_pct"], 2)}}

    # ------------------------------------------------------------------
    @staticmethod
    def _reason(t: TradeCandidate, spec: CabinSpec, res: Dict[str, Any]) -> str:
        f = t.features
        head = {
            "QUANT": f"{t.strategy} on {t.symbol}: R:R {t.rr:.2f} with a {t.score:.2f} scanner score;",
            "RISK": f"Stop sits {t.risk_pct:.2f}% away against a {t.target_pct:.2f}% target;",
            "NEWS": f"Tape read for {t.symbol}: regime {f.get('regime', 0):+.0f}, RSI {f.get('rsi', 50):.0f};",
            "MACRO": f"Top-down: BTC {f.get('btc_ret_12', 0):+.2f}% with beta proxy {f.get('corr_proxy', 1.3):.2f};",
            "COMPLIANCE": f"Book check on {t.symbol} ({len(f)} packet fields reviewed);",
            "CEO": f"Council on {t.symbol} {t.side}:",
        }[spec.key]
        body = " ".join(res["notes"])
        tail = {"APPROVE": "clears this desk.", "REJECT": "rejected by this desk.",
                "ABSTAIN": "cannot be judged."}[res["verdict"]]
        flag = f" Flag: {res['flags'][0]}." if res["flags"] else ""
        return f"{head} {body}.{flag} {tail}"

    async def judge(self, trade: TradeCandidate, ctx: Dict[str, Any],
                    prior: Optional[List[Verdict]] = None, stage: int = 1) -> Verdict:
        rng = self._seed(trade)
        local_ctx = dict(ctx)
        if self.spec.is_ceo:
            local_ctx["_council"] = prior or []
        t0 = time.time()
        await asyncio.sleep(self.base_latency + abs(rng.gauss(0, self.jitter)))
        res = self._score(trade, local_ctx, rng)
        parsed = {
            "verdict": res["verdict"],
            "confidence": res["confidence"],
            "reason": self._reason(trade, self.spec, res),
            "risk_flags": res["flags"][:4],
            "adjustment": res["adjustment"],
        }
        return make_verdict(self.spec, parsed, f"mock::{self.spec.key.lower()}",
                            int((time.time() - t0) * 1000), stage, trade.id)
