"""Geometry sweep — which stop/target/horizon pays on the tape the floor trades?

The first edge study showed the *direction rule* is where the money is
(trend-aligned entries: +0.11R expected, counter-trend: -0.04R) and that most
tickets resolve on the clock rather than on the target (65% timeouts). This
script sweeps the ticket geometry that the council votes on, always under the
trend-aligned rule, so the floor can be calibrated to a genuinely positive
expectancy instead of a coin flip.

Usage (backend/):
    python3 scripts/geometry_study.py --symbols 26 --cycles 30
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.brain.features import build_signal_levels, compute_metrics
from soul_exter.market.feed import MarketFeed
from soul_exter.market.universe import default_enabled

STEP = 6.0
GEOMS: List[Tuple[float, float, float]] = [
    # (stop x ATR, target x ATR, horizon seconds)
    (1.15, 2.45, 150.0), (1.15, 2.45, 300.0), (1.15, 2.45, 600.0),
    (1.00, 1.80, 240.0), (1.00, 1.80, 420.0),
    (0.85, 1.45, 240.0), (0.85, 1.45, 420.0),
    (1.30, 2.90, 420.0),
]


def trend_signal(m: Dict[str, float]) -> float:
    """Trend composite the fly can see (signed, -1..1-ish)."""
    import math

    return 0.62 * math.tanh(m["slope21"] * 120.0) + 0.38 * math.tanh(m["slope50"] * 60.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=26)
    ap.add_argument("--cycles", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20250914)
    ap.add_argument("--entry-offset", type=float, default=0.12)
    args = ap.parse_args()

    syms = default_enabled()[: max(4, args.symbols)]
    feed = MarketFeed(syms, seed=args.seed)
    print(f"feed {len(syms)} symbols · {args.cycles} cycles · {len(GEOMS)} geometries")

    open_probes: List[Dict] = []
    stats: Dict[Tuple, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    align_stats: Dict[str, List[float]] = defaultdict(list)

    for cycle in range(args.cycles):
        for _ in range(int(60.0 / STEP)):
            feed.advance(STEP)
            for p in open_probes:
                if all(p["done"]):
                    continue
                price = feed.tickers[p["symbol"]].last_price
                p["age"] += STEP
                for gi, (slm, tpm, hor) in enumerate(GEOMS):
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
                    expired = p["age"] >= hor
                    if hit or expired:
                        p["done"][gi] = True
                        stats[(slm, tpm, hor, p["rule"])][p["bucket"]].append(r)
                        stats[(slm, tpm, hor, p["rule"])]["ALL"].append(r)
        open_probes = [p for p in open_probes if not all(p["done"])]

        for sym in syms:
            m = compute_metrics(feed.tickers[sym])
            if m is None:
                continue
            ts = trend_signal(m)
            if abs(ts) < 0.12:
                continue                                  # no regime conviction → stand down
            dirn = "long" if ts > 0 else "short"
            bucket = "hi" if abs(ts) > 0.5 else "mid"
            if m["efficiency"] > 0.34:
                bucket += "+eff"
            probe = dict(symbol=sym, dirn=dirn, age=0.0, done=[False] * len(GEOMS),
                         rule="aligned", bucket=bucket)
            a = max(m["atr"], 1e-9)
            px = m["price"]
            entry = px + a * args.entry_offset * (1 if dirn == "long" else -1)
            probe["entry"] = entry
            probe["sl"], probe["tp"] = [], []
            for (slm, tpm, _h) in GEOMS:
                if dirn == "long":
                    probe["sl"].append(entry - a * slm)
                    probe["tp"].append(entry + a * tpm)
                else:
                    probe["sl"].append(entry + a * slm)
                    probe["tp"].append(entry - a * tpm)
            probe["risk"] = a * GEOMS[0][0]
            open_probes.append(probe)

    print(f"\n{'geometry (sl x tp @ horizon)':34s} {'n':>6s} {'tp':>6s} {'sl':>6s} "
          f"{'win':>6s} {'exp R':>8s} {'total R':>9s}")
    for (slm, tpm, hor, rule), buckets in sorted(stats.items()):
        rows = buckets["ALL"]
        if len(rows) < 40:
            continue
        tp = sum(1 for r in rows if r > 0 and r > 1.0) / len(rows)
        sl = sum(1 for r in rows if r <= -0.999) / len(rows)
        win = sum(1 for r in rows if r > 0) / len(rows)
        print(f"SL {slm:.2f} TP {tpm:.2f} @ {hor:5.0f}s {rule:8s} {len(rows):6d} {tp:6.2f} "
              f"{sl:6.2f} {win:6.2f} {statistics.fmean(rows):+8.3f} {sum(rows):+9.1f}")

    print("\n== conviction buckets (best geometry, SL 0.85 TP 1.45 @ 240s)")
    key = (0.85, 1.45, 240.0, "aligned")
    for bucket, rows in sorted(stats.get(key, {}).items()):
        if len(rows) < 30:
            continue
        win = sum(1 for r in rows if r > 0) / len(rows)
        print(f"  {bucket:10s} n={len(rows):4d} win={win:.2f} exp={statistics.fmean(rows):+.3f} "
              f"total={sum(rows):+.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
