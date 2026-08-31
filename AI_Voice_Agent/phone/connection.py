"""Connection / consent helpers for phone calls.

Handles the side concerns of a real call: recording consent reminder, session
state, and hanging up cleanly. Telephony laws differ by country — verify
consent/recording/AI-disclosure rules for your jurisdiction before using this
with the public phone network.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("phone.connection")


@dataclass
class CallSession:
    call_id: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S"))
    started: float = field(default_factory=time.time)
    status: str = "idle"          # idle | active | ended
    consent_notified: bool = False

    def mark_consent(self) -> None:
        self.consent_notified = True

    def end(self) -> None:
        self.status = "ended"


def consent_reminder(language: str = "en") -> str:
    """First message the agent says on a call (adjust per local law)."""
    return ("This call is with an AI assistant and may be recorded for "
            "quality purposes. Is now a good time to talk?")
