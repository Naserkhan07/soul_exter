"""Conversation Memory.

Stores the ongoing conversation as a list of turns. The controller sends the
most recent N turns to the model so it can reference earlier parts of the call
("What did I say my name was?" → "You said your name was Ahmed.").

Design is intentionally simple (JSON list) for v1 — no vector DB needed.
Every call is also persisted to data/conversations/<call_id>.jsonl.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .task import TaskProfile


@dataclass
class ConversationMemory:
    max_context_turns: int = 12
    summarize_after: int = 30
    persist: bool = True
    data_dir: Path | None = None
    call_id: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S"))
    turns: list[dict] = field(default_factory=list)
    _summary: str = ""

    def start(self) -> None:
        self.call_id = time.strftime("%Y%m%d-%H%M%S")
        self.turns = []
        self._summary = ""
        if self.persist and self.data_dir is not None:
            self.data_dir.mkdir(parents=True, exist_ok=True)

    def add(self, role: str, text: str, lang: str = "") -> None:
        self.turns.append({
            "role": role,             # "user" | "assistant" | "system"
            "text": text,
            "lang": lang,
            "ts": time.time(),
        })
        if self.persist and self.data_dir is not None:
            self._append_to_disk({"role": role, "text": text, "lang": lang})

    # ---------------- prompt construction ----------------
    def context_lines(self) -> list[dict]:
        """Most recent turns, oldest first, as OpenAI-style messages."""
        recent = self.turns[-self.max_context_turns:]
        msgs = []
        for t in recent:
            msgs.append({"role": t["role"], "content": t["text"]})
        return msgs

    def transcript(self) -> str:
        lines = []
        for t in self.turns:
            who = "Person" if t["role"] == "user" else "Agent"
            lines.append(f"{who}: {t['text']}")
        return "\n".join(lines)

    # ---------------- disk persistence ----------------
    def _append_to_disk(self, entry: dict) -> None:
        try:
            with (self.data_dir / f"{self.call_id}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:  # pragma: no cover
            print(f"[memory] could not persist turn: {e}")

    def save_summary(self, summary: str) -> None:
        self._summary = summary
        if self.persist:
            p = self.data_dir / f"{self.call_id}.summary.txt"
            p.write_text(summary, encoding="utf-8")
