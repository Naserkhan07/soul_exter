"""Cabins (personas), prompts and verdict parsing.

A *cabin* is a role on the trading floor (QUANT, RISK, NEWS, MACRO, COMPLIANCE).
Each cabin is staffed by a different open-source LLM. The CEO cabin receives the
full transcript of all five and makes the final call.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..models import TradeCandidate, Verdict, clamp

# --------------------------------------------------------------------------
# cabins
# --------------------------------------------------------------------------
@dataclass
class CabinSpec:
    key: str
    label: str
    role: str
    mandate: str
    model_prefs: List[str]
    temperature: float = 0.25
    max_new_tokens: int = 320
    weight: float = 1.0
    is_ceo: bool = False

    @property
    def system_prompt(self) -> str:
        return (
            f"You are {self.label}, the {self.role} on an autonomous crypto trading floor.\n"
            f"Your mandate: {self.mandate}\n"
            "You are one of five independent risk desks. Be blunt, numerate and skeptical. "
            "You do not have to be polite and you must not rubber-stamp.\n"
            "Reply with ONE JSON object and nothing else."
        )


CABINS: List[CabinSpec] = [
    CabinSpec(
        key="QUANT",
        label="QUANT DESK",
        role="statistical edge analyst",
        mandate=("Judge whether the numbers actually carry an edge: signal strength, sample "
                 "quality, R:R realism, slippage/fees, and whether the pattern is a known trap "
                 "(breakout into exhaustion, RSI divergence, squeeze that never expands)."),
        model_prefs=["Qwen/Qwen2.5-7B-Instruct", "microsoft/Phi-3.5-mini-instruct"],
    ),
    CabinSpec(
        key="RISK",
        label="RISK DESK",
        role="downside and position-sizing officer",
        mandate=("Judge the downside: stop distance vs volatility, tail risk, correlation to what "
                 "we already hold, event risk, and whether the stop would survive normal noise. "
                 "You are the desk that says NO by default."),
        model_prefs=["mistralai/Mistral-7B-Instruct-v0.3", "Qwen/Qwen2.5-7B-Instruct"],
        temperature=0.2,
    ),
    CabinSpec(
        key="NEWS",
        label="NEWS DESK",
        role="narrative and catalyst analyst",
        mandate=("Judge the story: is there a catalyst or a narrative that supports this direction, "
                 "or is price moving against the prevailing narrative? Flag anything that looks "
                 "like a news-driven whipsaw, and treat unexplained moves with suspicion."),
        model_prefs=["meta-llama/Meta-Llama-3.1-8B-Instruct", "Qwen/Qwen2.5-7B-Instruct"],
        temperature=0.35,
    ),
    CabinSpec(
        key="MACRO",
        label="MACRO DESK",
        role="top-down regime and correlation analyst",
        mandate=("Judge the regime: BTC trend, risk-on/risk-off posture, correlation crowding, "
                 "liquidity/spread conditions, and whether this trade is fighting the tape or "
                 "riding it."),
        model_prefs=["Qwen/Qwen2.5-14B-Instruct", "Qwen/Qwen2.5-7B-Instruct"],
        temperature=0.3,
    ),
    CabinSpec(
        key="COMPLIANCE",
        label="COMPLIANCE DESK",
        role="mandate and exposure-control officer",
        mandate=("Judge the book, not the thesis: position limits, total exposure, duplicate or "
                 "correlated positions, cash available, and whether this trade violates the "
                 "desk's own rules. Rules beat opinions."),
        model_prefs=["google/gemma-2-9b-it", "microsoft/Phi-3.5-mini-instruct"],
        temperature=0.15,
        max_new_tokens=280,
    ),
]

CEO_SPEC = CabinSpec(
    key="CEO",
    label="CEO / HEAD OF DESK",
    role="final decision maker",
    mandate=("Weigh the five desk verdicts, resolve the disagreement, and make the final call. "
             "You own the P&L. A split council is not automatically a veto and not automatically "
             "a pass: decide which desks' objections are material for THIS trade."),
    model_prefs=["Qwen/Qwen2.5-14B-Instruct", "Qwen/Qwen2.5-7B-Instruct"],
    temperature=0.2,
    max_new_tokens=420,
    is_ceo=True,
)


def cabin_map() -> Dict[str, CabinSpec]:
    return {c.key: c for c in CABINS}


# --------------------------------------------------------------------------
# prompts
# --------------------------------------------------------------------------
def _money(v: float) -> str:
    return f"{v:,.6f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:,.2f}"


def trade_block(trade: TradeCandidate) -> str:
    f = trade.features
    lines = [
        f"PAIR: {trade.symbol}",
        f"DIRECTION: {trade.side}",
        f"STRATEGY: {trade.strategy} (scanner score {trade.score:.2f}/1.00, timeframe {trade.timeframe})",
        f"ENTRY: {_money(trade.entry)}   STOP: {_money(trade.stop)}   TARGET: {_money(trade.target)}",
        f"RISK: {trade.risk_pct:.2f}% of entry   REWARD: {trade.target_pct:.2f}%   R:R = {trade.rr:.2f}",
        "SIGNAL FEATURES: " + ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in f.items()),
    ]
    if trade.notes:
        lines.append("SCANNER NOTES: " + "; ".join(trade.notes))
    return "\n".join(lines)


def market_block(ctx: Dict[str, Any]) -> str:
    m = ctx.get("market", {})
    lines = [
        f"PRICE NOW: {_money(m.get('price', 0))}   CHANGE: {m.get('change_pct', 0):+.2f}%",
        f"24h HIGH/LOW: {_money(m.get('high', 0))} / {_money(m.get('low', 0))}",
        f"REGIME: {m.get('regime', 'unknown')}   BTC: {m.get('btc_change_pct', 0):+.2f}%",
        f"VOLATILITY RANK (0-100): {m.get('vol_rank', 50):.0f}   SPREAD PROXY: {m.get('spread_bps', 3):.2f} bps",
    ]
    return "\n".join(lines)


def portfolio_block(ctx: Dict[str, Any]) -> str:
    p = ctx.get("portfolio", {})
    pos = p.get("positions", [])
    lines = [
        f"EQUITY: {_money(p.get('equity', 0))}   CASH: {_money(p.get('cash', 0))}   "
        f"OPEN P&L: {p.get('open_pnl', 0):+,.2f}",
        f"OPEN POSITIONS: {len(pos)} / {p.get('max_positions', 8)}   "
        f"GROSS EXPOSURE: {p.get('gross_exposure', 0):,.2f}   "
        f"PLANNED RISK: {p.get('planned_risk_pct', 0):.2f}% of equity",
        f"WIN RATE (session): {p.get('win_rate', 0) * 100:.0f}%   "
        f"TRADES CLOSED: {p.get('closed', 0)}   REALISED P&L: {p.get('realised_pnl', 0):+,.2f}",
    ]
    if pos:
        holdings = ", ".join(f"{x['symbol']} {x['side']} ({x.get('pnl_pct', 0):+.1f}%)" for x in pos[:8])
        lines.append(f"HELD: {holdings}")
    return "\n".join(lines)


def prior_verdicts_block(prior: List[Verdict]) -> str:
    if not prior:
        return "EARLIER DESKS: none yet — you are first to speak."
    out = ["EARLIER DESKS SAID:"]
    for v in prior:
        out.append(f"  - {v.cabin}: {v.verdict} (confidence {v.confidence:.0f}) — {v.reason}")
    return "\n".join(out)


VERDICT_SCHEMA = (
    '{\n'
    '  "verdict": "APPROVE" | "REJECT" | "ABSTAIN",\n'
    '  "confidence": <integer 0-100>,\n'
    '  "reason": "<one or two sentences, concrete, no fluff>",\n'
    '  "risk_flags": ["<short flag>", "..."],\n'
    '  "adjustment": {"size_multiplier": <0.0-1.5>, "stop_pct": <number or null>}\n'
    '}'
)

CEO_SCHEMA = (
    '{\n'
    '  "verdict": "APPROVE" | "REJECT",\n'
    '  "confidence": <integer 0-100>,\n'
    '  "reason": "<2-3 sentences: why this trade goes to the entry door or the exit door>",\n'
    '  "key_dissent": "<the single most important objection from the council and why it does or does not outweigh the rest>",\n'
    '  "risk_flags": ["..."],\n'
    '  "adjustment": {"size_multiplier": <0.0-1.5>, "stop_pct": <number or null>}\n'
    '}'
)


def build_cabin_prompt(spec: CabinSpec, trade: TradeCandidate, ctx: Dict[str, Any],
                       prior: List[Verdict]) -> str:
    return (
        f"A trader on the floor has proposed the trade below. {spec.label}, this is your call.\n\n"
        f"=== TRADE PACKET ===\n{trade_block(trade)}\n\n"
        f"=== LIVE MARKET ===\n{market_block(ctx)}\n\n"
        f"=== DESK BOOK ===\n{portfolio_block(ctx)}\n\n"
        f"=== COUNCIL SO FAR ===\n{prior_verdicts_block(prior)}\n\n"
        f"Rules:\n"
        f"- 'verdict' must be APPROVE, REJECT or ABSTAIN (ABSTAIN only if the packet is too thin to judge).\n"
        f"- 'confidence' is YOUR confidence in YOUR verdict, 0-100. Do not use 100 unless the case is airtight.\n"
        f"- 'reason' must reference the specific numbers above (R:R {trade.rr:.2f}, risk {trade.risk_pct:.2f}%, "
        f"the features). No generic advice.\n"
        f"- Disagree with the desks that came before you whenever the evidence says so.\n"
        f"- You may approve with an adjustment (smaller size or tighter stop) instead of rejecting.\n\n"
        f"Reply with exactly one JSON object:\n{VERDICT_SCHEMA}"
    )


def build_ceo_prompt(spec: CabinSpec, trade: TradeCandidate, verdicts: List[Verdict],
                     ctx: Dict[str, Any]) -> str:
    tally_lines = []
    for v in verdicts:
        adj = v.adjustment or {}
        tally_lines.append(
            f"  {v.cabin}: {v.verdict} (conf {v.confidence:.0f}) | {v.reason} "
            f"| flags: {', '.join(v.risk_flags) or 'none'} "
            f"| sizing x{adj.get('size_multiplier', 1.0)}"
        )
    approves = sum(1 for v in verdicts if v.verdict == "APPROVE")
    rejects = sum(1 for v in verdicts if v.verdict == "REJECT")
    abstains = len(verdicts) - approves - rejects
    return (
        "The council is split and has escalated this trade to you. You are the final word: "
        "APPROVE sends the trader through the ENTRY door, REJECT sends them out the EXIT door.\n\n"
        f"=== TRADE PACKET ===\n{trade_block(trade)}\n\n"
        f"=== LIVE MARKET ===\n{market_block(ctx)}\n\n"
        f"=== DESK BOOK ===\n{portfolio_block(ctx)}\n\n"
        f"=== COUNCIL TRANSCRIPT ({approves} approve / {rejects} reject / {abstains} abstain) ===\n"
        + "\n".join(tally_lines) +
        "\n\nDecide on the merits of THIS trade. Do not split the difference; do not defer to majority "
        "or minority automatically. If the dissent you are overruling is a real risk, cut size or tighten "
        "the stop instead of pretending it is not there.\n\n"
        f"Reply with exactly one JSON object:\n{CEO_SCHEMA}"
    )


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
_JSON_START = re.compile(r"\{")
_VERDICT_WORD = re.compile(r"\b(APPROVE|APPROVED|REJECT|REJECTED|ABSTAIN|HOLD|PASS)\b", re.I)


def _iter_json_objects(text: str):
    """Yield every balanced {...} block, outermost-first."""
    for m in _JSON_START.finditer(text):
        depth, start = 0, m.start()
        in_str, esc = False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:i + 1]
                    break


def _loose_fix(s: str) -> str:
    s = re.sub(r"//[^\n]*", "", s)
    s = re.sub(r",(\s*[}\]])", r"\1", s)          # trailing commas
    return s


def parse_verdict(text: str) -> Dict[str, Any]:
    """Best-effort extraction of a verdict dict from raw LLM text."""
    if not text:
        return {"verdict": "ABSTAIN", "confidence": 40, "reason": "empty response from model",
                "risk_flags": ["no_model_output"], "adjustment": {"size_multiplier": 0.0}}
    candidates = list(_iter_json_objects(text))
    for blob in reversed(candidates):
        for attempt in (blob, _loose_fix(blob)):
            try:
                data = json.loads(attempt)
            except Exception:
                continue
            if isinstance(data, dict) and any(k in data for k in ("verdict", "decision", "action")):
                return _normalize(data)
    # fall back to keyword scraping
    m = _VERDICT_WORD.search(text)
    word = (m.group(1).upper() if m else "ABSTAIN")
    word = {"APPROVED": "APPROVE", "REJECTED": "REJECT", "HOLD": "ABSTAIN", "PASS": "ABSTAIN"}.get(word, word)
    cm = re.search(r"confidence[^0-9]{0,12}(\d{1,3})", text, re.I)
    conf = int(cm.group(1)) if cm else 45
    reason = re.sub(r"\s+", " ", text.strip())[:300] or "unparsed model output"
    return {"verdict": word, "confidence": conf, "reason": reason,
            "risk_flags": ["unstructured_output"], "adjustment": {"size_multiplier": 1.0}}


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    raw_v = str(data.get("verdict") or data.get("decision") or data.get("action") or "ABSTAIN").upper()
    if raw_v.startswith("APPROVE") or raw_v in ("YES", "GO", "ENTER", "BUY"):
        verdict = "APPROVE"
    elif raw_v.startswith("REJECT") or raw_v in ("NO", "SKIP", "VETO", "STOP"):
        verdict = "REJECT"
    else:
        verdict = "ABSTAIN"

    try:
        conf = float(data.get("confidence", 50))
    except (TypeError, ValueError):
        conf = 50.0
    if 0 < conf <= 1.0:                     # models sometimes answer 0..1
        conf *= 100.0
    conf = clamp(conf, 0.0, 100.0)

    reason = data.get("reason") or data.get("rationale") or data.get("explanation") or ""
    if isinstance(reason, (list, tuple)):
        reason = " ".join(str(x) for x in reason)
    reason = re.sub(r"\s+", " ", str(reason)).strip()[:600]

    flags = data.get("risk_flags") or data.get("flags") or []
    if isinstance(flags, str):
        flags = [p.strip() for p in re.split(r"[,;]", flags) if p.strip()]
    flags = [re.sub(r"\s+", " ", str(f)).strip()[:60] for f in flags][:6]

    adj = data.get("adjustment") or data.get("adjustments") or {}
    if not isinstance(adj, dict):
        adj = {}
    try:
        mult = float(adj.get("size_multiplier", adj.get("size", 1.0)))
    except (TypeError, ValueError):
        mult = 1.0
    stop_pct = adj.get("stop_pct", adj.get("stop_distance_pct"))
    try:
        stop_pct = float(stop_pct) if stop_pct is not None else None
    except (TypeError, ValueError):
        stop_pct = None
    if verdict == "REJECT":
        mult = 0.0
    return {
        "verdict": verdict,
        "confidence": round(conf, 1),
        "reason": reason or "no reason given",
        "risk_flags": flags,
        "adjustment": {"size_multiplier": clamp(mult, 0.0, 1.5), "stop_pct": stop_pct},
        "key_dissent": str(data.get("key_dissent", ""))[:300],
    }


def make_verdict(spec: CabinSpec, parsed: Dict[str, Any], model: str,
                 latency_ms: int, stage: int, trade_id: str, raw: str = "") -> Verdict:
    return Verdict(
        cabin=spec.key,
        model=model,
        verdict=parsed["verdict"],
        confidence=parsed["confidence"],
        reason=parsed["reason"],
        risk_flags=parsed.get("risk_flags", []),
        adjustment=parsed.get("adjustment", {}),
        latency_ms=latency_ms,
        raw=raw,
        trade_id=trade_id,
        stage=stage,
    )
