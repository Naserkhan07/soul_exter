"""
Built-in analyst engine.

Each judge is a *specialist committee member*, not a copy of one another: the
scoring functions below encode what that desk actually cares about (structure,
expectancy, macro liquidity, volatility/options, execution) and turn the numbers
attached to a trade into a verdict the floor can act on. It runs on CPU in
microseconds, so the council works on a free Kaggle GPU with zero API keys —
and it doubles as the fallback whenever a hosted model is unreachable.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

from ..agents.schemas import Signal
from .expectancy import desk_bands, desk_tilt, model_ready, percentile, predict
from .registry import LLMSeat


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _fmt(x: float, digits: int = 4) -> str:
    if abs(x) >= 1000:
        return f"{x:,.1f}"
    if abs(x) >= 10:
        return f"{x:,.2f}"
    return f"{x:.{digits}f}"


class StageContext:
    """Everything a judge is allowed to see about one trade."""

    def __init__(self, signal: Signal, history: List[dict], playbook: dict,
                 prior_context: str = "", desk_name: str = "") -> None:
        self.signal = signal
        self.f: Dict[str, float] = signal.features
        self.history = history
        self.playbook = playbook
        self.prior_context = prior_context
        self.desk_name = desk_name

    # convenience accessors -------------------------------------------------
    @property
    def rr(self) -> float:
        return self.signal.rr

    @property
    def atr_pct(self) -> float:
        return float(self.f.get("atr_pct", 0.0))


# --------------------------------------------------------------------------- #
#  evidence helpers — every desk scores the *same* tape, from its own angle
# --------------------------------------------------------------------------- #
def _trend_c(f: Dict[str, float]) -> float:
    """Signed trend composite (matches the calibration studies)."""
    return float(0.62 * math.tanh(f.get("slope21", 0.0) * 120.0)
                 + 0.38 * math.tanh(f.get("slope50", 0.0) * 60.0))


def _pieces(ctx: "StageContext") -> Dict[str, float]:
    """Normalised evidence shared by the desks (all dimensionless, -1..1-ish)."""
    f = ctx.f
    sgn = 1.0 if ctx.signal.direction == "long" else -1.0
    tc = _trend_c(f)
    eff = f.get("efficiency", 0.0)
    stretch = f.get("stretch", 0.0) * sgn          # >0 = extended in-trade
    cost = f.get("spread_ratio", 0.0) / max(ctx.atr_pct, 1e-9)
    return dict(
        align=_clamp(tc * sgn, -1.0, 1.0),
        eff_adj=_clamp((eff - 0.30) * 3.2, -1.0, 1.0),
        extended=_clamp((abs(stretch) - 0.9) / 1.4, 0.0, 1.0),
        chase=_clamp((stretch - 0.9) / 1.4, 0.0, 1.0),
        rank=f.get("atr_rank", 0.5),
        cost=cost,
        cost_adj=_clamp((cost - 0.04) / 0.08, 0.0, 1.0),
        rr=ctx.rr,
        session=f.get("session", 1.0),
        vol_ratio=f.get("vol_ratio", 1.0),
    )


def score_trend(ctx: StageContext) -> Tuple[float, List[str], List[str]]:
    """ATLAS · structure and regime. Pays for aligned, efficient trends and
    refuses late entries into an exhausted move."""
    f, p, pts, risks = ctx.f, _pieces(ctx), [], []
    s = (0.34 * p["align"] + 0.26 * p["eff_adj"] - 0.24 * p["extended"]
         - 0.14 * p["cost_adj"])
    if p["rr"] < 1.8:
        s -= 0.12
        risks.append(f"Reward:risk {p['rr']:.2f} is thin for a continuation")
    if p["rank"] < 0.25:
        s += 0.06
        pts.append(f"Volatility compressed ({p['rank']*100:.0f}th pct) — expansion odds rise")
    pts.append(f"Trend composite {_trend_c(f):+.2f}σ, efficiency {f.get('efficiency',0):.2f} — "
               + ("structure backs the ticket" if p["align"] > 0.15 else
                  "structure does not back the ticket"))
    pts.append(f"Distance from the 20-bar mean: {abs(f.get('stretch',0)):.2f}σ "
               + ("(entry is stretched)" if p["extended"] > 0.4 else "(entry is fresh)"))
    if f.get("dist_hi", 9) < 0.4 and ctx.signal.direction == "short":
        s -= 0.14
        risks.append("Shorts into a 20-bar high: squeeze risk")
    if f.get("dist_lo", 9) < 0.4 and ctx.signal.direction == "long":
        s -= 0.14
        risks.append("Longs into fresh lows: falling-knife risk")
    return _clamp(0.5 + s), pts, risks


def score_quant(ctx: StageContext) -> Tuple[float, List[str], List[str]]:
    """QUANTA · expectancy model. Scores the ticket by modelled edge after cost."""
    f, p, pts, risks = ctx.f, _pieces(ctx), [], []
    # modelled hit probability, then expectancy in R
    phat = _clamp(0.36 + 0.20 * p["align"] + 0.20 * max(0.0, p["eff_adj"])
                  - 0.10 * p["extended"], 0.05, 0.85)
    cost_r = p["cost"] / max(ctx.signal.stop_loss and
                             abs(ctx.signal.entry - ctx.signal.stop_loss) /
                             max(ctx.signal.entry, 1e-9), 1e-9)
    expectancy = phat * p["rr"] - (1.0 - phat) - min(0.25, cost_r)
    hit = ctx.playbook.get("hit_rate")
    if hit is not None:
        pts.append(f"Playbook base rate {hit*100:.0f}% on {ctx.playbook.get('sample',0)} "
                   f"comparable tickets ({ctx.playbook.get('key','')})")
        expectancy += (hit - 0.5) * 0.6
    pts.append(f"Modelled hit rate {phat*100:.0f}% → expectancy {expectancy:+.2f}R "
               f"at {p['rr']:.2f} R:R")
    pts.append(f"Cost {p['cost']*100:.1f}% of the stop distance "
               + ("— workable" if p["cost"] < 0.10 else "— drags the edge"))
    if p["cost"] > 0.14:
        risks.append("Spread and fees eat too much of the stop distance")
    if p["vol_ratio"] > 2.2:
        pts.append(f"Participation {p['vol_ratio']:.1f}× baseline — flow is here")
    if p["rank"] > 0.93:
        s_risk = "Volatility in the top decile"
        risks.append(s_risk + " — size down or widen the stop")
    score = 0.5 + 0.46 * math.tanh(expectancy / 1.1)
    if p["extended"] > 0.6:
        score -= 0.08
        risks.append("Entry is already extended versus the mean")
    return _clamp(score), pts, risks


def score_vol(ctx: StageContext) -> Tuple[float, List[str], List[str]]:
    """VOLTA · volatility & options. Wants a live, directional vol regime with
    room to travel - not a dead tape, and not a crisis print."""
    f, p, pts, risks = ctx.f, _pieces(ctx), [], []
    rank = p["rank"]
    stretch_dir = f.get("stretch", 0.0) * (1 if ctx.signal.direction == "long" else -1)
    band = _clamp(1.0 - abs(stretch_dir - 0.7) / 1.3, -1.0, 1.0)      # peak ≈ 0.7σ
    rank_band = _clamp(1.0 - abs(rank - 0.62) / 0.45, -1.0, 1.0)
    s = 0.18 * p["align"] + 0.18 * band + 0.16 * rank_band
    pts.append(f"Realised vol at the {rank*100:.0f}th percentile of its 120-bar range")
    pts.append(f"Trend-distance {abs(stretch_dir):.2f}σ "
               + ("inside the travel band" if band > 0 else "outside the travel band"))
    if ctx.signal.asset_class == "options":
        und = ctx.signal.symbol.split("-")[0]
        pts.append(f"Chain play on {und}: delta-hedged directional expression, "
                   f"target ≈ {_fmt(ctx.signal.take_profit)}")
        s += 0.08 if rank < 0.85 else -0.20
    if rank > 0.94:
        s -= 0.18
        risks.append("Volatility is in a crisis percentile — implied gaps dominate")
    if rank < 0.18:
        s -= 0.08
        risks.append("Volatility is compressed; follow-through may never arrive")
    if abs(stretch_dir) > 2.0:
        risks.append(f"Entry {abs(stretch_dir):.2f}σ from the mean: mean-reversion risk")
    tail = ctx.playbook.get("tail_events", 0)
    if tail:
        s -= min(0.18, 0.05 * tail)
        risks.append(f"{tail} recent tail events in this asset class")
    return _clamp(0.5 + s), pts, risks


def score_exec(ctx: StageContext) -> Tuple[float, List[str], List[str]]:
    f, p, pts, risks = ctx.f, _pieces(ctx), [], []
    slip = f.get("spread_ratio", 0.0) / max(ctx.atr_pct, 1e-9)
    s = 0.10 * p["align"] + _clamp(0.14 - slip * 1.1, -0.26, 0.14)
    pts.append(f"Modelled slippage {slip*100:.2f}% of ATR at "
               f"{ctx.desk_name or 'desk'} fill (entry {_fmt(ctx.signal.entry)})")
    if slip > 0.15:
        risks.append("Liquidity is too thin for the intended clip")
    rate = f.get("tick_rate", 0.0)
    if rate:
        pts.append(f"Book activity {rate:.1f} ticks/s")
        s += 0.05 if rate > 1.0 else -0.04
    if ctx.signal.horizon == "swing":
        pts.append("Swing horizon: the clip can be worked with passive limits")
        s += 0.05
    if f.get("vol_z", 0.0) > 4.0:
        pts.append("Volume spike present — stage the exits")
        s += 0.04
    if p["rr"] < 1.8:
        s -= 0.12
        risks.append("Thin R:R leaves no room for execution error")
    return _clamp(0.5 + s), pts, risks


# --------------------------------------------------------------------------- #
#  specialist scorecards
# --------------------------------------------------------------------------- #
def score_macro(ctx: StageContext) -> Tuple[float, List[str], List[str]]:
    f = ctx.f
    pts, risks = [], []
    s = 0.0
    hour = f.get("hour", 12.0)
    sess = f.get("session", 1.0)
    if 7.5 <= hour <= 16.5:
        pts.append(f"Prime liquidity window (session factor {sess:.2f}, NY/London overlap)")
        s += 0.18
    elif hour < 5:
        pts.append(f"Asia hours (session factor {sess:.2f}) — thinner books, wider tails")
        s -= 0.10
    else:
        pts.append(f"Late-session drift (session factor {sess:.2f})")
        s += 0.04
    cls = ctx.signal.asset_class
    risk_on = f.get("roc30", 0.0)
    if cls in ("stocks", "indices", "crypto"):
        s += _clamp(risk_on * 6.0, -0.25, 0.25)
        pts.append(f"Cross-asset beta: 30-bar drift {risk_on*100:+.2f}% "
                   + ("supports risk" if risk_on * (-1 if ctx.signal.direction == 'short' else 1) > -0.5 else ""))
    if cls == "forex":
        s += 0.12 if f.get("efficiency", 0) > 0.45 else -0.08
        pts.append("FX leg: carry/differential backdrop treated as neutral-to-supportive")
    if cls == "futures":
        pts.append("Commodity curve in contango — roll drag priced in")
        s += 0.04
    if ctx.playbook.get("source") == "council":
        s += ctx.playbook.get("macro_tilt", 0.0)
    if f.get("atr_rank", 0.5) > 0.8 and sess < 1.0:
        risks.append("High vol into a thin session — gap and headline risk")
        s -= 0.14
    if abs(f.get("roc10", 0.0)) > ctx.atr_pct * 3.2:
        risks.append("Move is already extended versus ATR — chasing late entrants")
        s -= 0.12
    return _clamp(0.5 + s), pts, risks


SCORERS = {
    "judge_trend": score_trend,
    "judge_quant": score_quant,
    "judge_macro": score_macro,
    "judge_vol": score_vol,
    "judge_exec": score_exec,
}


def _narrate(seat: LLMSeat, ctx: StageContext, score: float, verdict: str,
             pts: List[str], risks: List[str]) -> str:
    sig = ctx.signal
    lead = {
        "approve": [
            f"{seat.name} clears this {sig.direction} in {sig.symbol} — passed on my mandate "
            f"({seat.specialty}).",
            f"{seat.name}: I'll sign it. On {seat.specialty} this ticket is internally consistent.",
            f"Approved at the {seat.name} desk: my mandate is {seat.specialty} and the setup holds "
            f"on it.",
        ],
        "reject": [
            f"{seat.name} refuses this {sig.direction} in {sig.symbol} — it fails on my mandate "
            f"({seat.specialty}).",
            f"{seat.name}: sending it back. Judged on {seat.specialty}, the setup as written is "
            f"not investable.",
            f"Held back at the {seat.name} desk: my mandate is {seat.specialty} and this one does "
            f"not clear it.",
        ],
        "abstain": [
            f"{seat.name} abstains — on my mandate ({seat.specialty}) the sample is too thin to "
            f"sign either way.",
        ],
    }[verdict]
    idx = int(abs(hash(seat.id + sig.symbol)) % len(lead))
    head = lead[idx]
    body = " ".join(pts[:3])
    tail = (" Residual concerns: " + "; ".join(risks[:2]) + ".") if risks else " No material objection."
    return f"{head} {body}{tail}"


def evaluate(seat: LLMSeat, ctx: StageContext) -> Dict[str, object]:
    """Score a ticket for one seat.

    The narrative terms come from that desk's specialist checks; the *verdict*
    comes from the calibrated expectancy model, so approvals and refusals are
    tied to measured outcomes rather than to how persuasive the story sounds.
    """
    fn = SCORERS.get(seat.id)
    if fn is None:                     # the CEO and any custom seat use the composite
        parts = [score_trend(ctx), score_quant(ctx), score_macro(ctx), score_vol(ctx), score_exec(ctx)]
        pts = [p for part in parts for p in part[1]][:6]
        risks = [rk for part in parts for rk in part[2]][:5]
    else:
        _narrative, pts, risks = fn(ctx)
    pts = list(pts)
    risks = list(risks)
    prior = float(ctx.playbook.get("expectancy_adj", 0.0) or 0.0)
    pred = predict(ctx.f, ctx.signal.direction, ctx.rr, seat.id, prior)
    if model_ready():
        tilt = desk_tilt(seat.id, ctx.signal.symbol, ctx.signal.direction) * 0.17
        score = _clamp(0.5 + 0.5 * math.tanh(pred / 1.10) + tilt * 0.5)
        pts.insert(0, f"Calibrated expectancy model: {pred:+.2f}R "
                      f"(quintile {percentile(pred)} of the trained distribution)")
    else:
        score = _clamp(0.5 + 0.4 * math.tanh(pred))
    hi, lo = desk_bands(seat.id)
    if score >= hi:
        verdict = "approve"
    elif score <= lo:
        verdict = "reject"
    else:
        verdict = "abstain"
    confidence = _clamp(abs(score - 0.5) * 2.0 * 0.86 + 0.10)
    reasoning = _narrate(seat, ctx, score, verdict, pts, risks)
    return dict(verdict=verdict, confidence=round(confidence, 3),
                score=round((score - 0.5) * 2, 4), expectancy=round(pred, 3),
                reasoning=reasoning, key_points=pts, risks=risks,
                descriptor=seat.specialty, engine="builtin")
