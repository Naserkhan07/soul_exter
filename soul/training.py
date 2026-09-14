"""Training the six desks on trading.

Three things train a desk in this project, and this module is the third one:

1. **The curriculum** (``knowledge.py``). The house playbook and the desk's own
   schooling sit in every system prompt, and the ten seed lessons are read back
   into every verdict as DESK MEMORY from the first trade of a session.
2. **The room** (``debate.py``). Every debate round ends with a rule the head of
   desk writes down, and those rules are fed back into the next prompt. That is
   the desks teaching each other in context.
3. **This module.** A supervised dataset built from the desk's *own settled
   decisions*: the packet it was shown, the verdict it gave, and what that
   decision was actually worth once the position closed. Export it, and
   ``python -m soul.train`` turns it into a LoRA adapter per desk, which the
   local-HF backend then loads from ``SOUL_ADAPTERS``. No API keys, no hosted
   trainer, nothing leaving the box.

What gets written is exactly the task each model performs:

* ``judge``  — system = the desk's real system prompt, user = the real packet
  (trade, market, book, memory, earlier desks), assistant = a verdict JSON.
* ``lesson`` — system = the desk, user = the topic the room argued, assistant =
  the rule the desk carried out of it.
* ``curriculum`` — the desk's playbook drilled as question and answer, so a
  fresh adapter does not need a session of history before it behaves.

The labels for settled trades are **noisy**: one trade is one sample, and the
market is not a teacher with a syllabus. They are weighted accordingly in
``meta`` (a refusal that saved the book is a strong sample; a winner that the
desk's own flags warned about is a lesson, not a law). The deliberate design is
that a desk which approved a loser is trained on *its own risk flags* as the
reason to refuse — that is how the room's rules and the desk's record end up
pointing the same way.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .brains.base import (
    CABINS,
    CEO_SPEC,
    build_cabin_prompt,
    build_ceo_prompt,
    trade_block,
)
from .knowledge import FOCUS, HOUSE_RULES, SEED_LESSONS
from .models import TradeCandidate, Verdict, clamp

log = logging.getLogger("soul.training")

#: Which desks the roster trains. The five voting cabins plus the head of desk.
DESKS: List[str] = ["QUANT", "RISK", "NEWS", "MACRO", "COMPLIANCE", "CEO"]

#: A hard ceiling on what the session keeps in memory (the exported file is what
#: the trainer reads; this is the live view for the panel).
MAX_SAMPLES = 6000
MAX_PENDING = 400


def _verdict_json(v: Dict[str, Any], ceo: bool = False) -> str:
    """The verdict the model should have emitted, as the model would emit it."""
    adj = dict(v.get("adjustment") or {})
    body: Dict[str, Any] = {
        "verdict": v.get("verdict", "ABSTAIN"),
        "confidence": int(round(float(v.get("confidence") or 0))),
        "reason": " ".join(str(v.get("reason") or "").split())[:400],
        "risk_flags": list(v.get("risk_flags") or [])[:4],
        "adjustment": {
            "size_multiplier": round(float(adj.get("size_multiplier", 1.0) or 1.0), 2),
            "stop_pct": adj.get("stop_pct"),
        },
    }
    if ceo:
        body["key_dissent"] = " ".join(str(v.get("key_dissent") or v.get("reason") or "").split())[:240]
    return json.dumps(body, ensure_ascii=False)


def _refusal_json(v: Dict[str, Any], why: str, size: float = 0.0, ceo: bool = False) -> str:
    """A reflection: the same desk, on the same packet, with hindsight."""
    flags = list(v.get("risk_flags") or [])
    return _verdict_json(
        {
            "verdict": "REJECT",
            "confidence": max(55, min(85, int(round(float(v.get("confidence") or 60))) + 10)),
            "reason": why,
            "risk_flags": flags or ["no invalidation written before the entry"],
            "adjustment": {"size_multiplier": size or 0.0, "stop_pct": None},
        },
        ceo=ceo,
    )


def _smaller_yes_json(v: Dict[str, Any], why: str, size: float = 0.5, ceo: bool = False) -> str:
    """The other reflection: a refusal that cost the book, at a size that would
    have paid for the objection."""
    return _verdict_json(
        {
            "verdict": "APPROVE",
            "confidence": max(50, min(80, int(round(float(v.get("confidence") or 55))))),
            "reason": why,
            "risk_flags": list(v.get("risk_flags") or [])[:3],
            "adjustment": {"size_multiplier": size, "stop_pct": None},
        },
        ceo=ceo,
    )


class TrainingBook:
    """The dataset every desk is trained on, built while the desk trades."""

    def __init__(self, cfg: Any = None, brains: Optional[Dict[str, Any]] = None) -> None:
        self.cfg = cfg
        self.brains = brains or {}
        self.dataset_path = Path(getattr(cfg, "training_dataset", "artifacts/training/desk-sft.jsonl"))
        self.adapters_dir = Path(getattr(cfg, "adapters_dir", "artifacts/adapters"))
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.samples: List[Dict[str, Any]] = []
        self.counts: Dict[str, int] = {}
        self.built_at: float = 0.0
        self.last_manifest: Optional[Dict[str, Any]] = None
        #: the state snapshot is polled by every client, so the curriculum is
        #: assembled once and the lesson rows are only rebuilt when the room has
        #: actually written something new
        self._curriculum: Optional[List[Dict[str, Any]]] = None
        self._lesson_cache: Tuple[Any, List[Dict[str, Any]]] = ((-1, 0.0), [])

    # ------------------------------------------------------------------
    # 1. the curriculum: what a desk knows before it ever trades
    # ------------------------------------------------------------------
    def _spec(self, key: str):
        """The desk's spec: from the live brain when there is one, from the
        roster otherwise.

        The trainer runs as its own process with no engine behind it, and it
        still has to be able to reproduce the prompt the desk was given — so the
        fallback is the same static spec the engine builds its brains from.
        """
        brain = self.brains.get(key)
        spec = getattr(brain, "spec", None)
        if spec is not None:
            return spec
        key = key.upper()
        for c in CABINS:
            if c.key == key:
                return c
        return CEO_SPEC if key == "CEO" else None

    def curriculum_rows(self) -> List[Dict[str, Any]]:
        """The playbook, drilled: one question per rule, answered by the desk.

        A rule the model can only quote is a rule it will not argue from. These
        rows put the rule in the desk's own mouth, against the desk's own
        mandate, in the same voice the debate room hears.
        """
        if self._curriculum is not None:
            return self._curriculum
        rows: List[Dict[str, Any]] = []
        for key in DESKS:
            spec = self._spec(key)
            if spec is None:
                continue
            system = spec.system_prompt
            for name, text in SEED_LESSONS.items():
                rows.append(self._row(
                    key, "curriculum", system,
                    f"Desk check — {name}. State the rule you trade by on this, and the "
                    f"condition that would make you break it.",
                    f"{text} On my desk that shows up as: {self._desk_angle(key, name)}",
                    weight=0.5,
                ))
            for i, rule in enumerate(_playbook_rules(), start=1):
                rows.append(self._row(
                    key, "curriculum", system,
                    f"House playbook rule {i}: {rule}\n\nHow does {spec.name or key} apply this "
                    f"at the {spec.label} desk?",
                    f"{rule} As {spec.title or spec.role}: {self._desk_angle(key, 'playbook')}",
                    weight=0.5,
                ))
        self._curriculum = rows
        return rows

    def _desk_angle(self, key: str, about: str) -> str:
        focus = FOCUS.get(key, "")
        # the first concrete sentence of the desk's schooling, which is the line
        # it argues from in the room
        for line in focus.splitlines():
            line = line.strip()
            if line.startswith("- ") and len(line) > 40:
                return line[2:]
        return "the rule is only worth what it saves on the next bad tape."

    # ------------------------------------------------------------------
    # 2. the trades: what the desk said, and what it was worth
    # ------------------------------------------------------------------
    def note(self, trade: TradeCandidate, result: Any, ctx: Optional[Dict[str, Any]] = None) -> None:
        """Record a council decision verbatim, waiting for its outcome.

        Nothing is learned here. A verdict is a *decision*; only the closed
        position says whether it was a good one, and that arrives later.
        """
        ctx = ctx or {}
        try:
            record = {
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "strategy": trade.strategy,
                "risk_pct": float(trade.risk_pct),
                "rr": float(trade.rr),
                "entry": float(trade.entry),
                "stop": float(trade.stop),
                "target": float(trade.target),
                "decision": getattr(result, "decision", "PENDING"),
                "opened": getattr(result, "decision", "") == "ENTER",
                "ts": time.time(),
                "prompts": self._prompts(trade, result, ctx),
                "verdicts": [v.as_dict() for v in getattr(result, "verdicts", [])],
                "ceo": (result.ceo_verdict.as_dict() if getattr(result, "ceo_verdict", None) else None),
            }
        except Exception as exc:                            # pragma: no cover
            log.debug("training note skipped for %s: %s", getattr(trade, "id", "?"), exc)
            return
        self.pending[record["trade_id"]] = record
        if len(self.pending) > MAX_PENDING:
            for k in list(self.pending)[: len(self.pending) - MAX_PENDING]:
                self.pending.pop(k, None)

    def _prompts(self, trade: TradeCandidate, result: Any, ctx: Dict[str, Any]) -> Dict[str, str]:
        """Reproduce the exact prompt each desk was given.

        Same builder, same packet: the training row is the task the model
        actually performed, not a paraphrase of it.
        """
        out: Dict[str, str] = {}
        verdicts = list(getattr(result, "verdicts", []) or [])
        for i, v in enumerate(verdicts):
            spec = self._spec(v.cabin)
            if spec is None:
                continue
            # wave mode: a desk sees the waves before it, not its own wave
            prior = [p for p in verdicts[:i] if p.stage < v.stage]
            try:
                out[v.cabin] = build_cabin_prompt(spec, trade, ctx, prior)
            except Exception:                               # pragma: no cover
                out[v.cabin] = ""
        ceo = getattr(result, "ceo_verdict", None)
        if ceo is not None:
            try:
                out["CEO"] = build_ceo_prompt(self._spec("CEO"), trade, verdicts, ctx)
            except Exception:                               # pragma: no cover
                pass
        out["__packet__"] = trade_block(trade)
        return out

    def settle(self, trade_id: str, pnl: float, risk: float = 0.0,
               pnl_pct: float = 0.0) -> int:
        """A closed trade becomes training rows for every desk that voted on it.

        The label is the outcome, and it is applied *symmetrically*: a desk that
        approved a winner and a desk that refused a loser are both rewarded with
        their own verdict, while the desk that approved a loser is trained on
        its own risk flags as the reason to refuse, and the desk that refused a
        winner is trained on the same objection at half size. Nothing here
        teaches "always approve" or "always refuse".
        """
        rec = self.pending.pop(trade_id, None)
        if rec is None:
            return 0
        if not rec.get("opened"):
            # the desk never took the risk, so there is no outcome to learn from
            return 0
        won = float(pnl or 0.0) > 0
        added = 0
        for v in rec["verdicts"]:
            key = str(v.get("cabin") or "")
            prompt = (rec.get("prompts") or {}).get(key) or ""
            if not prompt:
                continue
            added += self._settle_one(rec, v, prompt, won, pnl, pnl_pct, ceo=False)
        ceo = rec.get("ceo") or {}
        if ceo.get("verdict"):
            prompt = (rec.get("prompts") or {}).get("CEO") or ""
            if prompt:
                added += self._settle_one(rec, ceo, prompt, won, pnl, pnl_pct, ceo=True)
        if added:
            log.info("training: %s settled %s -> %d rows", trade_id,
                     "win" if won else "loss", added)
        return added

    def _settle_one(self, rec: Dict[str, Any], v: Dict[str, Any], prompt: str,
                    won: bool, pnl: float, pnl_pct: float, ceo: bool) -> int:
        key = str(v.get("cabin") or "")
        verdict = str(v.get("verdict") or "").upper()
        if not key or verdict not in ("APPROVE", "REJECT"):
            return 0
        money = f"{pnl:+.2f} ({pnl_pct:+.2f}%)"
        right = (verdict == "APPROVE") == won
        flags = ", ".join(v.get("risk_flags") or []) or "no flag on file"
        if right:
            meta_kind, weight = "settled", 1.0
            target = _verdict_json(v, ceo=ceo)
        elif verdict == "APPROVE":                     # approved a loser
            meta_kind, weight = "reflection", 1.5
            target = _refusal_json(
                v,
                (f"This one closed {money}. My own flags said it — {flags} — and I sized it "
                 f"anyway. Next time on a {rec['strategy']} into the same tape: refuse, or "
                 f"take it at a quarter size with the flag written into the plan."),
                size=0.25, ceo=ceo,
            )
        else:                                          # refused a winner
            meta_kind, weight = "reflection", 1.2
            target = _smaller_yes_json(
                v,
                (f"It closed {money} without me — my objection was {flags}. Right call to "
                 f"flag it, wrong call to make it a veto: the version that pays for the "
                 f"objection is a half-size entry with the flag in the plan."),
                size=0.5, ceo=ceo,
            )
        self._append(self._row(
            key, meta_kind, self._spec(key).system_prompt if self._spec(key) else "",
            prompt, target, weight=weight,
            meta={"trade_id": rec["trade_id"], "symbol": rec["symbol"], "side": rec["side"],
                  "strategy": rec["strategy"], "pnl": round(float(pnl), 2),
                  "pnl_pct": round(float(pnl_pct), 3), "outcome": "win" if won else "loss",
                  "was": verdict, "right": right},
        ))
        return 1

    # ------------------------------------------------------------------
    # 3. what the room taught itself
    # ------------------------------------------------------------------
    def lesson_rows(self, lessons: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Every rule the debate room agreed is a row for all six desks.

        A rule one desk wrote down is a rule the whole table trades by, so it is
        trained into every desk, not just the one that said it.
        """
        lessons = list(lessons or [])
        stamp = (len(lessons), float((lessons[-1] or {}).get("ts") or 0.0) if lessons else 0.0)
        if stamp == self._lesson_cache[0]:
            return self._lesson_cache[1]
        rows: List[Dict[str, Any]] = []
        for lesson in lessons:
            text = str(lesson.get("text") or "").strip()
            topic = str(lesson.get("topic") or "the desk meeting").strip()
            if not text:
                continue
            # the ten seed lessons are already drilled by `curriculum_rows`; the
            # engine hands them over with the room's rules so a fresh session has
            # memory, and they would otherwise be counted (and trained) twice
            if topic == "house curriculum":
                continue
            for key in DESKS:
                spec = self._spec(key)
                if spec is None:
                    continue
                rows.append(self._row(
                    key, "lesson", spec.system_prompt,
                    f"Desk meeting — the room argued: {topic}\n\nWhat did we agree, and how "
                    f"does the {spec.label} desk implement it?",
                    f"{text} On my desk: {self._desk_angle(key, 'lesson')}",
                    weight=0.8,
                    meta={"topic": topic, "round": lesson.get("round")},
                ))
        self._lesson_cache = (stamp, rows)
        return rows

    # ------------------------------------------------------------------
    # assembly
    # ------------------------------------------------------------------
    def _row(self, desk: str, kind: str, system: str, user: str, assistant: str,
             weight: float = 1.0, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ],
            "meta": {"desk": desk, "kind": kind, "weight": weight, **(meta or {})},
        }

    def _append(self, row: Dict[str, Any]) -> None:
        desk = row["meta"]["desk"]
        self.counts[desk] = self.counts.get(desk, 0) + 1
        self.samples.append(row)
        if len(self.samples) > MAX_SAMPLES:
            self.samples = self.samples[-MAX_SAMPLES:]

    def rows(self, lessons: Optional[Iterable[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Everything the desks should be trained on, curriculum first."""
        return self.curriculum_rows() + self.lesson_rows(lessons or []) + list(self.samples)

    def build(self, path: Optional[str] = None,
              lessons: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Write the dataset as chat JSONL and return the manifest."""
        rows = self.rows(lessons)
        target = Path(path) if path else self.dataset_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        per_desk: Dict[str, int] = {}
        per_kind: Dict[str, int] = {}
        for row in rows:
            per_desk[row["meta"]["desk"]] = per_desk.get(row["meta"]["desk"], 0) + 1
            per_kind[row["meta"]["kind"]] = per_kind.get(row["meta"]["kind"], 0) + 1
        self.built_at = time.time()
        self.last_manifest = {
            "path": str(target), "rows": len(rows), "desks": per_desk, "kinds": per_kind,
            "settled_trades": sum(1 for r in rows if r["meta"]["kind"] in ("settled", "reflection")),
            "generated_at": self.built_at,
        }
        log.info("training: wrote %d rows to %s (%s)", len(rows), target, per_kind)
        return self.last_manifest

    # ------------------------------------------------------------------
    # adapters: what the trainer left behind
    # ------------------------------------------------------------------
    def adapter_for(self, key: str) -> Optional[str]:
        """The LoRA adapter directory for this desk, if one has been trained."""
        path = self.adapters_dir / key.upper()
        return str(path) if (path / "adapter_config.json").exists() else None

    def adapters(self) -> Dict[str, Any]:
        manifest = self.adapters_dir / "manifest.json"
        data: Dict[str, Any] = {"dir": str(self.adapters_dir), "trained": {},
                                "manifest": str(manifest) if manifest.exists() else None}
        for key in DESKS:
            path = self.adapter_for(key)
            if path:
                data["trained"][key] = path
        if manifest.exists():
            try:
                man = json.loads(manifest.read_text())
                # The manifest says what the trainer did; the filesystem says what
                # is loadable right now. Disk wins on the union, or a manifest
                # written by an earlier no-op run would hide a real adapter.
                trained = dict(man.get("trained") or {})
                trained.update(data["trained"])
                man["trained"] = trained
                man["trained_now"] = bool(trained)
                data.update(man)
            except Exception:                               # pragma: no cover
                pass
        return data

    def stats(self, lessons: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """What the panel shows: rows per desk, and whether an adapter exists."""
        seed = len(self.curriculum_rows())
        lesson_rows = len(self.lesson_rows(lessons or []))
        adapters = self.adapters()
        trained = adapters.get("trained") or {}
        per_desk: Dict[str, Dict[str, Any]] = {}
        for key in DESKS:
            settled = sum(1 for r in self.samples if r["meta"]["desk"] == key)
            per_desk[key] = {
                "curriculum": seed // max(1, len(DESKS)),
                "lessons": lesson_rows // max(1, len(DESKS)),
                "settled": settled,
                "rows": seed // max(1, len(DESKS)) + lesson_rows // max(1, len(DESKS)) + settled,
                "adapter": trained.get(key),
                "trained_at": (adapters.get("finished_at") if trained.get(key) else None),
            }
        return {
            "enabled": True,
            "dataset": str(self.dataset_path),
            "rows": seed + lesson_rows + len(self.samples),
            "curriculum_rows": seed,
            "lesson_rows": lesson_rows,
            "settled_rows": len(self.samples),
            "waiting": len(self.pending),
            "built_at": self.built_at or None,
            "last_manifest": self.last_manifest,
            "adapters_dir": str(self.adapters_dir),
            "adapters": trained,
            "desks": per_desk,
            "trained_now": bool(adapters.get("trained") or trained),
        }


def _playbook_rules() -> List[str]:
    """The numbered rules of the house playbook, as standalone sentences."""
    rules: List[str] = []
    for line in HOUSE_RULES.splitlines():
        line = line.strip()
        if line and line[0].isdigit() and "." in line[:3]:
            rules.append(line.split(".", 1)[1].strip())
    return rules
