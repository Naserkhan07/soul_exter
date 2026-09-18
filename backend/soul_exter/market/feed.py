"""Market feed — synthetic regime tape + optional live venue bridge.

The floor never sleeps: this module keeps a rolling 1-minute OHLCV history for
every instrument in the universe. History is either (a) generated from a
regime-switching stochastic model with session-aware volatility, or (b) seeded
from a real venue and then kept alive by the same model (a hybrid that lets the
demo run on a Kaggle GPU with no API keys while still trading *real* prices when
a venue feed is reachable).
"""
from __future__ import annotations

import math
import random
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from ..agents.schemas import Instrument
from ..brain.features import Ticker
from .universe import UNIVERSE, fx_legs, sigma_per_step

SESSION_VOL = [  # (hour, multiplier) Asia / London / NY
    (0, 0.72), (3, 0.80), (6, 1.05), (8, 1.32), (12, 1.46), (15, 1.28), (18, 1.02),
    (21, 0.82), (24, 0.72),
]


def session_vol(hour: float) -> float:
    for i in range(len(SESSION_VOL) - 1):
        h0, v0 = SESSION_VOL[i]
        h1, v1 = SESSION_VOL[i + 1]
        if h0 <= hour <= h1:
            t = (hour - h0) / max(h1 - h0, 1e-6)
            return v0 + (v1 - v0) * t
    return 1.0


class InstrumentState:
    """Per-instrument market making state (regime + micro noise).

    The class constants below describe the *character* of the synthetic tape:
    how much of the move is persistent order flow (`MOMO_*`), how hard dealers
    fade an overshoot back to the anchor (`*_PULL`) and how trends are
    distributed (`DRIFT_*` / `REGIME_MIX`). They are calibrated by
    `scripts/character_study.py` so the council's mandates map onto structure
    that is genuinely, measurably present - not onto noise.
    """

    MOMO_PHI = (0.80, 0.90)
    MOMO_SHARE = (0.14, 0.24)
    RANGE_PULL = 0.12
    SQUEEZE_PULL = 0.072
    DRIFT = (0.16, 0.40)
    RANGE_DRIFT = 0.04
    REGIME_MIX = (0.30, 0.30, 0.28, 0.12)      # trend_up, trend_down, range, squeeze
    REGIME_BARS = (60, 300)

    def __init__(self, inst: Instrument, rng: random.Random) -> None:
        self.inst = inst
        self.rng = rng
        self.price = inst.price
        self.regime = rng.choice(["trend_up", "trend_down", "range", "squeeze"])  # type: ignore
        self.regime_left = rng.randint(40, 200)
        self.drift = 0.0
        # persistent order-flow component: real tapes show autocorrelated
        # returns in bursts, which is exactly what a trend-following desk earns.
        self.momo = 0.0
        self.momo_phi = rng.uniform(*self.MOMO_PHI)
        self.momo_share = rng.uniform(*self.MOMO_SHARE)
        self.micro = 0.0
        self.news_left = 0
        self._roll_regime()

    def _roll_regime(self) -> None:
        r = self.rng.random()
        up, dn, rng_b, sq = self.REGIME_MIX
        lo, hi = self.DRIFT
        rd = self.RANGE_DRIFT
        if r < up:
            self.regime = "trend_up"
            self.drift = self.rng.uniform(lo, hi)
        elif r < up + dn:
            self.regime = "trend_down"
            self.drift = -self.rng.uniform(lo, hi)
        elif r < up + dn + rng_b:
            self.regime = "range"
            self.drift = self.rng.uniform(-rd, rd)
        else:
            self.regime = "squeeze"
            self.drift = self.rng.uniform(-rd / 2, rd / 2)
        self.regime_left = self.rng.randint(*self.REGIME_BARS)

    def step(self, dt: float, hour: float, factor_shock: float = 0.0,
             ccy_shock: float = 0.0) -> float:
        """Advance the mid price by `dt` seconds; returns the new price.

        `factor_shock` is the shared macro move and `ccy_shock` the combined
        currency-leg shock (base leg minus quote leg) for this step — both
        standard-deviation-scaled, so FX pairs co-move in realistic blocs."""
        base_sigma = sigma_per_step(self.inst, dt) * session_vol(hour)
        if self.regime == "squeeze":
            base_sigma *= 0.45
        if self.regime in ("range", "squeeze"):
            self.momo *= 0.80          # dealers fade the tape back to the anchor
        if self.news_left > 0:
            base_sigma *= 3.1
            self.news_left -= 1
        elif self.rng.random() < 0.00035:
            self.news_left = self.rng.randint(8, 34)
        # drift term (per bar) + Ornstein-Uhlenbeck pull for range regimes
        bar_frac = dt / 60.0
        if self.regime in ("range", "squeeze"):
            anchor = self.inst.price
            pull = self.RANGE_PULL if self.regime == "range" else self.SQUEEZE_PULL
            self.price += (anchor - self.price) * pull * bar_frac
        share = self.momo_share
        phi = self.momo_phi
        factor_part = base_sigma * 0.62 * factor_shock + base_sigma * 0.70 * ccy_shock
        innov = base_sigma * math.sqrt(max(1.0 - share * share - 0.62 ** 2 - 0.70 ** 2,
                                           0.05)) * self.rng.gauss(0, 1)
        self.momo = phi * self.momo + base_sigma * share * math.sqrt(max(1.0 - phi * phi, 0.0)) \
            * self.rng.gauss(0, 1)
        self.price *= math.exp(self.drift * 0.0016 * bar_frac + share * self.momo
                               + factor_part + innov)
        # keep prices anchored to a realistic neighbourhood
        if self.price > self.inst.price * 1.6:
            self.price = self.inst.price * 1.5
        if self.price < self.inst.price * 0.62:
            self.price = self.inst.price * 0.68
        self.regime_left -= 1
        if self.regime_left <= 0:
            self._roll_regime()
        return self.price


class MarketFeed:
    def __init__(self, symbols: Sequence[str], seed: int = 20250914, history: int = 340) -> None:
        # --- shared correlation factors -----------------------------------
        # macro: one OU shock the whole market feels; ccy: one OU per currency,
        # so EURUSD/GBPUSD co-move (shared EUR + USD legs) while USDSEK vs
        # USDNOK still diverge on their own legs.
        self.factor_rng = random.Random(seed + 77)
        self.mkt = 0.0
        self.riskf = 0.0
        self.ccy: Dict[str, float] = {}
        self._ccy_last = 0.0
        self.rng = random.Random(seed)
        self.nprng = np.random.default_rng(seed)
        self.states: Dict[str, InstrumentState] = {}
        self.tickers: Dict[str, Ticker] = {}
        self.symbols: List[str] = list(symbols)
        self.sim_clock = time.time()
        for s in self.symbols:
            inst = UNIVERSE[s]
            self.ensure_currency(s)
            self.states[s] = InstrumentState(inst, random.Random(self.rng.randint(0, 10**9)))
            t = Ticker(s)
            self._seed_history(inst, t, history)
            self.tickers[s] = t

    # -------------------------------------------------------------- seeding
    def _seed_history(self, inst: Instrument, t: Ticker, bars: int) -> None:
        st = self.states[inst.symbol]
        now = self.sim_clock
        ts = np.array([now - (bars - i) * 60.0 for i in range(bars)], dtype=np.float64)
        o = np.empty(bars); h = np.empty(bars); l = np.empty(bars); c = np.empty(bars)
        v = np.empty(bars)
        price = st.price
        base_vol = inst.vol / math.sqrt(252.0 * 288.0)
        for i in range(bars):
            hour = (ts[i] / 3600.0) % 24
            st.regime_left -= 1
            if st.regime_left <= 0:
                st._roll_regime()
            sig = base_vol * session_vol(hour)
            if st.regime == "squeeze":
                sig *= 0.45
            drift = st.drift * 0.0009
            phi = st.momo_phi
            share = st.momo_share
            st.momo = phi * st.momo + sig * share * math.sqrt(max(1.0 - phi * phi, 0.0)) \
                * float(self.nprng.normal())
            # shared macro + currency-leg factors, same weights as live stepping
            self._seed_factor_step()
            base, quote = fx_legs(inst.symbol)
            ccy_shock = (self.ccy.get(base, 0.0) - self.ccy.get(quote, 0.0)) \
                if base else 0.0
            ret = drift + share * st.momo + sig * 0.62 * self.mkt \
                + sig * 0.70 * ccy_shock \
                + sig * math.sqrt(max(1.0 - share * share - 0.62 ** 2 - 0.70 ** 2,
                                      0.05)) \
                * float(self.nprng.normal()) * 1.15
            op = price
            price = op * math.exp(ret)
            rng_hi = abs(self.nprng.normal()) * sig * 1.5 + sig * 0.35
            rng_lo = abs(self.nprng.normal()) * sig * 1.5 + sig * 0.35
            hi = max(op, price) * math.exp(rng_hi)
            lo = min(op, price) * math.exp(-rng_lo)
            o[i], h[i], l[i], c[i] = op, hi, lo, price
            v[i] = abs(self.nprng.normal()) * 620 * session_vol(hour) + 90
        st.price = price
        t.seed(ts, o, h, l, c, v)

    def _seed_factor_step(self) -> None:
        """One OU update of the shared factors during history seeding."""
        self._update_factors(6.0)

    # ---------------------------------------------------------------- drive
    CCY_BETA = {   # risk-sentiment beta per currency: + risk-on, - safe haven
        "EUR": 0.50, "GBP": 0.50, "AUD": 0.70, "NZD": 0.60, "CAD": 0.40,
        "SEK": 0.60, "NOK": 0.50, "MXN": 0.35, "ZAR": 0.45, "TRY": 0.25,
        "SGD": 0.10, "CNH": 0.20, "USD": -0.40, "JPY": -0.50, "CHF": -0.50,
    }

    def _update_factors(self, dt: float) -> None:
        """OU dynamics: shared macro, risk sentiment, and each currency leg."""
        k = 0.045
        n = max(1, int(dt / 6.0))
        for _ in range(n):
            self.mkt = (1.0 - k) * self.mkt + k * 1.2 * self.factor_rng.gauss(0, 1)
            self.riskf = (1.0 - k) * self.riskf + k * 1.8 * self.factor_rng.gauss(0, 1)
            for ccy in self.ccy:
                self.ccy[ccy] = (1.0 - k) * self.ccy[ccy] + k * 0.5 * self.factor_rng.gauss(0, 1)
        self._ccy_last = self.factor_rng.random()

    def _ccy_shock(self, symbol: str) -> float:
        """Combined currency-leg shock for a pair, beta-weighted by risk sentiment.

        Pairs sharing currency *groups* (EURUSD/GBPUSD, AUDUSD/NZDUSD, EURUSD vs
        USDCHF...) therefore co-move strongly — the same bloc structure the real
        correlation table shows."""
        from .universe import fx_legs
        base, quote = fx_legs(symbol)
        if not base:
            return 0.0
        beta = self.CCY_BETA
        br = beta.get(base, 0.0) - beta.get(quote, 0.0)
        return br * self.riskf + (self.ccy.get(base, 0.0) - self.ccy.get(quote, 0.0))

    def ensure_currency(self, symbol: str) -> None:
        """Register the currency legs of an FX pair in the factor model."""
        from .universe import fx_legs
        base, quote = fx_legs(symbol)
        for ccy in (base, quote):
            if ccy and ccy not in self.ccy:
                self.ccy[ccy] = 0.0

    def advance(self, dt: float) -> None:
        """Evolve every symbol by `dt` seconds of simulated market time."""
        self.sim_clock += dt
        hour = (self.sim_clock / 3600.0) % 24
        ticks = max(1, int(dt / 6.0))
        self._update_factors(dt)
        for sym in self.symbols:
            st = self.states[sym]
            t = self.tickers[sym]
            ccy_shock = self._ccy_shock(sym)
            sub = dt / ticks
            for _ in range(ticks):
                p = st.step(sub, hour, factor_shock=self.mkt, ccy_shock=ccy_shock)
            spread = st.inst.spread * (0.6 + 1.6 * self.nprng.random()) * session_vol(hour)
            size = abs(self.nprng.normal()) * 4.0 + 1.0
            t.push_tick(p, size, self.sim_clock)
            t.spread_ratio = float(spread / max(p, 1e-9))
        for sym in self.symbols:
            t = self.tickers[sym]
            t.tick_rate = round(1.0 / max(dt, 1e-6) * 0.9, 2)

    def upsert_history(self, symbol: str, bars: Iterable[Tuple[float, float, float, float, float]],
                       anchor_price: Optional[float] = None) -> None:
        """Merge venue bars, then re-anchor the synthetic walk to the real price."""
        t = self.tickers.get(symbol)
        if t is None:
            return
        for (ts, o, h, l, c, v) in bars:  # type: ignore[misc]
            t.replace_bar(ts, o, h, l, c, v)
        if anchor_price:
            st = self.states[symbol]
            st.price = float(anchor_price)
            t.last_price = float(anchor_price)

    def recent(self, symbol: str, n: int = 40) -> List[dict]:
        t = self.tickers[symbol]
        out = []
        for i in range(max(0, len(t.ts) - n), len(t.ts)):
            out.append(dict(ts=t.ts[i], o=t.open[i], h=t.high[i], l=t.low[i], c=t.close[i],
                            v=t.volume[i]))
        return out

    def snapshot(self, symbols: Optional[Sequence[str]] = None) -> List[dict]:
        out = []
        for sym in (symbols or self.symbols):
            t = self.tickers[sym]
            inst = UNIVERSE[sym]
            if not t.close:
                continue
            last = t.close[-1]
            prev = t.close[-2] if len(t.close) > 1 else last
            out.append(dict(symbol=sym, name=inst.name, asset_class=inst.asset_class,
                            venue=inst.venue, price=round(last, 6),
                            change_pct=round((last / prev - 1) * 100, 4) if prev else 0.0,
                            spark=[round(x, 6) for x in list(t.close)[-40:]],
                            tick_rate=round(t.tick_rate, 2), spread=inst.spread))
        return out


def make_feed(symbols: Sequence[str], seed: int = 20250914) -> MarketFeed:
    return MarketFeed(symbols, seed=seed)
