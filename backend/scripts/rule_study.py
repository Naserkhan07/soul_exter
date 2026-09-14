"""Rule study — which (entry gate, ticket geometry) pair is genuinely profitable?

Sweeps plausible entry gates (regime conviction, efficiency, volatility rank,
pullback/continuation) against plausible stop/target/horizon geometries across
several feed seeds, so calibration is not fitted to a single tape. The winning
pair is what the fly is allowed to strike on and what the council votes on.

Usage (backend/):
    python3 scripts/rule_study.py --symbols 20 --cycles 24
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from collections import defaultdict
from typing import Callable, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.brain.features import compute_metrics
from soul_exter.market.feed import MarketFeed
from soul_exter.market.universe import default_enabled

STEP = 6.0
GEOMS: List[Tuple[str, float, float, float]] = [
    ("wide 1.30/2.90 @420s", 1.30, 2.90, 420.0),
    ("wide 1.30/2.90 @600s", 1.30, 2.90, 600.0),
    ("xwide 1.60/3.40 @420s", 1.60, 3.40, 420.0),
    ("base 1.15/2.45 @300s", 1.15, 2.45, 300.0),
    ("tight 1.00/2.00 @420s", 1.00, 2.00, 420.0),
]


def trend(m: Dict[str, float]) -> float:
    return 0.62 * math.tanh(m["slope21"] * 120.0) + 0.38 * math.tanh(m["slope50"] * 60.0)


GATES: List[Tuple[str, Callable[[Dict[str, float], float], bool]]] = [
    ("any", lambda m, ts: abs(ts) > 0.12),
    ("conv35", lambda m, ts: abs(ts) > 0.35),
    ("conv55", lambda m, ts: abs(ts) > 0.55),
    ("conv35+eff", lambda m, ts: abs(ts) > 0.35 and m["efficiency"] > 0.30),
    ("conv35+volhi", lambda m, ts: abs(ts) > 0.35 and m["atr_rank"] > 0.7),
    ("conv35+pb", lambda m, ts: abs(ts) > 0.35 and (m["stretch"] * (1 if ts > 0 else -1)) < 0.2),
    ("conv55+eff", lambda m, ts: abs(ts) > 0.55 and m["efficiency"] > 0.30),
]


def run(seed: int, syms: List[str], cycles: int, entry_offset: float) -> Dict[Tuple, List[float]]:
    feed = MarketFeed(syms, seed=seed)
    stats: Dict[Tuple, List[float]] = defaultdict(list)
    open_probes: List[Dict] = []
    for _cycle in range(cycles):
        for _ in range(int(60.0 / STEP)):
            feed.advance(STEP)
            for p in open_probes:
                if all(p["done"]):
                    continue
                price = feed.tickers[p["symbol"]].last_price
                p["age"] += STEP
                for gi, (_n, _sl, _tp, hor) in enumerate(GEOMS):
                    if p["done"][gi]:
                        continue
                    r = ((price - p["entry"]) if p["dirn"] == "long"
                         else (p["entry"] - price)) / p["risk"]
                    hit = None
                    if p["dirn"] == "long":
                        if price <= p["sl"][gi]:
                            hit, r = "sl", -1.0
                        elif price >= p["tp"][gi]:
                            hit, r = "tp", (p["tp"][gi] - p["entry"]) / p["risk"]
                    else:
                        if price >= p["sl"][gi]:
                            hit, r = "sl", -1.0
                        elif price <= p["tp"][gi]:
                            hit, r = "tp", (p["entry"] - p["tp"][gi]) / p["risk"]
                    if hit or p["age"] >= hor:
                        p["done"][gi] = True
                        stats[(GEOMS[gi][0], p["gate"])].append(r)
        open_probes = [p for p in open_probes if not all(p["done"])]
        for sym in syms:
            m = compute_metrics(feed.tickers[sym])
            if m is None:
                continue
            ts = trend(m)
            a = max(m["atr"], 1e-9)
            for gate_name, test in GATES:
                if not test(m, ts):
                    continue
                dirn = "long" if ts > 0 else "short"
                entry = m["price"] + a * entry_offset * (1 if dirn == "long" else -1)
                p = dict(symbol=sym, dirn=dirn, age=0.0, done=[False] * len(GEOMS),
                         gate=gate_name, entry=entry, risk=a * GEOMS[0][1], sl=[], tp=[])
                for (_n, slm, tpm, _h) in GEOMS:
                    s = 1 if dirn == "long" else -1
                    p["sl"].append(entry - s * a * slm)
                    p["tp"].append(entry + s * a * tpm)
                p["risk"] = a * GEOMS[0][1]
                open_probes.append(p)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=20)
    ap.add_argument("--cycles", type=int, default=24)
    ap.add_argument("--seeds", default="20250914,777,31337")
    ap.add_argument("--entry-offset", type=float, default=0.12)
    args = ap.parse_args()

    syms = default_enabled()[: max(4, args.symbols)]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    total: Dict[Tuple, List[float]] = defaultdict(list)
    for seed in seeds:
        part = run(seed, syms, args.cycles, args.entry_offset)
        for k, v in part.items():
            total[k].extend(v)

    print(f"seeds {seeds} · {len(syms)} symbols · {args.cycles} cycles each\n")
    print(f"{'geometry':24s} {'gate':14s} {'n':>6s} {'win':>6s} {'tp':>6s} {'exp R':>8s} "
          f"{'total R':>9s} {'per-seed':>10s}")
    rows = []
    for (geom, gate), vals in total.items():
        if len(vals) < 60:
            continue
        win = sum(1 for v in vals if v > 0) / len(vals)
        tp = sum(1 for v in vals if v > 1.0) / len(vals)
        exp = statistics.fmean(vals)
        per = exp / max(1, len(seeds))
        rows.append((exp, geom, gate, len(vals), win, tp, sum(vals), per))
    for exp, geom, gate, n, win, tp, tot, per in sorted(rows, reverse=True):
        print(f"{geom:24s} {gate:14s} {n:6d} {win:6.2f} {tp:6.2f} {exp:+8.3f} {tot:+9.1f} "
              f"{per:+10.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
