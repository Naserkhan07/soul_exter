"""
Fly brain — a spiking neural network that decides when the floor should trade.

This is a compact, dependency-light (numpy only, CPU, Kaggle-friendly) model of
the *Drosophila* olfactory / decision circuit that snedea/flybrain maps:

    Antennal Lobe (AL)      : 12 receptors -> 26 projection neurons (lateral inhibition)
    Mushroom Body (KC)      : 140 sparse Kenyon cells, 6 random PNs each, LIF spiking
    Mushroom Body Output    : 8 MBONs, plastic KC->MBON weights, reward modulated
    Central Complex         : heading ring attractor -> long / short / neutral
    Descending Neurons (DN) : strike · wait · retreat

The brain is *not* a decorator around the strategies: nothing is emitted to the
council unless the fly's descending neurons fire at threshold, and the MBON
weights are updated from the realised outcome of every finished trade, so the
floor really does learn across the session.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

N_RECEPTORS = 29      # glomeruli fed by the market feature encoder (tape + deep
                       # statistics + order-book microstructure + correlation)
N_PN = 26
N_KC = 140
KC_FANIN = 6
KC_SPARSITY = 0.09     # fraction of Kenyon cells allowed to fire
N_MBON = 8
T_STEPS = 26


def _sparse_matrix(rows: int, cols: int, fan_in: int, rng: np.random.Generator) -> np.ndarray:
    m = np.zeros((rows, cols), dtype=np.float32)
    for r in range(rows):
        idx = rng.choice(cols, size=fan_in, replace=False)
        m[r, idx] = rng.uniform(0.5, 1.5, size=fan_in)
    return m


class FlyBrain:
    MBON_NAMES = ["attack", "wait", "retreat", "investigate", "hold", "hedge", "scale", "abort"]

    def __init__(self, seed: int = 7, lr: float = 0.075, base_threshold: float = 0.34,
                 adaptive_w: float = 0.35, adaptive_q: float = 0.93,
                 center_innate: bool = True) -> None:
        self.rng = np.random.default_rng(seed)
        self.lr = lr
        # AL -> PN (excitatory) + lateral inhibition
        self.w_al_pn = self.rng.uniform(0.4, 1.1, size=(N_PN, N_RECEPTORS)).astype(np.float32)
        self.w_pn_inh = self.rng.uniform(0.05, 0.22, size=(N_PN, N_PN)).astype(np.float32)
        np.fill_diagonal(self.w_pn_inh, 0.0)
        # PN -> KC (sparse, fixed)
        self.w_pn_kc = _sparse_matrix(N_KC, N_PN, KC_FANIN, self.rng)
        # innate glomerulus -> MBON preferences (the fly's hard-wired instincts:
        # approach what smells like opportunity, retreat from what smells like cost)
        #            trend_up dn  momo stretch brk_up brk_dn volReg volZ eff  sess cost burst
        #            rngPos volExp conv pers autoc skew kurt vwap flow | bookP ofi aggr liq
        #            bloc cbreak ccy leadlag
        instincts = [
            [0.55, 0.55, 0.70, -0.25, 0.55, 0.55, 0.10, 0.45, 0.85, 0.45, 0.65, 0.30,
             0.30, 0.35, 0.35, 0.45, 0.30, 0.10, -0.10, 0.30, 0.45, 0.55, 0.50, 0.55,
             0.25, 0.20, 0.15, 0.55, 0.35],                                        # attack
            [0.00, 0.00, -0.25, 0.60, 0.15, 0.15, 0.55, 0.10, -0.65, 0.00, -0.25, 0.20,
             0.00, -0.20, 0.00, 0.10, 0.20, 0.15, 0.30, 0.10, -0.15, -0.30, -0.25, -0.20,
             0.10, 0.30, 0.45, 0.00, 0.10],                                        # wait
            [-0.25, -0.25, -0.35, 0.30, -0.25, -0.25, 0.45, -0.10, -0.55, -0.45, -0.65, -0.25,
             -0.20, -0.10, -0.15, -0.30, -0.20, -0.10, 0.35, -0.15, -0.35, -0.45, -0.40, -0.35,
             -0.15, -0.10, 0.20, -0.30, -0.15],                                    # retreat
            [0.20, 0.20, 0.55, 0.20, 0.30, 0.30, 0.30, 0.65, 0.45, 0.25, 0.30, 0.55,
             0.20, 0.40, 0.20, 0.30, 0.25, 0.20, 0.25, 0.20, 0.35, 0.45, 0.40, 0.40,
             0.20, 0.45, 0.50, 0.25, 0.45],                                        # investigate
            [0.25, 0.25, 0.25, -0.10, 0.10, 0.10, 0.00, 0.15, 0.75, 0.35, 0.55, 0.15,
             0.10, 0.05, 0.15, 0.20, 0.15, 0.05, 0.10, 0.10, 0.25, 0.30, 0.25, 0.30,
             0.20, 0.15, -0.10, 0.25, 0.15],                                       # hold
            [0.00, 0.00, 0.00, 0.45, 0.00, 0.00, 0.70, 0.30, -0.20, 0.00, -0.35, 0.25,
             0.00, 0.20, 0.00, 0.00, 0.10, 0.10, 0.25, 0.05, -0.10, -0.35, -0.20, -0.25,
             0.05, 0.35, 0.30, -0.20, 0.10],                                       # hedge
            [0.35, 0.35, 0.45, 0.00, 0.25, 0.25, 0.20, 0.40, 0.60, 0.55, 0.45, 0.35,
             0.20, 0.25, 0.20, 0.25, 0.20, 0.10, 0.00, 0.20, 0.30, 0.35, 0.30, 0.35,
             0.15, 0.20, 0.10, 0.35, 0.25],                                        # scale
            [-0.25, -0.25, -0.35, 0.20, -0.15, -0.15, 0.35, -0.10, -0.45, -0.55, -0.55, -0.20,
             -0.15, -0.15, -0.10, -0.20, -0.15, -0.05, 0.30, -0.10, -0.25, -0.35, -0.30, -0.30,
             -0.10, -0.05, 0.25, -0.25, -0.10],                                    # abort
        ]
        assert len(instincts[0]) == N_RECEPTORS, "instincts must match receptor count"
        self.w_g_mbon = np.array(instincts, dtype=np.float32)
        # KC -> MBON (plastic)
        self.w_kc_mbon = self.rng.uniform(-0.25, 0.25, size=(N_MBON, N_KC)).astype(np.float32)
        self.mbon_bias = self.rng.uniform(-0.1, 0.1, size=N_MBON).astype(np.float32)
        # descending neuron gains
        self.dn_gain = np.array([1.35, -0.85, -0.75, 1.0, 0.6, 0.5, 0.35, -0.55], dtype=np.float32)
        # state
        self.base_threshold = base_threshold
        self.adaptive_w = adaptive_w
        self.adaptive_q = adaptive_q
        self.center_innate = center_innate
        self._hungry: List[float] = []
        self.strike_kc = np.zeros(N_KC, dtype=np.float32)
        self.heading = 0.0            # ring attractor phase (-1 short .. +1 long)
        self.dopamine = 0.0
        self.fatigue = 0.0
        self.strikes = 0
        self.waits = 0
        self.rewards: List[float] = []
        self.trace: Dict[str, List[float]] = {"al": [], "pn": [], "kc": [], "mbon": []}
        self._spike_hist: List[float] = []
        self.last: Dict[str, object] = {}

    # ------------------------------------------------------------------ core
    def simulate(self, glomeruli: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Run T_STEPS of LIF dynamics; return (pn_rate, kc_rate, mbon)."""
        g = np.clip(np.asarray(glomeruli, dtype=np.float32), 0.0, 1.0)
        # --- AL: normalised excitation + lateral inhibition -----------------
        pn_raw = (g @ self.w_al_pn.T) / math.sqrt(N_RECEPTORS)
        inhib = (pn_raw @ self.w_pn_inh.T) / float(N_PN)
        pn = np.maximum(0.0, pn_raw - 1.15 * inhib)
        pn = pn / (1.0 + pn)                                      # divisive normalisation
        pn_rate = pn * 0.0
        # --- KC: LIF over T steps ------------------------------------------
        v = np.zeros(N_KC, dtype=np.float32)
        spikes = np.zeros(N_KC, dtype=np.float32)
        drive = self.w_pn_kc @ pn
        k_keep = max(4, int(KC_SPARSITY * N_KC))
        for t in range(T_STEPS):
            v = v * 0.80 + drive * (0.7 + 0.6 * math.sin((t + 1) / T_STEPS * math.pi))
            # winner-take-all sparsening: the mushroom body only ever codes a few odours
            keep = np.argpartition(v, -k_keep)[-k_keep:]
            fired = np.zeros(N_KC, dtype=bool)
            fired[keep] = v[keep] > 0.05
            spikes += fired
            v[fired] *= 0.15            # refractory reset
            pn_rate += pn
        kc_rate = spikes / float(T_STEPS * 0.35)     # ~1.0 for a cell that fires most steps
        kc_rate = np.clip(kc_rate, 0.0, 1.0)
        # --- MBON: innate drive + learned Kenyon-cell read-out --------------
        drive_in = (g - 0.5) * 2.0 if self.center_innate else g
        innate = self.w_g_mbon @ drive_in
        learned = self.w_kc_mbon @ (kc_rate - float(kc_rate.mean()))
        mbon = np.tanh(0.95 * innate + 1.15 * learned + self.mbon_bias)
        return pn, kc_rate, mbon

    def decide(self, glomeruli: np.ndarray, bias: float, atr_pct: float,
               spread_cost: float) -> Dict[str, object]:
        """Full sensory -> decision pass. `bias` (-1..1) is the strategy stimulus."""
        pn, kc, mbon = self.simulate(glomeruli)
        attack = float(mbon[0])
        wait = float(mbon[1])
        retreat = float(mbon[2])
        invest = float(mbon[3])
        self._last_kc = kc
        # central-complex heading: ring attractor pulled by stimulus + MBON
        drive = 0.55 * bias + 0.45 * (invest - retreat) + 0.12 * self.rng.normal()
        self.heading = float(np.clip(0.82 * self.heading + 0.34 * drive, -1.0, 1.0))
        # fatigue / habituation after a strike, decays back to zero
        self.fatigue *= 0.90
        hungry = attack + invest * 0.6 - wait * 0.7 - retreat * 0.5
        self._hungry.append(float(hungry))
        if len(self._hungry) >= 60:
            # novelty detection: the fly fires when this odour is unusually good
            adaptive = float(np.quantile(self._hungry, self.adaptive_q))
            threshold = self.adaptive_w * adaptive + (1 - self.adaptive_w) * self.base_threshold
        else:
            threshold = self.base_threshold
        threshold += 0.30 * self.fatigue + 2.4 * max(0.0, spread_cost) * 26.0
        margin = hungry - threshold
        strike = margin > 0 and abs(self.heading) > 0.22
        state = "STRIKE" if strike else ("WAIT_FOR_SETUP" if margin > -0.18 else "ROAM")
        if strike:
            self.strikes += 1
            self.fatigue = min(1.2, self.fatigue + 0.5)
            self.strike_kc = kc.copy()
        elif state == "WAIT_FOR_SETUP":
            self.waits += 1

        confidence = float(np.clip(margin / 0.34, 0.0, 1.0))
        score = float(np.clip(0.48 * confidence + 0.22 * abs(self.heading) +
                              0.30 * float(np.clip((attack + invest) / 1.4, 0, 1)), 0.0, 1.0))
        direction = "long" if self.heading >= 0 else "short"

        self.trace = {
            "al": [round(float(x), 4) for x in np.asarray(glomeruli)],
            "pn": [round(float(x), 4) for x in pn[:26]],
            "kc": [round(float(x), 4) for x in kc],
            "mbon": [round(float(x), 4) for x in mbon],
        }
        self._spike_hist.append(float(kc.mean()))
        self._spike_hist = self._spike_hist[-240:]
        self.last = dict(
            state=state, score=round(score, 4), confidence=round(confidence, 4),
            direction=direction, heading=round(self.heading, 4),
            attack=round(attack, 4), wait=round(wait, 4), retreat=round(retreat, 4),
            investigate=round(invest, 4), threshold=round(threshold, 4),
            fatigue=round(self.fatigue, 4), dopamine=round(self.dopamine, 4),
            active_kc=int((kc > 0).sum()), strikes=self.strikes, waits=self.waits,
            hungry=round(float(hungry), 4),
            mbon={n: round(float(v), 4) for n, v in zip(self.MBON_NAMES, mbon)},
            atr_pct=round(atr_pct, 5), spread_cost=round(spread_cost, 5),
        )
        return self.last

    # ---------------------------------------------------------------- learning
    def reinforce(self, reward: float, kc_rate: Optional[np.ndarray] = None) -> None:
        """Dopamine-modulated Hebbian update of the KC -> MBON synapses."""
        self.dopamine = float(np.clip(0.65 * self.dopamine + 0.55 * reward, -1.5, 1.5))
        self.rewards.append(round(reward, 3))
        self.rewards = self.rewards[-200:]
        if kc_rate is None:
            kc_rate = self.strike_kc if self.strike_kc.any() else getattr(self, "_last_kc", None)
            if kc_rate is None:
                return
        kc = np.asarray(kc_rate, dtype=np.float32)
        centred = kc - kc.mean()
        scale = float(np.abs(centred).sum()) + 1e-6
        err = np.outer(self.dopamine * np.ones(N_MBON, dtype=np.float32), centred) / scale
        self.w_kc_mbon += self.lr * err * 3.0
        self.w_kc_mbon = np.clip(self.w_kc_mbon, -1.6, 1.6)

    # ---------------------------------------------------------------- io
    def snapshot(self) -> dict:
        return dict(state=self.last, trace=self.trace, spike_history=self._spike_hist[-120:],
                    stats=dict(strikes=self.strikes, waits=self.waits,
                               dopamine=round(self.dopamine, 4), fatigue=round(self.fatigue, 4),
                               heading=round(self.heading, 4),
                               mean_reward=(round(float(np.mean(self.rewards)), 3)
                                            if self.rewards else 0.0),
                               synapse_energy=round(float(np.abs(self.w_kc_mbon).mean()), 4)))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez_compressed(path, w_kc_mbon=self.w_kc_mbon, w_al_pn=self.w_al_pn,
                            w_pn_inh=self.w_pn_inh, w_pn_kc=self.w_pn_kc,
                            mbon_bias=self.mbon_bias, heading=np.array([self.heading]),
                            strikes=np.array([self.strikes]), waits=np.array([self.waits]),
                            rewards=np.asarray(self.rewards, dtype=np.float32))

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            z = np.load(path, allow_pickle=False)
            if z["w_al_pn"].shape != (N_PN, N_RECEPTORS):
                return False      # brain anatomy changed -> learn fresh
            self.w_kc_mbon = z["w_kc_mbon"]
            self.w_al_pn = z["w_al_pn"]
            self.w_pn_inh = z["w_pn_inh"]
            self.w_pn_kc = z["w_pn_kc"]
            self.mbon_bias = z["mbon_bias"]
            self.heading = float(z["heading"][0])
            self.strikes = int(z["strikes"][0])
            self.waits = int(z["waits"][0])
            self.rewards = [float(x) for x in z["rewards"]]
            return True
        except Exception:
            return False


# --------------------------------------------------------------------------- #
#  Fly agent: owns navigation over the instruments and the floor
# --------------------------------------------------------------------------- #
@dataclass
class FlyAgent:
    """The market-hunting fly: brain + wing state + the symbol it is inspecting."""

    brain: FlyBrain
    symbol: str = "EURUSD"
    state: str = "ROAM"
    target: Tuple[float, float] = (0.0, 10.0)
    pos: Dict[str, float] = field(default_factory=lambda: dict(x=0.0, y=4.6, z=10.0))
    yaw: float = 0.0
    inspected: List[str] = field(default_factory=list)
    cooldown: Dict[str, float] = field(default_factory=dict)
    last_signal: Optional[dict] = None
    strike_flash: float = 0.0
    stats: Dict[str, float] = field(default_factory=dict)

    def note_strike(self, symbol: str, now: float, cooldown_s: float = 22.0) -> None:
        self.cooldown[symbol] = now + cooldown_s
        self.strike_flash = 1.0
        self.last_signal = None

    def cooling(self, symbol: str, now: float) -> bool:
        return self.cooldown.get(symbol, 0.0) > now

    def snapshot(self) -> dict:
        return dict(symbol=self.symbol, state=self.state, pos=self.pos, yaw=round(self.yaw, 3),
                    target=[round(self.target[0], 2), round(self.target[1], 2)],
                    strike_flash=round(self.strike_flash, 3),
                    inspected=self.inspected[-14:], stats=self.stats,
                    cooling=len([1 for v in self.cooldown.values() if v > 0]),
                    brain=self.brain.snapshot())
