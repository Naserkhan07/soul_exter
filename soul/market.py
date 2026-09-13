"""Market data.

Primary source: public exchange data (ccxt -> Binance spot, no API key needed).
Fallback: a correlated geometric-brownian simulator so the desk still runs
offline, in CI, or on a Kaggle box whose internet is switched off.

The rest of the system only ever talks to :class:`MarketFeed`, so swapping the
source never touches the council or the UI.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Dict, List, Optional

import numpy as np

from .config import Config
from .models import Tick

log = logging.getLogger("soul.market")

# Seed prices for the simulator (rough real-world levels, so the UI reads sane).
SEED_PRICES: Dict[str, float] = {
    "BTC/USDT": 61_400.0, "ETH/USDT": 2_930.0, "SOL/USDT": 152.0,
    "XRP/USDT": 0.525, "BNB/USDT": 585.0, "ADA/USDT": 0.392,
    "DOGE/USDT": 0.132, "AVAX/USDT": 27.4, "LINK/USDT": 11.9,
    "DOT/USDT": 5.15, "MATIC/USDT": 0.452, "LTC/USDT": 66.5,
    "NEAR/USDT": 4.05, "UNI/USDT": 7.15, "AAVE/USDT": 142.0,
    "ATOM/USDT": 5.35, "FIL/USDT": 3.72, "INJ/USDT": 21.8,
    "SUI/USDT": 0.945, "APT/USDT": 6.85, "ARB/USDT": 0.585,
    "OP/USDT": 1.62, "TIA/USDT": 5.72, "SEI/USDT": 0.375,
    "TON/USDT": 5.35, "XLM/USDT": 0.0945, "ETC/USDT": 19.9,
    "HBAR/USDT": 0.0525, "ALGO/USDT": 0.128, "VET/USDT": 0.0235,
    "ZEC/USDT": 28.4, "PAXG/USDT": 2_405.0, "TAO/USDT": 385.0,
    "RNDR/USDT": 6.15, "FET/USDT": 1.32, "HYPE/USDT": 26.8,
}

# beta to BTC + idiosyncratic vol, used by the simulator
BETA: Dict[str, float] = {
    "BTC/USDT": 1.0, "PAXG/USDT": 0.05, "ETH/USDT": 1.15, "SOL/USDT": 1.55,
    "DOGE/USDT": 1.9, "ADA/USDT": 1.45, "XRP/USDT": 0.95, "AVAX/USDT": 1.6,
    "LINK/USDT": 1.4, "NEAR/USDT": 1.8, "INJ/USDT": 2.1, "SUI/USDT": 1.95,
    "TIA/USDT": 2.0, "TAO/USDT": 1.9, "HYPE/USDT": 2.2, "ZEC/USDT": 1.5,
}
DEFAULT_BETA = 1.35


class MarketFeed:
    """Keeps a live price board plus lazily-cached OHLCV history."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.source = cfg.market_source
        self.mode = "sim"                       # resolved at runtime
        self.prices: Dict[str, Tick] = {}
        self._history: Dict[str, np.ndarray] = {}   # symbol -> (N, 6) OHLCV
        self._hist_ts: Dict[str, float] = {}
        self._hist_lock = asyncio.Lock()
        self._exchange: Any = None
        self._rng = random.Random(7)
        self._btc_drift = 0.0
        self._new_bar_at: Dict[str, float] = {}
        self._stopping = asyncio.Event()
        self.last_update: float = 0.0
        self.errors: List[str] = []

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self.cfg.market_source in ("auto", "ccxt"):
            ok = await asyncio.to_thread(self._try_ccxt)
            if ok:
                self.mode = "live"
                log.info("market: LIVE via ccxt/%s", self.cfg.venue)
            else:
                self.mode = "sim"
                log.warning("market: ccxt unavailable -> simulator")
        else:
            self.mode = "sim"

        self._seed_simulator()

        if self.mode == "live":
            try:
                await self._refresh_live()
            except Exception as exc:                       # pragma: no cover
                log.warning("market: first live fetch failed (%s) -> simulator", exc)
                self.mode = "sim"
                self._seed_simulator()

    async def stop(self) -> None:
        self._stopping.set()

    def _try_ccxt(self) -> bool:
        try:
            import ccxt  # type: ignore

            cls = getattr(ccxt, self.cfg.venue)
            self._exchange = cls({"enableRateLimit": True, "timeout": 15_000})
            self._exchange.load_markets()
            return True
        except Exception as exc:
            self.errors.append(str(exc))
            log.info("market: ccxt not usable (%s)", exc)
            return False

    # ------------------------------------------------------------------
    # polling loop
    # ------------------------------------------------------------------
    async def run(self) -> None:
        while not self._stopping.is_set():
            try:
                if self.mode == "live":
                    await self._refresh_live()
                else:
                    self._step_simulator()
            except Exception as exc:                       # pragma: no cover
                log.warning("market: poll failed: %s", exc)
                self.errors.append(str(exc))
                self.errors = self.errors[-8:]
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.cfg.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _refresh_live(self) -> None:
        syms = [s for s in self.cfg.universe if s in self._exchange.markets]
        tickers = await asyncio.to_thread(self._exchange.fetch_tickers, syms)
        for sym, t in tickers.items():
            last = t.get("last") or t.get("close")
            if not last:
                continue
            pct = t.get("percentage")
            prev = self.prices.get(sym)
            self.prices[sym] = Tick(
                symbol=sym,
                price=float(last),
                change_pct=float(pct) if pct is not None else (prev.change_pct if prev else 0.0),
                high=float(t.get("high") or 0.0),
                low=float(t.get("low") or 0.0),
                volume=float(t.get("quoteVolume") or 0.0),
            )
        self.last_update = time.time()
        self._expire_history()

    # ------------------------------------------------------------------
    # simulator
    # ------------------------------------------------------------------
    def _seed_simulator(self) -> None:
        """Correlated GBM with regime shifts — enough structure for the
        strategies to find real setups and for the cabins to argue about."""
        n = max(80, self.cfg.candle_limit)
        bar_s = self.cfg.sim_bar_seconds
        now = time.time() - n * bar_s
        for sym in self.cfg.universe:
            base = SEED_PRICES.get(sym, 1.0)
            beta = BETA.get(sym, DEFAULT_BETA) * (0.9 + 0.2 * self._rng.random())
            rows = np.zeros((n, 6), dtype=float)
            price = base * (0.9 + 0.2 * self._rng.random())
            drift, vol_mult = 0.0, 1.0
            for i in range(n):
                if i % 35 == 0:                       # regime shift
                    drift = self._rng.gauss(0, 0.0011)
                    vol_mult = 0.6 + 1.1 * self._rng.random()
                sigma = 0.0042 * vol_mult
                ret = drift + beta * self._rng.gauss(0, 0.0028) + self._rng.gauss(0, sigma)
                openp = price
                price = max(1e-8, price * (1.0 + ret))
                wick = abs(price) * sigma * (0.4 + 1.6 * self._rng.random())
                hi = max(openp, price) + wick * self._rng.random()
                lo = min(openp, price) - wick * self._rng.random()
                vol = base * (500 + 1500 * self._rng.random()) * (1 + 5 * abs(ret) / sigma)
                rows[i] = (now + i * bar_s, openp, hi, lo, price, vol / max(1e-9, base) * base)
            self._history[sym] = rows
            self._hist_ts[sym] = time.time()
            self._new_bar_at[sym] = now + n * bar_s
            first = float(rows[0, 4])
            self.prices[sym] = Tick(
                symbol=sym,
                price=float(rows[-1, 4]),
                change_pct=(float(rows[-1, 4]) / first - 1.0) * 100.0,
                high=float(rows[:, 2].max()),
                low=float(rows[:, 3].min()),
                volume=float(rows[-1, 5]),
            )
        self.last_update = time.time()

    def _step_simulator(self) -> None:
        if self._rng.random() < 0.02:
            self._btc_drift = self._rng.gauss(0, 0.0011)
        r_btc = self._btc_drift + self._rng.gauss(0, 0.0022)
        now = time.time()
        for sym in self.cfg.universe:
            t = self.prices.get(sym)
            hist = self._history.get(sym)
            if t is None or hist is None or len(hist) == 0:
                continue
            beta = BETA.get(sym, DEFAULT_BETA)
            ret = beta * r_btc + self._rng.gauss(0, 0.0034)
            bar_s = self.cfg.sim_bar_seconds
            price = max(1e-8, t.price * (1.0 + ret * (3.0 / max(1.0, self.cfg.poll_seconds))))
            if now >= self._new_bar_at.get(sym, now + bar_s):
                self._new_bar_at[sym] = now + bar_s
                new_row = np.array([now, t.price, max(t.price, price), min(t.price, price), price, 0.0])
                hist = np.vstack([hist[1:], new_row])
                self._history[sym] = hist
            else:
                hist[-1, 4] = price
                hist[-1, 2] = max(hist[-1, 2], price)
                hist[-1, 3] = min(hist[-1, 3], price)
            hist[-1, 5] += abs(price) * (30 + 90 * self._rng.random())
            first = float(hist[0, 4])
            self.prices[sym] = Tick(
                symbol=sym,
                price=price,
                change_pct=(price / first - 1.0) * 100.0,
                high=float(hist[:, 2].max()),
                low=float(hist[:, 3].min()),
                volume=float(hist[-1, 5]),
            )
        self.last_update = now

    def inject_volatility(self) -> None:
        """Inject a handful of volatility spikes (demo / operator hook)."""
        for sym in self.cfg.universe:
            t = self.prices.get(sym)
            if not t or self._rng.random() > 0.25:
                continue
            shock = self._rng.choice([-1, 1]) * (0.008 + 0.016 * self._rng.random())
            newp = max(1e-8, t.price * (1 + shock))
            self.prices[sym] = Tick(sym, newp, t.change_pct + shock * 100, max(t.high, newp),
                                    min(t.low, newp) if t.low else newp, t.volume)
            hist = self._history.get(sym)
            if hist is not None and len(hist):
                hist[-1, 4] = newp
                hist[-1, 2] = max(hist[-1, 2], newp)
                hist[-1, 3] = min(hist[-1, 3], newp)

    def _expire_history(self) -> None:
        cutoff = time.time() - 90
        for sym in list(self._hist_ts):
            if self._hist_ts[sym] < cutoff:
                self._hist_ts.pop(sym, None)
                self._history.pop(sym, None)

    # ------------------------------------------------------------------
    # access
    # ------------------------------------------------------------------
    async def candles(self, symbol: str, timeframe: Optional[str] = None, limit: Optional[int] = None) -> np.ndarray:
        """Return an (N, 6) array of [ts, open, high, low, close, volume]."""
        tf = timeframe or self.cfg.candle_timeframe
        n = limit or self.cfg.candle_limit
        if self.mode == "sim":
            hist = self._history.get(symbol)
            return hist[-n:].copy() if hist is not None else np.zeros((0, 6))

        async with self._hist_lock:
            cached = self._history.get(symbol)
            fresh = (time.time() - self._hist_ts.get(symbol, 0)) < 45 and cached is not None and len(cached) >= n
            if fresh:
                return cached[-n:].copy()
            tries = 0
            while tries < 2:
                tries += 1
                try:
                    rows = await asyncio.to_thread(self._exchange.fetch_ohlcv, symbol, tf, None, n)
                    if rows:
                        arr = np.array(rows, dtype=float)
                        self._history[symbol] = arr
                        self._hist_ts[symbol] = time.time()
                        return arr[-n:].copy()
                except Exception as exc:
                    self.errors.append(f"{symbol}: {exc}")
                    self.errors = self.errors[-8:]
            return cached[-n:].copy() if cached is not None else np.zeros((0, 6))

    def tick(self, symbol: str) -> Optional[Tick]:
        return self.prices.get(symbol)

    def board(self) -> List[Dict[str, Any]]:
        out = []
        for sym in self.cfg.universe:
            t = self.prices.get(sym)
            if not t:
                continue
            out.append({
                "symbol": sym,
                "base": sym.split("/")[0],
                "price": t.price,
                "change_pct": t.change_pct,
            })
        return out

    def snapshot(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "venue": self.cfg.venue,
            "timeframe": self.cfg.candle_timeframe,
            "updated": self.last_update,
            "board": self.board(),
            "errors": self.errors[-3:],
        }


def price_fmt(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 10:
        return f"{p:,.3f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.5f}"


def pct_fmt(p: float) -> str:
    return f"{p:+.2f}%"
