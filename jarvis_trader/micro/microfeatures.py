"""
FEATURE ENGINEERING - turns recorded raw streams into leak-free feature rows.

Reads the recorder's jsonl shards, replays them chronologically, and at a
fixed sampling cadence (default every 1s) emits one feature vector computed
ONLY from information available at that instant (spec sections 6-15):

  imbalance_L1/L5/L10/L20     multi-level order-book imbalance
  spread, spread_bps          best ask - best bid
  microprice_dist_bps         microprice vs mid (size-weighted pressure)
  delta_1s/5s/10s/30s         aggressive buy - sell volume
  vol_1s/5s/30s/1m            traded volume windows
  trade_intensity             trades per second (10s window)
  avg_trade_size              mean fill size (30s)
  large_trade_ratio           share of volume from top-decile prints (30s)
  bid/ask_cancel_rate         cancelled volume / removed volume (10s)
  bid/ask_add_rate            added volume per second (10s)
  absorption_score            aggressive volume hitting a side vs price move
  liq_consumed_10s            EXEC-removed volume both sides
  book_depth_ratio            total top-20 bid vol / ask vol
  mid_ret_1s/5s/30s           short returns (past only)
  realized_vol_1m             stdev of 1s mid returns
  price_accel                 d(ret_5s)/dt
  liq_buy/sell_30s            liquidation volume (futures stream)
  funding_rate                latest funding
  oi_change_5m                open-interest drift

Output: data_store/micro/<SYMBOL>_features.jsonl  (one row per sample)
Run:    python -m jarvis_trader.micro.microfeatures BTCUSDT
"""
import json
import math
import sys
from collections import deque
from pathlib import Path

from .. import config

MICRO_DIR = config.DATA_DIR / "micro"
SAMPLE_EVERY = 1.0          # seconds between feature rows
LEVELS = (1, 5, 10, 20)


class Rolling:
    """Time-windowed sum/count with O(1) amortized eviction."""

    def __init__(self, horizon):
        self.h = horizon
        self.q = deque()
        self.sum = 0.0

    def add(self, t, v):
        self.q.append((t, v))
        self.sum += v

    def trim(self, now):
        while self.q and self.q[0][0] < now - self.h:
            self.sum -= self.q.popleft()[1]

    def value(self, now):
        self.trim(now)
        return self.sum

    def count(self, now):
        self.trim(now)
        return len(self.q)


class FeatureEngine:
    """Streaming state -> feature vector at any instant (no lookahead)."""

    def __init__(self):
        self.bids = {}
        self.asks = {}
        # trade windows
        self.buy_vol = {h: Rolling(h) for h in (1, 5, 10, 30, 60)}
        self.sell_vol = {h: Rolling(h) for h in (1, 5, 10, 30, 60)}
        self.trades_30 = deque()            # (t, qty) for size stats
        self.trade_cnt_10 = Rolling(10)
        # event windows
        self.cancel_vol = {"B": Rolling(10), "A": Rolling(10)}
        self.removed_vol = {"B": Rolling(10), "A": Rolling(10)}
        self.added_vol = {"B": Rolling(10), "A": Rolling(10)}
        self.exec_vol = Rolling(10)
        # liquidations / funding / oi
        self.liq_buy = Rolling(30)
        self.liq_sell = Rolling(30)
        self.funding = 0.0
        self.oi_hist = deque()              # (t, oi)
        # mid-price history for returns/vol (1s buckets)
        self.mid_hist = deque()             # (t, mid)

    # ------------- stream ingestion ------------- #
    def on_record(self, r):
        t = r["t"]
        typ = r["type"]
        if typ == "snap":
            self.bids = {p: q for p, q in r["bids"]}
            self.asks = {p: q for p, q in r["asks"]}
        elif typ == "ev":
            side, ev = r["s"], r["e"]
            book = self.bids if side == "B" else self.asks
            if r["q1"] <= 0:
                book.pop(r["p"], None)
            else:
                book[r["p"]] = r["q1"]
            dv = r["q0"] - r["q1"]
            if ev in ("CANCEL", "DEC") and dv > 0:
                self.cancel_vol[side].add(t, dv)
                self.removed_vol[side].add(t, dv)
            elif ev == "EXEC" and dv > 0:
                self.removed_vol[side].add(t, dv)
                self.exec_vol.add(t, dv)
            elif ev in ("ADD", "INC"):
                self.added_vol[side].add(t, max(0.0, r["q1"] - r["q0"]))
        elif typ == "tr":
            qty = r["q"]
            # Binance aggTrade: m=True means buyer is maker -> SELL aggressor
            if r["m"]:
                for h in self.sell_vol.values():
                    h.add(t, qty)
            else:
                for h in self.buy_vol.values():
                    h.add(t, qty)
            self.trades_30.append((t, qty))
            self.trade_cnt_10.add(t, 1)
        elif typ == "liq":
            (self.liq_buy if r.get("s") == "BUY" else self.liq_sell).add(
                t, r.get("q", 0) * r.get("p", 0))
        elif typ == "mk":
            self.funding = r.get("fr", 0.0)
        elif typ == "oi":
            self.oi_hist.append((t, r["v"]))
            while self.oi_hist and self.oi_hist[0][0] < t - 360:
                self.oi_hist.popleft()

        # track mid each ingest (cheap)
        mid = self.mid()
        if mid and (not self.mid_hist or t - self.mid_hist[-1][0] >= 1.0):
            self.mid_hist.append((t, mid))
            while self.mid_hist and self.mid_hist[0][0] < t - 90:
                self.mid_hist.popleft()

    # ------------- book math ------------- #
    def best(self):
        if not self.bids or not self.asks:
            return None, None
        return max(self.bids), min(self.asks)

    def mid(self):
        b, a = self.best()
        return (b + a) / 2 if b and a else None

    def _levels(self, book, n, reverse):
        return sorted(book.items(), key=lambda x: -x[0] if reverse else x[0])[:n]

    def imbalance(self, n):
        bv = sum(q for _, q in self._levels(self.bids, n, True))
        av = sum(q for _, q in self._levels(self.asks, n, False))
        return (bv - av) / (bv + av) if bv + av > 0 else 0.0

    def _ret(self, now, sec):
        """Past return over `sec` seconds from mid history."""
        if len(self.mid_hist) < 2:
            return 0.0
        cur = self.mid_hist[-1][1]
        target = now - sec
        past = None
        for t, m in reversed(self.mid_hist):
            if t <= target:
                past = m
                break
        if past is None:
            past = self.mid_hist[0][1]
        return (cur / past - 1) if past else 0.0

    # ------------- the feature vector ------------- #
    def features(self, now):
        b, a = self.best()
        if not b or not a or a <= b:
            return None
        mid = (a + b) / 2
        bq = self.bids.get(b, 0)
        aq = self.asks.get(a, 0)
        micro = (a * bq + b * aq) / (bq + aq) if bq + aq > 0 else mid

        f = {"t": now, "mid": mid}
        for n in LEVELS:
            f[f"imb_l{n}"] = round(self.imbalance(n), 5)
        f["spread_bps"] = round((a - b) / mid * 1e4, 4)
        f["micro_dist_bps"] = round((micro - mid) / mid * 1e4, 4)

        for h in (1, 5, 10, 30):
            buy = self.buy_vol[h].value(now)
            sell = self.sell_vol[h].value(now)
            tot = buy + sell
            f[f"delta_{h}s"] = round((buy - sell) / tot, 5) if tot > 0 else 0.0
        for h in (1, 5, 30, 60):
            f[f"vol_{h}s"] = round(self.buy_vol[h].value(now) +
                                   self.sell_vol[h].value(now), 6)
        f["trade_intensity"] = round(self.trade_cnt_10.value(now) / 10.0, 3)

        # size stats (30s)
        while self.trades_30 and self.trades_30[0][0] < now - 30:
            self.trades_30.popleft()
        if self.trades_30:
            sizes = sorted(q for _, q in self.trades_30)
            avg = sum(sizes) / len(sizes)
            k = max(1, len(sizes) // 10)
            large = sum(sizes[-k:])
            f["avg_trade_size"] = round(avg, 6)
            f["large_trade_ratio"] = round(large / max(sum(sizes), 1e-12), 4)
        else:
            f["avg_trade_size"] = 0.0
            f["large_trade_ratio"] = 0.0

        # cancellation / addition behavior (10s)
        for side, tag in (("B", "bid"), ("A", "ask")):
            rem = self.removed_vol[side].value(now)
            can = self.cancel_vol[side].value(now)
            f[f"{tag}_cancel_rate"] = round(can / rem, 4) if rem > 0 else 0.0
            f[f"{tag}_add_rate"] = round(self.added_vol[side].value(now) / 10, 6)
        f["liq_consumed_10s"] = round(self.exec_vol.value(now), 6)

        # absorption: aggressive flow vs how little price moved (10s)
        agg = self.buy_vol[10].value(now) + self.sell_vol[10].value(now)
        move = abs(self._ret(now, 10))
        f["absorption"] = round(math.log1p(agg) / (move * 1e4 + 1.0), 4) \
            if agg > 0 else 0.0

        bv = sum(q for _, q in self._levels(self.bids, 20, True))
        av = sum(q for _, q in self._levels(self.asks, 20, False))
        f["depth_ratio"] = round(bv / av, 4) if av > 0 else 1.0

        # past returns + realized vol + acceleration
        r1, r5, r30 = (self._ret(now, s) for s in (1, 5, 30))
        f["ret_1s_bps"] = round(r1 * 1e4, 4)
        f["ret_5s_bps"] = round(r5 * 1e4, 4)
        f["ret_30s_bps"] = round(r30 * 1e4, 4)
        mids = [m for _, m in self.mid_hist]
        if len(mids) > 10:
            rets = [(mids[i] / mids[i - 1] - 1) for i in range(1, len(mids))]
            mu = sum(rets) / len(rets)
            f["rvol_1m_bps"] = round(math.sqrt(
                sum((x - mu) ** 2 for x in rets) / len(rets)) * 1e4, 4)
        else:
            f["rvol_1m_bps"] = 0.0
        f["accel_bps"] = round((r1 - r5 / 5) * 1e4, 4)

        # futures context
        f["liq_buy_30s"] = round(self.liq_buy.value(now), 2)
        f["liq_sell_30s"] = round(self.liq_sell.value(now), 2)
        f["funding_bps"] = round(self.funding * 1e4, 4)
        if len(self.oi_hist) >= 2:
            f["oi_chg_5m"] = round(
                (self.oi_hist[-1][1] / self.oi_hist[0][1] - 1) * 1e4, 4) \
                if self.oi_hist[0][1] else 0.0
        else:
            f["oi_chg_5m"] = 0.0
        return f


FEATURE_COLS = None   # set on first row by build()


def iter_records(symbol):
    """Yield raw records for a symbol across all shards, chronologically."""
    d = MICRO_DIR / symbol
    if not d.exists():
        return
    for shard in sorted(d.glob("*.jsonl")):
        with open(shard, encoding="utf-8") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except Exception:
                    continue


def build(symbol, sample_every=SAMPLE_EVERY, out_path=None, log=print):
    """Replay shards -> write feature rows. Leak-free by construction:
    each row uses only records with t <= row time."""
    eng = FeatureEngine()
    out_path = out_path or (MICRO_DIR / f"{symbol}_features.jsonl")
    n = 0
    next_sample = None
    with open(out_path, "w", encoding="utf-8") as out:
        for rec in iter_records(symbol):
            t = rec["t"]
            if next_sample is None:
                next_sample = t + sample_every
            # sample BEFORE applying records that are in the future
            while next_sample is not None and t >= next_sample:
                f = eng.features(next_sample)
                if f:
                    out.write(json.dumps(f, separators=(",", ":")) + "\n")
                    n += 1
                # gap handling: if the stream jumped far ahead, resync
                if t - next_sample > 30:
                    next_sample = t + sample_every
                else:
                    next_sample += sample_every
            eng.on_record(rec)
    log(f"[features] {symbol}: wrote {n} rows -> {out_path}")
    return out_path, n


if __name__ == "__main__":
    for sym in (sys.argv[1:] or ["BTCUSDT"]):
        build(sym.upper())
