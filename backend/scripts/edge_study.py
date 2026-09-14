"""Edge study — where does the synthetic/mixed tape actually pay?

The council can only be *right* if the entry rule it argues over carries a real,
measurable edge. This script samples thousands of hypothetical entries from the
live market feed (synthetic regime tape, or real venue history when reachable),
then walks each one forward under the exact stop/target geometry the floor
trades (SL 1.15xATR, TP 2.45xATR, 150s horizon) and reports hit rates and
expectancy conditioned on the features the fly brain and the judges can see.

Usage (backend/):
    python3 scripts/edge_study.py --symbols 30 --cycles 26
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.brain.features import Ticker, build_signal_levels, compute_metrics, strategy_bias
from soul_exter.market.feed import MarketFeed
from soul_exter.market.universe import UNIVERSE, default_enabled

STEP = 6.0          # seconds per feed tick
HORIZON = 150.0     # seconds a ticket lives before it is marked to market
SL_ATR, TP_ATR = 1.15, 2.45


def probe(feed: MarketFeed, sym: str, m: Dict[str, float], direction: str) -> Dict:
    """Open a hypothetical ticket and walk it forward to first touch."""
    levels = build_signal_levels(m, direction)
    entry, sl, tp = levels["entry"], levels["stop_loss"], levels["take_profit"]
    risk = max(abs(entry - sl), 1e-12)
    r_units = risk / max(m["price"], 1e-12)
    hit = None
    r = 0.0
    left = HORIZON
    while left > 0:
        feed.advance(STEP)
        left -= STEP
        price = feed.tickers[sym].last_price
        r = ((price - entry) if direction == "long" else (entry - price)) / risk
        if direction == "long":
            if price <= sl:
                hit, r = "sl", -1.0
                break
            if price >= tp:
                hit, r = "tp", (tp - entry) / risk
                break
        else:
            if price >= sl:
                hit, r = "sl", -1.0
                break
            if price <= tp:
                hit, r = "tp", (entry - tp) / risk
                break
    return dict(symbol=sym, direction=direction, hit=hit or "timeout", r=r, r_units=r_units,
                entry=entry, sl=sl, tp=tp)


def bucket_key(m: Dict[str, float], direction: str, mode: str) -> str:
    """Feature buckets the fly/judges can actually condition on."""
    sgn = 1.0 if direction == "long" else -1.0
    trend = (m["slope21"] * 120 + m["slope50"] * 60) * sgn
    align = "with" if trend > 0 else "against"
    if mode == "trend":
        return f"trend {align}"
    if mode == "eff":
        e = m["efficiency"]
        return f"eff {'hi' if e > 0.34 else 'mid' if e > 0.18 else 'lo'}"
    if mode == "vol":
        return f"atr {'hi' if m['atr_rank'] > 0.66 else 'mid' if m['atr_rank'] > 0.33 else 'lo'}"
    if mode == "stretch":
        st = m["stretch"] * sgn
        return f"stretch {'extended' if st > 1.2 else 'pullback' if st < -0.5 else 'fair'}"
    if mode == "rsi":
        rr = m["rsi"] if direction == "long" else 100 - m["rsi"]
        return f"rsi {'overbought' if rr > 68 else 'oversold' if rr < 32 else 'neutral'}"
    if mode == "combo":
        return f"{bucket_key(m, direction, 'trend')} | {bucket_key(m, direction, 'eff')} | " \
               f"{bucket_key(m, direction, 'stretch')}"
    if mode == "session":
        return f"hour {int(m['hour'] // 4) * 4:02d}"
    return "all"


def summarise(rows: List[Dict]) -> Dict:
    if not rows:
        return dict(n=0)
    wins = [r for r in rows if r["r"] > 0]
    exp = statistics.fmean(r["r"] for r in rows)
    tp = sum(1 for r in rows if r["hit"] == "tp") / len(rows)
    sl = sum(1 for r in rows if r["hit"] == "sl") / len(rows)
    to = sum(1 for r in rows if r["hit"] == "timeout") / len(rows)
    return dict(n=len(rows), tp=round(tp, 3), sl=round(sl, 3), timeout=round(to, 3),
                win_rate=round(len(wins) / len(rows), 3), expectancy=round(exp, 3),
                pnl=round(sum(r["r"] for r in rows), 1),
                avg_cost_bp=round(statistics.fmean(r["r_units"] for r in rows) * 1e4, 1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=30)
    ap.add_argument("--cycles", type=int, default=26)
    ap.add_argument("--seed", type=int, default=20250914)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    syms = default_enabled()[: max(4, args.symbols)]
    feed = MarketFeed(syms, seed=args.seed)
    print(f"feed: {len(syms)} symbols · {args.cycles} cycles x 60s · probes = "
          f"{len(syms) * args.cycles * 2}")

    pending: List[Tuple[Dict, Dict]] = []          # (features, probe)
    results: List[Dict] = []
    for cycle in range(args.cycles):
        for _ in range(int(60.0 / STEP)):
            feed.advance(STEP)
        for sym in syms:
            t = feed.tickers[sym]
            m = compute_metrics(t)
            if m is None:
                continue
            for direction in ("long", "short"):
                feats = dict(m)
                p = dict(symbol=sym, direction=direction, entry=0.0)
                pending.append((feats, p))

        still: List[Tuple[Dict, Dict]] = []
        for feats, p in pending:
            sym, direction = p["symbol"], p["direction"]
            levels = build_signal_levels(feats, direction)
            entry, sl, tp = levels["entry"], levels["stop_loss"], levels["take_profit"]
            risk = max(abs(entry - sl), 1e-12)
            price = feed.tickers[sym].last_price
            r = ((price - entry) if direction == "long" else (entry - price)) / risk
            hit = None
            if direction == "long":
                if price <= sl:
                    hit, r = "sl", -1.0
                elif price >= tp:
                    hit, r = "tp", (tp - entry) / risk
            else:
                if price >= sl:
                    hit, r = "sl", -1.0
                elif price <= tp:
                    hit, r = "tp", (entry - tp) / risk
            p["_age"] = p.get("_age", 0.0) + 60.0
            if hit or p["_age"] >= HORIZON:
                results.append(dict(symbol=sym, direction=direction, hit=hit or "timeout", r=r,
                                    r_units=risk / max(feats["price"], 1e-12), feats=feats))
            else:
                still.append((feats, p))
        pending = still

    print(f"settled probes: {len(results)}")

    def report(mode: str, rows: List[Dict], label: str) -> None:
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            groups[bucket_key(r["feats"], r["direction"], mode)].append(r)
        print(f"\n== {label}")
        print(f"{'bucket':44s} {'n':>5s} {'tp':>6s} {'sl':>6s} {'win':>6s} {'exp R':>7s}")
        for k in sorted(groups, key=lambda k: -len(groups[k])):
            s = summarise(groups[k])
            if s["n"] < 25:
                continue
            print(f"{k:44s} {s['n']:5d} {s['tp']:6.2f} {s['sl']:6.2f} "
                  f"{s['win_rate']:6.2f} {s['expectancy']:+7.3f}")

    all_rows = [{**r, "feats": r["feats"]} for r in results]
    print("\n== baseline (all probes)")
    print(json.dumps(summarise(all_rows), indent=1))
    print("\n== long vs short")
    for d in ("long", "short"):
        s = summarise([r for r in all_rows if r["direction"] == d])
        print(f"  {d:5s} n={s['n']:4d} tp={s['tp']:.2f} sl={s['sl']:.2f} exp={s['expectancy']:+.3f}")

    for mode in ("trend", "eff", "vol", "stretch", "rsi", "session"):
        report(mode, all_rows, f"conditioned on {mode}")
    report("combo", all_rows, "trend x efficiency x stretch")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(dict(summary=summarise(all_rows),
                           rows=[{k: v for k, v in r.items() if k != "feats"} for r in results]),
                      fh, indent=1)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
