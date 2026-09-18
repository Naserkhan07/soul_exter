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
from .correlation import RHO_STRONG, Z_TRIGGER, BREAK_TRIGGER, CorrelationMonitor
from .features import (Ticker, build_signal_levels, compute_metrics, encode_glomeruli,
                       strategy_bias, trend_composite)
from .flybrain import FlyAgent, FlyBrain
from .microstructure import MicroMonitor


class FlyScanner:
    """Round-robin scanner. Returns at most one strike per symbol per cooldown."""

    def __init__(self, feed: MarketFeed, brain: FlyBrain, strike_score: float = 0.62,
                 cooldown_s: float = 45.0, per_tick: int = 10,
                 global_cooldown_s: float = 11.0, min_efficiency: float = 0.32,
                 min_trend: float = 0.30, sl_atr: float = 1.00, tp_atr: float = 2.20,
                 corr: Optional[CorrelationMonitor] = None, micro: Optional[MicroMonitor] = None,
                 open_provider=None, corr_overlap_max: float = 0.85,
                 use_correlation: bool = True) -> None:
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
        self.corr = corr
        self.micro = micro
        self.open_provider = open_provider
        self.corr_overlap_max = corr_overlap_max
        self.use_correlation = use_correlation
        self.next_strike_ok = 0.0
        self.funnel = dict(scans=0, strikes=0, cooldown=0, score=0, cost=0, rr=0, no_trend=0,
                           emitted=0, capped=0, corr_overlap=0, corr_watch=0,
                           corr_emitted=0, book_ctx=0)
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
        if self.micro is not None:
            micro = self.micro.read(symbol, t)
            for key in ("book_pressure", "book_tilt", "ofi", "aggressor", "amihud",
                        "roll_spread", "live_spread_bps"):
                metrics[key] = micro.get(key, 0.0)
            if micro.get("has_book"):
                self.funnel["book_ctx"] += 1
        if self.corr is not None and self.use_correlation:
            for key, val in self.corr.features_for(symbol).items():
                if key != "peer":
                    metrics[key] = val
                else:
                    metrics["corr_peer"] = val
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

        if self._correlated_with_open(symbol, direction):
            self.funnel["corr_overlap"] += 1
            return None

        watch = self.watchers.pop(symbol, None)
        ags = np.asarray(glomeruli)
        signal = Signal(
            symbol=symbol, asset_class=UNIVERSE[symbol].asset_class, direction=direction,
            score=float(decision["score"]), entry=float(levels["entry"]),
            stop_loss=float(levels["stop_loss"]), take_profit=float(levels["take_profit"]),
            atr=float(metrics["atr"]), horizon=horizon_for(UNIVERSE[symbol], metrics["atr_pct"]),
            features={k: round(float(v), 6) for k, v in metrics.items()
                      if isinstance(v, (int, float)) and not isinstance(v, bool)},
            neural=dict(brain=decision, stimulus=parts,
                        peer=metrics.get("corr_peer", ""),
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

    # ------------------------------------------------- correlation setups ----
    def _correlated_with_open(self, symbol: str, direction: str) -> bool:
        """Portfolio gate: do not stack fresh risk on a pair already moving the
        floor the same way — correlated tickets are one ticket in disguise."""
        if self.open_provider is None or self.corr is None:
            return False
        try:
            opens = self.open_provider() or []
        except Exception:
            return False
        for sym, direc in opens:
            if sym == symbol or direc != direction:
                continue
            if abs(self.corr.rho_between(symbol, sym)) >= self.corr_overlap_max:
                return True
        return False

    def _base_gates_pass(self, symbol: str, metrics: Dict[str, float],
                         levels: Dict[str, float]) -> bool:
        spread = float(UNIVERSE[symbol].spread)
        spread_ratio = spread / max(metrics["price"], 1e-9)
        if metrics["atr_pct"] <= 0 or spread_ratio * 26.0 > 1.6:
            self.funnel["cost"] += 1
            return False
        risk = abs(levels["entry"] - levels["stop_loss"])
        reward = abs(levels["take_profit"] - levels["entry"])
        if risk <= 0 or reward / risk < 1.6:
            self.funnel["rr"] += 1
            return False
        return True

    def evaluate_correlation(self, symbol: str, now: Optional[float] = None) -> Optional[Signal]:
        """Two extra finders built on the live correlation table.

        bloc_lag   : a pair that usually tracks its strongest peer has lagged
                     it by >= Z_TRIGGER residual sigmas — convergence trade
                     back toward the bloc.
        corr_break : the pair's short-window correlation to its peer has
                     broken from its long-run regime — trade the new
                     idiosyncratic direction once the tape confirms it.
        """
        if self.corr is None or not self.use_correlation:
            return None
        now = now or time.time()
        t = self.feed.tickers.get(symbol)
        if t is None or not t.ready(70):
            return None
        feat = self.corr.features_for(symbol)
        peer = feat.get("peer", "")
        if not peer:
            return None
        rho = float(feat.get("corr_bloc", 0.0))
        resid_z = float(feat.get("resid_z", 0.0))
        cbreak = float(feat.get("corr_break", 0.0))
        if abs(rho) < RHO_STRONG:
            return None
        self.funnel["corr_watch"] += 1

        direction, source, score, metrics = "", "", 0.0, None
        peer_dir = float(feat.get("peer_dir", 0.0))
        if abs(resid_z) >= Z_TRIGGER:
            direction = "long" if resid_z < 0 else "short"
            source = "bloc_lag"
            score = 0.30 * min(abs(resid_z) / 3.0, 1.0) + 0.40 * abs(rho) \
                    + 0.30 * float(np.clip(abs(peer_dir), 0.0, 1.0))
        elif cbreak >= BREAK_TRIGGER:
            metrics = compute_metrics(t)
            if metrics is None:
                return None
            tc = trend_composite(metrics)
            if abs(tc) < self.min_trend:
                return None
            direction = "long" if tc > 0 else "short"
            source = "corr_break"
            score = 0.35 * min(cbreak / 0.8, 1.0) + 0.35 * min(abs(tc) / 0.8, 1.0) \
                    + 0.30 * float(metrics.get("efficiency", 0.0))
        else:
            return None
        if score < self.strike_score:
            self.funnel["score"] += 1
            return None
        if self.agent.cooling(symbol, now) or now < self.next_strike_ok:
            self.funnel["cooldown"] += 1
            return None
        if metrics is None:
            metrics = compute_metrics(t)
        if metrics is None:
            return None
        levels = build_signal_levels(metrics, direction, sl_atr=self.sl_atr, tp_atr=self.tp_atr)
        if not self._base_gates_pass(symbol, metrics, levels):
            return None
        if self._correlated_with_open(symbol, direction):
            self.funnel["corr_overlap"] += 1
            return None

        self.next_strike_ok = now + self.global_cooldown_s
        self.agent.note_strike(symbol, now, cooldown_s=self.cooldown_s)
        self.funnel["corr_emitted"] += 1
        self.funnel["emitted"] += 1
        feats = {k: (round(float(v), 6) if isinstance(v, (int, float)) else v)
                 for k, v in metrics.items()}
        feats.update({k: (round(float(v), 6) if isinstance(v, (int, float)) else v)
                      for k, v in feat.items() if k != "peer"})
        return Signal(
            symbol=symbol, asset_class=UNIVERSE[symbol].asset_class, direction=direction,
            score=float(np.clip(score, 0.0, 1.0)), entry=float(levels["entry"]),
            stop_loss=float(levels["stop_loss"]), take_profit=float(levels["take_profit"]),
            atr=float(metrics["atr"]), horizon=horizon_for(UNIVERSE[symbol], metrics["atr_pct"]),
            features=feats,
            neural=dict(source=source, peer=peer, rho=round(rho, 3), resid_z=resid_z,
                        corr_break=cbreak,
                        brain=dict(state="CORR_STRIKE", score=round(float(score), 4)),
                        stimulus=dict(kind=source)),
        )

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
        snap = dict(agent=self.agent.snapshot(), funnel=self.funnel, recent=list(self.recent_scans)[-40:],
                    signals=list(self.signal_log),
                    next_strike_in=max(0.0, round(self.next_strike_ok - time.time(), 2)),
                    watchers=[dict(symbol=s, since=round(w["created"], 1)) for s, w in
                              list(self.watchers.items())[-12:]])
        if self.corr is not None:
            snap["correlation"] = self.corr.snapshot()
        if self.micro is not None:
            snap["microstructure"] = self.micro.snapshot()
        return snap
