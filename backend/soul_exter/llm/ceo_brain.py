"""NAVEED's advanced training — the curriculum only the CEO holds.

The five cabin judges each see the tape through one specialty lens. NAVEED, the
Head of Council, was *trained* on top of that: a compact professional curriculum
covering regime analysis, expectancy and sizing doctrine, volatility, execution,
portfolio construction, backtest statistics and trading psychology. This module
is that training, in three usable forms:

* ``relevant`` / ``prompt_block``  — retrieval over the curriculum, injected into
  every prompt NAVEED answers with (his hosted model and the built-in engine),
  so his rulings, chats and answers all quote the same doctrine,
* ``overlays`` — the mechanical half of the training: rules from the curriculum
  that adjust his executive synthesis (score deltas, size multipliers, cited
  reasons) on every ticket that reaches the executive chamber,
* ``citation`` — a one-line doctrine quote for his chat voice.

The training is why the CEO outrules the five LLM judges: they vote from a
single angle; he reads their votes *weighted by how relevant each desk's
specialty is to the actual ticket numbers*, then overlays doctrine the cabins
do not hold, and only then does capital move. ``scripts/ceo_study.py`` measures
this — the trained synthesis is expected to beat every individual desk and the
naive majority vote on the same ticket sample.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Doctrine:
    id: str
    domain: str
    keys: Tuple[str, ...]
    title: str
    rule: str          # the mechanical form the executive applies
    lecture: str       # the trained understanding, quoted in answers


CURRICULUM: Tuple[Doctrine, ...] = (
    Doctrine("regime", "regime analysis", ("regime", "chop", "range", "filter", "environment", "conditions"),
             "Regime before direction",
             "Below 0.32 efficiency the desk demands a stronger consensus and never chases breaks.",
             "Classify the regime first and only then argue direction: in an efficient trend you "
             "buy pullbacks and hold structure; in a chop you fade extremes and take less size; "
             "in a regime change the first job is to survive the whipsaw. Direction without a "
             "regime label is a guess wearing a suit."),
    Doctrine("expectancy", "expectancy", ("expectancy", "edge", "positive expectancy", "ev"),
             "Expectancy is the only scoreboard",
             "A ticket is approvable only while E = win%×avgWin − loss%×avgLoss stays positive in R after costs.",
             "E = (win rate × average win) − (loss rate × average loss), always in R and always "
             "after costs. A 45% hit rate paying 2.2R against a 1R stop is +0.44R per ticket and "
             "compounds; a 70% hit rate paying 0.3R is a coin machine that eats you in one bad "
             "week. The floor optimises expectancy, never the win rate."),
    Doctrine("kelly", "position sizing", ("kelly", "fraction", "growth optimal", "half kelly"),
             "Quarter Kelly, never full Kelly",
             "Growth-optimal math caps the clip at a quarter to half of Kelly — heat feels boring, ruin doesn't.",
             "Kelly tells you the growth-optimal fraction; full Kelly also tells you the drawdown "
             "that will make you abandon the system. Professionals run a quarter to a half Kelly "
             "and vol-target on top. The optimal bet and the survivable bet are different bets."),
    Doctrine("vol_target", "volatility", ("vol rank", "atr rank", "volatility", "expansion", "compression", "atr"),
             "Vol rank sizes the clip",
             "Top-decile ATR rank cuts size in half; the same nominal stop is a bigger real risk.",
             "Position size is a function of volatility, not conviction. When ATR sits in the top "
             "decile, your 1×ATR stop is a much wider dollar risk and slippage grows with the "
             "same tape — so the clip halves. Cheap volatility is the only sale worth buying."),
    Doctrine("heat", "portfolio construction", ("heat", "portfolio risk", "open risk", "correlated risk"),
             "Cap the portfolio heat",
             "Total open risk across the book stays under ~3R; correlated tickets share one risk unit.",
             "Portfolio heat is the sum of all open 1R exposures. Cap it — three R of open risk "
             "is a full book for a desk this size — and remember five 'different' tickets that "
             "all short the dollar are one ticket with five commissions."),
    Doctrine("ruin", "risk of ruin", ("ruin", "blow up", "busted", "wipe out"),
             "Survival is the first edge",
             "Nothing is deployed that can end the desk; per-ticket risk is fixed so a losing streak is survivable.",
             "Risk of ruin is the only probability that matters at the tails: with 1% risk per "
             "ticket a 20-loss streak costs 18% of the book and you keep trading; at 10% you are "
             "mathematically dead before the expectancy ever arrives. Size for the streak, not "
             "for the average."),
    Doctrine("drawdown", "drawdown control", ("drawdown", "dd", "recovery", "losing streak"),
             "Know the drawdown arithmetic",
             "Cut size as the equity curve rolls; −20% needs +25%, −50% needs +100%.",
             "Drawdown arithmetic is brutal: −10% needs +11% back, −20% needs +25%, −50% needs "
             "+100%. That asymmetry is why professionals de-risk as the curve rolls instead of "
             "doubling to 'win it back' — the math, not the ego, sets the size."),
    Doctrine("stops", "stop discipline", ("stop", "stop loss", "invalidation", "wrong"),
             "Stops are structural, not negotiable",
             "The stop is placed where the idea is wrong (1×ATR here) and is never widened — only the size flexes.",
             "A stop is the price that proves the idea wrong, placed by structure and volatility "
             "(1×ATR on this floor), and it never moves away from the market. If you feel the "
             "urge to widen a stop, close the ticket instead — the stop you widen is the loss "
             "you are choosing to grow."),
    Doctrine("partials", "trade management", ("partial", "scale out", "take profit", "pay yourself"),
             "Pay the scale: partials at +1.2R",
             "A third comes off at +1.2R; the runner works a 2.2R objective.",
             "Book a third of the clip at +1.2R. It pays the ticket's risk, calms the hands, and "
             "lets the remaining two-thirds work toward the full 2.2R objective with house money. "
             "All-or-nothing exits are how a good system produces bad P&L."),
    Doctrine("trail", "trade management", ("trail", "trailing stop", "let it run", "runner"),
             "Trail with structure, not hope",
             "Beyond breakeven the runner trails at 1.1×ATR; the market, not the trader, ends the trade.",
             "Once a ticket pays, the job is to let it run without giving the gain back: trail at "
             "1.1×ATR beyond breakeven and let the tape close the position. The trend ends when "
             "it ends — the trailing stop is how you stay married to the move and divorced from "
             "your opinion."),
    Doctrine("time_stop", "trade management", ("time stop", "deadline", "expiration", "stale"),
             "Time is a stop too",
             "A ticket past its horizon without progress is flattened at market — capital doesn't wait.",
             "Capital has a carrying cost. A trade that hasn't worked by its horizon (scalp → "
             "intraday → swing) is consuming risk budget while paying nothing: flatten it at "
             "market. 'It will come back' is not a strategy; it is a subscription."),
    Doctrine("sessions", "macro liquidity", ("session", "liquidity window", "overlap", "asia", "london", "new york"),
             "Trade the liquidity, sit out the desert",
             "Momentum entries earn their keep in the session overlaps; dead hours are blacklisted.",
             "Liquidity is a schedule: the London/New York overlap carries the flow, the Asian "
             "lunch drifts, and the last hour before a holiday closes fades everything. The same "
             "setup at 10:00 and at 12:45 midnight are two different trades — only one of them "
             "deserves size."),
    Doctrine("news", "event risk", ("news", "event", "fomc", "nfp", "cpi", "red folder", "earnings"),
             "Respect the red folders",
             "No full clip inside 15 minutes of a scheduled catalyst; the first move is bait.",
             "Scheduled catalysts (rate decisions, CPI, payrolls, earnings) reprice the tape in "
             "seconds and the first print is usually the trap. Either be flat or be reduced — "
             "never full size into a known event, and never assume the first move is the real one."),
    Doctrine("staging", "execution", ("stage", "vwap", "twap", "slice", "fill", "algorithm"),
             "Stage the clip, don't dump it",
             "Full clips route as slices (VWAP/TWAP or staged limits) with a slippage budget of ~0.05R.",
             "Execution is a cost line you control: a full market order donates the spread and a "
             "slice of momentum to the room. Work the clip with VWAP/TWAP logic or staged limits, "
             "budget ~0.05R of slippage, and stop trading when the tape is thinner than your "
             "patience."),
    Doctrine("spread", "execution", ("spread", "slippage", "cost", "commission"),
             "Spread is a tax on urgency",
             "Wide-spread conditions take limit orders only, or no trade.",
             "Every trade starts owing the spread; the wider it is, the further the idea has to "
             "walk just to break even. When the spread blows out, the market is telling you who "
             "pays for liquidity — answer with limit orders or with silence."),
    Doctrine("distance", "volatility", ("atr percent", "atr pct", "distance", "wide stop", "quiet instrument"),
             "Distance is risk — price-relative vol",
             "Instruments whose ATR runs >1.2% of price carry a cut clip; quiet tape (<0.5%) earns full size.",
             "Two instruments can both 'have volatility' while only one is tradeable: what matters "
             "is distance as a fraction of price. When ATR runs over a percent of price, every "
             "fixed-R target lives commensurately further out in time and noise, fills degrade, "
             "and the 2.2R objective stops being reached before the horizon dies. The trained "
             "preference is for quiet instruments where distance works for the position, not "
             "against it."),
    Doctrine("surface", "volatility", ("skew", "surface", "options", "puts", "calls", "iv"),
             "Read the surface, not the quote",
             "Skew and IV rank say which tail the crowd is priced for; the desk fades mispriced fear.",
             "The options surface is the market's fear ledger: IV rank says if protection is on "
             "sale, skew says which tail the crowd is already paying for. Direction is opinion — "
             "the surface is inventory. Trade the mispricing between them, size for the tail "
             "they are NOT priced for."),
    Doctrine("greeks", "volatility", ("delta", "gamma", "theta", "vega", "hedge"),
             "Greeks are exposures, not trivia",
             "Directional P&L is only ever one of four exposures; the desk knows which three it is implicitly short.",
             "Delta is direction, gamma is how fast direction changes, theta is rent, vega is the "
             "fear position. Any position — spot, futures or options — is a bundle of all four, "
             "and professionals can state which ones they are implicitly short before they click "
             "the button."),
    Doctrine("carry", "macro liquidity", ("carry", "basis", "funding", "contango", "backwardation"),
             "Carry moves crowds; trade the flip",
             "Funding and basis extremes mark crowded boats; the desk trades the unwind, not the level.",
             "Funding rates, futures basis and roll yield tell you which boat is crowded and how "
             "painful it will be to leave. Extreme positive carry finances the crowd's favourite "
             "trade — and the unwind of that crowd is where the fast money lives. Trade the flip, "
             "not the level."),
    Doctrine("flow", "microstructure", ("order flow", "imbalance", "absorption", "delta", "tape reading"),
             "Flow confirms or it denies",
             "Entries want resting-liquidity absorption behind them; flow against the ticket halves its size.",
             "Price tells you what; order flow tells you how: imbalance, absorption and effort-"
             "versus-result at the level. A breakout with resting sellers absorbing underneath is "
             "a trap with a chart; the same break with aggressive lifting and no absorption is a "
             "ticket. Flow is the lie detector."),
    Doctrine("meanrev", "strategy", ("mean reversion", "fade", "overbought", "oversold", "rsi"),
             "Fade ranges, ride trends",
             "Stretched RSI is a fade only inside a range; inside a trend the same reading is strength.",
             "The same RSI print means opposite things in different regimes: above 70 in a range "
             "is a gift for the fade; above 70 inside an efficient uptrend is momentum you pay "
             "up for. Never fade structure, never chase a range — identify which one you are in "
             "before touching the stretched indicator."),
    Doctrine("overfit", "quant method", ("backtest", "overfit", "sharpe", "walk forward", "sample", "curve fit"),
             "Distrust beautiful backtests",
             "Under ~10 comparable samples the playbook earns observation, not size; thin evidence, thin clip.",
             "A backtest that was tuned until it shone is a biography of the past, not a "
             "forecast: deflated Sharpe, walk-forward splits and out-of-sample honesty are what "
             "separate an edge from a curve-fit. On a live floor this means small samples earn "
             "small size — ten trades is a hint, a hundred is evidence."),
    Doctrine("psychology", "trading psychology", ("psychology", "discipline", "revenge", "tilt", "bias", "fomo"),
             "Judge the process, never the last ticket",
             "Sizing and verdicts never change because of the previous outcome; only the evidence moves them.",
             "Disposition bias sells winners early and nurses losers; recency bias trades the "
             "last candle; revenge trading trades the last loss. The cure is procedural: fixed "
             "risk per ticket, written reasons, and a rule that the previous outcome has no vote "
             "in the next decision. Boredom and FOMO are position-sizing errors wearing costumes."),
    Doctrine("pressing", "portfolio construction", ("press", "add", "pyramid", "average down", "double down"),
             "Press winners, never average losers",
             "Adds go only to tickets already in profit and only inside the heat budget; losers get one decision: hold the plan or exit.",
             "Adding to winners inside the heat budget is how a good day becomes a great one; "
             "adding to losers is how a bad idea becomes a ruinous one. The desk pyramids into "
             "strength, never averages into weakness, and each add re-checks the stop and the "
             "heat cap."),
    Doctrine("correlation", "portfolio construction", ("correlation", "contagion", "risk on", "risk off", "converge"),
             "Correlations converge exactly when you need them not to",
             "When cross-asset correlation runs hot, treat the book as one position and de-risk the overlap.",
             "Diversification is written in calm weather and tested in storms: in a liquidation "
             "everything you own correlates to 1. When cross-asset correlation spikes, the book "
             "is one big position wearing several symbols — cut the overlap before the market "
             "cuts it for you."),
    Doctrine("gaps", "risk of ruin", ("gap", "overnight", "weekend", "close", "open risk"),
             "Respect the gap between sessions",
             "Positions that can gap past the stop carry reduced size going into closes and weekends.",
             "A stop orders your exit; a gap decides it. Overnight holds, weekends and holidays "
             "can open straight through a 1×ATR stop, so anything that must survive a close "
             "carries deliberately smaller size. The market opens when it wants, at the price it "
             "wants."),
)


# --------------------------------------------------------------------------- #
#  retrieval — what does the training say about this text?
# --------------------------------------------------------------------------- #
def _score(doctrine: Doctrine, lowered: str) -> int:
    s = 0
    for k in doctrine.keys:
        if k in lowered:
            s += len(k)
    if doctrine.domain.split()[0] in lowered:
        s += 2
    return s


def relevant(text: str, k: int = 3) -> List[Doctrine]:
    """Top-k doctrines whose keys touch the text (empty text → the core trio)."""
    lowered = (text or "").lower()
    scored = sorted(((_score(d, lowered), i, d) for i, d in enumerate(CURRICULUM)),
                    key=lambda x: (-x[0], x[1]))
    hits = [d for s, _i, d in scored if s > 0][:k]
    if not hits:                                   # the training's bedrock
        hits = [d for d in CURRICULUM if d.id in ("expectancy", "regime", "vol_target")][:k]
    return hits[:k]


def training_summary() -> str:
    domains: List[str] = []
    for d in CURRICULUM:
        if d.domain not in domains:
            domains.append(d.domain)
    return f"{len(CURRICULUM)} doctrines across {len(domains)} domains: " + ", ".join(domains)


def prompt_block(text: str, k: int = 3) -> str:
    """The trained-doctrine block injected into NAVEED's prompts."""
    hits = relevant(text, k)
    lines = [f"ADVANCED TRAINING — doctrines you (and only you) were trained on "
             f"({training_summary()}):"]
    lines += [f"• {d.title}: {d.rule}" for d in hits]
    lines.append("Apply the training before the vote tally; cite which doctrine moved you.")
    return "\n".join(lines)


def voice_note() -> str:
    """Short standing note for NAVEED's chat-room system prompt."""
    return ("You are the most trained desk on this floor: you alone hold the advanced "
            f"curriculum ({training_summary()}). Speak from it — cite a doctrine by name "
            "when it is why you believe something — and mentor the cabins.")


def citation(question: str, k: int = 1) -> str:
    """A one-line trained quote for NAVEED's answer voice (None if nothing applies)."""
    hits = relevant(question, k)
    if not hits:
        return ""
    d = hits[0]
    return f"From my advanced training — {d.title}: {d.lecture}"


# --------------------------------------------------------------------------- #
#  the mechanical half — doctrine rules applied to a live ticket
# --------------------------------------------------------------------------- #
def _trend_composite(f: Dict[str, float]) -> float:
    """Signed trend composite (matches the calibration studies / analyst engine)."""
    return float(0.62 * math.tanh(f.get("slope21", 0.0) * 120.0)
                 + 0.38 * math.tanh(f.get("slope50", 0.0) * 80.0))


# public alias — the engine's synthesis reads it too
trend_composite = _trend_composite


class Overlays:
    """Result of applying the doctrine rules to one ticket."""

    def __init__(self) -> None:
        self.delta = 0.0                 # score adjustment
        self.size_mult = 1.0             # multiplier on the mandate's clip
        self.notes: List[str] = []       # cited doctrines, in application order

    def note(self, doctrine_id: str, text: str) -> None:
        d = next((x for x in CURRICULUM if x.id == doctrine_id), None)
        self.notes.append(f"{d.title} — {text}" if d else text)


def overlays(f: Dict[str, float], playbook: Optional[dict], direction: str,
             rr: float, fly_score: float, horizon: str = "") -> Overlays:
    """Run the trained rules over a ticket. Pure, deterministic, microsecond-fast.

    The rule levels (efficiency bands, ATR-percent bands, RSI pullback zones)
    are calibrated on pooled settled-ticket samples from the entry gate — the
    same way the floor's other thresholds were tuned (council_study). NAVEED
    holds these; the five cabins do not.
    """
    ov = Overlays()
    sgn = 1.0 if direction == "long" else -1.0

    # vol_target: top-decile ATR rank halves the clip (a wider real risk per stop)
    atr_rank = float(f.get("atr_rank", 0.5))
    if atr_rank > 0.85:
        ov.size_mult *= 0.5
        ov.delta -= 0.04
        ov.note("vol_target", f"ATR rank {atr_rank:.2f} is top-decile — clip halved")

    # distance: ATR as % of price — the trained edge the cabins do not hold
    atr_pct = float(f.get("atr_pct", 0.0) or 0.0)
    if atr_pct > 0.012:
        ov.delta -= 0.20
        ov.size_mult *= 0.7
        ov.note("distance", f"ATR {atr_pct*100:.2f}% of price — distance works against the "
                            f"position, clip cut hard")
    elif atr_pct > 0.005:
        ov.delta -= 0.08
        ov.note("distance", f"ATR {atr_pct*100:.2f}% of price — wide tape, target lives far out")
    elif atr_pct > 0:
        ov.delta += 0.05
        ov.note("distance", f"ATR {atr_pct*100:.2f}% of price — quiet instrument, distance on our side")

    # regime: efficiency bands — the strongest single predictor the tape offers
    eff = float(f.get("efficiency", 0.5))
    tc = _trend_composite(f)
    if eff < 0.32:
        ov.delta -= 0.18
        ov.note("regime", f"efficiency {eff:.2f} < 0.32 — chop rules, direction needs a stronger case")
    elif eff < 0.45:
        ov.delta -= 0.10
        ov.note("regime", f"efficiency {eff:.2f} — lazy tape, the trend must pay for the noise")
    elif eff < 0.55:
        ov.delta -= 0.04
        ov.note("regime", f"efficiency {eff:.2f} — middling tape, size stays honest")
    elif eff > 0.65:
        ov.delta += 0.08
        ov.note("regime", f"efficiency {eff:.2f} — clean trend tape, continuation is the base case")

    # momentum alignment with the ticket's direction
    if abs(tc) > 0.30:
        if sgn * tc > 0:
            ov.delta += 0.04
            ov.note("meanrev", f"trend composite {tc:+.2f} rides with the {direction} — structure agrees")
        else:
            ov.delta -= 0.12
            ov.note("meanrev", f"trend composite {tc:+.2f} opposes the {direction} — fading structure")

    # meanrev: pullback entries inside a trend are the trained favourite;
    # stretched entries chasing the band are the trained bleed
    rsi = float(f.get("rsi", 50.0))
    if direction == "long" and rsi < 35:
        ov.delta += 0.10
        ov.note("meanrev", f"RSI {rsi:.0f} into a {direction} — buying the pullback inside the trend")
    elif direction == "short" and rsi > 65:
        ov.delta += 0.10
        ov.note("meanrev", f"RSI {rsi:.0f} into a {direction} — selling the pop inside the trend")
    elif direction == "long" and rsi > 75:
        ov.delta -= 0.08
        ov.note("meanrev", f"RSI {rsi:.0f} — stretched, chasing the top of the band")
    elif direction == "short" and rsi < 25:
        ov.delta -= 0.08
        ov.note("meanrev", f"RSI {rsi:.0f} — stretched, covering into the squeeze")

    # payoff discipline
    if rr < 1.6:
        ov.delta -= 0.06
        ov.note("expectancy", f"R:R {rr:.2f} under 1.6 — the payoff does not pay the variance")
    elif rr >= 2.2:
        ov.delta += 0.05
        ov.note("expectancy", f"R:R {rr:.2f} — payoff clears the desk's 2.2R bar")

    # the playbook is the desk's own memory — press proven buckets, respect thin ones
    if playbook and playbook.get("hit_rate") is not None:
        hr = float(playbook["hit_rate"])
        sample = int(playbook.get("sample", 0) or 0)
        if sample >= 8 and hr >= 0.56:
            ov.size_mult *= 1.15
            ov.delta += (hr - 0.5) * 0.4
            ov.note("overfit", f"playbook bucket {playbook.get('key','')} runs {hr*100:.0f}% "
                               f"over {sample} trades — proven bucket earns a press")
        elif sample < 4:
            ov.size_mult *= 0.8
            ov.note("overfit", f"playbook sample {sample} is thin — evidence earns observation, not size")

    # spread is a tax on the fill
    spread_ratio = float(f.get("spread_ratio", 0.0) or 0.0)
    if spread_ratio > 0.0012:
        ov.size_mult *= 0.85
        ov.note("spread", f"spread ratio {spread_ratio*1000:.2f}‰ — the fill tax is heavy, clip trimmed")

    # the hunter's own conviction still counts
    if fly_score < 0.45:
        ov.delta -= 0.05
        ov.note("flow", f"fly conviction {fly_score:.2f} is soft — the tape did not argue hard")

    # scalps in hot volatility age badly
    if horizon == "scalp" and atr_rank > 0.7:
        ov.size_mult *= 0.85
        ov.note("time_stop", "scalp horizon in hot volatility — time stops bite first")

    ov.delta = max(-0.55, min(0.45, ov.delta))
    return ov


def citations_for(f: Dict[str, float], playbook: Optional[dict], limit: int = 2) -> List[str]:
    """Short 'Training:' citations for the executive's key points."""
    text = " ".join(f"{k} {v}" for k, v in (f or {}).items())
    return [f"Training — {d.title}: {d.rule}" for d in relevant(text, limit)]
