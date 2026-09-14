"""Council playbook — the floor's institutional memory.

Every finalised trade writes into it, and the debate chamber writes lessons into
it. Judges then read it back: historical hit-rate for the bucket, tail-event
counts and an expectancy tilt. This is what makes later hearings differ from
earlier ones (the council genuinely adapts inside a session).
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..agents.schemas import Signal


def session_bucket(hour: float) -> str:
    if 0 <= hour < 6:
        return "asia"
    if 6 <= hour < 13:
        return "london"
    if 13 <= hour < 17:
        return "ny_overlap"
    return "late_us"


@dataclass
class Bucket:
    key: str
    wins: int = 0
    losses: int = 0
    pnl_r: float = 0.0
    vetoes: int = 0

    @property
    def sample(self) -> int:
        return self.wins + self.losses

    @property
    def hit_rate(self) -> Optional[float]:
        return (self.wins / self.sample) if self.sample >= 3 else None


class Playbook:
    def __init__(self) -> None:
        self.buckets: Dict[str, Bucket] = {}
        self.lessons: List[dict] = []
        self.tail_events: Dict[str, int] = defaultdict(int)
        self.expectancy_adj = 0.0
        self.macro_tilt = 0.0
        self.rejected_r: Dict[str, float] = defaultdict(float)

    def bucket_key(self, signal_like: dict) -> str:
        cls = signal_like.get("asset_class", "?")
        hour = float(signal_like.get("features", {}).get("hour", 12.0))
        return f"{cls}|{session_bucket(hour)}"

    def lookup(self, signal: Signal) -> dict:
        key = self.bucket_key(dict(asset_class=signal.asset_class,
                                   features={"hour": signal.features.get("hour", 12.0)}))
        b = self.buckets.get(key)
        return dict(key=key, hit_rate=(b.hit_rate if b else None), sample=(b.sample if b else 0),
                    expectancy_adj=self.expectancy_adj, macro_tilt=self.macro_tilt,
                    tail_events=self.tail_events.get(signal.asset_class, 0), source="council")

    def record(self, signal: Signal, accepted: bool, pnl_r: float, note: str = "") -> dict:
        key = self.bucket_key(dict(asset_class=signal.asset_class, features=signal.features))
        b = self.buckets.setdefault(key, Bucket(key=key))
        if accepted:
            if pnl_r >= 0:
                b.wins += 1
            else:
                b.losses += 1
            b.pnl_r += pnl_r
            self.expectancy_adj = max(-0.35, min(0.35, self.expectancy_adj * 0.94 + pnl_r * 0.05))
            if pnl_r <= -0.9:
                self.tail_events[signal.asset_class] += 1
        else:
            b.vetoes += 1
            # counterfactual tracking: what we would have made had we passed
            self.rejected_r[key] += pnl_r
        return dict(key=key, hit_rate=b.hit_rate, sample=b.sample, pnl_r=round(b.pnl_r, 2))

    def add_lesson(self, text: str, tags: Optional[List[str]] = None, source: str = "debate") -> dict:
        lesson = dict(id=f"L{len(self.lessons)+1:03d}", ts=time.time(), text=text,
                      tags=tags or [], source=source)
        self.lessons.append(lesson)
        self.lessons = self.lessons[-120:]
        return lesson

    def best_buckets(self, n: int = 4) -> List[dict]:
        rows = [b for b in self.buckets.values() if b.sample >= 3]
        rows.sort(key=lambda b: (b.hit_rate or 0) * b.sample, reverse=True)
        return [dict(key=b.key, hit_rate=round(b.hit_rate or 0, 3), sample=b.sample,
                     pnl_r=round(b.pnl_r, 2)) for b in rows[:n]]

    def worst_buckets(self, n: int = 4) -> List[dict]:
        rows = [b for b in self.buckets.values() if b.sample >= 3]
        rows.sort(key=lambda b: (b.hit_rate or 0) * b.sample)
        return [dict(key=b.key, hit_rate=round(b.hit_rate or 0, 3), sample=b.sample,
                     pnl_r=round(b.pnl_r, 2)) for b in rows[:n]]

    def snapshot(self) -> dict:
        return dict(buckets=[dict(key=b.key, wins=b.wins, losses=b.losses, vetoes=b.vetoes,
                                  pnl_r=round(b.pnl_r, 2), hit_rate=(round(b.hit_rate, 3)
                                                                      if b.hit_rate is not None else None),
                                  sample=b.sample)
                             for b in sorted(self.buckets.values(), key=lambda x: -x.sample)],
                    lessons=self.lessons[-40:], expectancy_adj=round(self.expectancy_adj, 4),
                    macro_tilt=round(self.macro_tilt, 4),
                    tail_events=dict(self.tail_events))
