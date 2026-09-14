"""Calibration harness for the mock personas.

Freezes a deck of real scanner candidates, then runs the mock council over it
so we can check the distribution of outcomes the operator will actually see:

    python tools/tune_mock.py            # report
    python tools/tune_mock.py --json     # dump the frozen deck (for fast reruns)

Target: a healthy mix of
  * 5/5 approve  -> straight through the ENTRY door
  * 0/5 approve  -> straight out the EXIT door
  * 1..4 approve -> escalated to the CEO, who should approve roughly half
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soul.brains.base import CABINS, CEO_SPEC
from soul.brains.mock import MockBrain
from soul.config import load_config
from soul.desk import PaperDesk
from soul.market import MarketFeed
from soul.scanner import Scanner


class QuietBus:
    async def publish(self, *a, **k):
        return None


async def build_deck(scans: int = 10):
    cfg = load_config()
    cfg.market_source = "sim"
    cfg.min_score = 0.05
    cfg.max_candidates_per_scan = 6
    mkt = MarketFeed(cfg)
    await mkt.start()
    scanner = Scanner(cfg, mkt)
    deck = []
    for i in range(scans):
        deck += await scanner.scan(force=True)
        for _ in range(6):
            mkt._step_simulator()
    return cfg, mkt, deck


def dedupe(deck):
    seen, out = set(), []
    for t in deck:
        k = (t.symbol, t.side, t.strategy)
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


async def evaluate(cfg, deck, ctx_of):
    brains = {c.key: MockBrain(c) for c in CABINS + [CEO_SPEC]}
    waves = [["QUANT", "RISK", "NEWS"], ["MACRO", "COMPLIANCE"]]
    hist = collections.Counter()
    ceo = collections.Counter()
    cabin = collections.Counter()
    conf = []
    for t in deck:
        prior, verdicts = [], []
        for w in waves:
            vs = await asyncio.gather(*[brains[k].judge(t, ctx_of(t), prior, 1) for k in w])
            for v in vs:
                verdicts.append(v)
                prior = verdicts[:]
                cabin[(v.cabin, v.verdict)] += 1
        approvals = sum(1 for v in verdicts if v.verdict == "APPROVE")
        hist[approvals] += 1
        route = cfg.rules.route(approvals, len(verdicts))
        conf.append(approvals / max(1, len(verdicts)))
        if route == "ESCALATED":
            v = await brains["CEO"].judge(t, {**ctx_of(t), "_council": verdicts}, verdicts, 3)
            ceo[v.verdict] += 1
    return hist, ceo, cabin, conf


def report(deck, hist, ceo, cabin, conf):
    n = len(deck)
    print(f"\ncandidates: {n}")
    print("approvals histogram (x/5):", dict(sorted(hist.items())))
    per = {c.key: round(cabin[(c.key, 'APPROVE')] / n, 2) for c in CABINS}
    print("per-cabin approve rate:", per)
    print("ceo (splits only):", dict(ceo))
    splits = sum(hist[k] for k in range(1, 5))
    entries = hist.get(5, 0) + ceo.get("APPROVE", 0)
    exits = n - entries
    print(f"splits escalated to CEO: {splits}/{n} = {splits/n:.0%}")
    print(f"ENTRY DOOR {entries}/{n} = {entries/n:.0%}   EXIT DOOR {exits}/{n} = {exits/n:.0%}")
    print(f"mean council approval share: {statistics.mean(conf):.2f}")
    ok = (0.10 <= hist.get(5, 0) / n <= 0.40) and (0.05 <= hist.get(0, 0) / n <= 0.40) and (0.30 <= entries / n <= 0.70)
    print("CALIBRATION:", "healthy" if ok else "needs tuning")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scans", type=int, default=10)
    ap.add_argument("--json", type=str, default="")
    args = ap.parse_args()
    cfg, mkt, deck = await build_deck(args.scans)
    deck = dedupe(deck)

    def ctx_of(t):
        tick = mkt.tick(t.symbol)
        desk = PaperDesk(cfg, QuietBus())
        return {
            "market": {
                "price": t.entry,
                "change_pct": tick.change_pct if tick else 0.0,
                "high": tick.high if tick else 0.0, "low": tick.low if tick else 0.0,
                "regime": "risk-on" if t.features.get("regime", 0) > 0 else "range",
                "btc_change_pct": t.features.get("btc_ret_12", 0.0),
                "vol_rank": t.features.get("atr_rank", 50.0),
                "spread_bps": t.features.get("spread_proxy_bps", 3.0),
            },
            "portfolio": desk.context(),
        }

    hist, ceo, cabin, conf = await evaluate(cfg, deck, ctx_of)
    report(deck, hist, ceo, cabin, conf)
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps([t.brief() for t in deck], indent=1))
        print("deck written to", args.json)


if __name__ == "__main__":
    asyncio.run(main())
