"""Council engine — cabin hearings, the executive review, chat and the debate chamber."""
from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from ..agents.schemas import Signal, Trade, Verdict_
from . import qa as desk_qa
from .analyst import StageContext, evaluate as builtin_evaluate
from .client import CLIENT
from .playbook import Playbook, session_bucket
from .registry import LLMSeat

JUDGE_SYSTEM = (
    "You are {name}, {role} of an autonomous trading council inside the SOUL EXTER floor. "
    "Your desk specialises in: {specialty}. You are a professional institutional trader: "
    "you are rigorous, sceptical, concise and you never approve a trade you would not put "
    "your own book behind. You must answer with STRICT JSON only, no prose outside the JSON:\n"
    '{{"verdict":"approve|reject|abstain","confidence":0.0-1.0,'
    '"key_points":["..."],"risks":["..."],'
    '"reasoning":"2-4 sentences, first person, referencing the numbers you were given",'
    '"suggested_adjustment":{{"stop_loss":number|null,"take_profit":number|null,'
    '"size_multiplier":number}}|null}}'
)

CEO_SYSTEM = (
    "You are {name}, Head of Council and CEO of the SOUL EXTER autonomous trading desk. "
    "Your desk owns capital allocation: {specialty}. Five specialist judges have already "
    "voted. You make the final, binding decision. Answer with STRICT JSON only:\n"
    '{{"verdict":"approve|reject","confidence":0.0-1.0,"key_points":["..."],"risks":["..."],'
    '"reasoning":"3-5 sentences referencing the votes, dissent and the playbook",'
    '"mandate":"one-line order for the execution desk",'
    '"size_multiplier":0.2-1.5}}'
)


DESK_CHAT_SYSTEM = (
    "You are {name}, {role} of the SOUL EXTER autonomous trading floor. Your mandate is: "
    "{specialty}. You are a professional institutional trader — rigorous, direct, numerate and "
    "never vague. The operator can ask you ANYTHING: a specific ticket, a market, risk and "
    "sizing, how the floor is performing, trading theory, or a general question. Always answer "
    "helpfully and in character; if the question is outside trading, still answer it as the "
    "professional you are, using the live context you are given and refusing to invent numbers "
    "you were not given. You may disagree with your colleagues, but you must be able to justify "
    "every position with the evidence supplied. Answer with STRICT JSON only:\n"
    '{{"answer":"4-8 sentences, first person, concrete and specific",'
    '"evidence":["the numbers or facts you relied on, max 6 short strings"],'
    '"topic":"one word"}}'
)


def _trade_brief(trade: Trade, prior: Sequence[Verdict_], playbook_info: dict,
                 market: Optional[dict] = None) -> str:
    s = trade.signal
    f = s.get("features", {})
    lines = [
        f"TICKET {trade.id} — {trade.symbol} ({trade.asset_class}) {trade.direction.upper()}",
        f"horizon={s.get('horizon')} fly_confidence={s.get('score')} rr={s.get('rr')}",
        f"entry={s.get('entry')} stop={s.get('stop_loss')} target={s.get('take_profit')} atr={s.get('atr')}",
        "features: " + json.dumps({k: round(float(v), 5) for k, v in list(f.items())[:18]}),
        f"fly_brain: " + json.dumps(s.get("neural", {}).get("brain", {}))[:600],
    ]
    if market:
        lines.append("market: " + json.dumps(market)[:400])
    if prior:
        lines.append("previous cabins: " + json.dumps(
            [dict(cabin=v.judge_name, verdict=v.verdict, conf=v.confidence,
                  reasoning=v.reasoning[:220]) for v in prior])[:1400])
    lines.append("playbook: " + json.dumps(playbook_info)[:600])
    return "\n".join(lines)


class CouncilEngine:
    def __init__(self, seats: List[LLMSeat], playbook: Playbook, rng: Optional[random.Random] = None) -> None:
        self.seats = seats
        self.by_id = {s.id: s for s in seats}
        self.playbook = playbook
        self.rng = rng or random.Random(4242)
        self.llm_calls = 0
        self.llm_failures = 0
        self.debate_log: List[dict] = []
        self.chat_log: Dict[str, List[dict]] = {}
        self._debate_turn = 0

    # ------------------------------------------------------------- hearings
    def judges(self) -> List[LLMSeat]:
        return [s for s in self.seats if s.cabin is not None and s.enabled]

    def judge_for_cabin(self, index: int) -> Optional[LLMSeat]:
        for s in self.judges():
            if s.cabin == index:
                return s
        return None

    async def adjudicate(self, seat: LLMSeat, trade: Trade, prior: Sequence[Verdict_],
                         pace_s: float = 0.0, market: Optional[dict] = None) -> Verdict_:
        t0 = time.time()
        signal = Signal(**{k: v for k, v in trade.signal.items()
                           if k in Signal.__dataclass_fields__})  # type: ignore[arg-type]
        book = self.playbook.lookup(signal)
        ctx = StageContext(signal, history=[v.dict() for v in prior], playbook=book,
                           prior_context="", desk_name=seat.name)
        verdict: Optional[dict] = None
        engine = "builtin"
        model = seat.model
        if seat.live():
            brief = _trade_brief(trade, prior, book, market)
            sys = JUDGE_SYSTEM.format(name=seat.name, role=seat.role, specialty=seat.specialty)
            msgs = [dict(role="system", content=sys),
                    dict(role="user", content="Review this ticket for your desk.\n" + brief)]
            if pace_s > 0.4:
                await asyncio.sleep(min(pace_s, 6.0))
            verdict = await CLIENT.chat_json(seat, msgs)
            self.llm_calls += 1
            if verdict is None:
                self.llm_failures += 1
            else:
                engine = f"{seat.provider}:{seat.model}"
        if verdict is None:
            verdict = builtin_evaluate(seat, ctx)
            model = "soul-exter-analyst"
        key_points = [str(x)[:220] for x in (verdict.get("key_points") or [])][:6]
        risks = [str(x)[:220] for x in (verdict.get("risks") or [])][:6]
        reasoning = str(verdict.get("reasoning") or "").strip() or \
            f"{seat.name} reviewed {trade.symbol} and reached a {verdict.get('verdict')} verdict."
        v = Verdict_(
            judge_id=seat.id, judge_name=seat.name,
            verdict=str(verdict.get("verdict", "abstain")).lower(),
            confidence=float(max(0.0, min(1.0, float(verdict.get("confidence", 0.5))))),
            score=float(max(-1.0, min(1.0, float(verdict.get("score", 0.0))))),
            reasoning=reasoning, key_points=key_points, risks=risks,
            engine=engine, model=model, latency_ms=int((time.time() - t0) * 1000),
        )
        if v.verdict not in ("approve", "reject", "abstain"):
            v.verdict = "abstain"
        return v

    async def executive(self, trade: Trade, prior: Sequence[Verdict_], pace_s: float = 0.0,
                        market: Optional[dict] = None) -> Verdict_:
        seat = self.by_id.get("ceo")
        if seat is None:
            raise RuntimeError("no CEO seat configured")
        t0 = time.time()
        signal = Signal(**{k: v for k, v in trade.signal.items()
                           if k in Signal.__dataclass_fields__})
        book = self.playbook.lookup(signal)
        ctx = StageContext(signal, history=[v.dict() for v in prior], playbook=book,
                           desk_name=seat.name)
        verdict: Optional[dict] = None
        engine, model = "builtin", "soul-exter-analyst"
        if seat.live():
            sys = CEO_SYSTEM.format(name=seat.name, specialty=seat.specialty)
            msgs = [dict(role="system", content=sys),
                    dict(role="user", content="Five cabin verdicts are in. Rule on the ticket.\n"
                             + _trade_brief(trade, prior, book, market))]
            if pace_s > 0.4:
                await asyncio.sleep(min(pace_s, 7.0))
            verdict = await CLIENT.chat_json(seat, msgs)
            self.llm_calls += 1
            if verdict is None:
                self.llm_failures += 1
            else:
                engine, model = f"{seat.provider}:{seat.model}", seat.model
        if verdict is None:
            verdict = self._builtin_exec(seat, ctx, trade, prior)
        v = Verdict_(
            judge_id=seat.id, judge_name=seat.name,
            verdict=str(verdict.get("verdict", "reject")).lower(),
            confidence=float(max(0.0, min(1.0, float(verdict.get("confidence", 0.5))))),
            score=float(np_clip(float(verdict.get("score", 0.0)))),
            reasoning=str(verdict.get("reasoning", "")).strip() or
                      f"{seat.name} issues the final ruling on {trade.symbol}.",
            key_points=[str(x)[:240] for x in (verdict.get("key_points") or [])][:5],
            risks=[str(x)[:240] for x in (verdict.get("risks") or [])][:4],
            engine=engine, model=model, latency_ms=int((time.time() - t0) * 1000),
        )
        if v.verdict not in ("approve", "reject"):
            v.verdict = "reject" if trade.votes_against >= trade.votes_for else "approve"
        extra = verdict.get("mandate") or ""
        if extra:
            v.key_points.append(f"Mandate: {extra}")
        return v

    def _builtin_exec(self, seat: LLMSeat, ctx: StageContext, trade: Trade,
                      prior: Sequence[Verdict_]) -> dict:
        votes_for = sum(1 for v in prior if v.verdict == "approve")
        against = sum(1 for v in prior if v.verdict == "reject")
        abstain = len(prior) - votes_for - against
        confs = [v.confidence for v in prior if v.verdict == "approve"]
        base = builtin_evaluate(seat, ctx)
        score = base["score"] if isinstance(base["score"], float) else 0.0
        pts = [f"Cabin tally: {votes_for} approve · {against} reject · {abstain} abstain "
               f"(mean confidence {sum(confs)/len(confs) if confs else 0:.2f})"]
        risks: List[str] = []
        # consensus maths: 5/0 or 4/1 approves need a strong prior, splits need the CEO's own read
        if votes_for == 5:
            score += 0.30
        elif votes_for == 4:
            score += 0.16
        elif votes_for == 3:
            score += 0.02
            risks.append("Split council — the dissenting desk may be seeing a regime I am not")
        elif votes_for == 2:
            score -= 0.16
            risks.append("Only two cabins supported the ticket")
        else:
            score -= 0.34
            risks.append("The council has effectively vetoed this ticket")
        if against and confs and max(v.confidence for v in prior if v.verdict == "reject") > 0.7:
            score -= 0.14
            risks.append("A high-conviction dissent is on the record")
        book = ctx.playbook
        if book.get("hit_rate") is not None:
            pts.append(f"Playbook: {book['hit_rate']*100:.0f}% hit rate on {book.get('sample',0)} "
                       f"comparable trades ({book.get('key','')})")
            score += (book["hit_rate"] - 0.5) * 0.5
        if book.get("sample", 0) < 4:
            pts.append("Sample size is thin — sizing stays conservative")
        score = np_clip(score)
        # calibrated on the tape: the consensus tally plus the composite read is
        # what separates the profitable cohort from the rest (see council_study).
        verdict = "approve" if score >= -0.22 else "reject"
        size = round(max(0.2, min(1.5, 0.55 + score * 0.9 + (votes_for - 2) * 0.12)), 2)
        reason = (f"{seat.name}: the ticket reaches me with {votes_for} of 5 cabins in favour. "
                  f"{'Consensus is strong enough to deploy capital' if verdict=='approve' else 'The council has not earned a position'}"
                  f" — {'but I am sizing at ' + str(size) + 'x because the dissent is real' if verdict=='approve' and against else ''}"
                  + ("." if verdict == "approve" else ", so the ticket exits without a fill."))
        return dict(verdict=verdict, confidence=round(min(0.97, 0.45 + abs(score)), 3),
                    score=score, key_points=pts, risks=risks, reasoning=reason.strip(),
                    mandate=(f"Deploy {size}x clip, trail at 1.1×ATR" if verdict == "approve"
                             else "Stand down — do not fill"))

    # ------------------------------------------------------------------ chat
    async def ask(self, seat_id: str, trade: Trade, question: str) -> dict:
        seat = self.by_id.get(seat_id)
        if seat is None:
            return dict(error="unknown seat")
        verdicts = [s.verdict for s in trade.stages if s.verdict]
        mine = next((v for v in verdicts if v.judge_id == seat_id), None)
        signal = Signal(**{k: v for k, v in trade.signal.items()
                           if k in Signal.__dataclass_fields__})
        ctx = StageContext(signal, history=[v.dict() for v in verdicts],
                           playbook=self.playbook.lookup(signal), desk_name=seat.name)
        answer = None
        engine = "builtin"
        if seat.live():
            msgs = [
                dict(role="system", content=JUDGE_SYSTEM.format(name=seat.name, role=seat.role,
                                                                specialty=seat.specialty)),
                dict(role="user", content=(
                    f"A floor operator asks you: {question}\n"
                    f"Your recorded verdict: {mine.dict() if mine else 'none yet'}\n"
                    "Ticket:\n" + _trade_brief(trade, verdicts, self.playbook.lookup(signal)) +
                    '\nAnswer in JSON with keys answer (2-4 sentences), evidence (list of '
                    'strings with the numbers you rely on).')),
            ]
            data = await CLIENT.chat_json(seat, msgs)
            if data and data.get("answer"):
                answer = str(data["answer"])
                engine = f"{seat.provider}:{seat.model}"
        if answer is None:
            built = desk_qa.reply(seat, question, {}, ticket=self._ticket_context(seat, trade,
                                                                                 verdicts, signal))
            answer = built["answer"]
            engine = built.get("engine", "soul-exter-analyst")
        entry = dict(ts=time.time(), seat_id=seat.id, name=seat.name, role=seat.role,
                     specialty=seat.specialty, question=question,
                     answer=answer, engine=engine, verdict=(mine.verdict if mine else None))
        self.chat_log.setdefault(trade.id, []).append(entry)
        return entry

    def _builtin_answer(self, seat: LLMSeat, ctx: StageContext, mine: Optional[Verdict_],
                        question: str) -> str:
        s = ctx.signal
        f = ctx.f
        facts = [
            f"ticket {s.symbol} {s.direction} at {s.entry:.4g} (stop {s.stop_loss:.4g}, "
            f"target {s.take_profit:.4g}, R:R {ctx.rr:.2f})",
            f"fly-brain conviction {s.score:.2f} and my read was {mine.verdict if mine else 'pending'}"
            f" at {mine.confidence:.2f} confidence" if mine else "no verdict recorded yet",
            f"ATR {s.atr:.4g} ({ctx.atr_pct*100:.3f}% of price), vol percentile "
            f"{f.get('atr_rank',0.5)*100:.0f}",
        ]
        if mine:
            facts += mine.key_points[:2]
        q = question.lower()
        if any(k in q for k in ("why", "reason", "explain", "based")):
            lead = f"My verdict was {mine.verdict if mine else 'pending'} because "
            body = (mine.reasoning if mine else
                    "the desk review is still running; I will not pre-judge a ticket")
        elif any(k in q for k in ("risk", "wrong", "stop", "invalidate")):
            lead = "What would prove me wrong: "
            body = ("; ".join((mine.risks if mine else [])[:3]) or
                    f"a close back through {s.stop_loss:.4g} on expanding volume")
        elif any(k in q for k in ("size", "lot", "how much", "capital")):
            lead = "Sizing view: "
            body = (f"at {ctx.rr:.2f}R and {ctx.atr_pct*100:.2f}% ATR I would deploy a "
                    f"{'reduced' if f.get('atr_rank',0.5)>0.8 else 'standard'} clip "
                    f"({0.4 if f.get('atr_rank',0.5)>0.8 else 0.8:.1f}× base)")
        elif any(k in q for k in ("improve", "adjust", "better", "level")):
            lead = "Adjustments I would insist on: "
            body = (f"push the stop to {s.stop_loss - s.atr*0.15:.4g} beyond the ATR band or "
                    f"take partials at {s.entry + (s.take_profit - s.entry)*0.55:.4g}; "
                    f"the current geometry is {'acceptable' if ctx.rr > 2 else 'tight'}")
        else:
            lead = f"{seat.name}, {seat.specialty}: "
            body = (f"{mine.reasoning if mine else 'The ticket is still in my queue.'} "
                    f"Key numbers: {', '.join(facts[:3])}.")
        return f"{lead}{body}"

    async def ask_any(self, seat_id: str, question: str, context: Optional[dict] = None,
                      trade: Optional[Trade] = None) -> dict:
        """Answer *anything*, for any seat, with or without a provider key.

        A hosted desk gets the live context (book, tape, its own rulings, the ticket)
        and answers in its own voice; the built-in engine answers through
        `llm.qa.reply`, which covers tickets, markets, process questions and general
        knowledge. Both paths always return text.
        """
        seat = self.by_id.get(seat_id) or self.by_id.get("ceo")
        if seat is None:
            ids = [s.id for s in self.seats]
            seat = self.seats[0]
            question = f"{question} (asked for {seat_id}; desks available: {', '.join(ids)})"
        ctx = dict(context or {})
        ticket_brief = None
        if trade is not None:
            verdicts = [st.verdict for st in trade.stages if st.verdict]
            sig = Signal(**{k: v for k, v in trade.signal.items()
                            if k in Signal.__dataclass_fields__})
            ticket_brief = self._ticket_context(seat, trade, verdicts, sig)
            ctx["ticket"] = ticket_brief
        answer, engine_name, model = None, "soul-exter-analyst", seat.model
        built: Optional[dict] = None
        if seat.live():
            prior = [st.verdict.dict() for st in trade.stages if st.verdict] if trade else []
            sys = DESK_CHAT_SYSTEM.format(name=seat.name, role=seat.role,
                                          specialty=seat.specialty)
            payload = dict(question=question,
                           floor=dict(stats=ctx.get("stats"), roster=ctx.get("seats"),
                                      lessons=(ctx.get("lessons") or [])[-3:]),
                           tape=(ctx.get("markets") or [])[:24],
                           my_recent_rulings=(ctx.get("own") or [])[:6],
                           ticket=ticket_brief,
                           prior_cabins=[dict(judge=v.get("judge_name"), verdict=v.get("verdict"),
                                              confidence=v.get("confidence"),
                                              reasoning=str(v.get("reasoning"))[:220])
                                         for v in prior])
            msgs = [dict(role="system", content=sys),
                    dict(role="user", content=("Live context (JSON):\n"
                                               + json.dumps(payload, default=str)[:6000]
                                               + f"\n\nOperator question: {question}"))]
            data = await CLIENT.chat_json(seat, msgs)
            if data and data.get("answer"):
                answer = str(data["answer"])
                engine_name, model = f"{seat.provider}:{seat.model}", seat.model
        if answer is None:
            built = desk_qa.reply(seat, question, ctx, ticket=ticket_brief)
            answer = built["answer"]
            engine_name = built.get("engine", "soul-exter-analyst")
        entry = dict(ts=time.time(), seat_id=seat.id, name=seat.name, role=seat.role,
                     specialty=seat.specialty, question=question, answer=answer,
                     engine=engine_name, model=model, live=seat.live(),
                     topic=(built or {}).get("topic"),
                     evidence=(built or {}).get("evidence"))
        self.chat_log.setdefault(trade.id if trade else "floor", []).append(entry)
        return entry

    def _ticket_context(self, seat: LLMSeat, trade: Trade, verdicts: Sequence[Verdict_],
                        sig: Signal) -> dict:
        mine = next((v for v in verdicts if v.judge_id == seat.id), None)
        return dict(ticket=trade.id, symbol=trade.symbol, direction=trade.direction,
                    asset_class=trade.asset_class, state=trade.state, outcome=trade.outcome,
                    entry=sig.entry, stop_loss=sig.stop_loss, take_profit=sig.take_profit,
                    rr=sig.rr, atr=sig.atr, fly_confidence=sig.score,
                    votes_for=trade.votes_for, votes_against=trade.votes_against,
                    verdict=(mine.verdict if mine else None),
                    confidence=(mine.confidence if mine else None),
                    reasoning=(mine.reasoning if mine else ""),
                    key_points=(mine.key_points if mine else []),
                    risks=(mine.risks if mine else []),
                    cabin_verdicts=[dict(judge=v.judge_name, verdict=v.verdict,
                                         confidence=round(v.confidence, 2),
                                         reasoning=v.reasoning[:220]) for v in verdicts],
                    thesis=trade.thesis, exec_note=trade.exec_note)

    # --------------------------------------------------------------- debate
    DEBATE_KINDS = ["claim", "evidence", "challenge", "concession", "agreement", "training_note"]

    def debate_turn(self, context: dict) -> dict:
        """One grounded turn in the council's self-training debate chamber."""
        seats = [s for s in self.seats if s.enabled]
        self._debate_turn += 1
        speaker = seats[self._debate_turn % len(seats)]
        _t = self._debate_turn
        kind = self.DEBATE_KINDS[(_t // 2) % len(self.DEBATE_KINDS)]
        lessons = context.get("lessons", [])
        buckets = context.get("buckets", [])
        recent = context.get("recent_trades", [])
        feed = context.get("markets", [])
        topic = context.get("topic") or "the last decision block"

        def num_row() -> str:
            if recent:
                t = recent[_t % len(recent)]
                return (f"{t.get('label','ticket')} closed {t.get('outcome','-')} at "
                        f"{t.get('pnl_r', 0):+.2f}R with {t.get('votes_for',0)}/5 votes")
            return "the session is still opening its first block of tickets"

        def bucket_row() -> str:
            if buckets:
                b = buckets[_t % len(buckets)]
                hr = b.get("hit_rate")
                return (f"{b['key']} runs {('%.0f%%' % (hr * 100)) if hr is not None else 'n/a'}"
                        f" over {b.get('sample',0)} closed trades ({b.get('pnl_r',0):+.2f}R)")
            return "no bucket has reached statistical significance yet"

        def market_row() -> str:
            if feed:
                m = feed[_t % len(feed)]
                return (f"{m['symbol']} is {m['change_pct']:+.2f}% on the bar with "
                        f"{m.get('tick_rate',0):.1f} ticks/s of flow")
            return "the tape is quiet on this block"

        def lesson_row() -> str:
            return lessons[-1]["text"] if lessons else "no lesson has been ratified yet"

        templates = {
            "judge_trend": {
                "claim": [f"My read on {topic}: structure still dominates noise. "
                          f"{num_row()} — and that is exactly the pattern I keep flagging.",
                          f"Trend desks should not fight this tape. {market_row()}, and the "
                          f"efficiency profile we saw on the last block supports continuation."],
                "evidence": [f"I re-ran the structure screen over the last block: {bucket_row()}"],
                "challenge": [f"ATLAS challenges the volatility desk — {market_row()}; a "
                              f"compression break needs a trigger, not hope."],
                "concession": [f"I accept the execution desk's point that slippage changes the "
                               f"geometry: {lesson_row()}"],
                "agreement": [f"Agreed with QUANTA on sizing discipline. {bucket_row()}"],
                "training_note": [f"Training note for the council: when efficiency < 0.35 treat "
                                  f"a breakout as a fade, not a continuation."],
            },
            "judge_quant": {
                "claim": [f"Expectancy first. {bucket_row()} — that is the only number that "
                          f"compounds."],
                "evidence": [f"Cost model check: round-trip drag stays under 12% of ATR on this "
                             f"block, so the edge survives frictions. {num_row()}"],
                "challenge": [f"QUANTA challenges the trend desk: your continuation signals still "
                              f"show a 1.6R average payoff — that is a coin flip after costs."],
                "concession": [f"Fair. I will raise the R:R floor to 1.9 for cabin 01's tickets."],
                "agreement": [f"Aligned with VECTOR: if the fill degrades the stop, the trade is "
                              f"not the same trade."],
                "training_note": [f"Training note: cap clip size at 0.8× when the sample for the "
                                  f"bucket is under 10 trades."],
            },
            "judge_macro": {
                "claim": [f"Liquidity regime matters more than the pattern. {market_row()}"],
                "evidence": [f"Session overlay: prime overlap windows are carrying the hit rate. "
                             f"{bucket_row()}"],
                "challenge": [f"MERIDIAN challenges the options desk — theta into a thin Asian "
                              f"tape is a donation, not a position."],
                "concession": [f"I concede the point on gap risk; the council should treat "
                               f"headline windows as no-trade zones."],
                "agreement": [f"{lesson_row()} — the council's own book agrees."],
                "training_note": [f"Training note: require a session factor above 1.0 for "
                                  f"momentum entries in FX."],
            },
            "judge_vol": {
                "claim": [f"Vol surface first. {bucket_row()} shows our best trades came from "
                          f"compressed regimes expanding, not from chasing extremes."],
                "evidence": [f"Tail ledger: {market_row()} and delta-adjusted targets are holding."],
                "challenge": [f"VOLTA challenges the macro desk: you are pricing carry without "
                              f"pricing the vol of carry."],
                "concession": [f"Conceded — I will mark implied-rich chains as reduce-only."],
                "agreement": [f"Agreed with ATLAS on compression breaks; the trigger has to be "
                              f"price, not narrative."],
                "training_note": [f"Training note: size options expressions at half the delta "
                                  f"equivalent when vol rank > 0.85."],
            },
            "judge_exec": {
                "claim": [f"Executable edge only. {num_row()} — I care about the fill, not the "
                          f"story."],
                "evidence": [f"Microstructure log: spread drag is inside tolerance on the majors; "
                             f"{market_row()}"],
                "challenge": [f"VECTOR challenges the quant desk: stop distances must include "
                              f"realistic slippage, not just ATR."],
                "concession": [f"Accepted. I will publish my fill-quality model to the council "
                               f"playbook."],
                "agreement": [f"Agreed — {lesson_row()}"],
                "training_note": [f"Training note: stage exits into volume spikes; do not dump "
                                  f"the whole clip at the target."],
            },
            "ceo": {
                "claim": [f"As Head of Council: {bucket_row()}. Capital follows discipline, and "
                          f"the council's discipline is what we are training here."],
                "evidence": [f"Mandate review: {num_row()} — the override record stands."],
                "challenge": [f"NAVEED challenges every desk: name the condition that "
                              f"invalidates your edge, or the edge is a story."],
                "concession": [f"I accept the dissent recorded in the last block; the council "
                               f"reviews it in the next."],
                "agreement": [f"Ratified: {lesson_row()}"],
                "training_note": [f"Training note for the desk heads: split councils get a "
                                  f"reduced mandate, consensus gets the full clip."],
            },
            "hunter": {
                "claim": [f"From the fly: {market_row()}. The brain struck four times this block "
                          f"and my glomeruli are saturating on {topic}."],
                "evidence": [f"Neural ledger: {num_row()} — MBON attack output leads the price by "
                             f"roughly one bar in this regime."],
                "challenge": [f"DROSOPHILA challenges the judges: you vetoed two tickets the "
                              f"fly had already committed to. Which of us is mis-calibrated?"],
                "concession": [f"I accept dopamine decay is making me hesitant after the last "
                               f"stop-out."],
                "agreement": [f"Agreed — {lesson_row()}"],
                "training_note": [f"Training note from the sensory desk: novelty in the glomeruli "
                                  f"vector is a feature, not noise."],
            },
        }
        seat_key = speaker.id if speaker.id in templates else "ceo"
        bank = templates[seat_key]
        text = self.rng.choice(bank.get(kind, bank["claim"]))
        if kind == "training_note":
            lesson = self.playbook.add_lesson(text, tags=[speaker.specialty.split(",")[0], kind],
                                              source=f"debate:{speaker.id}")
        else:
            lesson = None
        msg = dict(id=f"D{len(self.debate_log)+1:04d}", ts=time.time(), seat_id=speaker.id,
                   name=speaker.name, role=speaker.role, kind=kind, text=text,
                   accent=speaker.accent, lesson=lesson, topic=topic)
        self.debate_log.append(msg)
        self.debate_log = self.debate_log[-400:]
        return msg

    def debate_snapshot(self, limit: int = 60) -> List[dict]:
        return self.debate_log[-limit:]


def np_clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
