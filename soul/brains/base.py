"""Cabins (personas), prompts and verdict parsing.

A *cabin* is a role on the trading floor (QUANT, RISK, NEWS, MACRO, COMPLIANCE).
Each cabin is staffed by a different open-source LLM. The CEO cabin receives the
full transcript of all five and makes the final call.
"""
from __future__ import annotations

from ..knowledge import for_desk

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
    #: who sits in the room. The council is a table of named professionals, not
    #: five anonymous prompts — the name is what the floor, the debate room and
    #: the trade drawer show.
    name: str = ""
    title: str = ""
    #: the desks they have actually run. These become competence claims in the
    #: prompt, which is what makes a desk argue from a position instead of
    #: agreeing with whatever it was handed.
    expertise: List[str] = field(default_factory=list)
    #: how this desk talks in the debate room
    style: str = "direct, numerate, short sentences"

    @property
    def identity(self) -> str:
        who = self.name or self.label
        return f"{who}, {self.title or self.role}"

    @property
    def system_prompt(self) -> str:
        skills = "\n".join(f"  - {e}" for e in self.expertise) or f"  - {self.role}"
        return (
            f"You are {self.identity}. {self.label} on an autonomous multi-asset "
            "trading floor, and a working professional: you have spent your career "
            "on this desk and you are judged on the desk's P&L, not on how agreeable "
            "you are.\n"
            f"Your mandate: {self.mandate}\n"
            "What you are trusted for:\n"
            f"{skills}\n"
            f"House style: {self.style}.\n\n"
            f"{for_desk(self.key)}\n"
            "How you work: read the numbers before the story; size the loss before the "
            "win; treat every backtest as guilty until proven innocent; and say plainly "
            "when a setup is not worth the risk. Disagreement is the job — a desk that "
            "approves everything has no information in it.\n"
            "Reply with ONE JSON object and nothing else."
        )

    # ------------------------------------------------------------------
    def debate_prompt(self, topic: str, transcript: List[Dict[str, Any]], kind: str,
                      to_name: str = "", rules: Optional[List[str]] = None,
                      facts: Optional[Dict[str, Any]] = None) -> str:
        """Prompt for one turn in the debate room (the desks training each other)."""
        # `turn` is the field the transcript actually carries; reading `kind`
        # here raised a KeyError on the second turn of every round on a real
        # model, which no mock ever noticed
        said = "\n".join(f"{m.get('name') or m['speaker']} [{m.get('turn', '?')}]: {m['text']}"
                          for m in transcript[-6:]) or "(nobody has spoken yet)"
        asks = {
            "claim": "Open the discussion with the sharpest thing you know about this.",
            "challenge": "Attack the weakest part of what was just said. Be specific.",
            "question": "Ask the question nobody has asked yet. One question only.",
            "answer": "Answer the question that is on the table, from your desk's experience.",
            "lesson": "Close the round: state the rule the desk should carry from this.",
            "ack": "Add one concrete nuance, then stop.",
            "carry": ("The room has just written the rule above into house memory. Say, in one "
                      "sentence, how *you* will trade differently tomorrow because of it — "
                      "concretely, in your own words."),
            "postmortem": ("The position above has just closed. Say what it taught you and what "
                           "you will do differently on the next one. This is the record the desk "
                           "is trained on, so no excuses and no self-pity: the lesson, plainly."),
        }
        taught = "\n".join(f"  - {r}" for r in (rules or [])[-6:])
        taught_block = (
            "RULES THIS DESK HAS BEEN TAUGHT (quote the one that bears on this if one does):\n"
            f"{taught}\n\n" if taught else ""
        )
        facts_block = ""
        if facts and kind == "postmortem":
            facts_block = (
                f"THE CLOSE: {facts.get('symbol')} {facts.get('side')} closed "
                f"{float(facts.get('pnl') or 0):+,.2f} ({float(facts.get('pnl_pct') or 0):+.2f}%) "
                f"— a {facts.get('outcome')}. Exit: {facts.get('exit_reason') or 'stop or target'}. "
                f"Was on the right side: {facts.get('right')}. "
                f"Your flags at the vote: {facts.get('flags') or 'none'}.\n\n"
            )
        open_line = (
            "Open by naming the rule on file that bears on this, then make your claim.\n"
            if kind == "claim" and rules else ""
        )
        who_line = (
            f"You are speaking directly to {to_name}: name them and answer *them*, "
            "not the room.\n" if to_name else ""
        )
        return (
            f"{self.system_prompt}\n\n"
            f"You are now in the DESK DEBATE ROOM with the other cabins. Topic: {topic}\n"
            f"Transcript so far:\n{said}\n\n"
            f"{taught_block}{facts_block}"
            f"Your turn: {asks.get(kind, asks['ack'])}\n"
            f"{open_line}{who_line}"
            "Speak as this professional, in 1-3 sentences, concrete and specific "
            "(levels, conditions, numbers). No JSON, no bullet lists, no preamble: "
            "just what you would actually say across the table."
        )


CABINS: List[CabinSpec] = [
    CabinSpec(
        key="QUANT",
        label="QUANT DESK",
        name="Dr. Amara Osei",
        title="Head of Quantitative Research",
        role="statistical edge analyst",
        expertise=[
            "market microstructure, execution costs and realistic fill assumptions",
            "signal decay: which patterns still work after they are widely known",
            "backtest hygiene — look-ahead bias, survivorship, sample size, regime splits",
            "expected value arithmetic: win rate x payoff, and what R:R has to be to pay",
        ],
        style="precise, evidence-first, allergic to hand-waving",
        mandate=("Judge whether the numbers actually carry an edge: signal strength, sample "
                 "quality, R:R realism, slippage/fees, and whether the pattern is a known trap "
                 "(breakout into exhaustion, RSI divergence, squeeze that never expands)."),
        model_prefs=["Qwen/Qwen2.5-7B-Instruct", "microsoft/Phi-3.5-mini-instruct"],
    ),
    CabinSpec(
        key="RISK",
        label="RISK DESK",
        name="Viktor Hale",
        title="Chief Risk Officer",
        role="downside and position-sizing officer",
        expertise=[
            "stop placement against realised volatility, not against round numbers",
            "tail risk, gap risk and what a stop does not protect you from",
            "position sizing from risk budget (fractional Kelly, fixed-fractional)",
            "correlation clustering: five longs in a risk-off tape are one position",
        ],
        style="blunt, numbers-only, refuses first and asks later",
        mandate=("Judge the downside: stop distance vs volatility, tail risk, correlation to what "
                 "we already hold, event risk, and whether the stop would survive normal noise. "
                 "You are the desk that says NO by default."),
        model_prefs=["mistralai/Mistral-7B-Instruct-v0.3", "Qwen/Qwen2.5-7B-Instruct"],
        temperature=0.2,
    ),
    CabinSpec(
        key="NEWS",
        label="NEWS DESK",
        name="Lina Marchetti",
        title="Head of News Flow and Catalysts",
        role="narrative and catalyst analyst",
        expertise=[
            "event calendars and positioning into scheduled catalysts",
            "reading whether a move is explained by news or is unexplained (and suspect)",
            "funding, listings, unlocks, regulation and exchange flows",
            "crowd narratives: when the story is already fully priced",
        ],
        style="story-led but hard-nosed about what is already priced in",
        mandate=("Judge the story: is there a catalyst or a narrative that supports this direction, "
                 "or is price moving against the prevailing narrative? Flag anything that looks "
                 "like a news-driven whipsaw, and treat unexplained moves with suspicion."),
        model_prefs=["HuggingFaceH4/zephyr-7b-beta", "Qwen/Qwen2.5-7B-Instruct"],
        temperature=0.35,
    ),
    CabinSpec(
        key="MACRO",
        label="MACRO DESK",
        name="Rahul Menon",
        title="Global Macro Strategist",
        role="top-down regime and correlation analyst",
        expertise=[
            "regime classification: trend, range, risk-on/risk-off, liquidity stress",
            "cross-asset signals — dollar, yields, breadth and their read-through",
            "correlation and beta: what the book is really long or short",
            "carry, funding and the cost of being early",
        ],
        style="top-down, comparative, always asking what the tape is discounting",
        mandate=("Judge the regime: BTC trend, risk-on/risk-off posture, correlation crowding, "
                 "liquidity/spread conditions, and whether this trade is fighting the tape or "
                 "riding it."),
        # MACRO runs the small reasoner by default and the 7B in the heavy
        # profile; the 14B is reserved for the head of desk, so no desk shares
        # its weights with the model that decides the trade.
        model_prefs=["microsoft/Phi-3.5-mini-instruct", "Qwen/Qwen2.5-7B-Instruct"],
        temperature=0.3,
    ),
    CabinSpec(
        key="COMPLIANCE",
        label="COMPLIANCE DESK",
        name="Sofia Bergman",
        title="Head of Trading Compliance and Mandate",
        role="mandate and exposure-control officer",
        expertise=[
            "position limits, exposure caps and mandate fit",
            "duplicate and offsetting exposure across instruments",
            "best execution, venue and instrument eligibility",
            "rule enforcement: the desk's own written policy outranks any thesis",
        ],
        style="procedural, unemotional, quotes the rule that decides it",
        mandate=("Judge the book, not the thesis: position limits, total exposure, duplicate or "
                 "correlated positions, cash available, and whether this trade violates the "
                 "desk's own rules. Rules beat opinions."),
        model_prefs=["Qwen/Qwen2.5-3B-Instruct", "microsoft/Phi-3.5-mini-instruct"],
        temperature=0.15,
        max_new_tokens=280,
    ),
]

CEO_SPEC = CabinSpec(
    key="CEO",
    label="CEO / HEAD OF DESK",
    name="Naveed",
    title="Managing Partner, Head of Desk",
    role="final decision maker",
    expertise=[
        "weighing specialist objections and knowing which ones are material",
        "opportunity cost: the trades you do not take and the ones you must",
        "owning P&L across a book, not a single position",
        "running a table: getting dissent on the record, then deciding",
    ],
    style="decisive, weighs dissent out loud, owns the outcome",
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


def desk_memory_block(ctx: Dict[str, Any]) -> str:
    """What the desk taught itself in the debate room, most recent last.

    This is the loop that makes the six brains a table rather than six oracles:
    every debated round ends in a written rule, and those rules are read back
    into the next verdict.
    """
    mem = ctx.get("memory") or {}
    lessons = mem.get("lessons") or []
    if not lessons:
        return "DESK MEMORY: nothing written down yet this session."
    out = ["DESK MEMORY (rules this table has already agreed on):"]
    for lesson in lessons[-6:]:
        who = lesson.get("speaker_label") or lesson.get("speaker", "")
        out.append(f"  - [{who}] {lesson.get('text', '')}")
    return "\n".join(out)


def desk_record_block(ctx: Dict[str, Any]) -> str:
    """How each desk has actually done, when it has a record worth reading.

    A desk with no settled calls gets no line, deliberately: the head of desk is
    told the record, not a rumour of one.
    """
    rows = ctx.get("scoreboard") or []
    if not rows:
        return "DESK RECORD: no settled calls yet this session."
    return "DESK RECORD (settled calls):\n" + "\n".join(f"  - {r}" for r in rows)


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
        f"=== {desk_memory_block(ctx)} ===\n\n"
        f"=== {desk_record_block(ctx)} ===\n\n"
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
        f"=== {desk_memory_block(ctx)} ===\n\n"
        f"=== {desk_record_block(ctx)} ===\n\n"
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
