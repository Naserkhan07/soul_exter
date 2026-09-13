"""The scanner: finds the trades that fill the desks.

Pure-numpy indicators. Each strategy emits *candidates*; candidates are ranked
by score and the best ones stand up from their desk and walk to the cabins.

This is deliberately a compact, readable quant stack — the point of the project
is the LLM council on top of it, not the alpha model.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .market import MarketFeed
from .models import TradeCandidate, clamp, sigmoid

log = logging.getLogger("soul.scanner")


# --------------------------------------------------------------------------
# indicators
# --------------------------------------------------------------------------
def ema(x: np.ndarray, span: int) -> np.ndarray:
    if len(x) == 0:
        return x
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(x, dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    if len(close) < period + 1:
        return np.full(len(close), 50.0)
    delta = np.diff(close, prepend=close[0])
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    ru = np.empty_like(close)
    rd = np.empty_like(close)
    ru[:period] = up[:period].mean()
    rd[:period] = dn[:period].mean()
    for i in range(period, len(close)):
        ru[i] = (ru[i - 1] * (period - 1) + up[i]) / period
        rd[i] = (rd[i - 1] * (period - 1) + dn[i]) / period
    rs = ru / np.where(rd == 0, 1e-9, rd)
    return 100.0 - (100.0 / (1.0 + rs))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    if len(close) < 2:
        return np.zeros(len(close))
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    tr = np.concatenate([[high[0] - low[0]], tr])
    out = np.empty_like(tr)
    out[:period] = tr[:period].mean()
    for i in range(period, len(tr)):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def zscore(v: np.ndarray, window: int = 60) -> float:
    if len(v) < 5:
        return 0.0
    w = v[-window:] if len(v) >= window else v
    sd = float(np.std(w))
    if sd <= 1e-12:
        return 0.0
    return float((w[-1] - float(np.mean(w))) / sd)


def bollinger_width_pct(close: np.ndarray, window: int = 20) -> float:
    if len(close) < window:
        return 50.0
    w = close[-window:]
    sd = float(np.std(w))
    mean = float(np.mean(w))
    width = (4 * sd / mean * 100.0) if mean else 0.0
    hist = []
    for i in range(window, len(close)):
        seg = close[i - window:i]
        m = float(np.mean(seg))
        s = float(np.std(seg))
        hist.append((4 * s / m * 100.0) if m else 0.0)
    if not hist:
        return 50.0
    rank = float(np.mean(np.array(hist) <= width)) * 100.0
    return rank


def slope(v: np.ndarray, n: int = 20) -> float:
    if len(v) < n + 1:
        return 0.0
    y = v[-n:]
    x = np.arange(n, dtype=float)
    denom = float(((x - x.mean()) ** 2).sum())
    if denom <= 1e-12:
        return 0.0
    return float(((x - x.mean()) * (y - y.mean())).sum() / denom) / (abs(float(y.mean())) + 1e-9)


# --------------------------------------------------------------------------
# strategies
# --------------------------------------------------------------------------
class Strategy:
    name = "BASE"
    blurb = ""

    def evaluate(self, symbol: str, o: np.ndarray, h: np.ndarray, l: np.ndarray,
                 c: np.ndarray, v: np.ndarray, ctx: Dict[str, float]) -> Optional[TradeCandidate]:
        raise NotImplementedError


class MomentumBreakout(Strategy):
    name = "MOMENTUM_BREAKOUT"
    blurb = "breaks the 20-bar range with expanding volume"

    def evaluate(self, symbol, o, h, l, c, v, ctx):
        if len(c) < 60:
            return None
        hi20 = float(h[-21:-1].max())
        lo20 = float(l[-21:-1].min())
        close = float(c[-1])
        volz = zscore(v, 60)
        if close > hi20 and volz > 0.8:
            a = float(atr(h, l, c)[-1])
            stop = close - 1.4 * a
            target = close + 3.0 * a
            return TradeCandidate(symbol, "LONG", self.name, close, stop, target,
                                  score=clamp(0.32 + 0.16 * volz + 0.5 * min(0.25, (close / hi20 - 1) * 8), 0, 1),
                                  features={"vol_z": volz, "breakout_pct": (close / hi20 - 1) * 100,
                                            "atr_pct": a / close * 100, "rsi": float(rsi(c)[-1]),
                                            "range_hi": hi20, "range_lo": lo20})
        if close < lo20 and volz > 0.8:
            a = float(atr(h, l, c)[-1])
            return TradeCandidate(symbol, "SHORT", self.name, close, close + 1.4 * a, close - 3.0 * a,
                                  score=clamp(0.32 + 0.16 * volz + 0.5 * min(0.25, (lo20 / close - 1) * 8), 0, 1),
                                  features={"vol_z": volz, "breakdown_pct": (lo20 / close - 1) * 100,
                                            "atr_pct": a / close * 100, "rsi": float(rsi(c)[-1]),
                                            "range_hi": hi20, "range_lo": lo20})
        return None


class MeanReversion(Strategy):
    name = "MEAN_REVERSION"
    blurb = "buys oversold / sells overbought extremes"

    def evaluate(self, symbol, o, h, l, c, v, ctx):
        if len(c) < 60:
            return None
        r = rsi(c, 14)
        rv = float(r[-1])
        a = float(atr(h, l, c)[-1])
        close = float(c[-1])
        ema20 = float(ema(c, 20)[-1])
        if rv < 28 and close < ema20:
            return TradeCandidate(symbol, "LONG", self.name, close, close - 1.3 * a, close + 2.6 * a,
                                  score=clamp(0.30 + (30 - rv) / 60.0, 0, 1),
                                  features={"rsi": rv, "atr_pct": a / close * 100,
                                            "stretch_pct": (close / ema20 - 1) * 100,
                                            "vol_z": zscore(v, 60)})
        if rv > 72 and close > ema20:
            return TradeCandidate(symbol, "SHORT", self.name, close, close + 1.3 * a, close - 2.6 * a,
                                  score=clamp(0.30 + (rv - 70) / 60.0, 0, 1),
                                  features={"rsi": rv, "atr_pct": a / close * 100,
                                            "stretch_pct": (close / ema20 - 1) * 100,
                                            "vol_z": zscore(v, 60)})
        return None


class TrendPullback(Strategy):
    name = "TREND_PULLBACK"
    blurb = "with-trend continuation after a shallow pullback"

    def evaluate(self, symbol, o, h, l, c, v, ctx):
        if len(c) < 120:
            return None
        e20_series, e50_series = ema(c, 20), ema(c, 50)
        e20, e50 = float(e20_series[-1]), float(e50_series[-1])
        e200 = float(ema(c, 200)[-1]) if len(c) >= 200 else float(ema(c, 120)[-1])
        close = float(c[-1])
        a = float(atr(h, l, c)[-1])
        up = e50 > e200 and close > e200
        dn = e50 < e200 and close < e200
        pull = (e20 - close) / (a + 1e-9)
        # Normalised 20-bar slope of the EMA50 SERIES. (This used to be called as
        # slope(e50, 20) with e50 a float, which raised TypeError — and because
        # the scanner's per-symbol try/except swallows it, the strategy silently
        # never fired and took every later strategy for that symbol down with it.)
        trend_slope = slope(e50_series, 20)
        common = {"ema20": e20, "ema50": e50, "ema200": e200,
                  "pullback_atr": pull, "atr_pct": a / close * 100,
                  "trend_slope": trend_slope, "rsi": float(rsi(c)[-1])}
        if up and 0.2 < pull < 1.6:
            return TradeCandidate(symbol, "LONG", self.name, close, close - 1.5 * a, close + 3.6 * a,
                                  score=clamp(0.34 + 0.05 * min(3, pull)
                                              + 0.3 * clamp(trend_slope * 100, 0, 1), 0, 1),
                                  features=dict(common))
        if dn and 0.2 < -pull < 1.6:
            return TradeCandidate(symbol, "SHORT", self.name, close, close + 1.5 * a, close - 3.6 * a,
                                  score=clamp(0.34 + 0.05 * min(3, -pull)
                                              + 0.3 * clamp(-trend_slope * 100, 0, 1), 0, 1),
                                  features=dict(common))
        return None


class VolatilitySqueeze(Strategy):
    name = "VOLATILITY_SQUEEZE"
    blurb = "coiled range, betting on expansion"

    def evaluate(self, symbol, o, h, l, c, v, ctx):
        if len(c) < 80:
            return None
        rank = bollinger_width_pct(c, 20)
        a = float(atr(h, l, c)[-1])
        close = float(c[-1])
        atr_pct_rank = float(np.mean(atr(h, l, c)[-60:] <= a)) * 100.0
        e20 = float(ema(c, 20)[-1])
        if rank < 22 and atr_pct_rank < 30:
            side = "LONG" if c[-1] >= e20 else "SHORT"
            if side == "LONG":
                return TradeCandidate(symbol, "LONG", self.name, close, close - 1.2 * a, close + 3.4 * a,
                                      score=clamp(0.30 + (25 - rank) / 100.0 + (30 - atr_pct_rank) / 150.0, 0, 1),
                                      features={"bb_width_rank": rank, "atr_rank": atr_pct_rank,
                                                "atr_pct": a / close * 100, "rsi": float(rsi(c)[-1])})
            return TradeCandidate(symbol, "SHORT", self.name, close, close + 1.2 * a, close - 3.4 * a,
                                  score=clamp(0.30 + (25 - rank) / 100.0 + (30 - atr_pct_rank) / 150.0, 0, 1),
                                  features={"bb_width_rank": rank, "atr_rank": atr_pct_rank,
                                            "atr_pct": a / close * 100, "rsi": float(rsi(c)[-1])})
        return None


class RelativeStrength(Strategy):
    name = "RELATIVE_STRENGTH"
    blurb = "leading the majors on the 12-bar window"

    def evaluate(self, symbol, o, h, l, c, v, ctx):
        if len(c) < 40:
            return None
        beta_ret = ctx.get("btc_ret", 0.0)
        sym_ret = (float(c[-1]) / float(c[-13]) - 1.0) * 100.0 if len(c) > 13 else 0.0
        rs = sym_ret - beta_ret * ctx.get("beta", 1.0)
        a = float(atr(h, l, c)[-1])
        close = float(c[-1])
        if rs > 1.2:
            return TradeCandidate(symbol, "LONG", self.name, close, close - 1.6 * a, close + 3.2 * a,
                                  score=clamp(0.24 + abs(rs) / 22.0, 0, 1),
                                  features={"rel_strength": rs, "sym_ret_12": sym_ret,
                                            "btc_ret_12": beta_ret, "atr_pct": a / close * 100,
                                            "corr_proxy": ctx.get("beta", 1.0)})
        if rs < -1.2:
            return TradeCandidate(symbol, "SHORT", self.name, close, close + 1.6 * a, close - 3.2 * a,
                                  score=clamp(0.24 + abs(rs) / 22.0, 0, 1),
                                  features={"rel_strength": rs, "sym_ret_12": sym_ret,
                                            "btc_ret_12": beta_ret, "atr_pct": a / close * 100,
                                            "corr_proxy": ctx.get("beta", 1.0)})
        return None


STRATEGIES: List[Strategy] = [
    MomentumBreakout(), TrendPullback(), MeanReversion(), VolatilitySqueeze(), RelativeStrength(),
]


# --------------------------------------------------------------------------
# scanner
# --------------------------------------------------------------------------
class Scanner:
    def __init__(self, cfg, market: MarketFeed) -> None:
        self.cfg = cfg
        self.market = market
        self.last_scan: float = 0.0
        self.scan_count = 0
        self.recent_ids: List[str] = []
        #: symbol|side|strategy -> unix ts until which we will not re-review it.
        #: Without this the same setup (e.g. SOL LONG) walks up to the cabins on
        #: every single scan and the floor looks stuck.
        self.cooldowns: Dict[str, float] = {}
        self.cooldown_s = float(cfg.trade_cooldown_s)

    # ------------------------------------------------------------------
    @staticmethod
    def common_features(o, h, l, c, v, ctx, side: str) -> Dict[str, float]:
        """The full picture every cabin is shown.

        Strategies attach their own extras, but these are computed for every
        candidate so the QUANT/RISK/MACRO desks are never judging a packet with
        half the fields missing.
        """
        close = float(c[-1])
        a = float(atr(h, l, c)[-1])
        r = float(rsi(c, 14)[-1])
        e20 = float(ema(c, 20)[-1])
        e50 = float(ema(c, 50)[-1])
        a_series = atr(h, l, c)
        window = a_series[-60:] if len(a_series) >= 60 else a_series
        atr_rank = float(np.mean(window <= a)) * 100.0 if len(window) else 50.0
        hi60 = float(h[-60:].max()) if len(h) >= 60 else float(h.max())
        lo60 = float(l[-60:].min()) if len(l) >= 60 else float(l.min())
        rng = max(1e-12, hi60 - lo60)
        btc_ret = float(ctx.get("btc_ret", 0.0))
        sym_ret12 = (close / float(c[-13]) - 1.0) * 100.0 if len(c) > 13 else 0.0
        beta = float(ctx.get("beta", 1.3))
        return {
            "rsi": round(r, 1),
            "atr_pct": round(a / close * 100.0, 3) if close else 0.0,
            "atr_rank": round(atr_rank, 1),
            "vol_z": round(zscore(v, 60), 2),
            "bb_width_rank": round(bollinger_width_pct(c, 20), 1),
            "ema20_slope": round(slope(ema(c, 20), 20) * 100, 3),
            "ema50_slope": round(slope(ema(c, 50), 20) * 100, 3),
            "range_pos": round((close - lo60) / rng, 3),
            "btc_ret_12": round(btc_ret, 2),
            "rel_strength": round(sym_ret12 - btc_ret * beta, 2),
            "regime": 1.0 if btc_ret > 0.35 else (-1.0 if btc_ret < -0.35 else 0.0),
            "corr_proxy": round(beta, 2),
            "ema_stack": 1.0 if e20 > e50 else -1.0,
            "side_long": 1.0 if side == "LONG" else 0.0,
        }

    @staticmethod
    def score_candidate(cand: TradeCandidate, f: Dict[str, float]) -> float:
        """Blend the strategy's own conviction with a shared edge model so that
        candidates from different strategies are ranked on the same scale."""
        rr_edge = clamp((cand.rr - 1.2) / 2.0, 0.0, 1.0)
        vol_edge = clamp(f.get("vol_z", 0.0) / 2.5, 0.0, 1.0)
        alignment = 1.0 if ((cand.side == "LONG") == (f.get("ema_stack", 1.0) > 0)) else 0.0
        rs_edge = clamp(abs(f.get("rel_strength", 0.0)) / 6.0, 0.0, 1.0)
        regime_edge = 1.0 if ((cand.side == "LONG" and f.get("regime", 0) > 0)
                              or (cand.side == "SHORT" and f.get("regime", 0) < 0)) else 0.0
        rsi = f.get("rsi", 50.0)
        rsi_edge = 1.0 if ((cand.side == "LONG" and 35 < rsi < 68) or (cand.side == "SHORT" and 32 < rsi < 65)) else 0.0
        edge = (0.30 * rr_edge + 0.18 * vol_edge + 0.16 * alignment
                + 0.14 * rs_edge + 0.12 * regime_edge + 0.10 * rsi_edge)
        return clamp(0.45 * cand.score + 0.55 * edge, 0.0, 1.0)

    async def _context(self) -> Dict[str, Any]:
        """Market context for this scan.

        ``btc_ret`` must be BTC's return over the same 12-bar window the
        strategies use — using the 24h change here silently broke every
        relative-strength signal (it made alts look like 10%+ outperformers).
        """
        ret12 = 0.0
        if "BTC/USDT" in self.cfg.universe:
            try:
                rows = await self.market.candles("BTC/USDT")
                if rows is not None and len(rows) > 13:
                    ret12 = (float(rows[-1, 4]) / float(rows[-13, 4]) - 1.0) * 100.0
            except Exception as exc:                        # pragma: no cover
                log.debug("btc context failed: %s", exc)
        if ret12 > 0.35:
            regime = "risk-on"
        elif ret12 < -0.35:
            regime = "risk-off"
        else:
            regime = "range"
        return {"btc_ret": round(ret12, 3), "regime": regime, "tf": self.cfg.candle_timeframe}

    @staticmethod
    def signal_key(cand: TradeCandidate) -> str:
        return f"{cand.symbol}|{cand.side}|{cand.strategy}"

    def _prune_cooldowns(self, now: float) -> None:
        if len(self.cooldowns) > 400:
            self.cooldowns = {k: v for k, v in self.cooldowns.items() if v > now}

    async def scan(self, force: bool = False) -> List[TradeCandidate]:
        """Run every strategy over the universe, return the freshest candidates."""
        found: List[TradeCandidate] = []
        ctx = await self._context()
        board = {b["symbol"]: b for b in self.market.board()}
        for symbol in self.cfg.universe:
            try:
                rows = await self.market.candles(symbol)
                if rows is None or len(rows) < 60:
                    continue
                o, h, l, c, v = rows[:, 1], rows[:, 2], rows[:, 3], rows[:, 4], rows[:, 5]
                local = dict(ctx)
                local["beta"] = BETA_PROXY.get(symbol, 1.3)
                local["change_pct"] = board.get(symbol, {}).get("change_pct", 0.0)
                for strat in STRATEGIES:
                    cand = strat.evaluate(symbol, o, h, l, c, v, local)
                    if cand is None:
                        continue
                    cand.timeframe = self.cfg.candle_timeframe
                    # every packet carries the same complete feature block
                    common = self.common_features(o, h, l, c, v, local, cand.side)
                    cand.features = {**common, **cand.features}
                    cand.features["rr"] = round(cand.rr, 2)
                    cand.features["risk_pct"] = round(cand.risk_pct, 2)
                    cand.features["spread_proxy_bps"] = round(1.5 + 6 * abs(local["beta"] - 1), 2)
                    cand.features["strategy"] = strat.name
                    cand.notes.append(f"regime={local['regime']}")
                    cand.notes.append(f"rsi={common['rsi']:.0f} vol_z={common['vol_z']:.2f} "
                                      f"atr_rank={common['atr_rank']:.0f}")
                    cand.score = self.score_candidate(cand, common)
                    found.append(cand)
            except Exception as exc:                        # pragma: no cover
                log.debug("scan %s failed: %s", symbol, exc)
        self.scan_count += 1
        self.last_scan = time.time()
        found.sort(key=lambda t: t.score, reverse=True)
        now = time.time()
        self._prune_cooldowns(now)
        held = set()          # let the engine pass symbols it already holds
        picked: List[TradeCandidate] = []
        for cand in found:
            if cand.score < self.cfg.min_score:
                continue
            if cand.symbol in held:
                continue
            key = self.signal_key(cand)
            if not force and self.cooldowns.get(key, 0.0) > now:
                continue
            self.cooldowns[key] = now + self.cooldown_s
            held.add(cand.symbol)          # one signal per symbol per scan
            picked.append(cand)
            if len(picked) >= self.cfg.max_candidates_per_scan:
                break
        self.recent_ids = [c.id for c in picked] + self.recent_ids[:40]
        return picked


BETA_PROXY = {
    "BTC/USDT": 1.0, "ETH/USDT": 1.15, "SOL/USDT": 1.55, "DOGE/USDT": 1.9,
    "ADA/USDT": 1.45, "XRP/USDT": 0.95, "PAXG/USDT": 0.05, "NEAR/USDT": 1.8,
    "INJ/USDT": 2.1, "SUI/USDT": 1.95, "TIA/USDT": 2.0, "TAO/USDT": 1.9,
}
