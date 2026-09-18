"""Deep-market microstructure — order-book formulas as extra senses.

Two layers, so every symbol gets coverage:

1. Real L2 book (crypto on Binance spot, key-less):
   - book pressure   (bid depth vs ask depth across the top N levels)
   - depth-tilted mid (volume-weighted fair price vs mid, in bps)
   - order-flow imbalance (Cont/Kukanov/Stoikov OFI on the best levels)
   - live spread in bps
   - aggressor imbalance (taker-buy share from 1m klines)
2. Trade-only proxies (every symbol, incl. FX which has no public book):
   - Roll (1984) effective-spread estimator
   - Amihud (2002) illiquidity lambda |r| / dollar-volume
   - tick-rule aggressor proxy (signed volume over recent bars)

The poller thread is best-effort: on failure or staleness every channel
decays to neutral and the floor keeps hunting on bar data alone. Everything
is refreshed continuously, so the brain always reads the *current* book.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

import httpx

from ..market.universe import BINANCE_MAP

DEPTH_URL = "https://api.binance.com/api/v3/depth"
KLINES_URL = "https://api.binance.com/api/v3/klines"
LEVELS = 20            # book depth used per side
STALE_S = 75.0         # book older than this -> neutral channels


# ---------------------------------------------------------------- formulas --
def book_pressure(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]],
                  levels: int = LEVELS) -> float:
    """Signed depth imbalance of the visible book, -1 (all offers) .. +1 (all bids)."""
    if not bids or not asks:
        return 0.0
    b = sum(q for _, q in bids[:levels])
    a = sum(q for _, q in asks[:levels])
    return float((b - a) / max(b + a, 1e-12))


def depth_tilt_bps(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]],
                   levels: int = 10) -> float:
    """How far the depth-weighted fair price sits from the mid, in bps."""
    if not bids or not asks:
        return 0.0
    bb, ba = bids[:levels], asks[:levels]
    mid = (bb[0][0] + ba[0][0]) / 2.0
    num = sum(p * q for p, q in bb) + sum(p * q for p, q in ba)
    den = sum(q for _, q in bb) + sum(q for _, q in ba)
    if mid <= 0 or den <= 0:
        return 0.0
    return float((num / den - mid) / mid * 1e4)


def ofi_step(prev: Tuple[float, float], curr_b: float, prev_b: float,
             curr_a: float, prev_a: float) -> float:
    """One Cont-Kukanov-Stoikov order-flow-imbalance increment, size-normalised.

    prev = (bestBidPx, bestAskPx) of the previous snapshot.
    """
    if prev is None or prev[0] <= 0:
        return 0.0
    e_bid = curr_b - prev_b if curr_b >= prev[0] else 0.0        # bid improved/stayed
    e_ask = prev_a - curr_a if curr_a <= prev[1] else 0.0        # ask improved/stayed
    return float((e_bid - e_ask) / max(prev_b + prev_a, 1e-12))


def roll_spread(closes: np.ndarray) -> float:
    """Roll (1984): effective spread implied by bid-ask bounce, as a fraction of price."""
    if len(closes) < 20:
        return 0.0
    dp = np.diff(np.log(np.maximum(closes, 1e-12)))
    cov = float(np.mean(dp[1:] * dp[:-1]))
    if cov >= 0:
        return 0.0                       # no bounce visible -> spread below resolution
    price = float(np.mean(closes[-20:]))
    return float(2.0 * math.sqrt(-cov) / max(price, 1e-12))


def amihud_lambda(closes: np.ndarray, volumes: np.ndarray) -> float:
    """Amihud (2002): median |return| per unit dollar volume, scaled for display."""
    n = min(len(closes), len(volumes))
    if n < 30:
        return 0.0
    c = np.asarray(closes[-n:], dtype=np.float64)
    v = np.asarray(volumes[-n:], dtype=np.float64)
    rets = np.abs(np.diff(c) / np.maximum(c[:-1], 1e-12))
    dollars = v[1:] * c[:-1]
    ok = dollars > 0
    if not ok.any():
        return 0.0
    lam = float(np.median(rets[ok] / dollars[ok])) * 1e9   # per $1bn, readable scale
    return lam


def tick_rule_aggressor(closes: np.ndarray, volumes: np.ndarray) -> float:
    """Signed-volume proxy for taker flow: sum(sign(ret)*vol)/sum(vol), -1..+1."""
    n = min(len(closes), len(volumes), 12)
    if n < 6:
        return 0.0
    c = np.asarray(closes[-n:], dtype=np.float64)
    v = np.asarray(volumes[-n:], dtype=np.float64)
    rets = np.diff(c)
    den = float(v[1:].sum())
    if den <= 0:
        return 0.0
    return float(np.sum(np.sign(rets) * v[1:]) / den)


def aggressor_from_klines(klines: list) -> float:
    """Taker-buy imbalance straight from Binance klines: (2*takerBuy - total)/total."""
    if not klines:
        return 0.0
    total = sum(float(k[5]) for k in klines[-3:])
    buy = sum(float(k[9]) for k in klines[-3:])
    if total <= 0:
        return 0.0
    return float((2.0 * buy - total) / total)


# ------------------------------------------------------------------ monitor --
class MicroMonitor:
    """Continuously refreshed L2 book + microstructure snapshot per symbol."""

    def __init__(self, symbols: List[str], refresh_s: float = 12.0) -> None:
        self.symbols = [s for s in symbols if s in BINANCE_MAP][:14]
        self.refresh_s = refresh_s
        self.books: Dict[str, dict] = {}          # symbol -> last book (lists)
        self.ofi_ewma: Dict[str, float] = {s: 0.0 for s in self.symbols}
        self.snapshots: Dict[str, dict] = {}
        self.ok_count = 0
        self.fail_count = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        if self.symbols:
            self._thread = threading.Thread(target=self._loop, name="micro-book", daemon=True)
            self._thread.start()

    # ---------------------------------------------------------------- polling
    def _loop(self) -> None:
        i = 0
        with httpx.Client(timeout=6.0) as client:
            while not self._stop.is_set():
                sym = self.symbols[i % len(self.symbols)]
                i += 1
                try:
                    self._poll(sym, client)
                    self.ok_count += 1
                except Exception:
                    self.fail_count += 1
                self._stop.wait(max(1.2, self.refresh_s / max(len(self.symbols), 1)))

    def _poll(self, symbol: str, client: httpx.Client) -> None:
        pair = BINANCE_MAP[symbol]
        r = client.get(DEPTH_URL, params=dict(symbol=pair, limit=LEVELS))
        if r.status_code != 200:
            return
        data = r.json()
        bids = [(float(p), float(q)) for p, q in data.get("bids", [])[:LEVELS]]
        asks = [(float(p), float(q)) for p, q in data.get("asks", [])[:LEVELS]]
        if not bids or not asks:
            return
        now = time.time()
        prev = self.books.get(symbol)
        with self._lock:
            e = 0.0
            if prev and prev.get("ts", 0) > now - 120:
                pb = prev["bids"][0]
                pa = prev["asks"][0]
                e = ofi_step((pb[0], pa[0]), bids[0][1], pb[1], asks[0][1], pa[1])
            self.ofi_ewma[symbol] = float(np.clip(0.72 * self.ofi_ewma.get(symbol, 0.0)
                                                  + 0.28 * e, -1.0, 1.0))
            self.books[symbol] = dict(ts=now, bids=bids, asks=asks)
        # aggressor (taker flow) every ~3rd visit
        snap = self.snapshots.get(symbol) or {}
        if now - float(snap.get("aggr_ts", 0)) > 3 * self.refresh_s:
            try:
                k = client.get(KLINES_URL, params=dict(symbol=pair, interval="1m", limit=4)).json()
                aggr = aggressor_from_klines(k)
            except Exception:
                aggr = 0.0
            with self._lock:
                cur = self.snapshots.get(symbol, {})
                cur.update(aggressor=aggr, aggr_ts=now)
                self.snapshots[symbol] = cur

    # ---------------------------------------------------------------- reading
    def read(self, symbol: str, ticker=None) -> dict:
        """Microstructure channels for one symbol (book when available, else proxies)."""
        out = dict(book_pressure=0.0, book_tilt=0.0, ofi=0.0, live_spread_bps=0.0,
                   roll_spread=0.0, amihud=0.0, aggressor=0.0, book_age=1e9, has_book=False)
        closes = volumes = None
        if ticker is not None and len(ticker.close) >= 40:
            closes = np.asarray(ticker.close, dtype=np.float64)
            volumes = np.asarray(ticker.volume, dtype=np.float64)
            out["roll_spread"] = round(roll_spread(closes), 6)
            out["amihud"] = round(amihud_lambda(closes, volumes), 4)
            out["aggressor"] = round(0.45 * out["aggressor"]
                                     + 0.55 * tick_rule_aggressor(closes, volumes), 4)
        with self._lock:
            book = self.books.get(symbol)
            snap = dict(self.snapshots.get(symbol, {}))
            ofi = self.ofi_ewma.get(symbol, 0.0)
        if book and time.time() - book["ts"] < STALE_S:
            bp = book_pressure(book["bids"], book["asks"])
            tilt = depth_tilt_bps(book["bids"], book["asks"])
            mid = (book["bids"][0][0] + book["asks"][0][0]) / 2.0
            sp_bps = (book["asks"][0][0] - book["bids"][0][0]) / max(mid, 1e-12) * 1e4
            out.update(book_pressure=round(bp, 4), book_tilt=round(float(np.clip(tilt / 5, -1, 1)), 4),
                       ofi=round(ofi, 4), live_spread_bps=round(sp_bps, 3),
                       book_age=round(time.time() - book["ts"], 1), has_book=True)
        if snap.get("aggressor") is not None and abs(snap["aggressor"]) > 0:
            out["aggressor"] = round(0.5 * out["aggressor"] + 0.5 * snap["aggressor"], 4)
        return out

    def snapshot(self) -> dict:
        with self._lock:
            books = {s: dict(b for b in self.snapshots.get(s, {}).items()) for s in self.symbols}
            top = []
            for s, b in self.books.items():
                if time.time() - b["ts"] < STALE_S:
                    bp = book_pressure(b["bids"], b["asks"])
                    top.append(dict(symbol=s, pressure=round(bp, 3),
                                    age_s=round(time.time() - b["ts"], 1)))
            top.sort(key=lambda x: abs(x["pressure"]), reverse=True)
        return dict(active=bool(self.symbols), polls_ok=self.ok_count, polls_fail=self.fail_count,
                    books=len(top), strongest=top[:6], aggressor=books)

    def stop(self) -> None:
        self._stop.set()
