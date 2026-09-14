"""Grid study — calibrate the ticket geometry + entry gate that actually pays.

Earlier sweeps showed the floor's default ticket (SL 1.15xATR / TP 2.45xATR over
150s) is a coin flip on the tape, and that a signal picked on one seed often
fails on the next. This script therefore searches a *small, honest* grid of
geometries against a few entry gates over several feed seeds and reports only
cells that hold up per-seed.

Usage (backend/):
    python3 scripts/grid_study.py --symbols 12 --cycles 16
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
SLS = (1.0, 1.3, 1.6)
TPS = (2.0, 2.9, 3.6)
HORIZONS = (600.0, 1200.0, 1800.0)
GEOMS: List[Tuple[float, float, float]] = [(sl, tp, h) for h in HORIZONS for sl in SLS for tp in TPS]


def trend(m: Dict[str, float]) -> float:
    return 0.62 * math.tanh(m["slope21"] * 120.0) + 0.38 * math.tanh(m["slope50"] * 60.0)


GATES: List[Tuple[str, Callable[[Dict[str, float], float], bool]]] = [
    ("eff", lambda m, ts: m["efficiency"] > 0.32 and abs(ts) > 0.30),
    ("eff_strict", lambda m, ts: m["efficiency"] > 0.40 and abs(ts) > 0.45),
    ("any", lambda m, ts: abs(ts) > 0.12),
    ("conv35", lambda m, ts: abs(ts) > 0.35),
    ("conv35+cont", lambda m, ts: abs(ts) > 0.35 and m["stretch"] * (1 if ts > 0 else -1) > 0.0),
    ("conv35+pullback", lambda m, ts: abs(ts) > 0.35 and m["stretch"] * (1 if ts > 0 else -1) < -0.4),
]


def run(seed: int, syms: List[str], cycles: int, offset: float) -> Dict[Tuple, List[float]]:
    feed = MarketFeed(syms, seed=seed)
    stats: Dict[Tuple, List[float]] = defaultdict(list)
    open_probes: List[Dict] = []
    for _cycle in range(cycles):
        for _ in range(int(60.0 / STEP)):
            feed.advance(STEP)
            for p in open_probes:
                price = feed.tickers[p["symbol"]].last_price
                p["age"] += STEP
                s = p["sgn"]
                r = (price - p["entry"]) * s / p["risk"]
                for gi, (slm, tpm, hor) in enumerate(GEOMS):
                    if p["done"][gi]:
                        continue
                    hit = None
                    if r <= -slm * p["atr"] / p["risk"] * p["risk"] / p["risk"] and False:
                        pass
                    move = (price - p["entry"]) * s
                    if move <= -p["atr"] * slm:
                        hit, r = "sl", -1.0
                    elif move >= p["atr"] * tpm:
                        hit, r = "tp", tpm / slm
                    if hit or p["age"] >= hor:
                        p["done"][gi] = True
                        stats[(slm, tpm, hor, p["gate"])].append(r if hit != "sl" else -1.0)
        open_probes = [p for p in open_probes if not all(p["done"])]
        for sym in syms:
            m = compute_metrics(feed.tickers[sym])
            if m is None:
                continue
            ts = trend(m)
            a = max(m["atr"], 1e-9)
            for gate, test in GATES:
                if not test(m, ts):
                    continue
                sgn = 1.0 if ts > 0 else -1.0
                entry = m["price"] + a * offset * sgn
                open_probes.append(dict(symbol=sym, sgn=sgn, atr=a, entry=entry, risk=a * max(SLS),
                                        age=0.0, done=[False] * len(GEOMS), gate=gate))
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=12)
    ap.add_argument("--cycles", type=int, default=16)
    ap.add_argument("--seeds", default="20250914,777,31337")
    ap.add_argument("--offset", type=float, default=0.12)
    ap.add_argument("--min-n", type=int, default=150)
    ap.add_argument("--sls", default="", help="comma list override, e.g. 1.3")
    ap.add_argument("--tps", default="", help="comma list override, e.g. 2.0")
    ap.add_argument("--horizons", default="", help="comma list override, e.g. 300,600")
    ap.add_argument("--gates", default="", help="comma subset of gate names to test")
    args = ap.parse_args()

    global GEOMS, GATES
    if args.sls or args.tps or args.horizons:
        sls = tuple(float(x) for x in (args.sls or "1.0,1.3,1.6").split(","))
        tps = tuple(float(x) for x in (args.tps or "2.0,2.9,3.6").split(","))
        hors = tuple(float(x) for x in (args.horizons or "600,1200,1800").split(","))
        GEOMS = [(sl, tp, h) for h in hors for sl in sls for tp in tps]
    if args.gates:
        want = {g.strip() for g in args.gates.split(",")}
        GATES = [g for g in GATES if g[0] in want]
    syms = default_enabled()[: max(4, args.symbols)]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    total: Dict[Tuple, List[float]] = defaultdict(list)
    per_seed: Dict[Tuple, List[float]] = defaultdict(list)
    for seed in seeds:
        part = run(seed, syms, args.cycles, args.offset)
        for k, v in part.items():
            total[k].extend(v)
            per_seed[k].append(statistics.fmean(v) if v else 0.0)

    print(f"seeds {seeds} · {len(syms)} symbols · {args.cycles} cycles · {len(GEOMS)} geometries")
    print(f"\n{'SLxATR':>7s} {'TPxATR':>7s} {'horizon':>8s} {'gate':>16s} {'n':>6s} {'win':>6s} "
          f"{'exp R':>8s} {'worst seed':>11s}")
    rows = []
    for (slm, tpm, hor, gate), vals in total.items():
        if len(vals) < args.min_n:
            continue
        exp = statistics.fmean(vals)
        win = sum(1 for v in vals if v > 0) / len(vals)
        worst = min(per_seed[(slm, tpm, hor, gate)])
        rows.append((worst, exp, slm, tpm, hor, gate, len(vals), win))
    for worst, exp, slm, tpm, hor, gate, n, win in sorted(rows, reverse=True)[:24]:
        print(f"{slm:7.2f} {tpm:7.2f} {hor:8.0f} {gate:>16s} {n:6d} {win:6.2f} {exp:+8.3f} "
              f"{worst:+11.3f}")
    if not rows:
        print("no cell cleared the sample floor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
