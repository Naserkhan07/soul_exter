"""Conversation controller.

The "agent controller" from the spec. It owns the conversation loop:

    Pipeline A — Speech-to-Speech (STS, one model):
        person audio -> (understood text, reply audio) -> remember
    Pipeline B — three-stage:
        text_in (from STT or text mode)
            -> detect language
            -> ask LLM (system prompt = task profile + memory + rules)
            -> safety check
            -> text_out to TTS
            -> remember

It is phone-agnostic: the same controller is used with a microphone, a phone
bridge, or a plain terminal (text mode) for testing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from models.base import STTBase, LLMBase, TTSBase, STSBase, LLMRequest
from .memory import ConversationMemory
from .rules import SafetyRules
from .task import TaskProfile
from .lead import Lead

log = logging.getLogger("agent.controller")


@dataclass
class ControllerConfig:
    language: str = "auto"
    fallback_language: str = "en"
    max_turns: int = 1000
    reply_style: str = "conversational"
    max_context_turns: int = 12
    summarize_after: int = 30
    persist: bool = True


class Controller:
    def __init__(self, task: TaskProfile, stt: STTBase | None = None,
                 llm: LLMBase | None = None, tts: TTSBase | None = None,
                 sts: STSBase | None = None,
                 cfg: ControllerConfig | None = None, data_dir=None):
        self.task = task
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.sts = sts
        self.cfg = cfg or ControllerConfig()
        self.rules = SafetyRules()
        self.lead = Lead()
        self.memory = ConversationMemory(
            max_context_turns=self.cfg.max_context_turns,
            summarize_after=self.cfg.summarize_after,
            persist=self.cfg.persist,
            data_dir=data_dir,
        )

    # ---------------- call lifecycle ----------------
    def start_call(self) -> str:
        """Begin a new conversation; returns the agent's opening line (if any)."""
        self.memory.start()
        warnings = SafetyRules.validate_profile(self.task)
        for w in warnings:
            log.warning("Task profile warning: %s", w)
        opening = self.task.opening.strip()
        if opening:
            self.memory.add("assistant", opening)
        return opening

    def end_call(self) -> None:
        self.memory.add("system", "[call ended]")
        log.info("Call ended after %d turns.",
                 len([t for t in self.memory.turns if t['role'] in ('user', 'assistant')]))

    # ---------------- core: one utterance in, one reply out ----
    def handle_utterance(self, text: str) -> str:
        """Pipeline B: process one person utterance -> the agent's reply text."""
        text = (text or "").strip()
        if not text:
            return ""
        lang = self._detect_language(text)
        self.memory.add("user", text, lang)
        self.update_lead(text)

        system = self.task.system_prompt()
        req = LLMRequest(
            system=system,
            messages=self.memory.context_lines(),
            language=lang if self.cfg.language == "auto" else self.cfg.language,
            max_tokens=300,
        )
        reply = self.llm.complete(req)
        reply = self.rules.check(reply).strip()

        if not reply:
            reply = "I'm sorry, I didn't catch that. Could you say it again?"
        self.memory.add("assistant", reply, lang)
        return reply

    def handle_audio(self, audio_bytes: bytes) -> bytes:
        """Pipeline A (STS): send person audio, get the agent's reply audio."""
        if self.sts is None:
            raise RuntimeError("No Speech-to-Speech model configured (sts.*).")
        system = self.task.system_prompt()
        result = self.sts.converse(audio_bytes, system, self.memory.context_lines())
        text_in = (result.text or "").strip()
        if text_in:
            self.memory.add("user", text_in, result.language)
            self.update_lead(text_in)
        reply_text = (result.reply_text or result.text or "").strip()
        if reply_text or result.audio:
            self.memory.add("assistant", reply_text or "[spoken reply]", result.language)
        return result.audio

    def update_lead(self, text: str) -> list[str]:
        """Scan person speech for lead info; return new milestone messages."""
        changes = self.lead.update(text)
        for c in changes:
            log.info("LEAD: %s", c)
        return changes

    def speak(self, reply: str, out_path=None) -> bytes:
        """Synthesize speech for a reply (Pipeline B). Returns audio bytes."""
        lang = self._detect_language(reply)
        return self.tts.synthesize(reply, language=lang, out_path=out_path)

    # ---------------- helpers ----------------
    def _detect_language(self, text: str) -> str:
        if self.cfg.language != "auto":
            return self.cfg.language
        from models.llm.mock_llm import detect_language
        return detect_language(text)

    def transcript(self) -> str:
        return self.memory.transcript()

    def turn_count(self) -> int:
        return len(self.memory.turns)

    # convenience passthrough for mock STT/STS in text mode
    @property
    def mock_stt(self):
        return self.stt if self.stt and getattr(self.stt, "name", "") == "mock" else None

    @property
    def mock_sts(self):
        return self.sts if self.sts and getattr(self.sts, "name", "") == "mock" else None
