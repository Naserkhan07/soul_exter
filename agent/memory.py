"""
Session memory — light in-RAM state for the current run.
Long-term memory lives in SQLite (leads + seen_candidates).
"""

from collections import Counter
from datetime import datetime, timezone


class Memory:
    def __init__(self):
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.counters = Counter()
        self.recent_events = []            # rolling window of what happened

    def record(self, event: str, detail: str = "") -> None:
        self.counters[event] += 1
        self.recent_events.append(
            {"time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
             "event": event, "detail": detail})
        if len(self.recent_events) > 200:
            self.recent_events = self.recent_events[-100:]

    def summary(self) -> dict:
        return {
            "started_at": self.started_at,
            **dict(self.counters),
        }
