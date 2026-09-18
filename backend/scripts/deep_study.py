"""Deep-market study — do the new senses actually pay?

Walks the live tape (synthetic regime + factor model, or real venue history
when the network is up) thousands of steps, samples hypothetical entries under
the floor's exact stop/target geometry (SL 1.0xATR / TP 2.2xATR by default),
and reports expectancy (R) bucketed by every deep-market channel the fly brain
now sees:

    bar-derived : range_pos, atr_expand, body_conv, hurst_vr, autocorr1,
                  vwap_dist, flow_imb
    correlation : resid_z (bloc-lag convergence), corr regime

Usage (backend/):
    python3 scripts/deep_study.py --symbols 24 --steps 4000
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from typing import Dict, List

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.brain.correlation import CorrelationMonitor, _returns
from soul_exter.brain.features import (Ticker, build_signal_levels, compute_metrics,
                                       trend_composite)
from soul_exter.market.feed import MarketFeed
from soul_exter.market.universe import UNIVERSE, default_enabled, fx_legs

STEP = 6.0
HORIZON_S = 150.0
SL_ATR, TP_ATR = 1.00, 2.20

FIELDS = ["range_pos", "atr_expand", "body_conv", "hurst_vr", "autocorr1",
          "vwap_dist", "flow_imb", "efficiency", "resid_z"]


def probe(feed: MarketFeed, sym: str, entry: float, sl: float, tp: float,
          direction: str) -> float:
    """Walk the tape forward to first touch; return realised R."""
    left = HORIZON_S
    risk = max(abs(entry - sl), 1e-12)
    while left > 0:
        feed.advance(STEP)
        left -= STEP
        price = feed.tickers[sym].last_price
        if direction == "long":
            if price <= sl:
                return -1.0
            if price >= tp:
                return (tp - entry) / risk
        else:
            if price >= sl:
                return -1.0
            if price <= tp:
                return (entry - tp) / risk
    price = feed.tickers[sym].last_price
    return ((price - entry) if direction == "long" else (entry - price)) / risk


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=24)
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=90210)
    args = ap.parse_args()

    enabled = default_enabled()[:args.symbols]
    feed = MarketFeed(enabled, seed=args.seed)
    corr = CorrelationMonitor(feed)

    samples: Dict[str, List[Tuple[float, float]]] = defaultdict(list)   # field -> (val, R)
    bloc: Dict[str, List[float]] = defaultdict(list)                    # trigger -> Rs
    sym_i = 0
    every = 7
    for step_no in range(args.steps):
        feed.advance(STEP)
        if step_no % 25 == 0:
            corr.update(enabled)
        if step_no % every:
            continue
        sym = enabled[sym_i % len(enabled)]
        sym_i += 1
        t = feed.tickers[sym]
        if not t.ready(90):
            continue
        m = compute_metrics(t)
        if m is None:
            continue
        cf = corr.features_for(sym)
        m.update({k: v for k, v in cf.items() if k != "peer"})
        tc = trend_composite(m)
        direction = "long" if tc >= 0 else "short"
        levels = build_signal_levels(m, direction, sl_atr=SL_ATR, tp_atr=TP_ATR)
        r = probe(feed, sym, levels["entry"], levels["stop_loss"], levels["take_profit"],
                  direction)
        for f in FIELDS:
            if f in m:
                samples[f].append((float(m[f]), r))

        # ---- bloc-lag strategy sweep: resid_z beyond threshold -> converge
        rho = cf.get("corr_bloc", 0.0)
        if peer_dir_ok(rho) and abs(cf.get("resid_z", 0.0)) >= 1.0:
            d2 = "long" if cf["resid_z"] < 0 else "short"
            lv = build_signal_levels(m, d2, sl_atr=SL_ATR, tp_atr=TP_ATR)
            r2 = probe(feed, sym, lv["entry"], lv["stop_loss"], lv["take_profit"], d2)
            for trig in (1.0, 1.3, 1.5, 1.8, 2.1):
                if abs(cf["resid_z"]) >= trig:
                    bloc[f"z>={trig}"].append(r2)

    print(f"symbols={len(enabled)} steps={args.steps} samples={len(samples.get('efficiency', []))}")
    print(f"{'channel':<12} {'q1':>7} {'q2':>7} {'q3':>7} {'q4':>7}   (mean R per quartile, q4=high)")
    for f in FIELDS:
        rows = samples.get(f) or []
        if len(rows) < 80:
            print(f"{f:<12}  (insufficient samples: {len(rows)})")
            continue
        rows.sort(key=lambda x: x[0])
        vals = np.array([v for v, _ in rows], dtype=np.float64)
        rs = np.array([r for _, r in rows], dtype=np.float64)
        qs = np.quantile(vals, [0.25, 0.5, 0.75])
        means = []
        for lo, hi in zip([-9e9, *qs], [*qs, 9e9]):
            mask = (vals > lo) & (vals <= hi) if lo != -9e9 else vals <= hi
            means.append(float(rs[mask].mean()) if mask.any() else 0.0)
        print(f"{f:<12} " + " ".join(f"{x:>7.3f}" for x in means))
    print("\nbloc-lag convergence (residual-z trigger sweep):")
    for trig in sorted(bloc):
        rs = bloc[trig]
        if len(rs) >= 10:
            wins = sum(1 for x in rs if x > 0)
            print(f"  {trig:<7} n={len(rs):<5} hit={wins / len(rs):.2f} "
                  f"meanR={float(np.mean(rs)):+.3f}")
        else:
            print(f"  {trig:<7} n={len(rs)}")


def peer_dir_ok(rho: float) -> bool:
    return abs(rho) >= 0.72


if __name__ == "__main__":
    main()
