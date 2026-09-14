"""Character study — calibrate the tape so the council's mandates are earned.

The floor is allowed to claim an edge only if the tape *has* one. This script
searches the market's structural character (persistent order flow, dealer fade
of overshoots, trend drift, regime mix) against two rule families:

  FADE   fade an over-extended auction (|stretch| large) back to fair value
  TREND  follow an efficient trend, entering on strength

and reports, for each candidate character, the *worst* seed's expectancy for
each rule family. Characters where at least one family is robustly profitable
are what the fly is calibrated against and what the judges are scored on.

Usage (backend/):
    python3 scripts/character_study.py --symbols 12 --cycles 16
"""
from __future__ import annotations

import argparse
import itertools
import math
import os
import statistics
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.brain.features import compute_metrics
from soul_exter.market.feed import InstrumentState, MarketFeed
from soul_exter.market.universe import default_enabled

STEP = 6.0

FAMILIES = {
    # name: (gate, geometry (sl_atr, tp_atr, horizon))
    "fade": (lambda m: abs(m["stretch"]) > 1.5, (1.80, 1.20, 480.0)),
    "fade_tight": (lambda m: abs(m["stretch"]) > 1.5, (1.40, 1.00, 360.0)),
    "trend": (lambda m: m["efficiency"] > 0.32 and abs(_trend(m)) > 0.30, (1.20, 2.20, 900.0)),
    "trend_fast": (lambda m: m["efficiency"] > 0.32 and abs(_trend(m)) > 0.30, (1.00, 1.60, 480.0)),
}


def _trend(m: Dict[str, float]) -> float:
    return 0.62 * math.tanh(m["slope21"] * 120.0) + 0.38 * math.tanh(m["slope50"] * 60.0)


def run(seed: int, syms: List[str], cycles: int) -> Dict[str, List[float]]:
    feed = MarketFeed(syms, seed=seed)
    out: Dict[str, List[float]] = {k: [] for k in FAMILIES}
    pend: List[Dict] = []
    for _cycle in range(cycles):
        for _ in range(int(60.0 / STEP)):
            feed.advance(STEP)
            for p in pend:
                if p["done"]:
                    continue
                price = feed.tickers[p["symbol"]].last_price
                p["age"] += STEP
                move = (price - p["entry"]) * p["sgn"]
                sl_atr, tp_atr, hor = FAMILIES[p["fam"]][1]
                if move <= -p["atr"] * sl_atr:
                    p["done"] = True
                    out[p["fam"]].append(-1.0)
                elif move >= p["atr"] * tp_atr:
                    p["done"] = True
                    out[p["fam"]].append(tp_atr / sl_atr)
                else:
                    r = move / (p["atr"] * sl_atr)
                    if p["age"] >= hor:
                        p["done"] = True
                        out[p["fam"]].append(r)
        pend = [p for p in pend if not p["done"]]
        for sym in syms:
            m = compute_metrics(feed.tickers[sym])
            if m is None:
                continue
            a = max(m["atr"], 1e-9)
            ts = _trend(m)
            for fam, (gate, _geom) in FAMILIES.items():
                if not gate(m):
                    continue
                if fam.startswith("fade"):
                    sgn = -1.0 if m["stretch"] > 0 else 1.0
                else:
                    sgn = 1.0 if ts > 0 else -1.0
                pend.append(dict(symbol=sym, fam=fam, sgn=sgn, atr=a, age=0.0, done=False,
                                 entry=m["price"] + a * 0.10 * sgn))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=12)
    ap.add_argument("--cycles", type=int, default=16)
    ap.add_argument("--seeds", default="20250914,777,31337")
    ap.add_argument("--min-n", type=int, default=60)
    args = ap.parse_args()

    syms = default_enabled()[: max(4, args.symbols)]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    combos = []
    for share in [(0.10, 0.18), (0.14, 0.24), (0.22, 0.34)]:
        for pull in [0.12, 0.26, 0.45]:
            for mix in [(0.30, 0.30, 0.28, 0.12), (0.20, 0.20, 0.44, 0.16)]:
                combos.append((share, pull, mix))

    print(f"{'momo share':>12s} {'pull':>6s} {'mix':>16s} " +
          " ".join(f"{k:>18s}" for k in FAMILIES))
    best = []
    for share, pull, mix in combos:
        InstrumentState.MOMO_SHARE = share
        InstrumentState.RANGE_PULL = pull
        InstrumentState.SQUEEZE_PULL = pull * 0.6
        InstrumentState.REGIME_MIX = mix
        per_seed: Dict[str, List[statistics.StatisticsError]] = {k: [] for k in FAMILIES}
        counts: Dict[str, List[int]] = {k: [] for k in FAMILIES}
        for seed in seeds:
            part = run(seed, syms, args.cycles)
            for fam, vals in part.items():
                per_seed[fam].append(statistics.fmean(vals) if vals else 0.0)
                counts[fam].append(len(vals))
        cells = {}
        for fam in FAMILIES:
            if min(counts[fam]) < args.min_n:
                cells[fam] = None
                continue
            worst = min(per_seed[fam])
            mean = statistics.fmean(per_seed[fam])
            cells[fam] = (worst, mean, statistics.fmean(counts[fam]))
        line = f"{str(share):>12s} {pull:6.2f} {str(mix):>16s} "
        line += " ".join(
            (f"{v[0]:+6.2f}/{v[1]:+6.2f}" if v else "     n/a    ").rjust(18)
            for v in cells.values())
        print(line)
        score = max([v[0] for v in cells.values() if v] or [-9])
        best.append((score, share, pull, mix, cells))
    print("\nbest by worst-seed expectancy:")
    for score, share, pull, mix, cells in sorted(best, reverse=True)[:5]:
        fams = ", ".join(f"{k} {v[0]:+.3f}" for k, v in cells.items() if v)
        print(f"  momo {share} pull {pull} mix {mix} → {fams}")
        print(f"      {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
