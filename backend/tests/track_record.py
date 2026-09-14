"""Track-record test — does the council actually make money on this tape?

Runs the whole floor headless at high speed for a long stretch of floor time and
reports the realised book: accepted trades (real P&L), vetoed trades (the
counterfactual the council avoided) and the net result per asset class. This is
the number the product claims, so it is measured, not asserted.

Usage (backend/):
    python3 tests/track_record.py 600 12        # 600s wall clock, 12x floor speed
"""
import asyncio
import os
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.core.engine import FloorEngine
from soul_exter.core.settings import Settings


async def main(seconds: float = 300.0, speed: float = 12.0) -> None:
    s = Settings()
    s.speed = speed
    s.live_venues = False
    s.ambient_traders = 6
    s.scan_interval = 1.0
    s.scan_batch = 40
    s.max_trades_in_pipe = 14
    s.auto_trade_eval = True
    eng = FloorEngine(s)
    await eng.start()
    t0 = time.time()
    last_report = 0.0
    try:
        while time.time() - t0 < seconds:
            await asyncio.sleep(2.0)
            if eng.clock - last_report > 600:
                last_report = eng.clock
                acc = [t for t in eng.trades.values() if t.outcome == "accepted"]
                rej = [t for t in eng.trades.values() if t.outcome == "rejected"]
                print(f"  floor {eng.clock/60:6.1f} min · tickets {len(eng.trades):3d} · "
                      f"accepted {len(acc):3d} pnl {sum(t.pnl_r for t in acc):+7.2f}R · "
                      f"rejected {len(rej):3d} cf {sum(t.cf_r for t in rej):+7.2f}R · "
                      f"fly strikes {eng.brain.strikes} · funnel {eng.scanner.funnel}")
    finally:
        await eng.stop()

    acc = [t for t in eng.trades.values() if t.outcome == "accepted" and t.finalized_at]
    rej = [t for t in eng.trades.values() if t.outcome == "rejected" and t.finalized_at]
    settled_acc = [t for t in acc if t.pnl_r != 0.0]
    settled_rej = [t for t in rej if t.cf_r != 0.0]
    print(f"\n=== floor time {eng.clock/60:.1f} min · tickets {len(eng.trades)} · "
          f"pipeline exits {eng.stats['exited']}")
    print(f"funnel: {eng.scanner.funnel}")
    print(f"fly strikes {eng.brain.strikes} · waits {eng.brain.waits} · "
          f"llm calls {eng.stats['llm_calls']} · debate {len(eng.council.debate_log)} msgs "
          f"· lessons {len(eng.playbook.lessons)}")

    def block(name, rows, key):
        if not rows:
            print(f"{name}: none settled")
            return
        vals = [getattr(t, key) for t in rows]
        wins = [v for v in vals if v > 0]
        print(f"{name}: n={len(vals)} wins={len(wins)} ({len(wins)/len(vals)*100:.0f}%) "
              f"sum={sum(vals):+.2f}R mean={statistics.fmean(vals):+.3f}R "
              f"best={max(vals):+.2f} worst={min(vals):+.2f}")

    block("ACCEPTED (real book) ", settled_acc, "pnl_r")
    block("VETOED   (counterfact)", settled_rej, "cf_r")
    net = sum(t.pnl_r for t in settled_acc) + sum(t.cf_r for t in settled_rej)
    print(f"net incl. veto quality: {net:+.2f}R")

    by_class = defaultdict(list)
    for t in settled_acc:
        by_class[t.asset_class].append(t.pnl_r)
    for cls, vals in sorted(by_class.items()):
        print(f"  {cls:8s} n={len(vals):3d} {sum(vals):+7.2f}R")

    print("\nlast 12 tickets:")
    for t in list(eng.trades.values())[-12:]:
        print(f"  {t.id} {t.symbol:9s} {t.direction:5s} conf {t.confidence:.2f} "
              f"votes {t.votes_for}/{t.votes_against} outcome {t.outcome:9s} "
              f"pnl {t.pnl_r:+.2f} cf {t.cf_r:+.2f} stages {len(t.stages)}")


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 300.0,
                     float(sys.argv[2]) if len(sys.argv) > 2 else 12.0))
