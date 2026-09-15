"""CEO study — is NAVEED's advanced training actually outruling the five desks?

Samples tickets off the same calibrated entry gate the live floor uses, walks
each to first touch, then scores the decision rules on the identical sample:

* each cabin judge's built-in scorecard alone,
* the naive majority vote (accept when ≥3 of 5 cabins approve),
* NAVEED's trained synthesis (`llm.engine.naveed_synthesis`) — the weighted
  consensus + advanced-curriculum overlays now running in the executive chamber.

The training earns its keep when NAVEED harvests the most total R from the same
sample (book value — the CEO's actual objective) while keeping per-ticket
expectancy at the top of the table and the veto book clean (vetoes land on the
losers, not the winners). Run it across several --seed values; averaged over
seeds the trained synthesis is expected to sit at the top of the book column
while deploying more capital than any single cabin.

Usage (backend/):
    python3 scripts/ceo_study.py --symbols 24 --cycles 30
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.agents.schemas import Signal, Verdict_
from soul_exter.brain.features import (build_signal_levels, compute_metrics, encode_glomeruli,
                                       trend_composite)
from soul_exter.llm.analyst import StageContext, evaluate as builtin_evaluate
from soul_exter.llm.engine import naveed_synthesis
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
    ap.add_argument("--every", type=int, default=2)
    args = ap.parse_args()

    syms = default_enabled()[: max(4, args.symbols)]
    feed = MarketFeed(syms, seed=args.seed)
    seats = default_seats()
    judges = [s for s in seats if s.cabin is not None]
    ceo = next(s for s in seats if s.id == "ceo")
    book = Playbook()

    pend: List[dict] = []
    rows: List[dict] = []

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
                    score_ticket(p, judges, ceo, book)
                    rows.append(p)
                    book.record(p["signal"], accepted=p["verdict"] == "approve", pnl_r=p["r"])
                    mut = p["signal"]
                    mut.features = dict(mut.features, realised_r=round(p["r"], 3))
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

    def table(title: str, rules: List[tuple]) -> None:
        print(f"\n{title}")
        print(f"{'rule':26s} {'appr':>5s} {'pnl|appr':>9s} {'pnl|rej':>9s} {'spread':>8s} {'totalR':>8s}")
        ranked = []
        for name, decide in rules:
            appr = [p for p in rows if decide(p)]
            rej = [p for p in rows if not decide(p)]

            def mean(xs):
                return statistics.fmean([p["r"] for p in xs]) if xs else float("nan")

            spread = mean(appr) - mean(rej) if appr and rej else float("nan")
            tot = sum(p["r"] for p in appr)
            print(f"{name:26s} {len(appr):5d} {mean(appr):+9.3f} {mean(rej):+9.3f} "
                  f"{spread:+8.3f} {tot:+8.1f}")
            ranked.append((mean(appr), spread, name))
        ranked.sort(reverse=True)
        print(f"  → best approved-bucket expectancy: {ranked[0][2]} "
              f"({ranked[0][0]:+.3f}R/ticket, spread {ranked[0][1]:+.3f})")

    # per-desk rules
    desk_rules = [(seat.name, (lambda p, sid=seat.id: p["votes"][sid] == "approve"))
                  for seat in judges]
    desk_rules += [
        ("Naive majority (>=3/5)", lambda p: p["votes_for"] >= 3),
        ("NAVEED · trained synthesis", lambda p: p["verdict"] == "approve"),
    ]
    table("per-desk discrimination (identical ticket sample)", desk_rules)

    # what moved the needle: how often the training flipped the naive majority
    flips_up = [p for p in rows if p["verdict"] == "approve" and p["votes_for"] < 3]
    flips_dn = [p for p in rows if p["verdict"] != "approve" and p["votes_for"] >= 3]
    print("\ntraining overrides vs the naive majority:")
    for name, grp in (("approved where majority would veto", flips_up),
                      ("vetoed where majority would approve", flips_dn)):
        if grp:
            print(f"  {name}: n={len(grp)} mean R {statistics.fmean([p['r'] for p in grp]):+.3f} "
                  f"(total {sum(p['r'] for p in grp):+.1f}R)")
        else:
            print(f"  {name}: none")

    # sanity: NAVEED's expectancy per block
    acc = [p for p in rows if p["verdict"] == "approve"]
    rej = [p for p in rows if p["verdict"] != "approve"]
    if acc and rej:
        print(f"\nNAVEED approved n={len(acc)} mean {statistics.fmean([p['r'] for p in acc]):+.3f}R "
              f"| vetoed n={len(rej)} mean {statistics.fmean([p['r'] for p in rej]):+.3f}R "
              f"| discrimination "
              f"{statistics.fmean([p['r'] for p in acc]) - statistics.fmean([p['r'] for p in rej]):+.3f}R")
    return 0


def score_ticket(p: dict, judges, ceo, book) -> None:
    """Run the cabins, the naive tally and NAVEED's trained synthesis on a settled ticket."""
    sig = p["signal"]
    ctx = StageContext(sig, history=[], playbook=book.lookup(sig), desk_name="")
    votes: Dict[str, str] = {}
    prior: List[Verdict_] = []
    for seat in judges:
        v = builtin_evaluate(seat, ctx)
        votes[seat.id] = v["verdict"]
        if v["verdict"] in ("approve", "reject"):
            prior.append(Verdict_(
                judge_id=seat.id, judge_name=seat.name, verdict=str(v["verdict"]),
                confidence=float(v["confidence"]), score=float(v["score"] or 0.0),
                reasoning=str(v.get("reasoning", ""))))
    votes_for = sum(1 for v in prior if v.verdict == "approve")
    base = builtin_evaluate(ceo, ctx)
    base_score = float(base["score"] or 0.0)
    exec_v = naveed_synthesis(ceo.name, ctx, sig.symbol, sig.direction, prior,
                              base_score=base_score)
    p["votes"] = votes
    p["votes_for"] = votes_for
    p["verdict"] = exec_v["verdict"]


if __name__ == "__main__":
    raise SystemExit(main())
