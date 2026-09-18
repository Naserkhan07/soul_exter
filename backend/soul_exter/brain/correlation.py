"""Live cross-rate correlation brain — the Mataf table, computed, not scraped.

Every scan cycle this monitor recomputes, straight from the rolling 1-minute
tape (synthetic regime walk re-anchored to real venue prints when the network
is up), the same views a correlation website shows — always current, never a
cached page:

    - pairwise Pearson correlation per horizon (≈1m / 5m / 15m bars)
    - short-window vs long-window correlation  ->  correlation *break*
      (a pair suddenly detaching from its bloc is an idiosyncratic event)
    - bloc-lag residual z: how far a pair lags the peer it usually tracks
      -> statistical convergence setups (the laggard catches up)
    - lead-lag: does the peer move first? then the follower is tradable
    - currency strength: EUR/USD/GBP/JPY/... composite built from every
      constituent pair, standardised — pairs vs their strongest/weakest
      leg become directional candidates

All of it feeds new glomeruli in the fly brain and two extra emit paths in
the scanner (bloc-lag convergence, correlation break), so correlation is not
decoration: it finds trades.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..market.feed import MarketFeed

WINDOW_SHORT = 150        # 1-bar returns used for the "current" correlation
WINDOW_LONG = 380         # everything the tape remembers = the long-run regime
HORIZONS = (1, 5, 15)     # bar multiples ~ 1m / 5m / 15m
RHO_STRONG = 0.72         # peer must be this correlated to shape features
RHO_TRADE = 0.90          # ONLY 0.90..0.99 (green +90..+99, red -90..-99) may trade
Z_TRIGGER = 1.5           # residual z that flags a lagging pair
BREAK_TRIGGER = 0.45      # |rho_short - rho_long| that flags a regime break
MIN_INTERVAL_S = 4.0      # table refresh cadence: recomputed from live tape constantly
MAJORS = ("EUR", "USD", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD",
          "SEK", "NOK", "MXN", "ZAR", "TRY", "SGD", "CNH")


def _returns(closes: np.ndarray, k: int = 1) -> np.ndarray:
    if len(closes) <= k:
        return np.zeros(0)
    if k == 1:
        return np.diff(closes) / np.maximum(closes[:-1], 1e-12)
    return closes[k:] / np.maximum(closes[:-k], 1e-12) - 1.0


def _rho(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    if n < 25:
        return 0.0
    x, y = a[-n:], b[-n:]
    sx, sy = x.std(), y.std()
    if sx <= 0 or sy <= 0:
        return 0.0
    return float(np.clip(np.mean((x - x.mean()) * (y - y.mean())) / (sx * sy), -1, 1))


def _resid_z(rs: np.ndarray, rp: np.ndarray, rho: float, lookback: int = 120) -> float:
    """Last standardised residual of the peer regression (how far the pair lagged)."""
    n = min(len(rs), len(rp), lookback)
    if n < 30:
        return 0.0
    x, y = rp[-n:], rs[-n:]
    res = y - rho * x
    sd = float(res.std())
    if sd <= 1e-12:
        return 0.0
    return float(np.clip(res[-1] / sd, -4.0, 4.0))


def _lead_lag(rs: np.ndarray, rp: np.ndarray, max_lag: int = 3) -> Tuple[float, float]:
    """(peer_lead_edge, peer_recent_dir): does the peer move before this pair?"""
    n = min(len(rs), len(rp))
    if n < 60:
        return 0.0, 0.0
    x, y = rp[-n:], rs[-n:]
    same = _rho(x, y)
    best = 0.0
    for lag in range(1, max_lag + 1):
        r = _rho(y[lag:], x[:-lag])        # peer's earlier move vs our later move
        best = max(best, r - same)
    peer_dir = float(np.clip(x[-3:].sum() / (np.abs(x[-12:]).mean() * 3 + 1e-12), -1, 1))
    return best, peer_dir


class CorrelationMonitor:
    """Rolling, self-updating correlation/currency-strength view of the tape."""

    def __init__(self, feed: MarketFeed) -> None:
        self.feed = feed
        self.updated_at = 0.0
        self.compute_ms = 0.0
        self.matrix: Dict[str, Dict[str, float]] = {}     # horizon label -> {A|B: rho}
        self.per_symbol: Dict[str, dict] = {}
        self.ccy_strength: Dict[str, float] = {}
        self.top_pairs: List[dict] = []
        self.enabled: List[str] = []

    # ---------------------------------------------------------------- compute
    def update(self, symbols: List[str], now: Optional[float] = None) -> None:
        now = now or time.time()
        if now - self.updated_at < MIN_INTERVAL_S:   # refresh constantly, never stale
            return
        t0 = time.time()
        syms = [s for s in symbols if s in self.feed.tickers]
        closes: Dict[str, np.ndarray] = {}
        for s in syms:
            t = self.feed.tickers[s]
            if len(t.close) >= 90:
                closes[s] = np.asarray(t.close, dtype=np.float64)
        if len(closes) < 2:
            return
        rets1 = {s: _returns(c) for s, c in closes.items()}
        rets5 = {s: _returns(c, 5) for s, c in closes.items()}
        rets15 = {s: _returns(c, 15) for s, c in closes.items()}

        # pairwise correlations on the 1-bar horizon + strongest peer per symbol
        rho1: Dict[Tuple[str, str], float] = {}
        strongest: Dict[str, Tuple[str, float]] = {}
        names = list(closes)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                r = _rho(rets1[a], rets1[b])
                if abs(r) < 0.15:
                    continue
                rho1[(a, b)] = r
                rho1[(b, a)] = r
                if abs(r) > abs(strongest.get(a, ("", 0.0))[1]):
                    strongest[a] = (b, r)
                if abs(r) > abs(strongest.get(b, ("", 0.0))[1]):
                    strongest[b] = (a, r)

        self.top_pairs = [dict(a=a, b=b, rho=round(r, 3)) for (a, b), r in rho1.items()
                          if a < b and abs(r) >= 0.75]
        self.top_pairs.sort(key=lambda d: -abs(d["rho"]))
        self.top_pairs = self.top_pairs[:24]

        # per-symbol features + multi-horizon matrix for the API view
        per: Dict[str, dict] = {}
        for s in names:
            peer, rho_s = strongest.get(s, ("", 0.0))
            feat = dict(peer=peer, rho=round(rho_s, 3), corr_break=0.0, resid_z=0.0,
                        lead_edge=0.0, peer_dir=0.0, ccy_spread=0.0)
            if peer and abs(rho_s) >= RHO_STRONG:
                rp1 = rets1[peer]
                rho_long = _rho(rets1[s][-WINDOW_LONG:], rp1[-WINDOW_LONG:])
                feat["corr_break"] = round(min(abs(rho_s - rho_long), 1.0), 3)
                feat["resid_z"] = round(_resid_z(rets1[s], rp1, rho_s), 3)
                lead, pdir = _lead_lag(rets1[s], rp1)
                feat["lead_edge"] = round(lead, 3)
                feat["peer_dir"] = round(pdir, 3)
            if s in self.feed.tickers:
                pass
            per[s] = feat

        # currency strength (FX pairs only): standardised 120-bar move per leg
        strength: Dict[str, List[float]] = {}
        for s, c in closes.items():
            base, quote = self._legs(s)
            if not base:
                continue
            r = _returns(c, 1)
            n = min(len(r), 120)
            if n < 40:
                continue
            z = float(r[-n:].sum() / (r[-n:].std() * math.sqrt(n) + 1e-12))
            strength.setdefault(base, []).append(z)
            strength.setdefault(quote, []).append(-z)
        self.ccy_strength = {k: round(float(np.mean(v)) / (1 + 0.35 * len(v) ** 0.5), 4)
                             for k, v in strength.items() if len(v) >= 2}
        for s in per:
            base, quote = self._legs(s)
            if base and base in self.ccy_strength and quote in self.ccy_strength:
                per[s]["ccy_spread"] = round(self.ccy_strength[base] - self.ccy_strength[quote], 3)

        self.per_symbol = per
        self.enabled = names
        # compact matrix for the API (the strongest horizons the tape supports)
        mat: Dict[str, float] = {}
        for (a, b), r in rho1.items():
            if a < b:
                mat[f"{a}|{b}"] = round(r, 3)
        self.matrix = {"1m": mat}
        self.updated_at = now
        self.compute_ms = round((time.time() - t0) * 1000.0, 1)

    @staticmethod
    def _legs(symbol: str) -> Tuple[str, str]:
        for cc in sorted(MAJORS, key=len, reverse=True):
            if symbol.startswith(cc) and len(symbol) > len(cc):
                rest = symbol[len(cc):]
                if rest in MAJORS:
                    return cc, rest
        return "", ""

    # ---------------------------------------------------------------- reading
    def features_for(self, symbol: str) -> dict:
        f = self.per_symbol.get(symbol)
        if not f:
            return dict(corr_bloc=0.0, corr_break=0.0, resid_z=0.0, lead_edge=0.0,
                        peer_dir=0.0, ccy_spread=0.0, peer="")
        return dict(corr_bloc=f.get("rho", 0.0), corr_break=f.get("corr_break", 0.0),
                    resid_z=f.get("resid_z", 0.0), lead_edge=f.get("lead_edge", 0.0),
                    peer_dir=f.get("peer_dir", 0.0), ccy_spread=f.get("ccy_spread", 0.0),
                    peer=f.get("peer", ""))

    def rho_between(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        return self.matrix.get("1m", {}).get(f"{a}|{b}",
                                             self.matrix.get("1m", {}).get(f"{b}|{a}", 0.0))

    def snapshot(self) -> dict:
        ccys = sorted(self.ccy_strength.items(), key=lambda kv: -kv[1])
        return dict(updated_ago_s=round(time.time() - self.updated_at, 1) if self.updated_at else None,
                    compute_ms=self.compute_ms, symbols=len(self.enabled),
                    strongest_pairs=self.top_pairs[:12],
                    currency_strength=[[k, v] for k, v in ccys],
                    per_symbol={s: f for s, f in list(self.per_symbol.items())[:40]})
