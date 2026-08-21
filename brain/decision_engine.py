"""
Decision engine — the single entry point the agent uses to "ask Qwen".

    engine = DecisionEngine()
    qualification = engine.qualify(evidence_dict)

Whatever backend is active, the result is always a validated
brain.schemas.Qualification. Contact fields never pass through the model.
"""

import logging

from brain.prompts import SYSTEM_PROMPT, build_qualification_prompt
from brain.qwen import get_brain
from brain.schemas import Qualification, validate_qualification

log = logging.getLogger("brain.decision")


class DecisionEngine:
    def __init__(self, brain=None):
        self.brain = brain or get_brain()

    def qualify(self, evidence: dict) -> Qualification:
        """Feed evidence to the brain, get a validated qualification back."""
        prompt = build_qualification_prompt(self._strip_contacts(evidence))
        # Keep a boolean map of which contacts exist (for scoring),
        # but never the raw values.
        try:
            raw = self.brain.generate_json(SYSTEM_PROMPT, prompt)
        except Exception as exc:
            log.error("Brain call failed: %s", exc)
            raw = {}
        return validate_qualification(raw)

    @staticmethod
    def _strip_contacts(evidence: dict) -> dict:
        """
        Replace raw contact values with presence booleans before the evidence
        reaches the LLM. The model can reason 'a public phone exists' but can
        never see (or regurgitate/mutate) the actual number.
        """
        ev = dict(evidence)
        contacts = ev.pop("contacts", None) or {}
        ev["contacts_found"] = {
            key: bool(value) for key, value in contacts.items()
        }
        return ev
