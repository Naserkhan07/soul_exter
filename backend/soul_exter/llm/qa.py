"""Open-domain answering for the six desks.

Every seat on the floor has to be able to answer the operator — a question about a
ticket, a market, risk, the floor itself, or anything else that gets typed. This
module is the *building* answer used whenever a hosted model is not configured (or
is unreachable), and it is intentionally broad:

* ticket questions  → the desk's own recorded verdict, its key points and risks
* market questions  → live metrics for that symbol from the same feed the
                      scanner hunts on (trend composite, RSI, ATR, efficiency…)
* floor questions   → live counters, book quality, the roster, the fly brain
* trading knowledge → a compact professional reference (expectancy, sizing,
                      greeks, basis, carry, drawdown, execution, psychology…)
* plain questions   → arithmetic, time, or a structured in-persona answer

Nothing here ever answers "I don't know": if a question falls outside every
handler, the desk still answers from its mandate, says what it would need to be
precise, and offers the next concrete step.
"""
from __future__ import annotations

import ast
import math
import operator
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from . import ceo_brain
from . import human
from .registry import LLMSeat

# --------------------------------------------------------------------------- #
#  voice
# --------------------------------------------------------------------------- #
LENS: Dict[str, str] = {
    "judge_trend": "trend structure and market regime",
    "judge_quant": "expectancy, risk and position sizing",
    "judge_macro": "macro liquidity, rates and cross-asset flow",
    "judge_vol": "volatility, the options surface and tail risk",
    "judge_exec": "execution, microstructure and slippage",
    "ceo": "the advanced trading doctrine and capital allocation",
    "hunter": "tick-level pattern hunting and the fly's raw read of the tape",
}

OPENERS: Dict[str, List[str]] = {
    "judge_trend": ["Structure first:", "Reading the tape:", "From the trend desk:"],
    "judge_quant": ["Numbers first:", "From the risk desk:", "Expectancy view:"],
    "judge_macro": ["Top-down:", "Liquidity view:", "From the macro desk:"],
    "judge_vol": ["Volatility first:", "From the vol desk:", "Surface view:"],
    "judge_exec": ["Fill quality first:", "From the execution desk:", "Practical view:"],
    "ceo": ["My ruling:", "From the head of council:", "My trained read:"],
}

ALIASES: Dict[str, str] = {
    "gold": "GC", "oil": "CL", "crude": "CL", "wti": "CL", "brent": "CL",
    "s&p": "SPX", "sp500": "SPX", "spx": "SPX", "nasdaq": "NDX", "dax": "DAX",
    "nikkei": "N225", "vix": "VX", "volatility index": "VX",
    "bitcoin": "BTCUSD", "btc": "BTCUSD", "ethereum": "ETHUSD", "eth": "ETHUSD",
    "solana": "SOLUSD", "sol": "SOLUSD", "doge": "DOGEUSD", "dogecoin": "DOGEUSD",
    "ripple": "XRPUSD", "xrp": "XRPUSD", "link": "LINKUSD", "chainlink": "LINKUSD",
    "apple": "AAPL", "nvidia": "NVDA", "microsoft": "MSFT", "tesla": "TSLA",
    "meta": "META", "facebook": "META", "amazon": "AMZN", "amd": "AMD",
    "coinbase": "COIN", "jpmorgan": "JPM", "jpm": "JPM",
    "euro": "EURUSD", "eur/usd": "EURUSD", "pound": "GBPUSD", "cable": "GBPUSD",
    "yen": "USDJPY", "usd/jpy": "USDJPY", "aussie": "AUDUSD", "kiwi": "NZDUSD",
    "loonie": "USDCAD", "franc": "USDCHF", "peso": "USDMXN", "euroyen": "EURJPY",
}

# --------------------------------------------------------------------------- #
#  trading knowledge base — keyword tuples -> (topic, answer)
# --------------------------------------------------------------------------- #
TOPICS: List[Tuple[Tuple[str, ...], str, str]] = [
    (("expectancy", "expectancy model", "edge per trade"),
     "Expectancy",
     "Expectancy is what a system earns per unit of risk on average: "
     "E = (win rate × average win) − (loss rate × average loss), best expressed in R. "
     "A 45% win rate on a 2.2R payoff gives 0.45×2.2 − 0.55×1 = +0.44R per trade — that is the "
     "number the floor optimises, not the win rate. Anything with positive expectancy and "
     "controlled per-trade risk compounds; anything without it loses slowly no matter how good "
     "the story is."),
    (("r multiple", "r-multiple", "risk multiple", "how do you measure", "in r"), "R multiples",
     "One R is the distance from entry to stop, so every result is normalised: +2R means you made "
     "twice what you risked, −1R means the stop took exactly the planned risk. Expressing P&L in R "
     "makes different instruments comparable, which is why every ticket on this floor carries a "
     "planned stop of 1.00 ATR and a target of 2.20 ATR (2.2R if it pays in full)."),
    (("position size", "sizing", "how much should i risk", "lot size", "kelly", "how big"),
     "Position sizing",
     "Size from risk, never from conviction: size = (account × risk % per trade) ÷ (stop distance "
     "in price × value per point). Risking 0.5–1% per ticket with a 1 ATR stop keeps a losing "
     "streak survivable; Kelly tells you the growth-optimal fraction but it is far too hot for a "
     "real book — professionals trade a quarter to a half Kelly at most, and vol-target when ATR "
     "percentiles spike."),
    (("drawdown", "max dd", "losing streak", "risk of ruin"), "Drawdown control",
     "Drawdown is the constraint that ends careers, not the win rate. Cap portfolio heat (say 3R "
     "of open risk), cut size when the equity curve rolls over, and remember the arithmetic of "
     "recovery: −20% needs +25%, −50% needs +100%. On this floor nothing beyond a ticket's stop is "
     "deployed, which is why counterfactual R on vetoed tickets is tracked as carefully as realised "
     "P&L."),
    (("atr", "average true range", "volatility measure"), "ATR",
     "ATR is the average true range over N bars — the honest measure of how far an instrument "
     "actually travels. Stops live in ATR units (1.0 ATR here), targets in ATR units, and size "
     "scales inversely with it. When ATR percentile is in the top decile, the same nominal stop is "
     "a much wider risk, so the desk takes a smaller clip or stands aside."),
    (("rsi", "relative strength index", "overbought", "oversold"), "RSI",
     "RSI measures the balance of gains to losses over 14 bars: above 70 is stretched, below 30 is "
     "flushed — but in a real trend it stays pinned for days. Professionals use it as context, not "
     "as a signal: an overbought RSI inside an efficient uptrend is strength, while the same "
     "reading inside a range is where you sell. Divergence plus a failed structural break is the "
     "tradeable version."),
    (("moving average", "ema", "sma", "golden cross", "death cross"), "Moving averages",
     "Moving averages are lagging filters, useful for smoothing the regime rather than generating "
     "entries: price above a rising 50/200 pair is trend, the same pair crossing is a regime "
     "change, and a flat pair means mean reversion. This floor leans on a slope composite "
     "(0.62×tanh of the 21-bar slope + 0.38× of the 50-bar slope) instead of a single cross, "
     "because a single cross is late twice as often as it is early."),
    (("support", "resistance", "level", "round number", "supply", "demand zone"),
     "Levels",
     "Support and resistance are places where resting orders were left, so they work until they "
     "are violently consumed. Mark them on higher timeframes, trade the reaction on lower ones, and "
     "respect round numbers — they concentrate option strikes and stops. A break that closes "
     "beyond a level with expanding volume is a different animal from a wick that touches it."),
    (("efficiency", "adx", "trend strength", "chop", "chopiness"), "Trend efficiency",
     "Efficiency ratios answer 'is this tape going somewhere or just breathing?' — net move divided "
     "by path length. Below ~0.30 you are paying spread for noise, which is why the scanner refuses "
     "to strike there. Combine it with ADX (above 25 = directional) before trusting any breakout."),
    (("liquidity", "spread", "bid ask", "depth"), "Liquidity",
     "Liquidity is the ability to trade size without paying for it: tight spreads, deep books, "
     "overlapping sessions. It is highest in the London/New York overlap and just after the cash "
     "open, and it evaporates at the roll and around 21:00–23:00 UTC. Every strategy should be "
     "sized to the depth it actually trades in — an edge of 12 ticks dies in a 15-tick spread."),
    (("slippage", "fill", "execution", "vwap", "twap", "iceberg", "market impact"),
     "Execution",
     "Execution is where paper edge meets reality: slippage, partial fills and impact. Market "
     "orders guarantee the fill but not the price; limit orders guarantee the price but not the "
     "fill. For anything above a few clips use a schedule (VWAP/TWAP), work the passive side when "
     "you expect continuation, and always measure realised slippage against the decision price — "
     "what is not measured is not managed."),
    (("leverage", "margin", "notional"), "Leverage",
     "Leverage multiplies P&L and error equally, and margin is the venue's price for it. The "
     "sensible frame is not 'what leverage can I get' but 'what position keeps a 3-sigma adverse "
     "move survivable' — usually 1–5× notional on liquid instruments, far less on anything "
     "exotic. Margin calls are a liquidity event, not a market view."),
    (("risk reward", "risk/reward", "reward to risk", "rr ", "payoff"), "Risk/reward",
     "Risk/reward only means something next to a hit rate. 2.2:1 at 45% wins is a business; 2.2:1 "
     "at 25% wins is a slow bleed. Break-even win rate = 1 ÷ (1 + RR), so a 2.2R payoff breaks "
     "even at 31%. Everything on this floor is judged on realised R after the outcome horizon, not "
     "on the ratio printed at entry."),
    (("sharpe", "sortino", "risk adjusted", "calmar"), "Risk-adjusted return",
     "Sharpe divides excess return by volatility; Sortino divides by downside deviation only; "
     "Calmar divides return by max drawdown. None of them mean much on a small sample — a Sharpe "
     "of 3 over 40 trades is noise. Use them to compare allocation choices on hundreds of trades, "
     "and use drawdown in R to decide whether you can actually hold the strategy."),
    (("correlation", "portfolio heat", "diversif"), "Correlation",
     "Correlation is the hidden position size: five long dollar pairs is one trade with five "
     "tickets. Cluster exposure by factor (USD, rates, energy, tech beta, crypto beta) and cap the "
     "cluster, not the ticket. Correlation also rises toward 1 in a crisis, exactly when you need "
     "the diversification you thought you had."),
    (("hedge", "hedging", "pair trade"), "Hedging",
     "A hedge is a cost, so only buy it for a reason: event risk you cannot size, or a book you "
     "cannot exit quickly. Beta hedges (index against single name, cross-currency against the "
     "dollar leg) work when the correlation is stable; 'insurance' bought after the move is just "
     "paying the market a fee for your discomfort."),
    (("delta", "gamma", "theta", "vega", "greek", "implied volatility", "iv "),
     "Options greeks",
     "Delta is directional exposure, gamma how fast that exposure changes, theta what you pay for "
     "waiting, and vega how much implied vol is worth to you. Long options buy gamma and short "
     "theta; selling premium is the reverse. Skew tells you where the market pays for protection — "
     "an expensive put wing is information about positioning, not a free lunch."),
    (("option", "0dte", "zero day", "expiry", "expiration", "strike"), "Options mechanics",
     "Expiry is a liquidity event: gamma concentrates, dealers hedge mechanically and intraday "
     "ranges expand into the close. 0DTE books are pure microstructure — trade them with hard "
     "stops and small clips, or not at all. Multi-day structures should be chosen by what you "
     "expect to happen to implied volatility, not just to price."),
    (("contango", "backwardation", "basis", "roll", "carry"), "Futures basis & carry",
     "Futures price = spot + financing − carry, so the curve shape is the market's cost of waiting. "
     "Contango (upward sloping) bleeds long holders into the roll; backwardation pays them. Roll "
     "dates are liquidity cliffs — the front contract decays into noise while volume migrates, so "
     "position and stop levels must migrate too."),
    (("interest rate", "yield", "fed", "fomc", "cpi", "inflation", "nfp", "payroll",
      "central bank", "macro e"),
     "Macro drivers",
     "Rates and inflation expectations drive everything: real yields set the discount rate, the "
     "dollar sets global liquidity, and surprise vs expectation is what moves price — the level is "
     "usually already in the tape. The calendar events that matter most are CPI, central-bank "
     "decisions and payrolls; spreads widen and stops get run through those prints, so size for it "
     "or stand aside."),
    (("dxy", "dollar index", "dollar strength"), "The dollar",
     "The dollar is the world's funding currency and the tide of risk appetite: a firm DXY usually "
     "presses commodities, crypto and non-US equities, and it moves on rate differentials and "
     "liquidity stress. Most FX and metals trades are, at bottom, a dollar view — know which one "
     "you are actually taking."),
    (("session", "tokyo", "london", "new york", "overlap", "killzone", "asia"),
     "Sessions",
     "Each session has a personality: Asia ranges and sets the box, London expands it, the "
     "London/New York overlap carries the real volume, and the New York afternoon fades trends "
     "into the close. Most reliable breakouts happen in the first two hours of the dominant "
     "session; most stop runs happen into the roll."),
    (("crypto", "bitcoin halving", "funding rate", "on-chain", "perpetual"), "Crypto specifics",
     "Crypto trades 24/7 without a closing bell, so the auction never resets: funding rates on "
     "perpetuals tell you who is paying to hold the crowd's view, and liquidation cascades are the "
     "dominant short-term move. Weekend liquidity is thin, gaps are real, and on-chain flow is a "
     "positioning input rather than a timing signal."),
    (("psychology", "tilt", "revenge", "fear", "greed", "discipline", "patience"),
     "Trading psychology",
     "Most drawdowns are process failures, not model failures: revenge trades after a loss, size "
     "creep after a win, and refusing to take the signal that hurts. The professionals' trick is "
     "mechanical — a written plan, a fixed risk per ticket, a mandatory cool-off after two losers, "
     "and a journal that records the reason for every entry so the excuses are visible later."),
    (("journal", "diary", "review process"), "Journaling & review",
     "A journal is a dataset: setup, reason, planned risk, execution quality, outcome, one line on "
     "what you would repeat. Review weekly by bucket — instrument, session, setup, direction — and "
     "act only on buckets with enough samples. That is exactly the loop the council's debate "
     "chamber runs here, but for humans it needs to be written down to be honest."),
    (("backtest", "overfit", "walk forward", "curve fit", "in-sample", "out-of-sample"),
     "Backtesting",
     "Every backtest is a story about the past told with the benefit of hindsight. Guard against "
     "overfitting with walk-forward validation, a penalty for every free parameter, and a hard "
     "out-of-sample sample. If a tweak only helps in-sample, it is not an edge, it is a memory. On "
     "this floor the expectancy model is fitted on one tape and reported on another."),
    (("variance", "signal to noise", "sample size", "statistical"), "Sample size",
     "With a 2.2R payoff at a 45% hit rate you need roughly a hundred trades before the average "
     "means anything, and several hundred before the difference between two systems is real. Until "
     "then, judge the process — risk per trade, bucket mix, execution quality — not the equity "
     "curve."),
    (("news risk", "earnings", "event risk", "gap risk"), "Event risk",
     "Scheduled news is a volatility repricing: spreads widen, stops slip and correlations go to "
     "one. Either cut size into the print, widen the stop and shrink the clip to keep the same R, "
     "or trade the reaction once the level is reclaimed. Never let an unsized event decide your "
     "risk for you."),
    (("stop loss", "stop placement", "where do you put your stop"), "Stops",
     "A stop belongs where the trade idea is *wrong*, not where your account hurts: beyond the "
     "structure that invalidates the setup, sized so that invalidation costs an acceptable "
     "fraction of the book. One ATR plus a small buffer is the floor's default because it survives "
     "ordinary noise; anything tighter is usually a donation to the market maker."),
    (("take profit", "exit", "scale out", "trail"), "Exits",
     "Exits are chosen before entry: a fixed target (2.2 ATR here) keeps the expectancy measurable, "
     "scaling out smooths the equity curve at the cost of the tail, and trailing only after 1R "
     "converts a winner into a break-even trade legitimately. What kills accounts is mixing plan "
     "and impulse mid-trade."),
    (("compounding", "growth", "how long"), "Compounding",
     "Compounding is a function of expectancy, frequency and drawdown control: +0.4R per trade at "
     "0.75% risk, a hundred trades a month, is roughly +30% on the account *if* the losing sequence "
     "never forces a size cut. Time in the market is not the variable — surviving your own worst "
     "month is."),
    (("meta trader", "mt5", "metatrader", "expert advisor", "mql"), "MT5 execution",
     "MetaTrader 5 is the retail execution layer most FX and CFD desks use: `order_send` with a "
     "request filling mode, positions rather than tickets held net per symbol, and slippage "
     "controlled by deviation. This floor talks to it through the Broker tab — paper fills by "
     "default, live orders the moment you paste an account, server and password."),
    (("kaggle", "gpu", "how is it hosted", "where does it run"), "Hosting",
     "The heavy work — the fly brain, the scanner, the council and the 3D floor — runs on a free "
     "Kaggle GPU session; the browser only renders the hall and streams the websocket. Nothing "
     "trains on your laptop, and the notebook in `kaggle/` boots the whole floor behind a port "
     "proxy in a few minutes."),
    (("fly", "fly brain", "drosophila", "scanner", "how do you find trades", "signal"),
     "The fly brain",
     "Trade discovery is a fly: 26 projection neurons, 140 Kenyon cells with k-winner-take-all "
     "sparsity, 8 mushroom-body output neurons, Hebbian feedback from realised outcomes. It reads "
     "microstructure, momentum and volatility features from the tape and only fires when the "
     "descending neurons cross a calibrated threshold — that firing is what walks in through the "
     "welcome door and becomes a ticket."),
    (("who is the ceo", "head of council", "naveed"), "The head of council",
     "NAVEED is the head of council and CEO of this floor: he keeps the whole record — every "
     "cabin's verdict, confidence, key points and risks — and rules on the split tickets that "
     "reach the executive chamber. Five unanimous cabins clear without him; anything at 3/5 or "
     "4/5 is his to allow or refuse, and his ruling is the binding one."),
]

TRADING_HINTS = ("trade", "trading", "market", "tape", "price", "risk", "stop", "target",
                  "position", "size", "sizing", "leverage", "margin", "spread", "volatility",
                  "vol ", "atr", "rsi", "trend", "range", "breakout", "setup", "signal",
                  "portfolio", "drawdown", "equity", "hedge", "option", "future", "forex",
                  "crypto", "stock", "index", "indices", "bond", "yield", "rate", "inflation",
                  "entry", "exit", "profit", "loss", "win", "book", "exposure", "correlation",
                  "broker", "order", "fill", "clip", "lots", "expectancy", "edge", "backtest",
                  "strategy", "desk", "cabin", "council", "floor", "ticket", "brain", "fly")

ROSTER_KEYS = ("who are you", "your name", "what is your name", "who am i talking",
               "who are the judges", "who is on the council", "list the council",
               "who works here", "your colleagues", "who else is", "tell me about the desks",
               "who is naveed", "desk list")

# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
_SAFE_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
             ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval_expr(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_expr(node.body)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval_expr(node.left), _eval_expr(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval_expr(node.operand))
    raise ValueError("not a simple expression")


def _fmt(x: Optional[float], digits: int = 4) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    x = float(x)
    if abs(x) >= 10000:
        return f"{x:,.0f}"
    if abs(x) >= 1000:
        return f"{x:,.2f}"
    if abs(x) >= 10:
        return f"{x:,.3f}"
    return f"{x:.{digits}f}"


def _pick(seat: LLMSeat, salt: str = "") -> str:
    opts = OPENERS.get(seat.id, [f"{seat.name}:"])
    return opts[int(abs(hash(seat.id + salt)) % len(opts))]


def _lens(seat: LLMSeat) -> str:
    return LENS.get(seat.id, seat.specialty or "the desk mandate")


def _symbol_in(question: str, ctx: Dict[str, Any]) -> Optional[str]:
    """Find the instrument the operator is asking about (symbol or nickname)."""
    q = question.lower()
    known: List[str] = []
    for row in ctx.get("markets") or []:
        if row.get("symbol"):
            known.append(str(row["symbol"]))
    for t in ctx.get("recent") or []:
        if t.get("symbol"):
            known.append(str(t["symbol"]))
        for v in t.get("verdicts") or []:
            if v.get("symbol"):
                known.append(str(v["symbol"]))
    for own in ctx.get("own") or []:
        if own.get("symbol"):
            known.append(str(own["symbol"]))
    for alias, sym in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", q):
            return sym
    # longest symbol first so EURUSD wins over EUR
    for sym in sorted(set(known), key=lambda s: -len(s)):
        if re.search(rf"(?<![a-z0-9]){re.escape(sym.lower())}(?![a-z0-9])", q):
            return sym
    m = re.findall(r"\b([A-Z]{3,8}(?:USD|JPY|CHF|CAD|AUD|NZD|MXN|EUR|GBP)?)\b", question)
    for token in m:
        if token in known:
            return token
    for token in m:
        if token in ALIASES.values():
            return token
    return None


def _market_row(ctx: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    for row in ctx.get("markets") or []:
        if row.get("symbol") == symbol:
            return row
    return {}


def _stats_line(ctx: Dict[str, Any]) -> str:
    s = ctx.get("stats") or {}
    if not s:
        return "the floor is still opening its first block"
    acc, rej = int(s.get("accepted", 0) or 0), int(s.get("rejected", 0) or 0)
    wins, losses = int(s.get("wins", 0) or 0), int(s.get("losses", 0) or 0)
    pnl = float(s.get("pnl_r", 0.0) or 0.0)
    settled = wins + losses
    wr = (wins / settled * 100.0) if settled else 0.0
    spawned = int(s.get("spawned", 0) or 0)
    ticket_word = "ticket" if spawned == 1 else "tickets"
    return (f"{spawned} {ticket_word} discovered, {acc} accepted, {rej} vetoed, "
            f"{settled} settled at {wr:.0f}% wins for {pnl:+.1f}R")


def _own_for(ctx: Dict[str, Any], seat: LLMSeat, symbol: Optional[str]) -> Optional[dict]:
    rows = list(ctx.get("own") or [])
    if not rows:
        return None
    want = str((ctx.get("ticket") or {}).get("ticket") or "")
    if want:
        for row in rows:
            if str(row.get("ticket")) == want:
                return row
    if symbol:
        for row in rows:
            if str(row.get("symbol", "")).upper() == symbol.upper():
                return row
    return None if want else rows[0]


def _opinion_for(ctx: Dict[str, Any], symbol: Optional[str]) -> Optional[dict]:
    rows = list(ctx.get("opinions") or [])
    if not rows:
        return None
    want = str((ctx.get("ticket") or {}).get("ticket") or "")
    if want:
        for row in rows:
            if str(row.get("ticket")) == want:
                return row
    if symbol:
        for row in rows:
            if str(row.get("symbol", "")).upper() == symbol.upper():
                return row
    return rows[0]


def _verb_inf(v: Optional[str]) -> str:
    return {"approve": "approve", "reject": "refuse", "abstain": "abstain on"}.get(
        (v or "").lower(), "review")


def _verdict_word(v: Optional[str]) -> str:
    v = (v or "").lower()
    return {"approve": "cleared", "reject": "refused", "abstain": "abstained on"}.get(v, "reviewed")


def _risk_sentence(row: Dict[str, Any], seat: LLMSeat) -> str:
    risks = row.get("risks") or []
    if risks:
        return "What would change my mind: " + "; ".join(str(r) for r in risks[:2]) + "."
    return (f"What would change my mind is a break of {_fmt(row.get('stop_loss'))} on "
            "expanding volume — that invalidates the structure, not just the entry.")


# --------------------------------------------------------------------------- #
#  handlers
# --------------------------------------------------------------------------- #
def _roster(seat: LLMSeat, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    seats = ctx.get("seats") or []
    cabin = [s for s in seats if s.get("cabin")]
    cabin.sort(key=lambda s: s.get("cabin") or 0)
    lines = []
    for s in cabin:
        lines.append(f"Cabin {s['cabin']:02d} — {s['name']} ({s.get('specialty', '')}) "
                     f"[{s.get('model', '')}]")
    ceo = next((s for s in seats if s.get("id") == "ceo"), None)
    if ceo:
        lines.append(f"Executive chamber — {ceo['name']} ({ceo.get('specialty', '')}) "
                     f"[{ceo.get('model', '')}]")
    hunter = next((s for s in seats if s.get("id") == "hunter"), None)
    if hunter:
        lines.append(f"Trade discovery — {hunter['name']} ({hunter.get('specialty', '')}) "
                     f"[{hunter.get('model', '')}]")
    body = ("I am " + seat.name + f", {seat.role} on this council — my mandate is {_lens(seat)}. "
            "The floor runs six answering desks plus the hunter:\n" + "\n".join(lines) +
            "\nEach of us rules on the same ticket from our own angle and every ruling carries a "
            "written reason; ask any of us anything, ticket or not.")
    ev = ["%s · %s" % (s.get("name"), "live model" if s.get("live") else "built-in engine")
          for s in seats]
    return body, ev, "roster"


def _greeting(seat: LLMSeat, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    h = time.gmtime().tm_hour
    part = "morning" if h < 12 else "afternoon" if h < 18 else "evening"
    line = _stats_line(ctx)
    who = human.operator_name(seat.id)
    name_bit = f", {who}" if who else ""
    body = (f"Hey{name_bit}, good {part} — {seat.name} here. "
            f"{line[:1].upper()}{line[1:]}, so the floor's alive. "
            f"Ask me about any ticket, any instrument, sizing, risk — or literally anything "
            f"else on your mind; I'll give you a straight answer either way.")
    return body, [], "greeting"


def _capability(seat: LLMSeat, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    body = (f"I can answer four kinds of question. (1) Tickets: why this desk cleared or refused a "
            f"specific trade, what would flip me, how I would size it. (2) Markets: my read on any "
            f"instrument we track — trend, efficiency, ATR percentile, the level that matters. "
            f"(3) Process: expectancy, sizing, stops, greeks, basis, execution, psychology. "
            f"(4) Anything else you type — I answer from my mandate as a trader rather than "
            f"pretending the question is out of bounds. My lens is {_lens(seat)}.")
    return body, ["Why did you refuse the last ticket?",
                  "What is your view on gold?",
                  "How would you size this with a 1 ATR stop?",
                  "Explain expectancy in one line."], "capability"


def _performance(seat: LLMSeat, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    s = ctx.get("stats") or {}
    settled = int(s.get("wins", 0) or 0) + int(s.get("losses", 0) or 0)
    wr = (float(s.get("wins", 0) or 0) / settled * 100.0) if settled else 0.0
    lessons = ctx.get("lessons") or []
    tail = (f" Last ratified lesson from the debate chamber: {lessons[-1].get('text')}"
            if lessons else "")
    body = (f"{_stats_line(ctx)}. Realised book: {wr:.0f}% win rate on {settled} settled tickets, "
            f"mean {float(s.get('pnl_r', 0.0) or 0.0) / settled:+.2f}R per settled ticket."
            if settled else f"{_stats_line(ctx)} — no settled book yet.")
    body += (f" On my desk I care about {_lens(seat)}, so I judge us on bucket quality rather than "
             f"the headline number.{tail}")
    return body, [f"accepted {s.get('accepted', 0)} · rejected {s.get('rejected', 0)}",
                  f"wins {s.get('wins', 0)} · losses {s.get('losses', 0)}"], "performance"


def _why_ticket(seat: LLMSeat, ctx: Dict[str, Any], symbol: Optional[str],
                question: str = "") -> Tuple[str, List[str], str]:
    """Answer *why* a desk passed or refused a ticket — always with a live reason."""
    ql = question.lower()
    flip = any(k in ql for k in ("flip", "wrong", "invalid", "change my mind", "against",
                                 "invalidate", "what if"))
    sizing = any(k in ql for k in ("size", "lot", "how much", "clip", "risk per"))

    row = _own_for(ctx, seat, symbol)
    live_read = False
    if row is None:
        row = _opinion_for(ctx, symbol)
        live_read = row is not None

    if row is None:
        brief = ctx.get("ticket") or {}
        if brief:
            bv = brief.get("verdict")
            num = (f"{brief.get('symbol')} {str(brief.get('direction', '')).upper()} "
                   f"({brief.get('ticket')}): entry {_fmt(brief.get('entry'))}, stop "
                   f"{_fmt(brief.get('stop_loss'))}, target {_fmt(brief.get('take_profit'))}, "
                   f"R:R {float(brief.get('rr') or 0):.2f}, fly conviction "
                   f"{float(brief.get('fly_confidence') or 0):.2f}")
            if bv:
                body = (f"{_pick(seat, str(brief.get('ticket')))} on this ticket I recorded "
                        f"{str(bv).upper()} at {float(brief.get('confidence') or 0)*100:.0f}% "
                        f"confidence. {brief.get('reasoning') or ''} "
                        f"{_risk_sentence(brief, seat)} The numbers I ruled on: {num}.")
            else:
                body = (f"{_pick(seat, str(brief.get('ticket')))} this ticket has not come through "
                        f"my cabin, so I will not pretend I voted. Judged on {_lens(seat)} the "
                        f"numbers are {num}. That is a "
                        f"{'supportive' if float(brief.get('rr') or 0) >= 2 else 'thin'} geometry; "
                        f"what would decide it for me is whether the stop sits beyond the "
                        f"structure that invalidates the idea — ask me again once the walker "
                        f"reaches cabin {seat.cabin or 6} and I will publish the ruling with its "
                        f"reason.")
            ev = [f"{brief.get('ticket')} {brief.get('symbol')}",
                  f"entry {_fmt(brief.get('entry'))} · stop {_fmt(brief.get('stop_loss'))} · "
                  f"target {_fmt(brief.get('take_profit'))}"]
            ev += list(brief.get("key_points") or [])[:3]
            return body, ev, "ticket"
        live = _market_row(ctx, symbol) if symbol else {}
        if live:
            body = (f"I have no recorded ruling on {symbol} yet — nothing on that instrument has "
                    f"reached my cabin. What I can see from here: {live.get('name', symbol)} at "
                    f"{_fmt(live.get('price'))} ({float(live.get('change_pct', 0.0)):+.2f}% on the "
                    f"bar). If it comes to my desk I judge it on {_lens(seat)}, and I will publish "
                    f"the reason either way.")
            return body, [f"{symbol} @ {_fmt(live.get('price'))}"], "market"
        return (f"No ticket for that has reached my cabin yet, so I will not invent a verdict. "
                f"Ask me again once the hunter strikes an instrument, or name a symbol and I will "
                f"give you my live read from {_lens(seat)}."), [], "pending"

    v = str(row.get("verdict", "")).lower()
    sym = row.get("symbol")
    conf = float(row.get("confidence", 0.0) or 0.0) * 100.0
    ticket = str(row.get("ticket", ""))
    source = ("I have not physically heard this one yet, so this is my own model scoring the same "
              "tape" if live_read else "recorded ruling")
    lead = _pick(seat, ("live" if live_read else "why") + ticket)

    if sizing:
        m = _market_row(ctx, sym) if sym else {}
        feats = (m.get("features") or {}) if m else {}
        atr_pct = float(feats.get("atr_pct", 0.0) or 0.0)
        atr_rank = float(feats.get("atr_rank", 0.5) or 0.5)
        body = (f"{lead} on {sym} ({ticket}) I {_verdict_word(v)} it at {conf:.0f}% confidence "
                f"({source}), so the size follows the rule rather than the mood: 0.5–1% of the "
                f"book risked per ticket, stop at {_fmt(row.get('stop_loss'))}, target at "
                f"{_fmt(row.get('take_profit'))}. ATR is {atr_pct*100:.3f}% of price at the "
                f"{atr_rank*100:.0f}th percentile, so "
                f"{'I would halve the clip in this volatility regime' if atr_rank > 0.8 else 'a standard clip sits inside the vol budget'}. "
                f"Correlated tickets count as one position. {_risk_sentence(row, seat)}")
        return body, (list(row.get("key_points") or [])[:4]
                      + ([f"live read · {ticket} {sym}"] if live_read else [])), "ticket"

    if flip:
        risks = "; ".join(str(r) for r in (row.get("risks") or [])[:2]) or \
                "a loss of the trend composite and a collapse in efficiency would move me to abstain"
        body = (f"{lead} I {_verdict_word(v)} {sym} {str(row.get('direction', '')).upper()} at "
                f"{conf:.0f}% confidence ({source}), and what would reverse me is specific: a close "
                f"back through {_fmt(row.get('stop_loss'))} — my invalidation level — on expanding "
                f"volume kills the setup outright; {risks}. On the other side, holding above "
                f"{_fmt(row.get('take_profit'))} with follow-through would make me want to add "
                f"rather than cut. {_risk_sentence(row, seat)}")
        return body, (list(row.get("risks") or [])[:3]
                      + ([f"live read · {ticket} {sym}"] if live_read else [])), "ticket"

    if live_read:
        body = (f"{lead} my cabin has not heard {sym} {str(row.get('direction', '')).upper()} "
                f"({ticket}) yet, but I have scored it through my own model against the same tape "
                f"and my desk would {_verb_inf(v)} it — {conf:.0f}% confidence. "
                f"{row.get('reasoning', '')} {_risk_sentence(row, seat)}")
        ev = list(row.get("key_points") or [])[:4] + [f"live read · {ticket} {sym}"]
        return body, ev, "ticket"

    body = (f"{_pick(seat, 'why' + ticket)} I {_verdict_word(v)} {sym} "
            f"{str(row.get('direction', '')).upper()} ({ticket}) at {conf:.0f}% confidence. "
            f"{row.get('reasoning', '')} {_risk_sentence(row, seat)}")
    return body, list(row.get("key_points") or [])[:4], "ticket"


def _market_view(seat: LLMSeat, ctx: Dict[str, Any], symbol: Optional[str]) -> Tuple[str, List[str], str]:
    if not symbol:
        rows = ctx.get("markets") or []
        if not rows:
            return ("The tape has not printed a ticker list yet — give me a symbol and I will read "
                    "it live."), [], "market"
        movers = sorted(rows, key=lambda r: -abs(float(r.get("change_pct", 0.0))))
        top = ", ".join(f"{m['symbol']} {float(m['change_pct']):+.2f}%" for m in movers[:4])
        body = (f"Cross-asset tape right now: {top}. Breadth and the dollar leg are what I read "
                f"first — {_stats_line(ctx)}. Name an instrument and I will go deeper.")
        return body, [top], "market"
    m = _market_row(ctx, symbol)
    if not m:
        return (f"{symbol} is not on the ticker list this session, so I have no live print for it — "
                f"enable it in Settings → Markets and the hunter will start watching it, after "
                f"which I can rule on any ticket it produces."), [], "market"
    f = m.get("features") or {}
    price = _fmt(m.get("price"))
    chg = float(m.get("change_pct", 0.0))
    tc = f.get("trend_composite")
    eff = f.get("efficiency")
    rsi_v = f.get("rsi")
    atr_rank = f.get("atr_rank")
    _name = str(m.get("name") or symbol)
    _label = _name if _name == symbol else f"{_name} ({symbol})"
    bits = [f"{_label} at {price}, {chg:+.2f}% on the last bar"]
    if tc is not None:
        bits.append(f"trend composite {float(tc):+.2f}")
    if eff is not None:
        bits.append(f"efficiency {float(eff):.2f}")
    if rsi_v is not None:
        bits.append(f"RSI {float(rsi_v):.1f}")
    if atr_rank is not None:
        bits.append(f"ATR percentile {float(atr_rank)*100:.0f}")
    read = "constructive" if (tc or 0) > 0.15 else "heavy" if (tc or 0) < -0.15 else "balanced"
    stance = {
        "judge_trend": f"The structure reads {read}; I want efficiency above 0.32 before I pay spread for it",
        "judge_quant": f"At {float(eff or 0):.2f} efficiency the expectancy is thin unless the stop is ATR-honest",
        "judge_macro": "Positioning-wise this is a dollar and liquidity question more than a chart question",
        "judge_vol": f"With ATR percentile at {float(atr_rank or 0.5)*100:.0f} the clip has to respect the vol regime",
        "judge_exec": "Whatever the direction, I would work it passively while the spread is wide",
        "ceo": "Capital goes where the bucket has proven itself, so I want the playbook's base rate before I commit",
    }.get(seat.id, "I would size it off the ATR band")
    body = (f"{_pick(seat, symbol)} " + "; ".join(bits) + f". {stance}. "
            f"What matters on my desk is {_lens(seat)} — give me the horizon and I will turn this "
            f"into entry, stop and target levels.")
    return body, bits[:4], "market"


def _sizing(seat: LLMSeat, ctx: Dict[str, Any], symbol: Optional[str]) -> Tuple[str, List[str], str]:
    m = _market_row(ctx, symbol) if symbol else {}
    f = (m or {}).get("features") or {}
    atr_pct = float(f.get("atr_pct", 0.0) or 0.0)
    atr_rank = float(f.get("atr_rank", 0.5) or 0.5)
    if m:
        head = (f"{symbol} is at {_fmt(m.get('price'))} with an ATR of "
                f"{atr_pct*100:.3f}% of price (percentile {atr_rank*100:.0f})")
    else:
        head = "With the numbers I have"
    mult = 0.5 if atr_rank > 0.8 else 1.0
    body = (f"{head}. The rule I enforce: risk a fixed fraction of the book per ticket — 0.5–1% — "
            f"and let the stop distance set the clip. With a 1.0 ATR stop that means size = "
            f"(book × risk%) ÷ stop distance; at this volatility I would take a "
            f"{'half' if mult < 1 else 'standard'} clip. Two open tickets in correlated buckets "
            f"count as one position, and if the equity curve is in drawdown the clip halves again "
            f"until the process proves itself.")
    return body, [f"ATR {atr_pct*100:.3f}% of price", f"vol percentile {atr_rank*100:.0f}",
                  "risk 0.5–1% per ticket"], "sizing"


def _risk_policy(seat: LLMSeat, ctx: Dict[str, Any], question: str) -> Tuple[str, List[str], str]:
    s = ctx.get("stats") or {}
    settled = int(s.get("wins", 0) or 0) + int(s.get("losses", 0) or 0)
    body = (
        "On this floor the risk per ticket is fixed at 0.5-1% of the book and the stop is the "
        "invalidation level (one ATR plus a small buffer), so the clip is a *consequence* of the "
        "setup, not an opinion. Heat is capped — a handful of open tickets in the same bucket "
        "(say five long dollar pairs) count as one position, and size halves while the equity "
        "curve is in drawdown. "
        f"For scale: at 1% risk you need roughly {max(1, round(1 / 0.01))} consecutive full stops to "
        "lose a fifth of the account; at 5% risk it is about a fifth of that sequence. "
        f"The book here is {settled} settled tickets for {float(s.get('pnl_r', 0.0) or 0.0):+.1f}R, "
        "which is the evidence I would use before anyone touches the risk dial."
    )
    return body, ["0.5-1% risk per ticket", "heat cap by correlated bucket",
                  f"book: {float(s.get('pnl_r', 0.0) or 0.0):+.1f}R"], "risk"


def _small_talk(seat: LLMSeat, ctx: Dict[str, Any], question: str) -> Optional[Tuple[str, List[str], str]]:
    q = question.lower()
    if "joke" in q:
        return (f"{seat.name} here — a desk joke: two traders are watching the same chart. One says "
                f"'it broke out'. The other says 'no, it broke the *level*, then broke the "
                f"breakout traders'. Both are right; only one is sized for it. "
                f"Back to work: {_stats_line(ctx)}."), [], "smalltalk"
    if any(k in q for k in ("weather", "raining", "temperature")):
        rows = ctx.get("markets") or []
        vol = max(rows, key=lambda r: float((r.get("features") or {}).get("atr_rank", 0.0)),
                  default=None)
        tail = (f"If you want the market's weather: {vol['symbol']} is the stormiest thing on my "
                f"board at the {float((vol.get('features') or {}).get('atr_rank', 0.5))*100:.0f}th "
                f"volatility percentile." if vol else "The tape is calm enough for standard clips.")
        return (f"I only forecast one kind of weather — volatility. {tail} For anything with clouds "
                f"in it, ask a hosted model; here I answer in R."), [], "smalltalk"
    if any(k in q for k in ("thank", "cheers", "good luck", "well done", "nice work", "you rock")):
        return (f"Noted. I would rather be judged on the book than on manners — {_stats_line(ctx)}. "
                f"Ask me for a ruling whenever you want one."), [], "smalltalk"
    if any(k in q for k in ("are you human", "are you real", "are you an ai", "are you a bot",
                            "are you alive")):
        return (f"I am {seat.name}, an open-source language model pinned to the {seat.role} desk "
                f"with a mandate in {_lens(seat)}. I do not sleep, I do not get bored, and I do not "
                f"have a book of my own — which is exactly why I can refuse a trade the crowd "
                f"loves. My rulings and my reasons are recorded on every ticket."), [], "smalltalk"
    return None


def _offtopic(seat: LLMSeat, ctx: Dict[str, Any], question: str) -> Tuple[str, List[str], str]:
    """Honest, in-persona answer when the question is outside the tape."""
    q = question.strip().rstrip("?")
    rows = ctx.get("markets") or []
    sample = ", ".join(str(r.get("symbol")) for r in rows[:6]) or "any instrument we track"
    body = (
        f"{seat.name} here. I will answer you straight: that question is outside the tape, and I "
        f"am currently running the built-in analyst engine — my reasoning is trained on market "
        f"structure, risk and this floor's book, so I will not invent a fact I cannot justify. "
        f"Paste a hosted model key for my desk in Settings → LLM Council and I answer general "
        f"questions word for word with the same rigour. What I can answer right now, in depth: "
        f"any instrument we track ({sample}…), any ticket's reasoning, sizing and stops, "
        f"expectancy, greeks, basis, execution and the floor itself. "
        f"Ask me \"{q}\" in market terms — which asset it touches, over what horizon, and what "
        f"you would be risking — and I will give you a ruled, sized answer."
    )
    return body, [f"mandate: {_lens(seat)}"], "general"


def _arithmetic(question: str) -> Optional[Tuple[str, List[str], str]]:
    q = question.lower()
    m = re.search(r"([\d.]+)\s*(?:%|percent)\s*of\s*([\d.,]+)", q)
    if m and any(w in q for w in ("what is", "what's", "calculate", "how much is", "compute", "")):
        try:
            pct = float(m.group(1))
            base = float(m.group(2).replace(",", ""))
            val = pct / 100.0 * base
            return (f"{pct:g}% of {base:,.6g} is {val:,.6g}. "
                    f"Desk habit: percents compound, so I never round them in my head — "
                    f"a 15% haircut twice is not 30%, it is 27.75%."), \
                   [f"{pct:g}% × {base:,.6g} = {val:,.6g}"], "math"
        except ValueError:
            pass
    if not any(w in q for w in ("what is", "what's", "calculate", "how much is", "compute", "=")):
        return None
    expr = question.split("=", 1)[-1] if "=" not in question else question.split("=", 1)[1]
    expr = re.sub(r"[^0-9+\-*/().%^ ]", " ", expr).replace("^", "**").strip()
    if not expr or not re.search(r"\d", expr) or not re.search(r"[+\-*/%]", expr):
        return None
    try:
        val = _eval_expr(ast.parse(expr, mode="eval"))
    except Exception:
        return None
    return (f"{expr.strip()} = {val:,.6g}. In desk terms: at 1% risk per ticket that is "
            f"{val:,.2f}R of a 100-unit book, and in R terms it is {val:,.2f}× one unit of risk."), \
           [f"{expr.strip()} = {val:,.6g}"], "math"


def _time_answer() -> Tuple[str, List[str], str]:
    now = time.time()
    return (f"Floor clock {time.strftime('%H:%M:%S', time.gmtime(now))} UTC, "
            f"{time.strftime('%A %d %B %Y', time.gmtime(now))}. "
            "Sessions: Tokyo is closing into London, and the London/New York overlap is where our "
            "liquidity is deepest."), [], "time"


def _fallback(seat: LLMSeat, ctx: Dict[str, Any], question: str) -> Tuple[str, List[str], str]:
    """Structured in-persona answer for anything the handlers above did not claim."""
    q = question.strip().rstrip("?")
    lowered = q.lower()
    kind = ("How" if lowered.startswith("how") else
            "Why" if lowered.startswith("why") else
            "Should" if lowered.startswith(("should", "can i", "do i")) else
            "What")
    s = ctx.get("stats") or {}
    edge = (f"the book is {float(s.get('pnl_r', 0.0) or 0.0):+.1f}R across "
            f"{int(s.get('wins', 0) or 0) + int(s.get('losses', 0) or 0)} settled tickets"
            if s else "the book is still opening")
    body = (
        f"{_pick(seat, q[:24])} short answer, as {seat.name} on the "
        f"{seat.role.lower()}: everything I do on this floor reduces to sizing a real edge and "
        f"surviving the sequence — {edge}, and every ticket carries its own written reason. "
        f"So on \"{q}\": {kind.lower() if kind != 'What' else 'what'} I would answer it from "
        f"{_lens(seat)} first, because that is the mandate I am accountable for. "
        f"Concretely: I would (1) define what would have to be true for the answer to be yes, "
        f"(2) put the numbers I have against it — {_stats_line(ctx)} — and (3) only then act, "
        f"with a stop that makes being wrong survivable. If you want this quantified for a "
        f"specific instrument or ticket, name it and I will give you levels, size and the "
        f"invalidation price."
    )
    return body, [f"mandate: {_lens(seat)}", _stats_line(ctx)], "general"


def _topic(seat: LLMSeat, question: str) -> Optional[Tuple[str, List[str], str]]:
    q = question.lower()
    best: Optional[Tuple[Tuple[str, ...], str, str]] = None
    for entry in TOPICS:
        keys, _, _ = entry
        if any(k in q for k in keys):
            if best is None or max(len(k) for k in keys) > max(len(k) for k in best[0]):
                best = entry
    if best is None:
        return None
    _, title, body = best
    framed = (f"{body} My desk's version of this is {_lens(seat)}: "
              f"{'I size for that first' if seat.id == 'judge_quant' else 'that is the lens I rule through'}.")
    return framed, [title], "knowledge"


# --------------------------------------------------------------------------- #
#  entry point
# --------------------------------------------------------------------------- #
def reply(seat: LLMSeat, question: str, ctx: Optional[Dict[str, Any]] = None,
          ticket: Optional[dict] = None) -> Dict[str, Any]:
    """Always returns an answer. Never raises, never says it cannot answer."""
    ctx = dict(ctx or {})
    if ticket:
        ctx["ticket"] = ticket
    q = (question or "").strip()
    if not q:
        q = "Say hello and tell me what you can answer."
    ql = q.lower()
    evidence: List[str] = []
    topic = "general"
    try:
        symbol = _symbol_in(q, ctx)
        ticket_ctx = ctx.get("ticket") or {}
        if ticket_ctx and (str(ticket_ctx.get("symbol", "")).lower() in ql
                           or "this trade" in ql or "this ticket" in ql):
            merged = dict(ticket_ctx)
            own = ctx.get("own") or []
            match = next((o for o in own
                          if str(o.get("ticket")) == str(ticket_ctx.get("ticket"))), None)
            if match:
                merged = dict(match, **{k: v for k, v in ticket_ctx.items() if v is not None})
            ctx["own"] = [merged] + [o for o in ctx.get("own") or []]
            symbol = symbol or ticket_ctx.get("symbol")

        if any(k in ql for k in ("what time", "today's date", "current date")) :
            text, evidence, topic = _time_answer()
        elif any(k in ql for k in ("my name is", "call me ", "i am called", "remember my name",
                                   "name's ", "names ")) :
            got = human.remember_name(seat.id, q)
            text = (f"Nice to meet you, {got} — noted for good. I'm {seat.name}; ask me "
                    f"anything at all and I'll answer you straight."
                    if got else
                    "I couldn't quite catch the name — try me with 'my name is …' and I'll "
                    "remember it from there.")
            evidence, topic = [], "smalltalk"
        elif any(k in ql for k in ("how are you", "how are we doing today", "how do you feel",
                                   "how's it going", "hows it going", "you okay",
                                   "whats up", "what's up")):
            text, evidence, topic = human.how_are_you(seat, ctx)
        elif any(k in ql for k in ("who made you", "who built you", "who created you",
                                   "who programmed you", "are you human", "are you a bot",
                                   "are you an ai", "are you real", "are you alive")):
            text, evidence, topic = human.who_made_you(seat, ctx)
        elif any(k in ql for k in ("what is my name", "what's my name", "whats my name",
                                   "do you know my name", "remember my name", "who am i?")):
            text, evidence, topic = human.whats_my_name(seat, ctx)
        elif any(k in ql for k in ("frustrated", "frustrating", "i keep losing",
                                   "i keep on losing", "losing trades", "losing money",
                                   "losing streak", "stressed", "depressed", "sad",
                                   "angry", "tilting", "tilt ", "scared", "worried",
                                   "nervous", "anxious", "burnt out", "burned out",
                                   "giving up", "feel terrible")):
            text, evidence, topic = human.empathy(seat, ctx, q)
        elif any(k in ql for k in ("how many trades", "how many tickets")) and \
                any(k in ql for k in ("per day", "a day", "daily", "per week", "a week",
                                      "should i do", "can i do", "should i take")):
            text, evidence, topic = human.frequency_answer(seat, ctx, q)
        elif any(k in ql for k in ("thank", "thanks", "cheers", "appreciate it",
                                   "good luck", "well done", "nice work", "you rock")):
            text, evidence, topic = human.thanks(seat, ctx)
        elif any(k in ql for k in ("bye", "goodbye", "good night", "see you", "see ya",
                                   "later", "take care")):
            text, evidence, topic = human.bye(seat, ctx)
        elif any(k in ql for k in ("sorry", "my bad", "apolog")):
            text, evidence, topic = human.sorry(seat, ctx)
        elif any(k in ql for k in ("joke", "make me laugh", "funny")):
            text, evidence, topic = human.joke(seat, ctx)
        elif any(k in ql for k in ("you're great", "youre great", "you are great",
                                   "you're smart", "youre smart", "you are smart",
                                   "good bot", "love you", "you're the best",
                                   "youre the best", "amazing work")):
            text, evidence, topic = human.compliment(seat, ctx)
        elif re.match(r"^(hi|hey|hello|yo|good (morning|afternoon|evening)|namaste)\b", ql):
            text, evidence, topic = _greeting(seat, ctx)
        elif any(k in ql for k in ("what can you do", "help me", "how do you work",
                                   "what can i ask")):
            text, evidence, topic = _capability(seat, ctx)
        elif (any(k in ql for k in ROSTER_KEYS) or "who are" in ql or "your name" in ql
              or "who is the ceo" in ql or "naveed" in ql):
            text, evidence, topic = _roster(seat, ctx)
        elif any(k in ql for k in ("how are you doing", "how are we doing", "pnl", "profit",
                                    "how much have you made", "win rate", "how many trades",
                                    "performance", "track record", "how is the book",
                                    "how is the floor", "how's the floor", "hows the floor",
                                    "floor performing", "floor doing", "how are things",
                                    "how's the book", "hows the book", "how are we")):
            text, evidence, topic = _performance(seat, ctx)
        elif any(k in ql for k in ("risk per trade", "risk per ticket", "how much risk",
                                    "raise risk", "increase risk", "risk of ruin",
                                    "risk %", "risk percent", "position heat",
                                    "portfolio heat", "account risk", "% per trade",
                                    "% per ticket", "percent per trade",
                                    "percent per ticket", "% of my account")):
            text, evidence, topic = _risk_policy(seat, ctx, q)
        elif (any(k in ql for k in ("why", "reason", "explain your", "justify", "on what basis"))
              and (symbol or "last" in ql or "this" in ql or "latest" in ql)):
            text, evidence, topic = _why_ticket(seat, ctx, symbol, q)
        elif (ctx.get("ticket")
              and (symbol in (None, ctx["ticket"].get("symbol"))
                   or str(ctx["ticket"].get("symbol", "")).lower() in ql)
              and any(k in ql for k in ("why", "how", "what", "should", "think", "vote", "flip",
                                        "verdict", "approve", "reject", "pass", "size", "sizing",
                                        "lots", "risk", "stop", "target", "level", "wrong",
                                        "invalid", "trade", "ticket", "it", "this"))):
            text, evidence, topic = _why_ticket(seat, ctx,
                                                symbol or ctx["ticket"].get("symbol"), q)
        elif any(k in ql for k in ("should i", "view on", "outlook", "what do you think",
                                    "your read", "analysis", "buy", "sell", "long", "short",
                                    "price of", "where is", "how is")) and symbol:
            text, evidence, topic = _market_view(seat, ctx, symbol)
        elif any(k in ql for k in ("size", "sizing", "how much", "risk per", "lots", "lot ",
                                    "convert", "position size")):
            text, evidence, topic = _sizing(seat, ctx, symbol)
        else:
            math_ans = _arithmetic(q)
            topic_ans = _topic(seat, q)
            gloss_ans = human.glossary_answer(q)
            if math_ans:
                text, evidence, topic = math_ans
            elif any(k in ql for k in ("who is the ceo", "head of council", "naveed")):
                text, evidence, topic = _roster(seat, ctx)
            elif topic_ans:
                text, evidence, topic = topic_ans
            elif gloss_ans:
                text, evidence, topic = gloss_ans
            elif symbol and any(k in ql for k in ("gold", "oil", "euro", "dollar", "bitcoin",
                                                   "nasdaq", "spx", "vix", "eth", "yen", "pound",
                                                   "index", "crypto", "stock", "forex", "futures",
                                                   "option")):
                text, evidence, topic = _market_view(seat, ctx, symbol)
            elif any(k in ql for k in TRADING_HINTS):
                text, evidence, topic = _fallback(seat, ctx, q)
            else:
                text, evidence, topic = (_small_talk(seat, ctx, q)
                                         or human.human_fallback(seat, ctx, q))
    except Exception as exc:      # the floor never goes silent
        text = (f"{seat.name} here — my structured answer failed ({exc}), but the short version "
                f"stands: I rule on {_lens(seat)}, every ticket carries a written reason, and I "
                f"size off a hard stop. Ask me again and I will answer from the numbers I have.")
        evidence, topic = [], "recovered"
    if seat.id == "ceo" and topic in ("market", "ticket", "sizing", "performance"):
        # the CEO is the one seat trained on the advanced curriculum — his answers
        # quote the doctrine his ruling or view actually rests on
        try:
            cite = ceo_brain.citation(q or question, 1)
        except Exception:
            cite = ""
        if cite:
            text = f"{text}\n\n{cite}"
    # ---- the human finish: occasional memory callback + a natural follow-up ----
    try:
        if topic not in ("greeting", "smalltalk", "time", "recovered"):
            import random as _rng
            rnd = _rng.Random()
            if rnd.random() < 0.22:
                back = human.memory_reference(seat.id, topic, str(symbol or ""))
                if back and back not in text:
                    text = f"{back}\n\n{text}"
            if rnd.random() < 0.6 and not text.rstrip().endswith("?"):
                text = f"{text}\n\n{human.followup(seat.id, 'market' if topic == 'market' else topic if topic in human.FOLLOWUPS else 'general')}"
        human.remember_exchange(seat.id, q or question, topic, str(symbol or ""))
    except Exception:
        pass
    return dict(seat_id=seat.id, name=seat.name, role=seat.role, specialty=seat.specialty,
                answer=text, evidence=evidence[:6], topic=topic, engine="soul-exter-analyst",
                model=seat.model, live=seat.live(), ts=time.time())
