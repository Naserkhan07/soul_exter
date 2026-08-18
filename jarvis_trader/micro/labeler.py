"""
TRIPLE-BARRIER LABELING (spec sections 16-19).

For each feature row at time T (entry = mid at T):
  BUY test :  TP = entry * (1 + tp_bps/1e4), SL = entry * (1 - sl_bps/1e4)
  SELL test:  mirrored
  time barrier = horizon seconds

Walk the FUTURE mid-price path (from the same feature file - leak-safe
because labels are only used as targets, never as inputs):
  label 2 (BUY)      if buy-TP hits before buy-SL within horizon
  label 0 (SELL)     if sell-TP hits before sell-SL within horizon
  label 1 (NO-TRADE) otherwise (neither side offered the R:R), or both
                     directions won (ambiguous chop = not attractive)

Defaults per discussion: BTC TP=12bps SL=8bps 5min; ETH slightly wider.

Output: <SYMBOL>_labeled.jsonl  (feature row + "y" + realized path info)
Run:    python -m jarvis_trader.micro.labeler BTCUSDT
"""
import json
import sys
from pathlib import Path

from .. import config

MICRO_DIR = config.DATA_DIR / "micro"

PARAMS = {
    "BTCUSDT": {"tp_bps": 12.0, "sl_bps": 8.0, "horizon": 300},
    "ETHUSDT": {"tp_bps": 15.0, "sl_bps": 10.0, "horizon": 300},
    "_default": {"tp_bps": 15.0, "sl_bps": 10.0, "horizon": 300},
}

SELL, NOTRADE, BUY = 0, 1, 2


def _first_touch(path, entry, up_px, dn_px):
    """Scan (t, mid) path; return ('up'|'dn'|None, index)."""
    for i, (_, m) in enumerate(path):
        up = m >= up_px
        dn = m <= dn_px
        if up and dn:      # gap through both in one step: ambiguous
            return "both", i
        if up:
            return "up", i
        if dn:
            return "dn", i
    return None, None


def label(symbol, in_path=None, out_path=None, log=print):
    p = PARAMS.get(symbol, PARAMS["_default"])
    tp, sl, horizon = p["tp_bps"] / 1e4, p["sl_bps"] / 1e4, p["horizon"]

    in_path = in_path or (MICRO_DIR / f"{symbol}_features.jsonl")
    out_path = out_path or (MICRO_DIR / f"{symbol}_labeled.jsonl")

    rows = []
    with open(in_path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        log(f"[labeler] {symbol}: no feature rows")
        return out_path, 0, {}

    times = [r["t"] for r in rows]
    mids = [r["mid"] for r in rows]
    n = len(rows)
    counts = {SELL: 0, NOTRADE: 0, BUY: 0, "skipped": 0}

    with open(out_path, "w", encoding="utf-8") as out:
        j_start = 0
        for i, r in enumerate(rows):
            t0, entry = r["t"], r["mid"]
            # future path within horizon (STRICTLY after t0)
            j = max(i + 1, j_start)
            path = []
            k = j
            while k < n and times[k] - t0 <= horizon:
                path.append((times[k], mids[k]))
                k += 1
            # gap check: need coverage of at least 60% of horizon
            if not path or (path[-1][0] - t0) < horizon * 0.6:
                counts["skipped"] += 1
                continue

            buy_hit, bi = _first_touch(path, entry, entry * (1 + tp),
                                       entry * (1 - sl))
            sell_hit, si = _first_touch(path, entry, entry * (1 + sl),
                                        entry * (1 - tp))
            # for SELL: TP is the DOWN barrier, SL is the UP barrier
            buy_win = buy_hit == "up"
            sell_win = sell_hit == "dn"

            if buy_win and not sell_win:
                y = BUY
            elif sell_win and not buy_win:
                y = SELL
            else:
                y = NOTRADE     # both, neither, or ambiguous
            counts[y] += 1

            rec = dict(r)
            rec["y"] = y
            rec["tp_bps"] = p["tp_bps"]
            rec["sl_bps"] = p["sl_bps"]
            rec["horizon"] = horizon
            out.write(json.dumps(rec, separators=(",", ":")) + "\n")

    total = counts[SELL] + counts[NOTRADE] + counts[BUY]
    log(f"[labeler] {symbol}: {total} labeled "
        f"(BUY {counts[BUY]}, SELL {counts[SELL]}, NO-TRADE {counts[NOTRADE]}, "
        f"skipped {counts['skipped']}) -> {out_path}")
    return out_path, total, counts


if __name__ == "__main__":
    for sym in (sys.argv[1:] or ["BTCUSDT"]):
        label(sym.upper())
