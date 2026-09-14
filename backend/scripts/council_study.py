"""Council study — do the six desks actually discriminate winners from losers?

Samples hundreds of tickets straight off the calibrated entry gate, runs every
seat's built-in scorecard on them, walks each ticket to first touch, and reports
how the votes line up with the realised P&L. Used to tune the desks so the
council's *approve* bucket has positive expectancy and its *reject* bucket is
negative - i.e. the debate earns its keep.

Usage (backend/):
    python3 scripts/council_study.py --symbols 24 --cycles 30
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from collections import defaultdict
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.agents.schemas import Signal
from soul_exter.brain.features import (build_signal_levels, compute_metrics, encode_glomeruli,
                                       trend_composite)
from soul_exter.llm.analyst import StageContext, evaluate as builtin_evaluate
from soul_exter.llm.playbook import Playbook
from soul_exter.llm.registry import default_seats
from soul_exter.market.feed import MarketFeed
from soul_exter.market.universe import UNIVERSE, default_enabled, horizon_for

STEP = 6.0
MIN_EFF = 0.32
MIN_TREND = 0.30
SL_ATR, TP_ATR = 1.00, 2.20
HORIZON = 600.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=24)
    ap.add_argument("--cycles", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20250914)
    ap.add_argument("--every", type=int, default=2, help="open tickets every N cycles")
    args = ap.parse_args()

    syms = default_enabled()[: max(4, args.symbols)]
    feed = MarketFeed(syms, seed=args.seed)
    seats = default_seats()
    judges = [s for s in seats if s.cabin is not None]
    ceo = next(s for s in seats if s.id == "ceo")
    book = Playbook()

    pend: List[dict] = []
    rows: List[dict] = []
    hist: List[dict] = []

    for cycle in range(args.cycles):
        for _ in range(int(60.0 / STEP)):
            feed.advance(STEP)
            for p in list(pend):
                if p["done"]:
                    continue
                price = feed.tickers[p["sym"]].last_price
                move = (price - p["entry"]) * p["sgn"]
                p["age"] += STEP
                if move <= -p["atr"] * SL_ATR:
                    p["done"], p["r"] = True, -1.0
                elif move >= p["atr"] * TP_ATR:
                    p["done"], p["r"] = True, TP_ATR / SL_ATR
                elif p["age"] >= HORIZON:
                    p["done"], p["r"] = True, move / (p["atr"] * SL_ATR)
                if p["done"]:
                    recompute_verdicts(p, judges, ceo, book)
                    rows.append(p)
                    book.record(p["signal"], accepted=p["accepted"], pnl_r=p["r"])
                    mut = p["signal"]
                    mut.features = dict(mut.features, realised_r=round(p["r"], 3))
                    hist.append(mut)
            pend = [p for p in pend if not p["done"]]

        if cycle % max(1, args.every):
            continue
        for sym in syms:
            m = compute_metrics(feed.tickers[sym])
            if m is None:
                continue
            tc = trend_composite(m)
            if m["efficiency"] < MIN_EFF or abs(tc) < MIN_TREND:
                continue
            direction = "long" if tc >= 0 else "short"
            m["spread_ratio"] = UNIVERSE[sym].spread / max(m["price"], 1e-9)
            levels = build_signal_levels(m, direction, sl_atr=SL_ATR, tp_atr=TP_ATR)
            sig = Signal(symbol=sym, asset_class=UNIVERSE[sym].asset_class, direction=direction,
                         score=0.6, entry=levels["entry"], stop_loss=levels["stop_loss"],
                         take_profit=levels["take_profit"], atr=m["atr"],
                         horizon=horizon_for(UNIVERSE[sym], m["atr_pct"]),
                         features={k: round(float(v), 6) for k, v in m.items()},
                         neural=dict(glomeruli=[round(float(x), 4) for x in encode_glomeruli(m, 0.0)]))
            sgn = 1.0 if direction == "long" else -1.0
            pend.append(dict(sym=sym, sgn=sgn, atr=max(m["atr"], 1e-9), entry=levels["entry"],
                             age=0.0, done=False, r=0.0, signal=sig))

    print(f"settled tickets: {len(rows)}")
    if not rows:
        return 0

    # per-desk discrimination
    print(f"\n{'desk':16s} {'appr':>5s} {'rej':>5s} {'abst':>5s} "
          f"{'pnl|appr':>9s} {'pnl|rej':>9s} {'spread':>7s}")
    for seat in judges + [ceo]:
        appr = [p for p in rows if p["votes"][seat.id] == "approve"]
        rej = [p for p in rows if p["votes"][seat.id] == "reject"]
        abst = [p for p in rows if p["votes"][seat.id] == "abstain"]

        def mean(xs):
            return statistics.fmean([p["r"] for p in xs]) if xs else float("nan")

        spread = mean(appr) - mean(rej) if appr and rej else float("nan")
        print(f"{seat.name:16s} {len(appr):5d} {len(rej):5d} {len(abst):5d} "
              f"{mean(appr):+9.3f} {mean(rej):+9.3f} {spread:+7.3f}")

    # council outcome
    acc = [p for p in rows if p["accepted"]]
    rej = [p for p in rows if not p["accepted"]]
    print(f"\nCOUNCIL accept n={len(acc)} ({len(acc)/len(rows)*100:.0f}%) "
          f"mean {statistics.fmean([p['r'] for p in acc]) if acc else 0:+.3f}R "
          f"| reject n={len(rej)} mean {statistics.fmean([p['r'] for p in rej]) if rej else 0:+.3f}R")
    if acc and rej:
        print(f"discrimination spread: "
              f"{statistics.fmean([p['r'] for p in acc]) - statistics.fmean([p['r'] for p in rej]):+.3f}R")

    # vote-count table
    print(f"\n{'votes for':>9s} {'n':>5s} {'mean R':>8s} {'accept%':>8s}")
    by_votes = defaultdict(list)
    for p in rows:
        by_votes[p["votes_for"]].append(p)
    for vf in sorted(by_votes):
        grp = by_votes[vf]
        print(f"{vf:9d} {len(grp):5d} {statistics.fmean([p['r'] for p in grp]):+8.3f} "
              f"{sum(1 for p in grp if p['accepted'])/len(grp)*100:8.0f}")

    # score deciles for the composite (CEO) desk
    print("\ncomposite score vs realised R (CEO view)")
    deciles = defaultdict(list)
    for p in rows:
        s = p["scores"][ceo.id]
        deciles[min(9, max(0, int((s + 1) / 2 * 10)))].append(p["r"])
    for d in sorted(deciles):
        vals = deciles[d]
        lo = d / 10 * 2 - 1
        print(f"  score {lo:+.2f}..{lo+0.2:+.2f} n={len(vals):4d} mean {statistics.fmean(vals):+.3f}R")

    # threshold sweep on the composite score
    print("\nthreshold sweep (approve when composite score >= t)")
    print(f"{'t':>6s} {'n acc':>6s} {'mean acc':>9s} {'n rej':>6s} {'mean rej':>9s} {'total R':>9s}")
    for t in (-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4):
        a = [p for p in rows if p["scores"][ceo.id] >= t]
        r = [p for p in rows if p["scores"][ceo.id] < t]
        ma = statistics.fmean([p["r"] for p in a]) if a else float("nan")
        mr = statistics.fmean([p["r"] for p in r]) if r else float("nan")
        tot = sum(p["r"] for p in a)
        print(f"{t:6.2f} {len(a):6d} {ma:+9.3f} {len(r):6d} {mr:+9.3f} {tot:+9.1f}")
    return 0


def recompute_verdicts(p: dict, judges, ceo, book) -> None:
    """Run every built-in scorecard on a settled ticket."""
    sig = p["signal"]
    ctx = StageContext(sig, history=[], playbook=book.lookup(sig), desk_name="")
    votes, scores = {}, {}
    prior = []
    for seat in judges:
        v = builtin_evaluate(seat, ctx)
        votes[seat.id] = v["verdict"]
        scores[seat.id] = v["score"]
        if v["verdict"] in ("approve", "reject"):
            prior.append(v)
    base = builtin_evaluate(ceo, ctx)
    votes_for = sum(1 for v in prior if v["verdict"] == "approve")
    against = sum(1 for v in prior if v["verdict"] == "reject")
    score = float(base["score"] or 0.0)
    if votes_for == 5:
        score += 0.30
    elif votes_for == 4:
        score += 0.16
    elif votes_for == 3:
        score += 0.02
    elif votes_for == 2:
        score -= 0.16
    else:
        score -= 0.34
    high_dissent = any(v["confidence"] > 0.7 for v in prior if v["verdict"] == "reject")
    if high_dissent:
        score -= 0.14
    hr = ctx.playbook.get("hit_rate")
    if hr is not None:
        score += (hr - 0.5) * 0.5
    score = max(-1.0, min(1.0, score))
    votes[ceo.id] = "approve" if score >= 0.12 else "reject"
    scores[ceo.id] = score
    # cabin rule (mirrors engine._after_cabins): 5/5 unanimous clears straight to the
    # entry gate, 3-4 escalate to the CEO, 2 or fewer are vetoed by the cabins alone.
    p["votes"] = votes
    p["scores"] = scores
    p["votes_for"] = votes_for
    if votes_for >= 5:
        p["accepted"] = True
    elif votes_for >= 3:
        p["accepted"] = votes[ceo.id] == "approve"
    else:
        p["accepted"] = False
    p["score"] = score


if __name__ == "__main__":
    raise SystemExit(main())
