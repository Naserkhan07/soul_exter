"""Safety Rules / guardrails.

A lightweight post-processing layer that checks the model's reply against
hard rules and strips obviously off-limits content. The real enforcement is
in the system prompt; this is a defensive second layer for local/mock models.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("agent.rules")

# Phrases that indicate the model is trying to do something it shouldn't.
_BLOCKLIST = [
    re.compile(r"i\s+am\s+a\s+human", re.I),
    re.compile(r"system\s*(prompt|instructions)", re.I),
]


class SafetyRules:
    def __init__(self, strict: bool = True):
        self.strict = strict

    def check(self, text: str) -> str:
        """Return the text, possibly modified/blanked if it breaks a rule."""
        if not text:
            return text
        for pat in _BLOCKLIST:
            if pat.search(text):
                log.warning("Blocked reply matching safety rule: %r", pat.pattern)
                return "I'm sorry, I can't answer that."
        return text

    @staticmethod
    def validate_profile(profile) -> list[str]:
        """Check a task profile is well-formed; return list of warnings."""
        warnings = []
        if not profile.instructions:
            warnings.append("instructions.txt is empty — the agent has no task.")
        if not profile.knowledge:
            warnings.append("knowledge/ is empty — the agent may not know what you do/provide.")
        return warnings
