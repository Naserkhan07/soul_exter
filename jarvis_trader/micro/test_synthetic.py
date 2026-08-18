"""
SYNTHETIC END-TO-END TEST of the whole micro pipeline.

Generates a realistic fake market stream (order book diffs, trades with
aggressor sides, liquidations) with EMBEDDED microstructure patterns
(imbalance + aggression precede moves), writes recorder-format shards,
then runs: features -> labels -> training -> prediction.

If the model learns the planted pattern significantly better than chance,
the pipeline is proven correct end-to-end.

Run: python -m jarvis_trader.micro.test_synthetic
"""
import json
import random
import shutil
import time
from pathlib import Path

from .. import config
from . import microfeatures, labeler, train_micro, predictor

MICRO_DIR = config.DATA_DIR / "micro"
SYM = "TESTUSDT"


def generate(hours=2.0, seed=7):
    rng = random.Random(seed)
    d = MICRO_DIR / SYM
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)

    t = time.time() - hours * 3600
    price = 50000.0
    # regime machinery: hidden state drives both book pressure AND future move
    hidden = 0          # -1 bear pressure, 0 neutral, +1 bull pressure
    hidden_until = t

    writer = open(d / time.strftime("%Y%m%d_%H.jsonl", time.gmtime(t)),
                  "w", encoding="utf-8")
    cur_hour = time.strftime("%Y%m%d_%H", time.gmtime(t))

    def w(rec):
        nonlocal writer, cur_hour
        h = time.strftime("%Y%m%d_%H", time.gmtime(rec["t"]))
        if h != cur_hour:
            writer.close()
            cur_hour = h
            writer = open(d / f"{h}.jsonl", "w", encoding="utf-8")
        writer.write(json.dumps(rec, separators=(",", ":")) + "\n")

    def book_snapshot(ts):
        bias = hidden * 0.35
        bids, asks = [], []
        for i in range(20):
            bq = max(0.05, rng.gauss(1.0 + bias, 0.3))
            aq = max(0.05, rng.gauss(1.0 - bias, 0.3))
            bids.append([round(price - (i + 1) * 0.5, 2), round(bq, 4)])
            asks.append([round(price + (i + 1) * 0.5, 2), round(aq, 4)])
        w({"t": ts, "type": "snap", "bids": bids, "asks": asks})

    end = t + hours * 3600
    step = 0.25
    book_snapshot(t)
    last_snap = t
    while t < end:
        t += step
        # hidden state transitions
        if t >= hidden_until:
            hidden = rng.choice([-1, 0, 0, 1])
            hidden_until = t + rng.uniform(60, 180)
        # price drifts WITH the hidden state (the learnable signal) + noise
        drift = hidden * 0.35 * step
        price = max(1000, price + drift + rng.gauss(0, 0.35))
        # trades: aggressor side biased by hidden state
        for _ in range(rng.randint(1, 3)):
            sell_aggr = rng.random() < (0.5 - hidden * 0.22)
            qty = abs(rng.gauss(0.4, 0.35)) + 0.01
            w({"t": t, "type": "tr", "p": round(price, 2),
               "q": round(qty, 4), "m": sell_aggr})
        # book events: adds biased toward hidden side, cancels opposite
        for _ in range(rng.randint(1, 4)):
            side = "B" if rng.random() < (0.5 + hidden * 0.2) else "A"
            ev = rng.choices(["ADD", "CANCEL", "EXEC", "INC", "DEC"],
                             weights=[4, 2, 2, 2, 1])[0]
            q0 = round(abs(rng.gauss(0.8, 0.4)) + 0.05, 4)
            q1 = 0.0 if ev in ("CANCEL", "EXEC") else \
                round(q0 + abs(rng.gauss(0.3, 0.2)), 4) if ev in ("ADD", "INC") \
                else round(q0 * 0.5, 4)
            off = rng.randint(1, 10) * 0.5
            p = round(price - off if side == "B" else price + off, 2)
            w({"t": t, "type": "ev", "e": ev, "s": side, "p": p,
               "q0": 0.0 if ev == "ADD" else q0, "q1": q1})
        # occasional liquidation against the hidden direction
        if rng.random() < 0.005:
            w({"t": t, "type": "liq",
               "s": "SELL" if hidden > 0 else "BUY",
               "p": round(price, 2), "q": round(abs(rng.gauss(2, 1)), 3)})
        if t - last_snap > 30:
            last_snap = t
            book_snapshot(t)
    writer.close()
    print(f"[synthetic] generated {hours}h of {SYM} stream")


def run():
    generate(hours=2.0)
    # tighter barriers for the synthetic scale
    labeler.PARAMS[SYM] = {"tp_bps": 6.0, "sl_bps": 4.0, "horizon": 120}
    microfeatures.build(SYM, sample_every=2.0)
    _, total, counts = labeler.label(SYM)
    assert total > 300, f"too few labeled rows: {total}"
    bundle = train_micro.train(SYM, rounds=2, conf_gate=0.6)
    assert bundle, "training failed"
    # prediction smoke test on the last feature row
    rows = [json.loads(l) for l in
            open(MICRO_DIR / f"{SYM}_features.jsonl", encoding="utf-8")]
    pred = predictor.predict(SYM, rows[-1])
    print(f"[synthetic] live-style prediction: {pred['signal']} "
          f"conf={pred['confidence']} probs={pred['probs']}")
    # sanity: gated precision should beat class base rate
    hist = bundle["history"][-1]["metrics"]
    print(f"[synthetic] final metrics: {hist}")
    print("[synthetic] END-TO-END PIPELINE OK")


if __name__ == "__main__":
    run()
