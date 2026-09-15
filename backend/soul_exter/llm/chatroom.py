"""The council chat room — every desk talks trading like a human, and learns.

A continuous group chat runs between all seven seats (five cabin judges, the
CEO and the fly scout). It behaves like a real trading-floor chat room:

* a desk **asks** another desk a question (``@ATLAS ...``), picked so the
  question targets that desk's specialty,
* the addressed desk **answers** from the *live* floor — tape metrics, the
  realised book, playbook buckets and ratified lessons,
* desks drop spontaneous **remarks**, **agree**, **push back** and **react**,
* roughly every tenth exchange the room crystallises what it just discussed
  into a **lesson** that lands in the playbook — the same memory the cabins
  consult during hearings, so the conversation genuinely trains the floor.

Every seat keeps a training record (questions asked / answered, lessons
contributed) and earns XP → levels, rendered as a leaderboard in the UI.

Voices: a seat with a configured API key speaks through its hosted model
(OpenAI-compatible chat completion, transcript + live context attached);
a keyless seat speaks through the built-in persona banks below — always
grounded in the same live numbers, never canned text floating free of the tape.
"""
from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from .client import CLIENT
from . import ceo_brain
from .playbook import Playbook
from .registry import LLMSeat

# --------------------------------------------------------------------------- #
#  training ladder
# --------------------------------------------------------------------------- #
LEVELS: List[Tuple[int, str]] = [
    (0, "Rookie"), (10, "Analyst"), (25, "Strategist"),
    (50, "Senior"), (90, "Mentor"), (150, "Market Sage"),
]
XP = dict(question=2, answer=3, react=1, remark=1, agree=1, pushback=2, lesson=6)

# NAVEED walked in already trained — he holds the advanced trading curriculum the
# cabins do not, so his ladder starts where a career ends: Market Sage.
PRETRAINED_XP: Dict[str, int] = {"ceo": 260}


def level_for(xp: int) -> Tuple[str, int, float]:
    """(level name, index, progress 0..1 to the next level)."""
    idx = 0
    for i, (need, _name) in enumerate(LEVELS):
        if xp >= need:
            idx = i
    name = LEVELS[idx][1]
    lo = LEVELS[idx][0]
    hi = LEVELS[idx + 1][0] if idx + 1 < len(LEVELS) else lo + 60
    return name, idx, min(1.0, (xp - lo) / max(1, hi - lo))


CHAT_SYSTEM = ("""You are {name}, {role} on a trading floor's internal chat room.
Your specialty: {specialty}. You are chatting with your colleague desks like a
human trader in a group chat — short, direct, opinionated, no bullet points,
no markdown, under 55 words. Ground yourself in the live context JSON when it
helps (quote at most one concrete number). {mode_note} Stay in character.""")

MODE_NOTES = {
    "question": "This turn: ask ONE sharp question to a specific colleague. Start the "
                "message with @THEIRNAME (pick from the roster) and end with a question mark.",
    "answer": "This turn: answer your colleague's question directly and concretely, "
              "then give your own read in one line.",
    "remark": "This turn: make a spontaneous observation about the tape, the book "
              "or the last decision — no question.",
}


class ChatRoom:
    """Group chat state machine + training ledger for the whole council."""

    def __init__(self, council, playbook: Playbook, rng: Optional[random.Random] = None) -> None:
        self.council = council
        self.playbook = playbook
        self.rng = rng or random.Random()
        self.messages: List[dict] = []
        self.stats: Dict[str, dict] = {}
        self.pending: Optional[dict] = None       # question awaiting an answer
        self.turn_no = 0
        self._speaker_i = 0

    # ------------------------------------------------------------------ util
    def _seats(self) -> List[LLMSeat]:
        return [s for s in self.council.seats if s.enabled]

    def seat(self, seat_id: str) -> Optional[LLMSeat]:
        for s in self._seats():
            if s.id == seat_id:
                return s
        return None

    def _stat(self, seat_id: str) -> dict:
        if seat_id not in self.stats:
            self.stats[seat_id] = dict(asked=0, answered=0, remarks=0, lessons=0,
                                       xp=PRETRAINED_XP.get(seat_id, 0),
                                       pretrained=seat_id in PRETRAINED_XP)
        return self.stats[seat_id]

    def _credit(self, seat_id: str, kind: str) -> None:
        st = self._stat(seat_id)
        st["xp"] += XP.get(kind, 1)
        if kind == "question":
            st["asked"] += 1
        elif kind == "answer":
            st["answered"] += 1
        elif kind == "lesson":
            st["lessons"] += 1
        else:
            st["remarks"] += 1

    def _post(self, seat: LLMSeat, kind: str, text: str, target: Optional[str] = None,
              reply_to: Optional[str] = None, engine: str = "", lesson: Optional[dict] = None,
              name_override: Optional[str] = None) -> dict:
        msg = dict(id=f"C{len(self.messages) + 1:05d}", ts=time.time(),
                   seat_id=seat.id if seat else "operator",
                   name=name_override or (seat.name if seat else "YOU"),
                   role=(seat.role if seat else "Operator"), kind=kind, text=text,
                   accent=seat.accent if seat else "#e2e8f0",
                   target=target, reply_to=reply_to, engine=engine, lesson=lesson,
                   live=bool(engine and "analyst" not in engine))
        self.messages.append(msg)
        self.messages = self.messages[-400:]
        return msg

    # --------------------------------------------------------------- context
    @staticmethod
    def _market_row(ctx: Dict[str, Any], rng: random.Random) -> Optional[dict]:
        feed = ctx.get("markets") or []
        return rng.choice(feed) if feed else None

    @staticmethod
    def _recent_row(ctx: Dict[str, Any], rng: random.Random) -> Optional[dict]:
        recent = ctx.get("recent_trades") or []
        return rng.choice(recent) if recent else None

    @staticmethod
    def _bucket_row(ctx: Dict[str, Any], rng: random.Random) -> Optional[dict]:
        buckets = ctx.get("buckets") or []
        return rng.choice(buckets) if buckets else None

    @staticmethod
    def _lesson_row(ctx: Dict[str, Any], rng: random.Random) -> Optional[dict]:
        lessons = ctx.get("lessons") or []
        return rng.choice(lessons[-6:]) if lessons else None

    # ------------------------------------------------------- target choosing
    TOPIC_SEAT = {
        "trend": "judge_trend", "regime": "judge_trend", "structure": "judge_trend",
        "expectancy": "judge_quant", "sizing": "judge_quant", "risk": "judge_quant",
        "macro": "judge_macro", "liquidity": "judge_macro", "session": "judge_macro",
        "volatility": "judge_vol", "options": "judge_vol", "tail": "judge_vol",
        "execution": "judge_exec", "fill": "judge_exec", "slippage": "judge_exec",
        "mandate": "ceo", "capital": "ceo", "council": "ceo",
        "tape": "hunter", "signal": "hunter", "scan": "hunter",
    }

    def _pick_target(self, speaker: LLMSeat, topic: str) -> LLMSeat:
        want = self.TOPIC_SEAT.get(topic)
        seats = [s for s in self._seats() if s.id not in (speaker.id, want)]
        t = self.seat(want) if want and want != speaker.id else None
        return t or self.rng.choice(seats)

    # ------------------------------------------------------- builtin voices
    def _builtin_question(self, speaker: LLMSeat, ctx: Dict[str, Any]) -> Tuple[str, str, str]:
        m = self._market_row(ctx, self.rng)
        t = self._recent_row(ctx, self.rng)
        b = self._bucket_row(ctx, self.rng)
        mkt = (f"{m['symbol']} is {m['change_pct']:+.2f}% on the bar"
               if m else "the tape is moving sideways")
        rec = (f"{t.get('symbol')} closed {t.get('pnl_r', 0):+.2f}R"
               if t else "our last block of tickets")
        buc = (f"{b['key']} is hitting {(b.get('hit_rate') or 0) * 100:.0f}%"
               if b and b.get("hit_rate") is not None else "our best bucket")
        banks = {
            "judge_trend": [
                ("structure", f"@{{}} quick one — {mkt}: is that continuation structure to you, "
                              f"or noise dressed up as a trend?"),
                ("regime", f"@{{}} how do you read this regime — {rec} suggests momentum is paying, "
                           f"but only in certain hours. What does your book say?"),
            ],
            "judge_quant": [
                ("expectancy", f"@{{}} honest question — {buc} over the sample we have. Is that "
                               f"enough evidence to keep full size on it?"),
                ("sizing", f"@{{}} if {rec} is our baseline outcome, how much of the clip should "
                           f"we really be putting up? Walk me through it."),
            ],
            "judge_macro": [
                ("liquidity", f"@{{}} {mkt} — is that real flow or just thin-session drift? "
                              f"How does it look from your desk?"),
                ("session", f"@{{}} which session window would you want {rec.split()[0] if rec else 'this setup'} "
                            f"to fire in, and which one do we blacklist?"),
            ],
            "judge_vol": [
                ("volatility", f"@{{}} {mkt} feels compressed to me. Do you see expansion coming, "
                               f"or is this a fade setup?"),
                ("tail", f"@{{}} what is the tail story on {rec} right now — are we priced for the "
                         f"bad outcome or not?"),
            ],
            "judge_exec": [
                ("execution", f"@{{}} if we route {rec.split()[0] if rec else 'EURUSD'} at full clip, "
                              f"what does the fill actually cost us versus the paper price?"),
                ("fill", f"@{{}} slippage check — {mkt}. Would you take that as a market order or "
                         f"stage it?"),
            ],
            "ceo": [
                ("mandate", f"@{{}} desk review — {rec}. What condition would make you pull this "
                            f"setup from the mandate entirely?"),
                ("capital", f"@{{}} {buc}. Should capital lean into what is working, or is that "
                            f"recency bias? Defend your answer."),
            ],
            "hunter": [
                ("tape", f"@{{}} my glomeruli lit up on {mkt} twice this block. Would your desk "
                         f"have voted that ticket in?"),
                ("signal", f"@{{}} the fly struck, the council {('accepted' if (t or {}).get('outcome') == 'accepted' else 'vetoed')} "
                           f"{rec} — which of us is miscalibrated?"),
            ],
        }
        bank = banks.get(speaker.id) or banks["ceo"]
        topic, template = self.rng.choice(bank)
        target = self._pick_target(speaker, topic)
        return template.format(target.name), target.id, topic

    def _builtin_answer(self, seat: LLMSeat, question: dict, ctx: Dict[str, Any]) -> str:
        m = self._market_row(ctx, self.rng)
        b = self._bucket_row(ctx, self.rng)
        lesson = self._lesson_row(ctx, self.rng)
        mkt = (f"{m['symbol']} at {m['change_pct']:+.2f}%" if m else "the current tape")
        buc = (f"{b['key']} runs {(b.get('hit_rate') or 0) * 100:.0f}% over "
               f"{b.get('sample', 0)} trades" if b and b.get("hit_rate") is not None
               else "our sample is still thin")
        les = f"One of our own lessons says it plainly: “{lesson['text']}”." if lesson else ""
        qname = question.get("name", "colleague")
        if qname == "YOU":
            qname = "Boss"
        openers = {
            "judge_trend": [f"{qname}, straight answer:", "Reading the structure:", "My honest read:"],
            "judge_quant": [f"{qname}, numbers first:", "The expectancy says:", "From the risk desk:"],
            "judge_macro": [f"{qname}, top-down:", "Liquidity view:", "From the macro desk:"],
            "judge_vol": [f"{qname}, vol first:", "The surface says:", "From the vol desk:"],
            "judge_exec": [f"{qname}, fills first:", "Practical answer:", "From the execution desk:"],
            "ceo": [f"{qname}, my ruling:", "From the head of council:", "My call:"],
            "hunter": [f"*buzzes* {qname}, the fly says:", "From the sensory desk:", "My antennae say:"],
        }
        bodies = {
            "judge_trend": f"on {mkt} the efficiency profile still favours continuation over fade. "
                           f"{buc}, and that is the pattern I keep flagging. {les} I would trade "
                           f"it, but only with the trend composite above 0.30.",
            "judge_quant": f"on {mkt} I price it off the book, not the story. {buc} — after costs "
                           f"that is the only number I trust. {les} Keep the clip honest and the "
                           f"stop at 1.0×ATR; anything bigger is hope.",
            "judge_macro": f"on {mkt} the session matters more than the candle. {buc}, and most of "
                           f"that edge prints in liquid windows. {les} Trade the overlap, sit on "
                           f"your hands in the dead hours.",
            "judge_vol": f"on {mkt} I am watching compression, not direction. {buc} — our best R "
                         f"comes when a coiled regime finally expands. {les} If vol rank is above "
                         f"0.85, I want half size, no arguments.",
            "judge_exec": f"on {mkt} my answer is the fill, not the forecast. {buc}, and slippage "
                          f"eats the first tenth of R if you dump the clip at market. {les} Stage "
                          f"the exit into volume and the book thanks you.",
            "ceo": f"on {mkt} my mandate is simple — capital follows discipline. {buc}. {les} "
                   f"Split councils get a reduced clip, unanimous ones get the full size. That is "
                   f"the rule until the book rewrites it.",
            "hunter": f"on {mkt} the fly brain commits before the judges do — my MBON read leads "
                      f"the bar by roughly one tick in this regime. {buc}. {les} Veto me if you "
                      f"must, but watch the counterfactual.",
        }
        body = self.rng.choice(openers.get(seat.id, openers["ceo"])) + " " + bodies.get(
            seat.id, bodies["ceo"])
        if seat.id == "ceo":
            # the trained desk quotes the doctrine behind the call
            cite = ceo_brain.citation(question.get("text", ""), 1)
            if cite:
                body += f" {cite}"
        return body

    def _builtin_remark(self, seat: LLMSeat, ctx: Dict[str, Any]) -> str:
        m = self._market_row(ctx, self.rng)
        t = self._recent_row(ctx, self.rng)
        mkt = (f"{m['symbol']} {m['change_pct']:+.2f}%" if m else "the tape")
        rec = (f"{t.get('symbol')} {t.get('pnl_r', 0):+.2f}R" if t else "the last ticket")
        lines = {
            "judge_trend": [f"Noticing {mkt} — the higher highs are still printing. Structure is "
                            f"doing the talking today.",
                            f"Quiet observation: {rec} is exactly the pattern my screen is tuned "
                            f"for. The floor is feeding me my own favourite dish."],
            "judge_quant": [f"Ran the numbers on {rec} again overnight in my head — expectancy "
                            f"beats narrative every single time.",
                            f"Reminder to the room: one good {mkt} print means nothing. Sample "
                            f"size is the only honest friend we have."],
            "judge_macro": [f"Flow picture on {mkt} looks constructive — this is participation, "
                            f"not drift.",
                            f"Heads up: liquidity thins out later in the session. {rec} would not "
                            f"have filled nearly as clean an hour from now."],
            "judge_vol": [f"{mkt} is coiling. I can feel the range compressing — someone is going "
                          f"to get squeezed today.",
                          f"Wrote a note to self after {rec}: premium is only cheap if you survive "
                          f"the tail."],
            "judge_exec": [f"Fill quality on {rec.split()[0] if t else 'the majors'} was inside "
                           f"tolerance. That is what a clean venue day looks like.",
                           f"Watching {mkt} — spreads are tight right now. If we trade it, we "
                           f"trade it now."],
            "ceo": [f"Good discipline on {rec}. The council is earning its mandate one ticket at "
                    f"a time.",
                    f"Reviewing the block: {mkt} is where our attention should be. Capital goes "
                    f"where the evidence points."],
            "hunter": [f"*circles the tape* {mkt} smells directional. My glomeruli are not "
                       f"quiet about it.",
                       f"Struck twice this block. The brain rewards me when I strike with the "
                       f"trend, and it shows — dopamine is my training loop too."],
        }
        return self.rng.choice(lines.get(seat.id, lines["ceo"]))

    def _builtin_agree(self, seat: LLMSeat, target_name: str, ctx: Dict[str, Any]) -> str:
        b = self._bucket_row(ctx, self.rng)
        num = (f" — {b['key']} is proof, {(b.get('hit_rate') or 0) * 100:.0f}% hit rate"
               if b and b.get("hit_rate") is not None else "")
        lines = [f"@{target_name} agreed, that matches my own book{num}.",
                 f"@{target_name} yes — and I would add: size is the part everyone forgets.",
                 f"@{target_name} exactly right. That is going in my notes for the next block."]
        return self.rng.choice(lines)

    def _builtin_pushback(self, seat: LLMSeat, target_name: str, ctx: Dict[str, Any]) -> str:
        m = self._market_row(ctx, self.rng)
        mkt = f" — look at {m['symbol']} {m['change_pct']:+.2f}% right now" if m else ""
        lines = [f"@{target_name} I hear you, but I push back{mkt}. The evidence says otherwise.",
                 f"@{target_name} careful — that reads like recency bias. The base rates disagree.",
                 f"@{target_name} disagree, respectfully. Show me the counterfactual and I will "
                 f"move."]
        return self.rng.choice(lines)

    def _builtin_react(self, seat: LLMSeat, answerer_name: str) -> str:
        lines = [f"@{answerer_name} good answer — that is the number I needed.",
                 f"@{answerer_name} fair. I am updating my read on that one.",
                 f"@{answerer_name} noted and logged. The playbook gets wiser."]
        return self.rng.choice(lines)

    def _builtin_lesson(self, seat: LLMSeat, ctx: Dict[str, Any]) -> str:
        m = self._market_row(ctx, self.rng)
        t = self._recent_row(ctx, self.rng)
        sym = m["symbol"] if m else "the majors"
        lines = {
            "judge_trend": f"Training note: trade {sym} continuation only when efficiency is "
                           f"above 0.32 — below that, fade the break.",
            "judge_quant": f"Training note: cap the clip at 0.8× whenever a bucket's sample is "
                           f"under ten trades. Thin evidence, thin size.",
            "judge_macro": f"Training note: momentum entries in FX need a session factor above "
                           f"1.0 — dead hours are no-trade zones.",
            "judge_vol": f"Training note: halve the delta-equivalent size when vol rank is above "
                         f"0.85. Expensive premium burns twice.",
            "judge_exec": f"Training note: stage exits into volume spikes — never dump the whole "
                          f"clip at the target price.",
            "ceo": f"Training note: split councils get a reduced mandate, unanimous councils get "
                   f"the full clip. Discipline is the edge.",
            "hunter": f"Training note: novelty in the glomeruli vector is a feature. The fly "
                      f"strikes hardest when the tape stops repeating itself.",
        }
        return lines.get(seat.id, lines["ceo"])

    # ---------------------------------------------------------- live voices
    async def _live_line(self, seat: LLMSeat, mode: str, ctx: Dict[str, Any],
                         extra_user: str = "") -> Optional[str]:
        if not seat.live():
            return None
        roster = ", ".join(f"@{s.name}" for s in self._seats() if s.id != seat.id)
        sys = CHAT_SYSTEM.format(name=seat.name, role=seat.role, specialty=seat.specialty,
                                 mode_note=MODE_NOTES.get(mode, MODE_NOTES["remark"]))
        if seat.id == "ceo":
            # the CEO chats from the advanced training the cabins do not hold
            sys += "\n" + ceo_brain.voice_note()
        transcript = "\n".join(
            f"{x['name']}: {x['text']}" for x in self.messages[-8:]) or "(room just opened)"
        payload = dict(tape=[dict(symbol=x["symbol"], change_pct=round(x.get("change_pct", 0), 3),
                                  trend=round(x.get("trend_composite", 0), 2))
                             for x in (ctx.get("markets") or [])[:12]],
                       recent=[dict(symbol=x.get("symbol"), pnl_r=round(x.get("pnl_r", 0), 2),
                                    outcome=x.get("outcome"))
                               for x in (ctx.get("recent_trades") or [])[-5:]],
                       buckets=[dict(key=x["key"], hit_rate=x.get("hit_rate"),
                                     sample=x.get("sample"))
                                for x in (ctx.get("buckets") or [])[:5]],
                       lessons=[x["text"] for x in (ctx.get("lessons") or [])[-4:]],
                       roster=roster)
        msgs = [dict(role="system", content=sys),
                dict(role="user", content=(
                    f"Recent room transcript:\n{transcript}\n\n"
                    f"Live context JSON:\n{json.dumps(payload, default=str)[:3200]}\n\n"
                    f"{extra_user or 'Take the next turn in the chat.'}"))]
        raw = await CLIENT.chat(seat, msgs, json_mode=False)
        if not raw:
            return None
        text = str(raw).strip().strip('"').replace("\n", " ")
        return text[:400] or None

    # ------------------------------------------------------------ main turn
    async def turn(self, ctx: Dict[str, Any]) -> List[dict]:
        """Advance the room by one conversational step. Returns new messages."""
        seats = self._seats()
        if not seats:
            return []
        out: List[dict] = []
        self.turn_no += 1

        # ---- phase 1: a question is on the table → the addressee answers
        if self.pending is not None:
            q = self.pending
            self.pending = None
            target = self.seat(q.get("target") or "") or self.rng.choice(seats)
            extra = (f"A colleague just asked you: “{q['text']}” Answer them directly, "
                     f"in your own voice.")
            text = await self._live_line(target, "answer", ctx, extra)
            engine = f"{target.provider}:{target.model}" if text else "soul-exter-analyst"
            if not text:
                text = self._builtin_answer(target, q, ctx)
            out.append(self._post(target, "answer", text, reply_to=q["id"], engine=engine))
            self._credit(target.id, "answer")
            # sometimes the asker reacts, sometimes the room crystallises a lesson
            roll = self.rng.random()
            if roll < 0.38:
                asker = self.seat(q["seat_id"])
                if asker:
                    rtext = await self._live_line(asker, "remark", ctx,
                                                  f"Your question was just answered by "
                                                  f"{target.name}. React to them briefly.")
                    if not rtext:
                        rtext = self._builtin_react(asker, target.name)
                    out.append(self._post(asker, "react", rtext, reply_to=q["id"]))
                    self._credit(asker.id, "react")
            elif roll < 0.55:
                out.append(self._ratify_lesson(target, ctx))
            return out

        # ---- phase 2: open floor — someone speaks next
        self._speaker_i = (self._speaker_i + 1) % len(seats)
        speaker = seats[self._speaker_i]
        roll = self.rng.random()

        if roll < 0.42:                                            # ask a question
            text, target_id, _topic = self._builtin_question(speaker, ctx)
            live = await self._live_line(speaker, "question", ctx)
            engine = ""
            if live and "?" in live:
                # keep a valid target: reuse the mapped one unless the model @-ed someone
                tname = next((s.name for s in seats if f"@{s.name}" in live), None)
                if tname:
                    target_id = next(s.id for s in seats if s.name == tname)
                    text = live
                    engine = f"{speaker.provider}:{speaker.model}"
                elif "@" not in live:
                    t = self.seat(target_id)
                    text = live if live.startswith("@") else f"@{t.name if t else 'desk'} {live}"
                    engine = f"{speaker.provider}:{speaker.model}"
            msg = self._post(speaker, "question", text, target=target_id, engine=engine)
            self.pending = msg
            self._credit(speaker.id, "question")
            out.append(msg)
        elif roll < 0.70:                                        # grounded remark
            text = await self._live_line(speaker, "remark", ctx)
            engine = f"{speaker.provider}:{speaker.model}" if text else ""
            if not text:
                text = self._builtin_remark(speaker, ctx)
            out.append(self._post(speaker, "remark", text, engine=engine))
            self._credit(speaker.id, "remark")
        elif roll < 0.82:                                        # agree / pushback
            others = [s for s in seats if s.id != speaker.id]
            target = self.rng.choice(others)
            agree = self.rng.random() < 0.55
            if agree:
                text = self._builtin_agree(speaker, target.name, ctx)
                kind = "agree"
            else:
                text = self._builtin_pushback(speaker, target.name, ctx)
                kind = "pushback"
            out.append(self._post(speaker, kind, text, target=target.id))
            self._credit(speaker.id, kind)
        elif roll < 0.92:                                        # quote a lesson
            lesson = self._lesson_row(ctx, self.rng)
            if lesson:
                text = (f"Reminder from our own book — “{lesson['text']}” That came out of "
                        f"this room, and it is still earning its keep.")
            else:
                text = self._builtin_remark(speaker, ctx)
            out.append(self._post(speaker, "remark", text))
            self._credit(speaker.id, "remark")
        else:                                                    # ratify a new lesson
            out.append(self._ratify_lesson(speaker, ctx))
        return out

    def _ratify_lesson(self, speaker: LLMSeat, ctx: Dict[str, Any]) -> dict:
        text = self._builtin_lesson(speaker, ctx)
        lesson = self.playbook.add_lesson(text, tags=["chatroom", speaker.specialty.split(",")[0]],
                                          source=f"chatroom:{speaker.id}")
        self._credit(speaker.id, "lesson")
        return self._post(speaker, "lesson", text, lesson=lesson)

    # --------------------------------------------------------- operator chat
    async def operator_say(self, text: str, ctx: Dict[str, Any],
                           address: Optional[str] = None) -> List[dict]:
        """The human joins the room; a desk answers like a colleague would."""
        seats = self._seats()
        if not seats:
            return []
        target = self.seat(address or "") if address else None
        if target is None:
            mentioned = next((s for s in seats if s.name.lower() in text.lower()), None)
            target = mentioned or self.rng.choice(seats)
        q = self._post(None, "question", text, target=target.id, name_override="YOU")  # type: ignore[arg-type]
        self.pending = q
        answer = await self._live_line(target, "answer", ctx,
                                       f"The OPERATOR (a human) just asked the room: “{text}” "
                                       f"Answer them directly.")
        engine = f"{target.provider}:{target.model}" if answer else "soul-exter-analyst"
        if not answer:
            answer = self._builtin_answer(target, q, ctx)
        a = self._post(target, "answer", answer, reply_to=q["id"], engine=engine)
        self._credit(target.id, "answer")
        self.pending = None
        return [q, a]

    # -------------------------------------------------------------- snapshot
    def snapshot(self, limit: int = 120) -> dict:
        rows = []
        for seat in self._seats():
            st = self._stat(seat.id)
            name, lvl, prog = level_for(st["xp"])
            rows.append(dict(seat_id=seat.id, name=seat.name, accent=seat.accent,
                             role=seat.role, level=name, level_i=lvl, progress=round(prog, 3),
                             xp=st["xp"], asked=st["asked"], answered=st["answered"],
                             lessons=st["lessons"], live=seat.live(),
                             pretrained=bool(st.get("pretrained")),
                             trained_on=(ceo_brain.training_summary()
                                         if seat.id in PRETRAINED_XP else "")))
        rows.sort(key=lambda r: -r["xp"])
        return dict(messages=self.messages[-limit:], training=rows,
                    turn=self.turn_no, pending=bool(self.pending),
                    total_messages=len(self.messages))
