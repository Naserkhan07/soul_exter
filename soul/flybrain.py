"""FlyBrain — a spiking, connectome-inspired market scout.

The trade-finding brain the floor runs before the council. It is not a
transformer: it is a small **leaky integrate-and-fire (LIF) network** wired like
an insect brain, in the spirit of the FlyWire FAFB connectome (see
github.com/snedea/flybrain for the full 139K-neuron simulation this borrows its
structure from).

Pathway (sensory in -> action out):

    ORN   olfactory/visual receptor neurons   ~ 64   rate-coded market features
     |        (one small pool per feature channel)
    LN    local interneurons                  ~260   80/20 excitatory/inhibitory,
     |        sparse small-world wiring              the fly's lateral processing
    PN    projection neurons                  ~ 96   sparse readout of the LN layer
     |
    KC    Kenyon cells (mushroom body)        ~192   sparse expansion coding: only a
     |        few percent of KC fire for any given stimulus, which is what makes
     |        the mushroom body a good associative learner
    MBON  mushroom body output neurons        ~ 10   one per action. THIS is the
     |        learned layer (reward-modulated plasticity)
    DN    descending neurons                  ~ 6    the motor decision

Two things make it useful rather than decorative:

1. **It learns.** ``reinforce()`` applies a three-factor rule
   (pre-synaptic trace x post-synaptic activity x reward) to the KC->MBON
   weights, with reward coming from realised trade P&L. Patterns that preceded
   winning trades get potentiated; losers get depressed. That is the mushroom
   body's job in a real fly, and it is the same primitive as
   reward-modulated Hebbian learning.

2. **It is a gate, not a toy.** Its output is a conviction per direction plus a
   salience score, which the floor uses to decide whether a candidate is worth
   the council's time (LLM tokens are expensive on a T4).

Everything here is numpy and runs in a few milliseconds per symbol on a CPU, so
it costs almost nothing next to the LLM cabins.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# --------------------------------------------------------------------------
# neuron model
# --------------------------------------------------------------------------
@dataclass
class LIFParams:
    dt_ms: float = 1.0
    tau_m_ms: float = 20.0
    v_rest: float = 0.0
    v_reset: float = 0.0
    v_thresh: float = 1.0
    refractory_ms: float = 2.0
    tau_trace_ms: float = 30.0        # pre-synaptic eligibility trace


@dataclass
class FlyConfig:
    n_orn_pools: int = 16             # feature channels that drive sensory pools
    orn_per_pool: int = 4
    n_ln: int = 260
    n_pn: int = 96
    n_kc: int = 192
    n_mbon: int = 10
    ei_ratio: float = 0.8             # 80% excitatory
    ln_fanout: float = 0.06           # sparse local wiring
    pn_fanout: float = 0.08
    kc_fanout: float = 0.05           # sparse expansion -> few KC active
    seed: int = 1337
    sim_ms: int = 140                 # stimulus window
    warmup_ms: int = 40
    # Synaptic gains. These are calibrated (tools/tune_flybrain.py) so that a
    # weak stimulus leaves the network quiet, a strong one drives ~5-10% of the
    # Kenyon cells, and the descending neurons pick a direction with margin.
    gain_orn_ln: float = 3.0
    gain_ln_ln: float = 0.55
    gain_ln_pn: float = 2.6
    gain_pn_kc: float = 5.5
    gain_kc_mbon: float = 0.85
    #: APL (anterior paired lateral) neuron: one giant GABAergic cell that
    #: normalises the whole mushroom body. Modelled as global divisive
    #: inhibition, which is what keeps the Kenyon cell code sparse.
    apl_gain: float = 2.6
    #: spontaneous background drive (Hz per neuron). A real brain is never
    #: silent, and without this a threshold network only responds to extreme
    #: stimuli, which is useless for reading a market.
    background_hz: float = 6.0
    #: multi-scale factor applied to the typical read when calibrating
    calibrate_stimulus: float = 1.0
    #: Target firing rates used by calibrate(). These are deliberately modest:
    #: the network is calibrated against a TYPICAL market read, so a quiet tape
    #: keeps it near rest, an interesting one lifts it, and an extreme one
    #: saturates it. Calibrating against an extreme stimulus instead is a trap —
    #: the threshold nonlinearity then leaves the brain silent on real data.
    target_ln: float = 0.030
    target_pn: float = 0.045
    target_kc: float = 0.030
    target_mbon: float = 0.080
    #: fraction of Kenyon cells allowed to fire for a typical read. A sparse code
    #: is what lets the mushroom body separate patterns instead of reporting the
    #: market's overall level.
    target_kc_coverage: float = 0.10

    @property
    def n_orn(self) -> int:
        return self.n_orn_pools * self.orn_per_pool


#: The fly votes on the DIRECTION THE SCANNER PROPOSED, not on the market in the
#: abstract. That mirrors how an insect works: the same visual field drives
#: approach on one side and avoidance on the other, and it is what makes the
#: brain useful as a filter in front of the council.
ACTIONS = ["CONFIRM", "CONTRADICT", "WAIT"]
MBON_CONFIRM, MBON_CONTRADICT, MBON_WAIT = 0, 1, 2

#: Which sensory channels argue for upside vs downside. The mushroom body's
#: output neurons are hardwired to approach/avoid behaviours in a real fly;
#: these two sets are what we hardwire before any learning happens.
#: Sensory channel map (see featurize()):
#:   0 volume surprise   1 volatility regime  2 RSI displacement  3 oversold flag
#:   4 overbought flag   5 relative strength  6 range position    7 BB compression
#:   8 absolute vol      9 short-trend strength 10 long-trend strength
#:  11 risk-on          12 risk-off          13 market tailwind   14 beta crowding
#:  15 EMA stack
#:
#: Channels that argue "the proposed direction is supported" once the stimulus
#: is expressed in the candidate's own frame.
CONFIRM_CHANNELS = (5, 6, 11, 13, 15)
#: Channels that argue "this move is already exhausted or crowded": the two RSI
#: flags (whichever of them points against the proposal) and beta crowding.
#: Channels 9/10 (trend strength) are magnitudes with no direction, so they are
#: deliberately NOT given a polarity: a strong bearish tape has just as much
#: slope magnitude as a bullish one, and including them made the readout call
#: every violent move a confirmation.
CONTRADICT_CHANNELS = (3, 4, 14)
#: Channels that carry a direction and can simply be flipped for a short
#: proposal: relative strength, range position, market tailwind, EMA stack.
INVERT_CHANNELS = (5, 6, 13, 15)
#: Binary pairs that SWAP sides for a short proposal — a short is supported by
#: "oversold" and "risk-off" exactly as a long is supported by "overbought" and
#: "risk-on". Inverting these instead would leave both flags saying the same
#: thing, which is what a naive mirror does.
SWAP_PAIRS = ((3, 4), (11, 12))

#: A "nothing is happening" market read, in raw feature units. Used both to
#: calibrate the sensory gains and as the reference point for salience.
TYPICAL_FEATURES: Dict[str, float] = {
    "vol_z": 0.4, "atr_rank": 50.0, "rsi": 50.0, "rel_strength": 0.0,
    "range_pos": 0.5, "bb_width_rank": 50.0, "atr_pct": 1.0,
    "ema20_slope": 0.05, "ema50_slope": 0.03, "regime": 0.0,
    "btc_ret_12": 0.0, "corr_proxy": 1.4, "ema_stack": 1.0, "side_long": 1.0,
}


@dataclass
class FlySignal:
    """What the fly brain thinks about one symbol."""

    symbol: str
    direction: str = "WAIT"           # LONG | SHORT | WAIT
    conviction: float = 0.0           # 0..1 from MBON firing rates
    salience: float = 0.0             # 0..1 how much this stimulus excites the brain
    kc_sparsity: float = 0.0          # fraction of Kenyon cells active (diagnostic)
    rates: Dict[str, float] = field(default_factory=dict)
    features: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol, "direction": self.direction,
            "conviction": round(self.conviction, 3), "salience": round(self.salience, 3),
            "kc_sparsity": round(self.kc_sparsity, 3),
            "rates": {k: round(v, 4) for k, v in self.rates.items()},
        }


class FlyBrain:
    """A LIF spiking network with a learned mushroom-body readout."""

    def __init__(self, cfg: Optional[FlyConfig] = None, lif: Optional[LIFParams] = None) -> None:
        self.cfg = cfg or FlyConfig()
        self.lif = lif or LIFParams()
        c = self.cfg
        rng = np.random.default_rng(c.seed)
        self.rng = rng

        # ---- populations -------------------------------------------------
        self.n_orn, self.n_ln, self.n_pn, self.n_kc = c.n_orn, c.n_ln, c.n_pn, c.n_kc
        self.n_mbon = c.n_mbon

        # 80/20 excitatory/inhibitory, like the fly's local interneuron pools
        n_exc = int(round(self.n_ln * c.ei_ratio))
        self.ln_sign = np.ones(self.n_ln, dtype=np.float32)
        self.ln_sign[n_exc:] = -1.0

        # ---- fixed sensory wiring ---------------------------------------
        # every ORN pool projects to a compact bundle of LNs, so each feature
        # has a local neighbourhood it can drive (lateral inhibition comes from
        # the inhibitory LNs mixing across pools)
        self.W_orn_ln = self._sparse((self.n_orn, self.n_ln), 0.10, c.gain_orn_ln)
        # local recurrent wiring: sparse, small-world (ring + long-range)
        self.W_ln_ln = self._small_world(self.n_ln, c.ln_fanout, c.gain_ln_ln)
        self.W_ln_ln *= self.ln_sign[None, :]
        self.W_ln_pn = self._sparse((self.n_ln, self.n_pn), c.pn_fanout, c.gain_ln_pn)
        # sparse expansion into Kenyon cells (the mushroom body trick)
        self.W_pn_kc = self._sparse((self.n_pn, self.n_kc), c.kc_fanout, c.gain_pn_kc)
        # Kenyon cell inhibition keeps the code sparse (~5-10% active)
        self.kc_gain = np.zeros(self.n_kc, dtype=np.float32)
        self.kc_gain[: int(self.n_kc * 0.85)] = 1.0     # most KC are excitatory

        # ---- the learned layer ------------------------------------------
        # KC -> MBON is the only plastic layer in a fly's mushroom body. It is
        # read out as a graded decoder: each output neuron reports the weighted
        # average of the Kenyon-cell code, with the weight columns normalised so
        # the output stays in rate units instead of saturating the way a
        # threshold unit does. (The spiking dynamics live upstream, in the
        # sensory and mushroom-body layers, which is where the connectome
        # actually constrains the computation.)
        self.W_kc_mbon = self._sparse((self.n_kc, self.n_mbon), 0.12, c.gain_kc_mbon)
        # MBON are mutually inhibitory: committing to one action suppresses the
        # rest. The strength is divided across the population so the inhibition
        # is a mean field rather than a sum that grows with the number of
        # neurons — a sum would swamp the drive and the readout would sit at zero.
        self.inhib_gain = 0.5
        self.W_mbon_mbon = np.full((self.n_mbon, self.n_mbon),
                                   -self.inhib_gain / max(1, self.n_mbon - 1), dtype=np.float32)
        np.fill_diagonal(self.W_mbon_mbon, 0.0)
        # homeostatic per-output offset, set by calibrate() so a quiet tape reads
        # as "do nothing" rather than a coin flip
        self.mbon_bias = np.zeros(self.n_mbon, dtype=np.float32)
        #: overall excitability of the readout, fitted by calibrate()
        self.mbon_gain = 1.0
        self.readout_iters = 3
        self._seed_readout_prior()

        # ---- state -------------------------------------------------------
        self.v_ln = np.zeros(self.n_ln, dtype=np.float32)
        self.v_pn = np.zeros(self.n_pn, dtype=np.float32)
        self.v_kc = np.zeros(self.n_kc, dtype=np.float32)
        self.v_mbon = np.zeros(self.n_mbon, dtype=np.float32)
        self.trace_kc = np.zeros(self.n_kc, dtype=np.float32)
        self.refractory = np.zeros(self.n_ln, dtype=np.float32)

        self.plasticity_events = 0
        self.reward_history: List[float] = []
        self.last_kc = np.zeros(self.n_kc, dtype=np.float32)
        self.calibration: Dict[str, Any] = {}
        #: per-output mean/std of the network's response to "ordinary" market
        #: reads. Decisions are made on the z-score against this, not on absolute
        #: firing rates: an insect brain reports surprise, not level, and it
        #: makes the readout immune to drift in the random wiring.
        self.baseline_mean = np.zeros(self.n_mbon, dtype=np.float32)
        self.baseline_std = np.ones(self.n_mbon, dtype=np.float32)
        self.baseline_kc = 0.0
        self.baseline_salience = 0.0
        #: spread of the CONFIRM-minus-CONTRADICT gap over ordinary market reads;
        #: this is the yardstick the decision threshold is expressed in
        self.margin_std = 1.0
        self.baseline_kc_coverage = 0.1
        self.calibrate()

    # ------------------------------------------------------------------
    # wiring helpers
    # ------------------------------------------------------------------
    def _sparse(self, shape: Tuple[int, int], density: float, gain: float,
                positive: bool = True) -> np.ndarray:
        """Sparse random matrix whose non-zero weights average exactly ``gain``."""
        mask = self.rng.random(shape) < density
        w = np.abs(self.rng.normal(1.0, 0.35, size=shape)).astype(np.float32)
        w *= mask
        nz = float(w[mask].mean()) if mask.any() else 0.0
        if nz > 0:
            w = (w / nz) * gain
        return w.astype(np.float32)

    def _small_world(self, n: int, density: float, gain: float) -> np.ndarray:
        """Ring wiring plus long-range shortcuts — the fly's local interneuron mesh."""
        w = np.zeros((n, n), dtype=np.float32)
        k = max(2, int(n * density))
        idx = np.arange(n)
        for off in range(1, k // 2 + 1):
            w[idx, (idx + off) % n] = np.abs(self.rng.normal(1.0, 0.35, n))
            w[idx, (idx - off) % n] = np.abs(self.rng.normal(1.0, 0.35, n))
        n_long = max(1, n // 12)
        for i in range(n):
            targets = self.rng.integers(0, n, n_long)
            w[i, targets] = np.abs(self.rng.normal(0.7, 0.3, n_long))
        nz = float(w[w > 0].mean()) if (w > 0).any() else 0.0
        if nz > 0:
            w = (w / nz) * gain
        return w.astype(np.float32)

    def _seed_readout_prior(self, strength: float = 1.0) -> None:
        """Hardwire an innate confirm/contradict polarity into the readout.

        Propagating the fixed wiring one layer deep gives every Kenyon cell a
        linear receptive field over the sensory channels
        (A = W_pn_kc^T W_ln_pn^T W_orn_ln^T). Stacking the two channel sets into a
        single SIGNED polarity vector — +1 on the channels that support a
        proposal, -1 on the channels that argue it is exhausted — and projecting
        it through A gives each Kenyon cell an innate value score. Cells that
        read the supportive channels go onto CONFIRM, cells that read the
        exhaustion channels go onto CONTRADICT.

        Using one signed vector rather than two positive scores is the whole
        point: it makes the two output columns anti-correlated by construction,
        so the readout can actually take sides. (Two separately-built positive
        scores come out ~90% correlated and the network cannot tell a bull tape
        from a bear tape, which is precisely how an earlier version failed.)

        Learning then refines these weights from realised P&L — the same
        division of labour as a real mushroom body, where the wiring is innate
        and the synaptic weights are learned.
        """
        A = self.W_pn_kc.T @ self.W_ln_pn.T @ self.W_orn_ln.T     # (n_kc, n_orn)
        pools, per_pool = self.cfg.n_orn_pools, self.cfg.orn_per_pool
        polarity = np.zeros(self.n_orn, dtype=np.float32)
        for ch in CONFIRM_CHANNELS:
            if ch < pools:
                polarity[ch * per_pool:(ch + 1) * per_pool] = 1.0
        for ch in CONTRADICT_CHANNELS:
            if ch < pools:
                polarity[ch * per_pool:(ch + 1) * per_pool] = -1.0

        score = A @ polarity
        sd = float(score.std()) or 1.0
        score = (score - float(score.mean())) / sd
        yes, no = np.maximum(0.0, score), np.maximum(0.0, -score)

        # Scale the prior against the random component of the same column, so it
        # carries real contrast without erasing the innate background weights.
        for col, vec in ((MBON_CONFIRM, yes), (MBON_CONTRADICT, no)):
            base_mass = float(self.W_kc_mbon[:, col].sum()) or 1.0
            mass = float(vec.sum()) or 1.0
            self.W_kc_mbon[:, col] += strength * 0.9 * base_mass * vec / mass
        self._normalise_readout()

    def _normalise_readout(self) -> None:
        """Keep every KC -> MBON column a probability distribution over KCs."""
        np.clip(self.W_kc_mbon, 0.0, None, out=self.W_kc_mbon)
        col = self.W_kc_mbon.sum(axis=0, keepdims=True)
        self.W_kc_mbon /= np.maximum(col, 1e-6)

    def _readout(self, kc_activity: np.ndarray) -> np.ndarray:
        """Graded MBON output for a Kenyon-cell activity vector.

        drive = W^T kc is the weighted average KC rate each output neuron reads.
        Cross-inhibition between outputs is relaxed over a few iterations, which
        sharpens the winner the way MBON-MBON inhibition does in the fly.
        """
        drive = self.mbon_gain * (self.W_kc_mbon.T @ kc_activity) - self.mbon_bias

        # Soft saturation, not a hard clip. A hard clip is non-monotone in
        # practice: a violent tape pins every output at the ceiling, the
        # confirm-minus-contradict margin collapses to zero, and the strongest
        # setups read as "no opinion". drive/(1+drive) is monotone everywhere,
        # so the margin keeps growing with the evidence.
        def act(d: np.ndarray) -> np.ndarray:
            d = np.maximum(d, 0.0)
            return d / (1.0 + d)

        r = act(drive)
        for _ in range(max(0, self.readout_iters)):
            nxt = act(drive + self.W_mbon_mbon.T @ r)
            r = 0.5 * r + 0.5 * nxt          # damped relaxation, so it converges
        return np.clip(r, 0.0, 1.0).astype(np.float32)

    # ------------------------------------------------------------------
    # calibration
    # ------------------------------------------------------------------
    def calibrate(self, iters: int = 4) -> Dict[str, float]:
        """Fit the fixed wiring to a typical market read.

        Three things have to be true before the brain is useful, and none of them
        can be hand-tuned once the population sizes change:

        1. every layer is driven above threshold, or the brain just sits silent;
        2. the Kenyon-cell code is SPARSE. A dense mushroom body is a running
           average of the market and cannot tell a bull tape from a bear tape —
           an early version of this net failed exactly that way (0.91 correlation
           between the code for opposite stimuli). Sparsity is what makes the
           expansion a pattern separator, so it gets its own controller rather
           than a hand-picked gain;
        3. the readout sits at a visible but low level for an ordinary read, so
           that deviations from it mean something.

        A rate controller sets (1), a coverage controller sets (2), and a direct
        solve sets (3). Runs once at construction (a fraction of a second).
        """
        c = self.cfg
        base = self.featurize(TYPICAL_FEATURES)
        strong = np.clip(base * c.calibrate_stimulus, 0.0, 1.4).astype(np.float32)

        # ---- (1) sensory and projection layers ----------------------------
        targets = {"ln": c.target_ln, "pn": c.target_pn}
        matrices = {"ln": "W_orn_ln", "pn": "W_ln_pn"}
        for _ in range(max(1, iters)):
            out = self.run(strong)
            for layer in ("ln", "pn"):
                measured = float(np.mean(out[layer]))
                if measured <= 1e-6:
                    factor = 2.2
                else:
                    factor = float(np.clip((targets[layer] / measured) ** 0.5, 0.35, 2.6))
                if abs(factor - 1.0) < 0.02:
                    continue
                setattr(self, matrices[layer], getattr(self, matrices[layer]) * factor)

        # ---- (2) mushroom body sparsity -----------------------------------
        probe = [strong] + self._ordinary_reads(6)
        coverage = float("nan")
        for _ in range(12):
            coverage = float(np.mean([(self.run(v)["kc"] > 0).mean() for v in probe]))
            if coverage <= 1e-9:
                self.W_pn_kc *= 2.0
                continue
            if abs(coverage - c.target_kc_coverage) / c.target_kc_coverage < 0.25:
                break
            self.W_pn_kc *= 1.0 / float(np.clip(
                (coverage / c.target_kc_coverage) ** 0.6, 0.25, 4.0))

        # ---- (3) readout level and baseline --------------------------------
        # How each output neuron behaves across ORDINARY tape conditions — the
        # market reads that should not move a trader to do anything. Every
        # decision downstream is a standard score against this distribution, so
        # the fly reports surprise rather than absolute level.
        quiet = self.featurize(TYPICAL_FEATURES)

        def sample(n: int) -> np.ndarray:
            rows = []
            for vec in self._ordinary_reads(n):
                res = self.run(vec)
                rows.append(np.concatenate([res["mbon"], [float(res["kc"].mean()),
                                                          res["salience"], res["readout_raw"]]]))
            return np.array(rows, dtype=np.float32)

        arr = sample(24)
        # Solve for the gain that puts an ordinary read on the target output
        # rate. Because the KC -> MBON columns are normalised to a weighted
        # average the raw drive is tiny in absolute terms, so this is a direct
        # solve on the unclipped drive rather than a search.
        raw = float(arr[:, self.n_mbon + 2].mean())
        if raw <= 1e-12:
            raw = float(np.mean([self.run(v)["readout_raw"] for v in self._ordinary_reads(8)])) or 1e-12
        self.mbon_gain = float(np.clip(c.target_mbon / max(raw, 1e-12), 1e-6, 1e12))

        # Opponent balance: the confirm and contradict pools must be equally
        # sensitive, or the louder one wins every argument. Without this the
        # confirm pool (built from six channels) is about twice as reactive as
        # the contradict pool (three channels) and the fly confirms everything it
        # is shown — which is useless for a filter.
        for _ in range(3):
            sd = arr[:, :2].std(axis=0)
            ratio = float(np.clip(float(sd[MBON_CONFIRM]) / max(1e-9, float(sd[MBON_CONTRADICT])),
                                  0.25, 4.0))
            if abs(ratio - 1.0) < 0.06:
                break
            self.W_kc_mbon[:, MBON_CONTRADICT] *= ratio
            self._normalise_readout()
            arr = sample(20)
            raw = float(arr[:, self.n_mbon + 2].mean())
            self.mbon_gain = float(np.clip(c.target_mbon / max(raw, 1e-12), 1e-6, 1e12))

        # Homeostatic balance: on an ordinary read every output should sit at the
        # same level, so the decision comes from the stimulus and not from which
        # random output neuron happened to draw bigger weights.
        for _ in range(8):
            rates = self.run(quiet)["mbon"][:3]
            self.mbon_bias[:3] = np.clip(
                self.mbon_bias[:3] + 0.5 * (rates - float(rates.mean())), -1.5, 1.5)
            if float(np.abs(rates - float(rates.mean())).max()) < 0.002:
                break
        self.mbon_bias[MBON_WAIT] += 0.02           # slight nudge toward inaction

        arr = np.vstack([arr, sample(24)]).astype(np.float32)
        self.baseline_mean = arr[:, : self.n_mbon].mean(axis=0)
        self.baseline_std = np.maximum(arr[:, : self.n_mbon].std(axis=0), 1e-3)
        self.baseline_kc = float(arr[:, self.n_mbon].mean())
        self.baseline_salience = float(max(arr[:, self.n_mbon + 1].mean(), 1e-3))
        self.margin_std = float(max(1e-4, (arr[:, MBON_CONFIRM] - arr[:, MBON_CONTRADICT]).std()))
        self.baseline_kc_coverage = float(np.mean([
            (self.run(v)["kc"] > 0).mean() for v in self._ordinary_reads(12)]))

        out = self.run(strong)
        self.calibration = {
            "ln_rate": round(float(out["ln"].mean()), 4),
            "pn_rate": round(float(out["pn"].mean()), 4),
            "kc_rate": round(float(out["kc"].mean()), 4),
            "kc_coverage": round(float((out["kc"] > 0).mean()), 4),
            "kc_coverage_probe": round(coverage, 4),
            "mbon_rate": round(float(out["mbon"].mean()), 4),
            "mbon_gain": round(float(self.mbon_gain), 4),
            "mbon_bias": [round(float(x), 4) for x in self.mbon_bias],
            "baseline_mbon": [round(float(x), 4) for x in self.baseline_mean],
            "margin_std": round(float(self.margin_std), 5),
            "baseline_kc_coverage": round(float(self.baseline_kc_coverage), 4),
            "effective_gains": {
                "orn_ln": round(float(np.mean(self.W_orn_ln[self.W_orn_ln > 0])), 3),
                "ln_pn": round(float(np.mean(self.W_ln_pn[self.W_ln_pn > 0])), 3),
                "pn_kc": round(float(np.mean(self.W_pn_kc[self.W_pn_kc > 0])), 3),
                "kc_mbon": round(float(np.mean(self.W_kc_mbon[self.W_kc_mbon > 0])), 3),
            },
        }
        return self.calibration

    # ------------------------------------------------------------------
    # feature encoding
    # ------------------------------------------------------------------
    @staticmethod
    def mirror(vec: np.ndarray, side_long: bool) -> np.ndarray:
        """Express the stimulus in the candidate's own frame.

        A short proposal is the mirror image of a long one, so the directional
        channels are flipped and the risk-on/risk-off pair swaps sides. After
        this, "channel is high" always means "this supports my proposal".
        """
        if side_long:
            return vec
        out = vec.copy()
        for ch in INVERT_CHANNELS:
            out[ch] = 1.0 - vec[ch]
        for a, b in SWAP_PAIRS:
            out[a], out[b] = vec[b], vec[a]
        return out

    @staticmethod
    def featurize(features: Dict[str, float], side_bias: float = 0.0) -> np.ndarray:
        """Map the scanner's feature dict onto the fly's sensory channels.

        Every channel is squashed to 0..1 so the sensory layer fires at a
        comparable rate regardless of the underlying units.
        """
        def g(key: str, lo: float, hi: float) -> float:
            v = float(features.get(key, 0.0) or 0.0)
            return float(np.clip((v - lo) / (hi - lo), 0.0, 1.0))

        rsi = float(features.get("rsi", 50.0) or 50.0)
        side_long = 1.0 if float(features.get("side_long", 1.0) or 0.0) >= 0.5 else 0.0
        regime = float(features.get("regime", 0.0) or 0.0)
        ema_stack = float(features.get("ema_stack", 1.0) or 0.0)

        # Channel 5 used to be built with `g(...) if v >= 0 else 1 - g(...)`,
        # which encoded a strongly NEGATIVE relative strength as bullish (1 - 0.0
        # = 1.0). A plain signed ramp over -6..6 is what the polarity wiring
        # below assumes: 0.5 is neutral, 0 is maximally bearish, 1 maximally
        # bullish. Every directional channel is built the same way.
        ch = [
            g("vol_z", -1.0, 4.0),                                    # 0 volume surprise
            g("atr_rank", 0.0, 100.0),                                # 1 volatility regime
            abs(rsi - 50.0) / 50.0,                                   # 2 RSI displacement
            1.0 if rsi < 45 else 0.0,                                 # 3 oversold flag
            1.0 if rsi > 55 else 0.0,                                 # 4 overbought flag
            g("rel_strength", -6.0, 6.0),                             # 5 relative strength
            g("range_pos", 0.0, 1.0),                                 # 6 where in the 60-bar range
            g("bb_width_rank", 0.0, 100.0),                           # 7 compression
            g("atr_pct", 0.0, 3.0),                                   # 8 absolute volatility
            abs(float(features.get("ema20_slope", 0.0) or 0.0)) / 0.5,  # 9 short trend strength
            abs(float(features.get("ema50_slope", 0.0) or 0.0)) / 0.5,  # 10 long trend strength
            1.0 if regime > 0 else 0.0,                               # 11 risk-on
            1.0 if regime < 0 else 0.0,                               # 12 risk-off
            g("btc_ret_12", -3.0, 3.0),                               # 13 market tailwind
            g("corr_proxy", 0.5, 2.2),                                # 14 beta crowding
            1.0 if ema_stack > 0 else 0.0,                            # 15 stack direction
        ]
        vec = np.clip(np.array(ch, dtype=np.float32), 0.0, 1.0)
        return np.clip(vec, 0.0, 1.4)

    def _ordinary_reads(self, k: int) -> List[np.ndarray]:
        """Sample reads from a market that is doing nothing in particular.

        These define the calibration baseline. They are drawn from the middle of
        every channel's natural range — quiet volatility, mid RSI, noise-level
        relative strength, flat slopes — and mirrored into the candidate's frame
        exactly like a real stimulus, so the baseline is directly comparable.
        """
        rng = np.random.default_rng(self.cfg.seed + 991)
        reads: List[np.ndarray] = []
        for _ in range(k):
            slope = float(rng.uniform(-0.06, 0.06))
            f = dict(TYPICAL_FEATURES)
            f["rsi"] = float(rng.uniform(38.0, 62.0))
            f["rel_strength"] = float(rng.uniform(-1.2, 1.2))
            f["range_pos"] = float(rng.uniform(0.25, 0.75))
            f["ema20_slope"] = slope
            f["ema50_slope"] = float(rng.uniform(-0.05, 0.05))
            f["regime"] = float(rng.choice([-1.0, 0.0, 1.0]))
            f["btc_ret_12"] = float(rng.uniform(-0.6, 0.6))
            f["vol_z"] = float(rng.uniform(-0.8, 1.2))
            f["atr_rank"] = float(rng.uniform(25.0, 75.0))
            f["bb_width_rank"] = float(rng.uniform(25.0, 75.0))
            f["atr_pct"] = float(rng.uniform(0.6, 1.6))
            f["corr_proxy"] = float(rng.uniform(1.1, 1.7))
            f["ema_stack"] = 1.0 if slope >= 0 else -1.0
            side_long = bool(rng.integers(0, 2))
            f["side_long"] = 1.0 if side_long else 0.0
            reads.append(self.mirror(self.featurize(f), side_long))
        return reads

    def _stimulus(self, vec: np.ndarray, t: int,
                  rng: Optional[np.random.Generator] = None) -> np.ndarray:
        """Poisson-ish sensory drive for one millisecond."""
        c = self.cfg
        pools = vec[: c.n_orn_pools] if vec.size >= c.n_orn_pools else np.pad(
            vec, (0, c.n_orn_pools - vec.size))
        rate = np.repeat(pools, c.orn_per_pool) * 55.0        # Hz-ish per ORN
        rng = rng or self.rng
        spikes = (rng.random(rate.shape) < (rate / 1000.0) * self.lif.dt_ms)
        return spikes.astype(np.float32)

    # ------------------------------------------------------------------
    # simulation
    # ------------------------------------------------------------------
    def _stimulus_rng(self, vec: np.ndarray) -> np.random.Generator:
        """Deterministic RNG keyed on the stimulus (see run())."""
        key = np.round(np.asarray(vec, dtype=np.float32) * 4096.0).astype(np.int32).tobytes()
        digest = hashlib.blake2b(key, digest_size=8,
                                 key=str(self.cfg.seed).encode()[:16] or b"soul").digest()
        return np.random.default_rng(int.from_bytes(digest, "little"))

    def run(self, vec: np.ndarray, ms: Optional[int] = None) -> Dict[str, Any]:
        """Integrate the network over one stimulus window and return firing rates."""
        c, p = self.cfg, self.lif
        T = int(ms or c.sim_ms)
        alpha = p.dt_ms / p.tau_m_ms
        trace_decay = math.exp(-p.dt_ms / p.tau_trace_ms)
        refr_steps = max(0, int(p.refractory_ms / p.dt_ms))

        # Every stimulus gets its OWN background noise, seeded from the stimulus
        # itself. Two consequences, both wanted: the same market read always
        # gives the same verdict (the UI explains decisions, and tests assert
        # them), and different reads are still independently noisy, so the
        # network never becomes a lookup table.
        rng = self._stimulus_rng(vec)

        self.v_ln[:] = 0.0
        self.v_pn[:] = 0.0
        self.v_kc[:] = 0.0
        self.trace_kc[:] = 0.0
        self.refractory[:] = 0

        spk_ln = np.zeros(self.n_ln, dtype=np.float32)
        spk_kc = np.zeros(self.n_kc, dtype=np.float32)
        rate_ln = np.zeros(self.n_ln, dtype=np.float32)
        rate_pn = np.zeros(self.n_pn, dtype=np.float32)
        rate_kc = np.zeros(self.n_kc, dtype=np.float32)
        salience_acc = 0.0

        bg_ln = (c.background_hz / 1000.0) * p.dt_ms
        bg_pn = bg_ln * 0.6

        for t in range(T):
            orn = self._stimulus(vec, t, rng)

            # ---- ORN -> LN (with lateral recurrent mixing) ---------------
            drive = self.W_orn_ln.T @ orn + self.W_ln_ln.T @ spk_ln
            drive += (rng.random(self.n_ln) < bg_ln).astype(np.float32) * 0.55
            self.v_ln += alpha * (-self.v_ln + drive)
            self.refractory = np.maximum(0.0, self.refractory - 1)
            fired = (self.v_ln >= p.v_thresh) & (self.refractory <= 0)
            self.v_ln[fired] = p.v_reset
            self.refractory[fired] = refr_steps
            spk_ln = fired.astype(np.float32)
            if t >= c.warmup_ms:
                rate_ln += spk_ln

            # ---- LN -> PN -----------------------------------------------
            pn_drive = self.W_ln_pn.T @ spk_ln
            pn_drive += (rng.random(self.n_pn) < bg_pn).astype(np.float32) * 0.5
            self.v_pn += alpha * (-self.v_pn + pn_drive)
            fired_pn = self.v_pn >= p.v_thresh
            self.v_pn[fired_pn] = p.v_reset
            if t >= c.warmup_ms:
                rate_pn += fired_pn.astype(np.float32)

            # ---- PN -> KC (sparse expansion, APL-normalised) ------------
            kc_drive = self.W_pn_kc.T @ fired_pn.astype(np.float32)
            # The APL neuron is a single cell that reads global KC activity and
            # inhibits the whole mushroom body proportionally. Subtracting a
            # multiple of the mean drive is what leaves only the strongest cells
            # active, i.e. a sparse expansion code.
            kc_drive = np.maximum(0.0, kc_drive - c.apl_gain * float(kc_drive.mean())) * self.kc_gain
            self.v_kc += alpha * (-self.v_kc + kc_drive)
            fired_kc = self.v_kc >= p.v_thresh
            self.v_kc[fired_kc] = p.v_reset
            spk_kc = fired_kc.astype(np.float32)
            if t >= c.warmup_ms:
                rate_kc += spk_kc

            if t >= c.warmup_ms:
                salience_acc += float(spk_kc.sum())

        window = max(1, T - c.warmup_ms)
        kc_activity = rate_kc / window
        out = {
            "ln": rate_ln / window, "pn": rate_pn / window,
            "kc": kc_activity, "mbon": self._readout(kc_activity),
            # unclipped drive level: calibrate() solves for the gain that puts an
            # ordinary read on the target output rate
            "readout_raw": float(np.mean(self.W_kc_mbon.T @ kc_activity)),
            "salience": min(1.0, (salience_acc / window) / max(1.0, self.n_kc * 0.12)),
        }
        self.last_kc = out["kc"]
        return out

    # ------------------------------------------------------------------
    # decision
    # ------------------------------------------------------------------
    def judge(self, symbol: str, features: Dict[str, float], side: Optional[str] = None,
              threshold: float = 1.3) -> FlySignal:
        """Run the network and read the descending output.

        ``threshold`` is in units of the margin distribution the network shows for
        ordinary tape conditions: 1.3 means "the gap between the confirm and
        contradict outputs is larger than 1.3 standard deviations of the gap the
        market normally produces".
        """
        side_long = 1.0 if (side or "LONG") == "LONG" else 0.0
        features = {**features, "side_long": side_long}
        raw = self.featurize(features)
        vec = self.mirror(raw, bool(side_long))
        return self.judge_vec(symbol, vec, threshold)

    def judge_vec(self, symbol: str, vec: np.ndarray, threshold: float = 1.3,
                  out: Optional[Dict[str, Any]] = None) -> FlySignal:
        """Judge an already-encoded, already-mirrored stimulus.

        Split out from judge() so the offline harnesses can push exact channel
        vectors (and mirrored pairs) through the same decision path the server
        uses -- one code path, no test-only branch.
        """
        out = self.run(vec) if out is None else out
        mb = out["mbon"]

        confirm = float(mb[MBON_CONFIRM]) if mb.size > MBON_CONFIRM else 0.0
        contradict = float(mb[MBON_CONTRADICT]) if mb.size > MBON_CONTRADICT else 0.0
        wait_rate = float(mb[MBON_WAIT]) if mb.size > MBON_WAIT else 0.0

        # The two competing outputs are z-scored against the calibrated
        # "ordinary tape" baseline, and the decision is their MARGIN: a fly that
        # cannot take sides is useless, and the two columns are built to be
        # anti-correlated, so the difference is the informative quantity while
        # their common level (the market's overall liveliness) cancels out.
        z_confirm = (confirm - float(self.baseline_mean[MBON_CONFIRM])) / max(
            1e-6, float(self.baseline_std[MBON_CONFIRM]))
        z_contradict = (contradict - float(self.baseline_mean[MBON_CONTRADICT])) / max(
            1e-6, float(self.baseline_std[MBON_CONTRADICT]))
        z_wait = (wait_rate - float(self.baseline_mean[MBON_WAIT])) / max(
            1e-6, float(self.baseline_std[MBON_WAIT]))

        margin = confirm - contradict
        scale = max(1e-6, float(self.margin_std))
        z_margin = margin / scale
        winner_z = max(z_confirm, z_contradict)

        # The decision reads BOTH pools against their own baselines, not just
        # their difference. A difference-only rule is dominated by the market's
        # overall liveliness: a violent tape lifts every output, the confirm pool
        # rises faster (it is wired to five sensory channels against three), and
        # the fly then "confirms" blow-off tops it should refuse. Requiring the
        # winning pool to clear its OWN ordinary level by `threshold` removes
        # that common mode.
        if z_confirm >= threshold and z_confirm >= z_contradict:
            direction = "CONFIRM"
        elif z_contradict >= threshold and z_contradict > z_confirm:
            direction = "CONTRADICT"
        else:
            direction = "WAIT"

        conviction = float(np.clip(winner_z / 3.0, 0.0, 1.0)) if direction != "WAIT" \
            else float(np.clip(max(0.0, winner_z) / 3.0, 0.0, 1.0))
        # salience = how far the mushroom-body code departs from an ordinary tape
        coverage = float((out["kc"] > 0).mean())
        surprise = (coverage - self.baseline_kc_coverage) / max(0.02, 3.0 * self.baseline_kc_coverage)
        salience = float(np.clip(0.65 * conviction + 0.35 * (surprise / 2.0), 0.0, 1.0))
        return FlySignal(
            symbol=symbol, direction=direction, conviction=conviction, salience=salience,
            kc_sparsity=coverage,
            rates={"ln": float(out["ln"].mean()), "pn": float(out["pn"].mean()),
                   "kc": float(out["kc"].mean()),
                   "confirm": confirm, "contradict": contradict, "wait": wait_rate,
                   "z_confirm": z_confirm, "z_contradict": z_contradict,
                   "z_wait": z_wait, "z_margin": z_margin},
            features=vec,
        )


    # ------------------------------------------------------------------
    # learning
    # ------------------------------------------------------------------
    def reinforce(self, features: np.ndarray, reward: float, lr: float = 0.05,
                  action: int = -1) -> None:
        """Three-factor plasticity on the Kenyon-cell -> MBON weights.

        Re-running the stimulus recovers the eligibility trace (which Kenyon
        cells were active when the fly made its call); ``reward`` is the third
        factor. The winning output's column is pulled toward the cells that were
        active — up when the trade worked, down when it did not. Columns are
        renormalised so the readout stays a weighted average and cannot drift
        into saturation.
        """
        vec = np.asarray(features, dtype=np.float32)
        out = self.run(vec)
        kc = out["kc"]
        total = float(kc.sum())
        if total <= 0.0:
            return
        if action in (MBON_CONFIRM, MBON_CONTRADICT):
            winner = int(action)
        else:
            winner = MBON_CONFIRM if out["mbon"][MBON_CONFIRM] >= out["mbon"][MBON_CONTRADICT] else MBON_CONTRADICT
        post = np.zeros(self.n_mbon, dtype=np.float32)
        post[winner] = 1.0

        elig = kc / total                       # L1-normalised eligibility trace
        delta = lr * float(np.clip(reward, -1.5, 1.5)) * np.outer(elig, post)
        self.W_kc_mbon += delta
        self._normalise_readout()

        self.plasticity_events += 1
        self.reward_history.append(float(np.clip(reward, -1.5, 1.5)))
        if len(self.reward_history) > 200:
            del self.reward_history[:-200]

    def stats(self) -> Dict[str, Any]:
        recent = self.reward_history[-50:]
        return {
            "neurons": {"orn": self.n_orn, "ln": self.n_ln, "pn": self.n_pn,
                        "kc": self.n_kc, "mbon": self.n_mbon},
            "synapses": int((self.W_orn_ln > 0).sum() + (self.W_ln_ln > 0).sum()
                            + (self.W_ln_pn > 0).sum() + (self.W_pn_kc > 0).sum()
                            + (self.W_kc_mbon != 0).sum()),
            "plasticity_events": self.plasticity_events,
            "mean_recent_reward": round(float(np.mean(recent)), 4) if recent else 0.0,
            "sim_ms": self.cfg.sim_ms,
            "calibration": self.calibration,
            "backend": "numpy LIF (FlyWire-inspired)",
        }
