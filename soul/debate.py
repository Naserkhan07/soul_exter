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
import hashlib
import logging
import random
import re
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

#: Turn shapes per round: a lead claim, then the challenge/answer rhythm, the close
#: where the rule is written, and the desks that carry it out of the room.
ROUND_SHAPE = ["claim", "challenge", "question", "answer", "ack", "lesson", "carry"]

#: The desks that say how they will trade the rule. Two a round, rotating, so
#: every desk speaks on the record over a session without making each meeting
#: twice as long.
CARRIERS_PER_ROUND = 2

#: One room, one name. It is on the icon on the floor, in the room header and in
#: the API payload, so there is no ambiguity about where the desks talk.
ROOM_NAME = "The Pit"
ROOM_TAGLINE = "six desks, one room — they talk, listen, argue and train each other here"


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
    #: who the desk was speaking *to* — the room is a conversation, not six
    #: monologues: a challenge names the desk whose claim it is attacking, a
    #: question names the desk that has to answer it.
    to: str = ""
    to_name: str = ""
    #: The rule this turn is about. A desk opening a round names the rule on
    #: file that bears on the topic; the head of desk writes a new one; the desks
    #: that follow say how they will carry it. This is what makes the training
    #: channel *visible*: you can see what was learned and who learned it.
    rule: str = ""
    #: True when the turn is the training channel itself rather than an argument:
    #: a rule being recalled, written, carried, or a closed trade reviewed.
    training: bool = False
    #: who taught this desk the rule, and in which round — the room trains its
    #: members, so a turn about a rule says whose rule it was
    rule_from: str = ""
    rule_round: int = 0
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def packet(trade: TradeCandidate, result: CouncilResult,
           extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The numbers a desk is shown when it is asked about a trade.

    One builder, used by the review round and by an ad-hoc question from the
    floor, so a desk can never be asked about a trade it cannot see.
    """
    out: Dict[str, Any] = {
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
    out.update(extra or {})
    return out


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
        #: how many rules each desk has *heard* another desk write. Listening is
        #: the cheapest training there is, and it is now countable: a desk that
        #: heard the rule is a desk that will be prompted with it next trade.
        self.heard: Dict[str, int] = {}
        self.rounds = 0
        self.next_round_at: float = 0.0
        self.current_topic: Optional[str] = None
        self._queued: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._rng = random.Random(getattr(cfg, "debate_seed", 20240914))

    # ------------------------------------------------------------------
    def queue_trade(self, trade: TradeCandidate, result: CouncilResult,
                    extra: Optional[Dict[str, Any]] = None) -> None:
        """Put the trade the council just decided on the debate agenda."""
        inner = packet(trade, result, extra)
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
    def _name_of(self, key: str) -> str:
        brain = self.brains.get(key) or self.ceo
        spec = getattr(brain, "spec", None)
        return (spec.name or spec.label) if spec else key

    async def _say(self, key: str, kind: str, topic: str, inner: Dict[str, Any],
                   to: str = "", to_name: str = "", rule: str = "",
                   training: bool = False, rule_from: str = "",
                   rule_round: int = 0) -> Optional[Dict[str, Any]]:
        brain = self.brains.get(key) or self.ceo
        if brain is None:
            return None
        spec: CabinSpec = brain.spec
        reg = self.registry.get(key, {})
        inner = dict(inner)
        if to_name:
            # the brain is told who it is talking to, so it answers *that desk*
            inner["to_name"] = to_name
        # the turn number goes in too: without it a persona with a small bank of
        # lines (mock, and any model that latches onto the transcript length)
        # answers every round with the same sentence
        inner["round"] = self.rounds + 1
        if rule:
            inner["rule"] = rule
        # every turn can see the rules this table has already agreed: that is how
        # a desk argues from what it was taught instead of from scratch
        inner.setdefault("rules", [str(l.get("text", "")) for l in self.lessons[-6:]])
        # note: `turn`, not `kind` — publish() already owns that keyword
        await self.bus.publish("debate_thinking", room="desk", speaker=key,
                               name=spec.name or spec.label, turn=kind, topic=topic,
                               round=self.rounds + 1)
        await self.bus.publish("debate_listening", room="desk", speaker=key,
                               name=spec.name or spec.label, turn=kind, topic=topic,
                               to=to, to_name=to_name, round=self.rounds + 1)
        text = await brain.debate(topic, self.transcript, kind, inner)
        text = " ".join(str(text).split())
        if not text:
            return None
        msg = DebateMessage(
            room="desk", topic=topic, speaker=key, name=spec.name or spec.label,
            label=spec.label, model=reg.get("model", getattr(brain, "model_name", "mock")),
            turn=kind, text=text[:600], round=self.rounds + 1,
            trade_id=inner.get("trade_id"), to=to, to_name=to_name,
            rule=str(rule or "")[:200], training=bool(training),
            rule_from=str(rule_from or "")[:60], rule_round=int(rule_round or 0),
        ).as_dict()
        self.transcript.append(msg)
        self.transcript = self.transcript[-160:]
        if kind == "lesson":
            # everyone in the room hears a rule being written: this is the desks
            # training each other by listening, and it is published as its own
            # event so the room can show who just learned what
            for listener in self.brains.keys():
                if listener == key:
                    continue
                self.heard[listener] = self.heard.get(listener, 0) + 1
                await self.bus.publish("debate_heard", room="desk", listener=listener,
                                       name=self._name_of(listener), speaker=key,
                                       speaker_name=self._name_of(key),
                                       rule=str(text)[:200], round=self.rounds + 1,
                                       heard=self.heard[listener])
            entry = {
                "topic": topic, "speaker": key, "rule": str(inner.get("rule") or "")[:200],
                "speaker_label": f"{spec.name or spec.label}, {spec.title or spec.role}",
                "text": text[:400], "ts": msg["ts"], "round": msg["round"],
            }
            # The same rule re-agreed in a later round is not a second rule: the
            # list is what the desk has agreed, so restate the one on file.
            same = next((l for l in self.lessons if l["text"] == entry["text"]), None)
            if same is not None:
                same.update({"ts": entry["ts"], "round": entry["round"],
                             "topic": entry["topic"]})
            else:
                self.lessons.append(entry)
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
            # The room closes every round by writing a rule. The CEO phrases it,
            # but the rule has to come out of *this* trade — a fixed sentence
            # repeated every round is not training, it is a slogan.
            inner.setdefault("rule", self._rule_for(text, inner))
            # ...and the desk that opens names a rule it was already taught, so
            # the previous rounds are visibly in force, not just stored
            recall, recall_lesson = self._recall_for(text)
            inner["recall"] = recall
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

            # A round is a conversation between named desks: the lead claims,
            # a second desk challenges *the lead*, a third puts a question to the
            # challenger, the challenger answers it, a fourth adds a nuance, and
            # the head of desk closes with the rule the room will carry.
            lead = order[0]
            second = order[1] if len(order) > 1 else lead
            third = order[2] if len(order) > 2 else second
            fourth = order[3] if len(order) > 3 else third
            turns = [
                ("claim", lead, ""),
                ("challenge", second, lead),
                ("question", third, second),
                ("answer", second, third),          # the desk that was asked answers
                ("ack", fourth, third if fourth != third else second),
                ("lesson", self.ceo_key(), ""),     # the close is addressed to the room
            ]

            said: List[Dict[str, Any]] = []
            for kind, speaker, target in turns:
                if speaker == self.ceo_key() and kind != "lesson":
                    speaker = second
                msg = await self._say(speaker, kind, text, inner,
                                      to=target if target else "",
                                      to_name=self._name_of(target) if target else "",
                                      rule=recall if kind == "claim" else "",
                                      training=kind == "claim" and bool(recall),
                                      rule_from=(recall_lesson.get("speaker_label", "").split(",")[0]
                                                 if kind == "claim" and recall_lesson else ""),
                                      rule_round=(int(recall_lesson.get("round") or 0)
                                                  if kind == "claim" and recall_lesson else 0))
                if msg:
                    said.append(msg)
            # carry: two desks say, in their own words, how they will trade the
            # rule that was just written. A rule nobody has to act on is a
            # slogan; this is the part where the desk shows it was taught.
            rule = str(inner.get("rule") or "")
            author = self._name_of(self.ceo_key())
            for key in self._carriers():
                msg = await self._say(key, "carry", text, inner, rule=rule, training=True,
                                      rule_from=author, rule_round=self.rounds)
                if msg:
                    said.append(msg)
                    await self.bus.publish("debate_carry", room="desk", speaker=key,
                                           name=self._name_of(key), rule=rule[:200],
                                           topic=text, round=self.rounds)
            log.info("debate round %d on %r: %d turns, %d lessons on file",
                     self.rounds, text[:48], len(said), len(self.lessons))
            return said

    def ceo_key(self) -> str:
        return "CEO"

    # ------------------------------------------------------------------
    def _recall_for(self, topic: str) -> tuple:
        """A rule already on file that bears on this topic, and who wrote it."""
        if not self.lessons:
            return "", {}
        seed = hashlib.sha256(f"{topic}|{self.rounds}".encode()).digest()[:4]
        lesson = self.lessons[int.from_bytes(seed, "big") % len(self.lessons)]
        text = str(lesson.get("text", ""))
        # the rule, not the sentence that introduced it
        text = re.sub(r"^rule written[:—-]\s*", "", text.strip(), flags=re.I)
        return text[:200], lesson

    def _carriers(self) -> List[str]:
        """The desks that carry the new rule out of this round (rotating pair)."""
        if not self.brains:
            return []
        keys = list(self.brains.keys())
        start = self.rounds % len(keys)
        n = min(CARRIERS_PER_ROUND, len(keys))
        return [keys[(start + i) % len(keys)] for i in range(n)]

    async def post_mortem(self, trade_id: str, record: Optional[Dict[str, Any]],
                          pnl: float, pnl_pct: float,
                          exit_reason: str = "") -> Optional[Dict[str, Any]]:
        """A closed position is reviewed in the room, by a desk that was wrong.

        The verdicts went into the training set the moment the position closed;
        this is the same lesson *spoken*, so the room shows how the desks get
        trained: a desk that was on the wrong side of a closed trade says what it
        will do differently, on the record, in front of the others.
        """
        if self._lock.locked() or not self.brains:
            # a round is mid-flight — the training row is already written, and
            # interrupting the meeting to say it again helps nobody
            return None
        won = float(pnl or 0.0) > 0
        verdicts = [v for v in ((record or {}).get("verdicts") or [])
                    if str(v.get("verdict")) in ("APPROVE", "REJECT")]
        wrong = [v for v in verdicts if (v.get("verdict") == "APPROVE") != won]
        right = [str(v.get("cabin")) for v in verdicts
                 if (v.get("verdict") == "APPROVE") == won]
        was_wrong = bool(wrong)
        if wrong:
            pick = wrong[self._rng.randrange(len(wrong))]
            speaker = str(pick.get("cabin"))
            flags = ", ".join(pick.get("risk_flags") or [])
        else:
            # nobody was on the wrong side: the head of desk says so, and the
            # sample is filed as a settled decision rather than a correction
            speaker, flags = self.ceo_key(), ""
        symbol = str((record or {}).get("symbol") or "the position")
        side = str((record or {}).get("side") or "")
        strategy = str((record or {}).get("strategy") or "setup")
        topic = (f"post-mortem: {symbol} {side} closed {float(pnl or 0.0):+,.2f} "
                 f"({float(pnl_pct or 0.0):+.2f}%)")
        inner: Dict[str, Any] = {
            "trade_id": trade_id, "symbol": symbol, "side": side, "strategy": strategy,
            "pnl": round(float(pnl or 0.0), 2), "pnl_pct": round(float(pnl_pct or 0.0), 3),
            "outcome": "win" if won else "loss", "exit_reason": exit_reason,
            "flags": flags, "right": ", ".join(right) or "nobody",
            "wrong": was_wrong,
        }
        async with self._lock:
            return await self._say(speaker, "postmortem", topic, inner, training=True)

    # ------------------------------------------------------------------
    # The rules the room can write. Each one is a sentence a desk could act on
    # tomorrow, and the pick is a hash of the trade plus the round, so the
    # training channel does not repeat itself on consecutive meetings.
    RULES = (
        "when a setup is extended, halve the size instead of skipping it",
        "a {strategy} entry that needs a catalyst waits for the level to be reclaimed",
        "when the council splits, the smaller size is the decision and the opinion is not",
        "a stop inside the noise band is a coin flip, so it gets coin-flip risk",
        "correlated tickets are one risk: the second one pays half",
        "no new risk into a session that has already spent its budget",
        "if the regime and the setup disagree, the regime wins and the trade waits",
        "a thesis with no invalidation level is a story, so it is not sized",
    )

    def _rule_for(self, topic: str, inner: Dict[str, Any]) -> str:
        seed = f"{topic}|{inner.get('trade_id')}|{self.rounds}"
        idx = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big") % len(self.RULES)
        rule = self.RULES[idx]
        try:
            return rule.format(
                strategy=str(inner.get("strategy", "trend")).lower() or "trend",
                symbol=inner.get("symbol", "this name"),
            )
        except (KeyError, ValueError):
            return rule

    async def ask(self, key: str, question: str,
                  trade_id: Optional[str] = None,
                  inner: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """A human asks one desk a question, and the desk answers in the room.

        The answer is an ordinary turn: it lands in the transcript, on the bus and
        on the cabin's card, so a question asked from the floor is the same kind
        of object as an argument the desk made on its own.
        """
        key = (key or "").strip().upper()
        if key not in self.brains and key != self.ceo_key():
            return None
        text = " ".join(str(question or "").split())[:240]
        if not text:
            return None
        payload = dict(inner or {})
        if trade_id:
            payload["trade_id"] = trade_id
        # The question is a turn too. Written into the transcript first, so the
        # desk sees it, every client renders it in order, and a refresh does not
        # lose what was asked.
        asked = DebateMessage(
            room="desk", topic=self.current_topic or text, speaker="YOU", name="you",
            label="the person on the floor", model="", turn="you", text=text,
            round=self.rounds, trade_id=trade_id,
            to=key, to_name=self._name_of(key),
        ).as_dict()
        self.transcript.append(asked)
        self.transcript = self.transcript[-160:]
        await self.bus.publish("debate_message", **asked)
        return await self._say(key, "answer", text, payload)

    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        return {
            "room": "desk",
            "rounds": self.rounds,
            "topic": self.current_topic,
            "transcript": self.transcript[-40:],
            "lessons": self.lessons[-12:],
            "name": ROOM_NAME,
            "tagline": ROOM_TAGLINE,
            "heard": dict(self.heard),
            "next_round_in": max(0.0, round(self.next_round_at - time.time(), 1))
            if self.next_round_at else None,
            "training_turns": sum(1 for m in self.transcript[-160:]
                                  if m.get("training") or m.get("turn") == "lesson"),
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
