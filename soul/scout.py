"""The trade scout: a fly brain that decides what is worth the council's time.

The council is expensive. Five LLM cabins plus a CEO, several seconds each, on
every candidate the scanner produces, is a lot of GPU for setups that are
obviously going nowhere. Real trading desks solve this the same way animals do:
a fast, cheap, pre-attentive system decides what deserves the slow deliberative
system's attention.

So the pipeline is:

    live market -> scanner (finds setups) -> SCOUT (fly brain) -> council -> desk

The scout is a FlyWire-inspired spiking network (``soul/flybrain.py``). It reads
the same feature block the cabins get, expresses it in the frame of the setup
being proposed ("is this tape for me or against me?"), and answers CONFIRM,
CONTRADICT or WAIT. Only candidates it confirms reach the council — and they
reach it through the front of the building, walking in past the welcome door.

The scout also *learns*: when a trade it confirmed closes, the realised P&L is
fed back as a reward signal to the Kenyon-cell -> MBON weights. Over a session it
develops preferences, which is the whole point of putting a mushroom body in
front of an LLM council.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from .config import Config
from .flybrain import FlyBrain, FlyConfig, FlySignal
from .models import TradeCandidate

log = logging.getLogger("soul.scout")


@dataclass
class ScoutPick:
    """One candidate that survived the scout, with the fly's read attached."""

    candidate: TradeCandidate
    signal: FlySignal
    rank: int = 0

    @property
    def symbol(self) -> str:
        return self.candidate.symbol

    @property
    def conviction(self) -> float:
        return self.signal.conviction

    def as_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.candidate.id,
            "symbol": self.candidate.symbol,
            "side": self.candidate.side,
            "strategy": self.candidate.strategy,
            "score": round(self.candidate.score, 3),
            "verdict": self.signal.direction,
            "conviction": round(self.signal.conviction, 3),
            "salience": round(self.signal.salience, 3),
            "z_margin": round(float(self.signal.rates.get("z_margin", 0.0)), 3),
            "z_confirm": round(float(self.signal.rates.get("z_confirm", 0.0)), 3),
            "z_contradict": round(float(self.signal.rates.get("z_contradict", 0.0)), 3),
            "kc_sparsity": round(self.signal.kc_sparsity, 3),
            "rank": self.rank,
            "ts": time.time(),
        }


class FlyScout:
    """Wraps a :class:`FlyBrain` into a gate + ranker for scanner candidates."""

    def __init__(self, cfg: Config, fly: Optional[FlyBrain] = None) -> None:
        self.cfg = cfg
        self.fly = fly or FlyBrain(FlyConfig(seed=int(getattr(cfg, "scout_seed", 1337))))
        self.min_z = float(getattr(cfg, "scout_min_z", 1.3))
        self.top_n = int(getattr(cfg, "scout_top_n", 0)) or int(cfg.max_candidates_per_scan)
        self.learn_enabled = bool(getattr(cfg, "scout_learn", True))
        self.judged = 0
        self.confirmed = 0
        self.waited = 0
        self.contradicted = 0
        self.passed = 0
        self.rewards = 0
        self.cum_reward = 0.0
        #: what the fly saw for each trade it let through, so the outcome can be
        #: credited back to the exact stimulus that produced it
        self._memory: Dict[str, Dict[str, Any]] = {}
        self.last_batch: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # screening
    # ------------------------------------------------------------------
    def screen(self, candidates: List[TradeCandidate],
               top_n: Optional[int] = None) -> List[ScoutPick]:
        """Judge every candidate, then gate and rank.

        Every candidate is judged (that is what the fly is for), but only the
        confirmed ones with the strongest conviction are put forward — the
        council's attention is the scarce resource.

        The gate has two parts: an absolute floor on how far the confirm pool
        stands above its ordinary-tape reading (``min_z``), and a budget
        (``top_n``). The floor rejects setups the fly has no opinion about; the
        budget keeps a busy scan from flooding the cabins.
        """
        picks: List[ScoutPick] = []
        batch: List[Dict[str, Any]] = []
        for cand in candidates:
            signal = self.judge(cand)
            self.judged += 1
            record = {
                "trade_id": cand.id, "symbol": cand.symbol, "side": cand.side,
                "strategy": cand.strategy, "score": round(cand.score, 3),
                "verdict": signal.direction,
                "conviction": round(signal.conviction, 3),
                "salience": round(signal.salience, 3),
                "z_margin": round(float(signal.rates.get("z_margin", 0.0)), 3),
                "z_confirm": round(float(signal.rates.get("z_confirm", 0.0)), 3),
                "z_contradict": round(float(signal.rates.get("z_contradict", 0.0)), 3),
                "kc_sparsity": round(signal.kc_sparsity, 3),
                "admitted": False, "ts": time.time(),
            }
            if signal.direction == "CONFIRM":
                self.confirmed += 1
                picks.append(ScoutPick(candidate=cand, signal=signal))
            elif signal.direction == "CONTRADICT":
                self.contradicted += 1
            else:
                self.waited += 1
            batch.append(record)

        picks.sort(key=lambda p: (p.signal.conviction, p.signal.salience), reverse=True)
        budget = int(top_n if top_n is not None else self.top_n)
        picks = picks[: max(1, budget)]

        for rank, pick in enumerate(picks):
            pick.rank = rank
            self.passed += 1
            self._memory[pick.candidate.id] = {
                "features": pick.signal.features.copy(),
                "side": pick.candidate.side,
                "action": 0 if pick.signal.direction == "CONFIRM" else 1,
                "ts": time.time(),
            }
            for record in batch:
                if record["trade_id"] == pick.candidate.id:
                    record["admitted"] = True
                    record["rank"] = rank

        # keep the memory bounded — this is a session-scoped learner
        if len(self._memory) > 400:
            for key in sorted(self._memory, key=lambda k: self._memory[k]["ts"])[:100]:
                self._memory.pop(key, None)

        self.last_batch = batch[-40:]
        if candidates:
            log.info("scout: %d candidates -> %d admitted (%d confirm / %d wait / %d contradict)",
                     len(candidates), len(picks), self.confirmed, self.waited, self.contradicted)
        return picks

    def judge(self, cand: TradeCandidate) -> FlySignal:
        """Run the fly over one candidate. ~6 ms on one CPU core."""
        features = dict(cand.features)
        features["side_long"] = 1.0 if cand.side == "LONG" else 0.0
        return self.fly.judge(cand.symbol, features, side=cand.side, threshold=self.min_z)

    # ------------------------------------------------------------------
    # learning
    # ------------------------------------------------------------------
    def learn(self, trade_id: str, pnl_pct: float, reward_scale: float = 2.0) -> bool:
        """Credit a closed trade back to the fly that approved it."""
        if not self.learn_enabled:
            return False
        memory = self._memory.pop(trade_id, None)
        if memory is None:
            return False
        reward = float(np.clip(pnl_pct / max(1e-6, reward_scale), -1.5, 1.5))
        self.fly.reinforce(np.asarray(memory["features"], dtype=np.float32), reward=reward,
                           action=int(memory["action"]))
        self.rewards += 1
        self.cum_reward += reward
        log.info("scout: learned from %s (%.2f%% -> reward %+.2f)", trade_id, pnl_pct, reward)
        return True

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        total = max(1, self.judged)
        return {
            "enabled": True,
            "engine": self.fly.stats().get("backend", "numpy LIF"),
            "neurons": self.fly.stats().get("neurons", {}),
            "synapses": self.fly.stats().get("synapses", 0),
            "judged": self.judged,
            "confirmed": self.confirmed,
            "waited": self.waited,
            "contradicted": self.contradicted,
            "admitted": self.passed,
            "admit_rate": round(self.passed / total, 3),
            "min_z": round(self.min_z, 2),
            "top_n": self.top_n,
            "rewards": self.rewards,
            "mean_reward": round(self.cum_reward / self.rewards, 3) if self.rewards else 0.0,
            "plasticity_events": self.fly.plasticity_events,
            "calibration": self.fly.calibration,
            "last_batch": self.last_batch,
        }
