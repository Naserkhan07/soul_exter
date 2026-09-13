"""A tiny async pub/sub bus.

The engine publishes events; the websocket handler forwards them to the
browser. A bounded ring buffer keeps the last N events so a page that
connects late can still paint the recent history.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Deque, Dict, List, Set


class EventBus:
    def __init__(self, history: int = 400) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._history: Deque[Dict[str, Any]] = deque(maxlen=history)
        self._lock = asyncio.Lock()

    # ---- pub ----------------------------------------------------------
    async def publish(self, kind: str, **payload: Any) -> Dict[str, Any]:
        event = {"type": kind, "ts": time.time(), "payload": payload}
        self._history.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # slow client: drop the oldest event rather than stalling the desk
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass
        return event

    # ---- sub ----------------------------------------------------------
    def subscribe(self, maxsize: int = 600) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def recent(self, limit: int = 120) -> List[Dict[str, Any]]:
        items = list(self._history)
        return items[-limit:]

    def replayable(self, kinds: Set[str]) -> List[Dict[str, Any]]:
        return [e for e in self._history if e["type"] in kinds]
