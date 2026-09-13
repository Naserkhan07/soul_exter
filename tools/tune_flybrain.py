"""Calibrate and sanity-check the FlyBrain scout.

Runs the spiking network over
  (a) synthetic weak / medium / strong stimuli, and
  (b) a deck of REAL scanner candidates,
and reports the firing rates and decision spread. Use it after changing any
population size or gain.

    python tools/tune_flybrain.py
"""
from __future__ import annotations

import asyncio
import collections
import pathlib
import random
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soul.config import load_config
from soul.flybrain import FlyBrain, FlyConfig
from soul.market import MarketFeed
from soul.scanner import Scanner

BARS = "─" * 74


def synthetic(fb: FlyBrain, strength: float, n: int = 120) -> None:
    rng = random.Random(11)
    dirs, rates, spars = collections.Counter(), [], []

    def feats(k: float) -> dict:
        return {
            "vol_z": rng.uniform(-0.5, 3.5) * k, "atr_rank": rng.uniform(5, 95),
            "rsi": rng.uniform(20, 85), "rel_strength": rng.gauss(0, 4) * k,
            "range_pos": rng.random(), "bb_width_rank": rng.uniform(0, 100),
            "atr_pct": rng.uniform(0.3, 2.5), "ema20_slope": rng.gauss(0, 0.3) * k,
            "ema50_slope": rng.gauss(0, 0.15) * k, "regime": rng.choice([-1, 0, 1]),
            "btc_ret_12": rng.gauss(0, 1.2) * k, "corr_proxy": rng.uniform(0.8, 2.0),
            "ema_stack": rng.choice([-1.0, 1.0]),
        }

    for _ in range(n):
        sig = fb.judge("SYN/USDT", feats(strength), side="LONG")
        dirs[sig.direction] += 1
        rates.append(sig.rates["kc"])
        spars.append(sig.kc_sparsity)
    print(f"  strength {strength:<4} {dict(dirs)}  kc_rate={np.mean(rates):.4f} "
          f"kc_sparsity={np.mean(spars):.3f}")


async def real_candidates(n_scans: int = 12):
    cfg = load_config()
    cfg.market_source = "sim"
    cfg.min_score = 0.05
    cfg.max_candidates_per_scan = 5
    cfg.trade_cooldown_s = 0
    mkt = MarketFeed(cfg)
    await mkt.start()
    scanner = Scanner(cfg, mkt)
    deck, seen = [], set()
    for _ in range(n_scans):
        scanner.cooldowns.clear()
        for t in await scanner.scan(force=True):
            key = (t.symbol, t.side, t.strategy)
            if key in seen:
                continue
            seen.add(key)
            deck.append(t)
        for _ in range(4):
            mkt._step_simulator()
    return deck


def main() -> int:
    t0 = time.time()
    fb = FlyBrain(FlyConfig())
    print(f"FlyBrain built + self-calibrated in {time.time() - t0:.2f}s")
    print(BARS)
    print("calibration (maximal stimulus):")
    for k, v in fb.calibration.items():
        print(f"  {k}: {v}")
    print(BARS)
    print("synthetic stimuli:")
    for s in (0.15, 0.5, 1.0):
        synthetic(fb, s)

    print(BARS)
    deck = asyncio.run(real_candidates())
    print(f"real scanner candidates: {len(deck)}")
    dirs = collections.Counter()
    by_side = collections.defaultdict(collections.Counter)
    conv, sal = [], []
    t0 = time.time()
    for t in deck:
        f = {**t.features, "side_long": 1.0 if t.side == "LONG" else 0.0}
        sig = fb.judge(t.symbol, f, side=t.side)
        dirs[sig.direction] += 1
        by_side[t.side][sig.direction] += 1
        conv.append(sig.conviction)
        sal.append(sig.salience)
    dt = time.time() - t0
    print(f"  decisions: {dict(dirs)}   mean conviction {np.mean(conv):.3f}   "
          f"mean salience {np.mean(sal):.3f}")
    print("  per side (CONFIRM = the fly backs the scanner's proposal):")
    for side, c in sorted(by_side.items()):
        n = sum(c.values())
        print(f"    {side:<5} confirm {c.get('CONFIRM', 0)}/{n}  wait {c.get('WAIT', 0)}/"
              f"{n}  contradict {c.get('CONTRADICT', 0)}/{n}   {dict(c)}")
    print(f"  speed: {dt / max(1, len(deck)) * 1000:.1f} ms/symbol")

    print("  sample of the deck:")
    for t in deck[:6]:
        f = {**t.features, "side_long": 1.0 if t.side == "LONG" else 0.0}
        sig = fb.judge(t.symbol, f, side=t.side)
        print(f"    {t.symbol:<10} {t.side:<5} {t.strategy:<19} -> {sig.direction:<10} "
              f"conv={sig.conviction:.2f} sal={sig.salience:.2f} z={sig.rates['z_margin']:+.2f}")

    # plasticity: does rewarding a pattern move the weights?
    before = fb.W_kc_mbon.copy()
    for _ in range(30):
        f = fb.featurize(deck[0].features if deck else {})
        fb.run(f)
        fb.reinforce(f, reward=1.0, action=0)
    moved = float(np.abs(fb.W_kc_mbon - before).sum())
    print(BARS)
    print(f"reward-modulated plasticity: {fb.plasticity_events} events, "
          f"|ΔW| on KC→MBON = {moved:.3f}")
    print("stats:", {k: v for k, v in fb.stats().items() if k != "calibration"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
