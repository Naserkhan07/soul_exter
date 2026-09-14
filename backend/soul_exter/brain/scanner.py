"""The hunt: a rotating scan of the enabled universe that gates signals through
the fly brain. Only instruments where the descending neurons fire become trades.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from ..agents.schemas import Signal
from ..market.feed import MarketFeed
from ..market.universe import UNIVERSE, horizon_for
from .features import (Ticker, build_signal_levels, compute_metrics, encode_glomeruli,
                       strategy_bias, trend_composite)
from .flybrain import FlyAgent, FlyBrain


class FlyScanner:
    """Round-robin scanner. Returns at most one strike per symbol per cooldown."""

    def __init__(self, feed: MarketFeed, brain: FlyBrain, strike_score: float = 0.62,
                 cooldown_s: float = 45.0, per_tick: int = 10,
                 global_cooldown_s: float = 11.0, min_efficiency: float = 0.32,
                 min_trend: float = 0.30, sl_atr: float = 1.00, tp_atr: float = 2.20) -> None:
        self.feed = feed
        self.brain = brain
        self.agent = FlyAgent(brain=brain)
        self.strike_score = strike_score
        self.cooldown_s = cooldown_s
        self.per_tick = per_tick
        self.global_cooldown_s = global_cooldown_s
        self.min_efficiency = min_efficiency
        self.min_trend = min_trend
        self.sl_atr = sl_atr
        self.tp_atr = tp_atr
        self.next_strike_ok = 0.0
        self.funnel = dict(scans=0, strikes=0, cooldown=0, score=0, cost=0, rr=0, no_trend=0,
                           emitted=0, capped=0)
        self.cursor = 0
        self.watchers: Dict[str, dict] = {}
        self.recent_scans: Deque[dict] = deque(maxlen=180)
        self.signal_log: Deque[dict] = deque(maxlen=60)

    # ------------------------------------------------------------------ scan
    def scan(self, enabled: List[str], now: Optional[float] = None,
             budget: Optional[int] = None) -> List[Signal]:
        now = now or time.time()
        if not enabled:
            return []
        budget = budget or self.per_tick
        n = len(enabled)
        signals: List[Signal] = []
        for k in range(min(budget, n)):
            sym = enabled[(self.cursor + k) % n]
            sig = self.evaluate(sym, now)
            if sig is not None:
                signals.append(sig)
        self.cursor = (self.cursor + budget) % n
        return signals

    def evaluate(self, symbol: str, now: Optional[float] = None) -> Optional[Signal]:
        now = now or time.time()
        t = self.feed.tickers.get(symbol)
        if t is None or not t.ready(70):
            return None
        self.agent.symbol = symbol
        metrics = compute_metrics(t)
        if metrics is None:
            return None
        spread = float(UNIVERSE[symbol].spread)
        metrics["spread_ratio"] = float(spread / max(metrics["price"], 1e-9))
        glomeruli = encode_glomeruli(metrics, spread)
        bias, parts = strategy_bias(metrics)
        decision = self.brain.decide(glomeruli, bias, metrics["atr_pct"], metrics["spread_ratio"])
        # the desk only bids *with* a directional tape: an efficient trend is the
        # one structure that paid on every tape we calibrated against.
        trend_comp = trend_composite(metrics)
        decided_dir = "long" if trend_comp >= 0 else "short"
        decision["direction"] = decided_dir
        decision["trend_composite"] = round(trend_comp, 4)
        decision["bias"] = parts["composite"]

        self.agent.state = str(decision["state"])
        self.recent_scans.append(dict(ts=now, symbol=symbol, state=decision["state"],
                                      score=decision["score"], direction=decision["direction"],
                                      bias=parts["composite"], atr_pct=round(metrics["atr_pct"], 5)))

        self.funnel["scans"] += 1
        if decision["state"] == "WAIT_FOR_SETUP":
            self.funnel["waits"] = self.funnel.get("waits", 0) + 1
        cooling = self.agent.cooling(symbol, now) or now < self.next_strike_ok
        attrs = dict(pair=symbol, direction=decision["direction"], score=decision["score"],
                     confidence=decision["confidence"], bias=parts["composite"],
                     state=decision["state"], rsi=round(metrics["rsi"], 2),
                     atr_pct=round(metrics["atr_pct"], 5), atr_rank=round(metrics["atr_rank"], 3),
                     efficiency=round(metrics["efficiency"], 3), vol_z=round(metrics["vol_z"], 2),
                     session=round(metrics["session"], 2), hour=round(metrics["hour"], 1))
        if decision["state"] == "WAIT_FOR_SETUP" and not cooling:
            self.watchers[symbol] = dict(created=now, last=attrs)
            return None
        if decision["state"] != "STRIKE":
            return None
        self.funnel["strikes"] += 1
        if cooling:
            self.funnel["cooldown"] += 1
            return None
        if float(decision["score"]) < self.strike_score:
            self.funnel["score"] += 1
            return None
        if metrics["atr_pct"] <= 0 or metrics["spread_ratio"] * 26.0 > 1.6:
            self.funnel["cost"] += 1
            return None
        if metrics["efficiency"] < self.min_efficiency or abs(trend_comp) < self.min_trend:
            self.funnel["no_trend"] = self.funnel.get("no_trend", 0) + 1
            return None

        direction = str(decision["direction"])
        levels = build_signal_levels(metrics, direction, sl_atr=self.sl_atr, tp_atr=self.tp_atr)
        risk = abs(levels["entry"] - levels["stop_loss"])
        reward = abs(levels["take_profit"] - levels["entry"])
        if risk <= 0 or reward / risk < 1.6:
            self.funnel["rr"] += 1
            return None

        watch = self.watchers.pop(symbol, None)
        ags = np.asarray(glomeruli)
        signal = Signal(
            symbol=symbol, asset_class=UNIVERSE[symbol].asset_class, direction=direction,
            score=float(decision["score"]), entry=float(levels["entry"]),
            stop_loss=float(levels["stop_loss"]), take_profit=float(levels["take_profit"]),
            atr=float(metrics["atr"]), horizon=horizon_for(UNIVERSE[symbol], metrics["atr_pct"]),
            features={k: round(float(v), 6) for k, v in metrics.items()},
            neural=dict(brain=decision, stimulus=parts,
                        watched_since=(watch or {}).get("created"),
                        glomeruli=[round(float(x), 4) for x in ags]),
        )
        self.agent.inspected.append(symbol)
        self.agent.note_strike(symbol, now, cooldown_s=self.cooldown_s)
        self.next_strike_ok = now + self.global_cooldown_s
        self.agent.stats = dict(strikes=self.brain.strikes, score=decision["score"],
                                heading=decision["heading"], dopamine=self.brain.dopamine)
        self.signal_log.append(dict(ts=now, symbol=symbol, direction=direction,
                                    score=round(float(decision["score"]), 3),
                                    entry=round(float(levels["entry"]), 6)))
        self.funnel["emitted"] += 1
        return signal

    # ------------------------------------------------------------- behaviour
    def wander(self, dt: float, loop: List[Tuple[float, float, float]], nav=None) -> None:
        """Move the fly along its patrol loop (figure-of-eight over the pit)."""
        self.agent.strike_flash = max(0.0, self.agent.strike_flash - dt * 0.8)
        if not loop:
            return
        self.agent.stats.setdefault("loop_pos", 0.0)  # type: ignore[union-attr]
        p = float(self.agent.stats["loop_pos"])  # type: ignore[index]
        speed = 0.42 if self.agent.state == "ROAM" else 0.95
        p = (p + dt * speed) % 1.0
        idx = p * len(loop)
        i0 = int(idx) % len(loop)
        i1 = (i0 + 1) % len(loop)
        f = idx - int(idx)
        a, b = loop[i0], loop[i1]
        x = a[0] + (b[0] - a[0]) * f
        y = a[2] + (b[2] - a[2]) * f
        z = a[1] + (b[1] - a[1]) * f
        # gentle bobbing so the flight reads as alive
        y += 0.18 * math.sin(time.time() * 2.4)
        prev = self.agent.pos
        self.agent.pos = dict(x=round(x, 3), y=round(y, 3), z=round(z, 3))
        self.agent.yaw = math.atan2(x - prev["x"], z - prev["z"]) if (x != prev["x"] or z != prev["z"]) else self.agent.yaw
        self.agent.stats["loop_pos"] = p  # type: ignore[index]
        self.agent.stats["inspected"] = len(self.agent.inspected)  # type: ignore[index]

    def snapshot(self) -> dict:
        return dict(agent=self.agent.snapshot(), funnel=self.funnel, recent=list(self.recent_scans)[-40:],
                    signals=list(self.signal_log),
                    next_strike_in=max(0.0, round(self.next_strike_ok - time.time(), 2)),
                    watchers=[dict(symbol=s, since=round(w["created"], 1)) for s, w in
                              list(self.watchers.items())[-12:]])
