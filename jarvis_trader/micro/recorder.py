"""
MARKET RECORDER - Phase 1 of the microstructure system.

Connects to Binance websocket streams and records, per symbol:
  - order book:   depth20@100ms diffs -> locally reconstructed book state
  - book EVENTS:  ADD / INCREASE / DECREASE / CANCEL / EXECUTE per level
                  (derived by diffing successive book states and matching
                   against the aggTrade stream - the "order behavior" data)
  - trades:       aggTrade (price, qty, aggressor side)
  - liquidations: forceOrder stream
  - funding/OI:   markPrice stream + periodic open-interest poll

Output: newline-JSON shards in data_store/micro/<SYMBOL>/<YYYYMMDD_HH>.jsonl
(one line per record, typed; hourly rotation; ~laptop-friendly volumes).
Snapshots of the full book are written every SNAPSHOT_EVERY seconds so the
feature builder can reconstruct state from any shard without full history.

Run standalone on your PC (this is the thing that must run for weeks):
    python -m jarvis_trader.micro.recorder BTCUSDT ETHUSDT

Stop with Ctrl+C. Restart-safe: it re-snapshots on boot. Gaps (laptop asleep)
are fine - the labeler simply skips windows that span gaps.
"""
import asyncio
import gzip
import json
import signal
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    websockets = None

import urllib.request

from .. import config

MICRO_DIR = config.DATA_DIR / "micro"
DEPTH_LEVELS = 20
SNAPSHOT_EVERY = 60          # seconds between full-book snapshot records
OI_POLL_EVERY = 60           # seconds between open-interest polls
WS_BASE = "wss://stream.binance.com:9443/stream"
FAPI_WS_BASE = "wss://fstream.binance.com/stream"   # liquidations live on futures
REST_DEPTH = "https://api.binance.com/api/v3/depth?symbol={sym}&limit=1000"
REST_OI = "https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}"


class BookState:
    """Local order-book mirror maintained from depth diffs."""

    def __init__(self):
        self.bids = {}   # price -> qty
        self.asks = {}
        self.last_update_id = 0
        self.synced = False

    def load_snapshot(self, snap):
        self.bids = {float(p): float(q) for p, q in snap["bids"] if float(q) > 0}
        self.asks = {float(p): float(q) for p, q in snap["asks"] if float(q) > 0}
        self.last_update_id = snap["lastUpdateId"]
        self.synced = True

    def apply_diff(self, bids, asks):
        """Apply a diff; returns list of (side, price, old_qty, new_qty)."""
        changes = []
        for arr, side, book in ((bids, "B", self.bids), (asks, "A", self.asks)):
            for p_s, q_s in arr:
                p, q = float(p_s), float(q_s)
                old = book.get(p, 0.0)
                if q <= 0:
                    if old > 0:
                        del book[p]
                        changes.append((side, p, old, 0.0))
                else:
                    if old != q:
                        book[p] = q
                        changes.append((side, p, old, q))
        return changes

    def top(self, n=DEPTH_LEVELS):
        bids = sorted(self.bids.items(), key=lambda x: -x[0])[:n]
        asks = sorted(self.asks.items(), key=lambda x: x[0])[:n]
        return bids, asks


class ShardWriter:
    """Hourly-rotated newline-JSON writer per symbol."""

    def __init__(self, symbol):
        self.symbol = symbol
        self.dir = MICRO_DIR / symbol
        self.dir.mkdir(parents=True, exist_ok=True)
        self.f = None
        self.hour = None
        self.written = 0

    def write(self, rec):
        hour = time.strftime("%Y%m%d_%H", time.gmtime(rec["t"]))
        if hour != self.hour:
            if self.f:
                self.f.close()
            self.hour = hour
            self.f = open(self.dir / f"{hour}.jsonl", "a", encoding="utf-8")
        self.f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.written += 1
        if self.written % 500 == 0:
            self.f.flush()

    def close(self):
        if self.f:
            self.f.close()


class Recorder:
    def __init__(self, symbols):
        self.symbols = [s.upper() for s in symbols]
        self.books = {s: BookState() for s in self.symbols}
        self.writers = {s: ShardWriter(s) for s in self.symbols}
        # recent trade tape per symbol for CANCEL-vs-EXECUTE attribution
        self.recent_trades = {s: [] for s in self.symbols}
        self.stats = {s: {"events": 0, "trades": 0, "snapshots": 0}
                      for s in self.symbols}
        self.running = True

    # ---------------- REST helpers ---------------- #
    def _rest_json(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisMicro/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def snapshot_book(self, sym):
        snap = self._rest_json(REST_DEPTH.format(sym=sym))
        self.books[sym].load_snapshot(snap)
        bids, asks = self.books[sym].top()
        self.writers[sym].write({
            "t": time.time(), "type": "snap",
            "bids": [[p, q] for p, q in bids],
            "asks": [[p, q] for p, q in asks]})
        self.stats[sym]["snapshots"] += 1

    # ---------------- event derivation ---------------- #
    def classify_changes(self, sym, changes, ts):
        """Turn raw level changes into ADD/INCREASE/DECREASE/CANCEL/EXECUTE.
        A DECREASE at a price that matches recent aggressive trades at that
        price = EXECUTE (liquidity consumed); otherwise CANCEL/DECREASE."""
        tape = self.recent_trades[sym]
        cutoff = ts - 1.0
        while tape and tape[0][0] < cutoff:
            tape.pop(0)
        traded_px = {}
        for t_ts, px, qty in tape:
            traded_px[px] = traded_px.get(px, 0.0) + qty

        out = []
        for side, price, old, new in changes:
            if old == 0 and new > 0:
                ev = "ADD"
            elif new > old:
                ev = "INC"
            elif new == 0:
                ev = "EXEC" if traded_px.get(price, 0) > 0 else "CANCEL"
            else:  # partial decrease
                ev = "EXEC" if traded_px.get(price, 0) > 0 else "DEC"
            out.append({"t": ts, "type": "ev", "e": ev, "s": side,
                        "p": price, "q0": round(old, 8), "q1": round(new, 8)})
        return out

    # ---------------- websocket loops ---------------- #
    async def spot_loop(self):
        streams = []
        for s in self.symbols:
            ls = s.lower()
            streams += [f"{ls}@depth@100ms", f"{ls}@aggTrade", f"{ls}@markPrice@1s"]
        url = WS_BASE + "/?streams=" + "/".join(streams)
        # markPrice only exists on futures; harmless if rejected on spot -
        # build the spot list without it:
        streams = [x for x in streams if "markPrice" not in x]
        url = WS_BASE + "/?streams=" + "/".join(streams)

        while self.running:
            try:
                async with websockets.connect(url, ping_interval=20,
                                              max_size=2 ** 22) as ws:
                    for s in self.symbols:
                        self.snapshot_book(s)
                    print(f"[recorder] connected: {', '.join(self.symbols)}")
                    last_snap = time.time()
                    async for msg in ws:
                        if not self.running:
                            break
                        data = json.loads(msg)
                        stream = data.get("stream", "")
                        d = data.get("data", {})
                        sym = stream.split("@")[0].upper()
                        if sym not in self.books:
                            continue
                        now = time.time()
                        if "depth" in stream:
                            book = self.books[sym]
                            if not book.synced:
                                continue
                            changes = book.apply_diff(d.get("b", []), d.get("a", []))
                            for ev in self.classify_changes(sym, changes, now):
                                self.writers[sym].write(ev)
                                self.stats[sym]["events"] += 1
                        elif "aggTrade" in stream:
                            px, qty = float(d["p"]), float(d["q"])
                            rec = {"t": now, "type": "tr", "p": px, "q": qty,
                                   "m": bool(d["m"])}   # m=True -> seller aggressor? (buyer is maker)
                            self.writers[sym].write(rec)
                            self.recent_trades[sym].append((now, px, qty))
                            self.stats[sym]["trades"] += 1
                        # periodic full snapshot for resync-ability
                        if now - last_snap > SNAPSHOT_EVERY:
                            last_snap = now
                            for s in self.symbols:
                                bids, asks = self.books[s].top()
                                if bids and asks:
                                    self.writers[s].write({
                                        "t": now, "type": "snap",
                                        "bids": [[p, q] for p, q in bids],
                                        "asks": [[p, q] for p, q in asks]})
                                    self.stats[s]["snapshots"] += 1
            except Exception as e:
                if self.running:
                    self._retry = min(getattr(self, "_retry", 5) * 1.6, 300)
                    if getattr(self, "_retry", 5) <= 15 or int(self._retry) % 60 < 10:
                        print(f"[recorder] spot ws error: {e or 'unreachable'} - "
                              f"retrying in {int(self._retry)}s")
                    await asyncio.sleep(self._retry)

    async def futures_loop(self):
        """Liquidations + mark/funding from the futures stream."""
        streams = []
        for s in self.symbols:
            ls = s.lower()
            streams += [f"{ls}@forceOrder", f"{ls}@markPrice@1s"]
        url = FAPI_WS_BASE + "/?streams=" + "/".join(streams)
        while self.running:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    async for msg in ws:
                        if not self.running:
                            break
                        data = json.loads(msg)
                        stream = data.get("stream", "")
                        d = data.get("data", {})
                        sym = stream.split("@")[0].upper()
                        if sym not in self.writers:
                            continue
                        now = time.time()
                        if "forceOrder" in stream:
                            o = d.get("o", {})
                            self.writers[sym].write({
                                "t": now, "type": "liq",
                                "s": o.get("S"), "p": float(o.get("ap", 0) or 0),
                                "q": float(o.get("q", 0) or 0)})
                        elif "markPrice" in stream:
                            self.writers[sym].write({
                                "t": now, "type": "mk",
                                "mp": float(d.get("p", 0) or 0),
                                "fr": float(d.get("r", 0) or 0)})
            except Exception as e:
                if self.running:
                    await asyncio.sleep(10)

    async def oi_loop(self):
        while self.running:
            for s in self.symbols:
                try:
                    oi = self._rest_json(REST_OI.format(sym=s))
                    self.writers[s].write({"t": time.time(), "type": "oi",
                                           "v": float(oi.get("openInterest", 0))})
                except Exception:
                    pass
            await asyncio.sleep(OI_POLL_EVERY)

    async def stats_loop(self):
        while self.running:
            await asyncio.sleep(300)
            for s in self.symbols:
                st = self.stats[s]
                if st["events"] or st["trades"]:
                    print(f"[recorder] {s}: {st['events']} events, "
                          f"{st['trades']} trades, {st['snapshots']} snaps")

    async def run(self):
        if websockets is None:
            raise RuntimeError("pip install websockets")
        await asyncio.gather(self.spot_loop(), self.futures_loop(),
                             self.oi_loop(), self.stats_loop())

    def stop(self):
        self.running = False
        for w in self.writers.values():
            w.close()


def main():
    symbols = [a for a in sys.argv[1:] if not a.startswith("-")] or \
        ["BTCUSDT", "ETHUSDT"]
    rec = Recorder(symbols)

    def _sig(*_):
        print("\n[recorder] stopping...")
        rec.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig)
    print(f"[recorder] recording {symbols} -> {MICRO_DIR}")
    print("[recorder] leave this running - every hour of data makes the "
          "model smarter. Ctrl+C to stop.")
    asyncio.run(rec.run())


if __name__ == "__main__":
    main()
