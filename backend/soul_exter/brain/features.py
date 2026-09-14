"""Market feature encoder: raw tape -> (metrics, 12 glomeruli, strategy bias).

Everything the council argues about is produced here, so a judge's reasoning can
always be tied back to a number ("ATR percentile 0.86, efficiency 0.61, ...").
"""
from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

N_FEATURES = 12


def sigmoid(x: float) -> float:
    """Numerically safe logistic."""
    if x >= 0:
        z = math.exp(-min(x, 60.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(x, -60.0))
    return z / (1.0 + z)


def ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=np.float64)
    acc = values[0]
    for i, v in enumerate(values):
        acc = alpha * v + (1 - alpha) * acc
        out[i] = acc
    return out


def rsi(values: np.ndarray, period: int = 14) -> float:
    if len(values) < period + 2:
        return 50.0
    d = np.diff(values[-(period + 1):])
    up = np.clip(d, 0, None).mean()
    dn = -np.clip(d, None, 0).mean()
    if dn == 0:
        return 100.0 if up > 0 else 50.0
    rs = up / dn
    return float(100.0 - 100.0 / (1.0 + rs))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    n = min(len(high), len(low), len(close))
    if n < 3:
        return 0.0
    h, l, c = high[-n:], low[-n:], close[-n:]
    prev = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    k = min(period, len(tr))
    return float(tr[-k:].mean())


class Ticker:
    """Rolling OHLCV history for a single instrument + microstructure state."""

    def __init__(self, symbol: str, maxlen: int = 420) -> None:
        self.symbol = symbol
        self.ts: Deque[float] = deque(maxlen=maxlen)
        self.open: Deque[float] = deque(maxlen=maxlen)
        self.high: Deque[float] = deque(maxlen=maxlen)
        self.low: Deque[float] = deque(maxlen=maxlen)
        self.close: Deque[float] = deque(maxlen=maxlen)
        self.volume: Deque[float] = deque(maxlen=maxlen)
        self.bar_seconds = 60.0
        self.last_price = 0.0
        self.ticks = 0
        self.tick_rate = 0.0
        self.prev_close = 0.0
        self.session_open = 0.0
        self._bar_start = 0.0

    # ------------------------------------------------------------------ tape
    def seed(self, ts: np.ndarray, o: np.ndarray, h: np.ndarray, l: np.ndarray,
             c: np.ndarray, v: np.ndarray) -> None:
        for i in range(len(ts)):
            self.ts.append(float(ts[i]))
            self.open.append(float(o[i]))
            self.high.append(float(h[i]))
            self.low.append(float(l[i]))
            self.close.append(float(c[i]))
            self.volume.append(float(v[i]))
        if len(c):
            self.last_price = float(c[-1])
            self.prev_close = float(c[-2]) if len(c) > 1 else float(c[-1])
            self.session_open = float(c[0])

    def push_tick(self, price: float, size: float, ts: float) -> None:
        self.last_price = price
        self.ticks += 1
        if not self.close:
            for _ in range(3):
                self.ts.append(ts); self.open.append(price); self.high.append(price)
                self.low.append(price); self.close.append(price); self.volume.append(size)
            self.session_open = self.prev_close = price
            self._bar_start = ts
            return
        if ts - self._bar_start >= self.bar_seconds:
            self.prev_close = float(self.close[-1])
            self.ts.append(ts); self.open.append(price); self.high.append(price)
            self.low.append(price); self.close.append(price); self.volume.append(size)
            self._bar_start = ts
            return
        self.high[-1] = max(self.high[-1], price)
        self.low[-1] = min(self.low[-1], price)
        self.close[-1] = price
        self.volume[-1] += size

    def replace_bar(self, ts: float, o: float, h: float, l: float, c: float, v: float) -> None:
        """Merge an authoritative bar from a live venue feed."""
        if not self.ts or ts > self.ts[-1]:
            self.ts.append(ts); self.open.append(o); self.high.append(h)
            self.low.append(l); self.close.append(c); self.volume.append(v)
            self.last_price = c
            return
        if abs(ts - self.ts[-1]) < self.bar_seconds / 2:
            self.high[-1] = max(self.high[-1], h)
            self.low[-1] = min(self.low[-1], l)
            self.close[-1] = c
            self.volume[-1] = max(self.volume[-1], v)
            self.last_price = c

    # -------------------------------------------------------------- derived
    def arrays(self) -> Tuple[np.ndarray, ...]:
        return (np.asarray(self.ts), np.asarray(self.open), np.asarray(self.high),
                np.asarray(self.low), np.asarray(self.close), np.asarray(self.volume))

    def ready(self, minimum: int = 60) -> bool:
        return len(self.close) >= minimum


def compute_metrics(t: Ticker) -> Optional[Dict[str, float]]:
    if not t.ready(60):
        return None
    _, o, h, l, c, v = t.arrays()
    price = float(c[-1])
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    a = atr(h, l, c, 14)
    atr_pct = a / price if price else 0.0
    atr_series = np.array([atr(h[:i + 1], l[:i + 1], c[:i + 1], 14) for i in
                           range(max(3, len(c) - 120), len(c))]) / max(price, 1e-9)
    atr_rank = float((atr_series < atr_pct).mean()) if len(atr_series) else 0.5
    win20h, win20l = float(h[-20:].max()), float(l[-20:].min())
    win55h, win55l = float(h[-55:].max()), float(l[-55:].min())
    ma20, sd20 = float(c[-20:].mean()), float(c[-20:].std() + 1e-12)
    bb_pos = float(np.clip((price - (ma20 - 2 * sd20)) / (4 * sd20), -0.2, 1.2))
    r = rsi(c, 14)
    rets = np.diff(c[-21:]) / np.maximum(c[-21:-1], 1e-12)
    vol_recent = float(np.std(rets[-10:]) + 1e-12)
    vol_base = float(np.std(rets[-40:]) + 1e-12)
    roc10 = float(price / c[-11] - 1.0) if len(c) > 11 else 0.0
    roc30 = float(price / c[-31] - 1.0) if len(c) > 31 else 0.0
    net = float(abs(c[-1] - c[-21]))
    path = float(np.abs(np.diff(c[-21:])).sum() + 1e-12)
    efficiency = float(np.clip(net / path, 0.0, 1.0))
    vmean = float(v[-40:].mean() + 1e-9)
    vol_z = float(np.clip((v[-1] - vmean) / (float(v[-40:].std()) + 1e-9), -3, 6))
    slope9 = float((e9[-1] - e9[-6]) / max(price, 1e-9)) if len(e9) > 6 else 0.0
    slope21 = float((e21[-1] - e21[-11]) / max(price, 1e-9)) if len(e21) > 11 else 0.0
    slope50 = float((e50[-1] - e50[-16]) / max(price, 1e-9)) if len(e50) > 16 else 0.0
    above = float(price / e21[-1] - 1.0)
    stretch = float((price - ma20) / (2 * sd20 + 1e-12))
    hour = float((t.ts[-1] / 3600.0) % 24)
    session = 1.0 + 0.55 * math.exp(-((hour - 13.5) ** 2) / 9.0) + 0.5 * math.exp(-((hour - 9.0) ** 2) / 6.0)
    return dict(
        price=price, atr=a, atr_pct=atr_pct, atr_rank=atr_rank, rsi=r, bb_pos=bb_pos,
        win20h=win20h, win20l=win20l, win55h=win55h, win55l=win55l,
        dist_hi=float((win20h - price) / max(a, 1e-9)), dist_lo=float((price - win20l) / max(a, 1e-9)),
        roc10=roc10, roc30=roc30, efficiency=efficiency, vol_z=vol_z, slope9=slope9,
        slope21=slope21, slope50=slope50, above_ema21=above, stretch=stretch,
        vol_ratio=float(np.clip(vol_recent / vol_base, 0.2, 4.0)), session=session,
        hour=hour, bars=len(c), spread_ratio=0.0, tick_rate=t.tick_rate,
    )


def encode_glomeruli(m: Dict[str, float], spread: float) -> np.ndarray:
    """12 glomeruli in [0,1] — the fly's sensory input vector."""
    a = max(m["atr"], 1e-9)
    up_slope = (m["slope9"] * 260 + m["slope21"] * 120 + m["slope50"] * 55)
    dn_slope = -(m["slope9"] * 260 + m["slope21"] * 120 + m["slope50"] * 55)
    breakout_up = float(np.clip(1.0 - min(m["dist_hi"], 6.0) / 6.0, 0, 1))
    breakout_dn = float(np.clip(1.0 - min(m["dist_lo"], 6.0) / 6.0, 0, 1))
    g = np.array([
        sigmoid(up_slope * 9),                                   # 0 trend up
        sigmoid(dn_slope * 9),                                   # 1 trend down
        float(np.clip(0.5 + m["roc10"] / max(m["atr_pct"] * 2.2, 1e-6) * 0.5, 0, 1)),  # momentum
        float(np.clip(abs(m["stretch"]) / 2.4, 0, 1)),           # mean-reversion stretch
        breakout_up,                                             # breakout proximity up
        breakout_dn,                                             # breakout proximity down
        float(np.clip(m["atr_rank"], 0, 1)),                     # volatility regime
        float(np.clip(m["vol_z"] / 4.0, 0, 1)),                  # participation surge
        float(np.clip(m["efficiency"] * 1.4, 0, 1)),             # trendiness
        float(np.clip((m["session"] - 0.9) / 1.1, 0, 1)),        # session liquidity
        float(np.clip(1.0 - m["spread_ratio"] * 26.0, 0, 1)),    # cost of entry
        float(np.clip(m["vol_ratio"] / 3.0, 0, 1)),              # micro volatility burst
    ], dtype=np.float64)
    return np.clip(g, 0.0, 1.0)


def trend_composite(m: Dict[str, float]) -> float:
    """Signed trend strength the desks agree on (-1..1).

    Weighted the way the calibration study measured it: the 21-EMA slope carries
    most of the signal, the 50-EMA confirms it, and the value saturates so a
    single burst cannot dominate the committee's read.
    """
    return float(0.62 * math.tanh(m["slope21"] * 120.0) + 0.38 * math.tanh(m["slope50"] * 60.0))


def strategy_bias(m: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
    """Signed (-1..1) directional stimulus assembled from independent edges."""
    trend = 0.42 * math.tanh(m["slope21"] * 140) + 0.28 * math.tanh(m["slope50"] * 70)
    momo = 0.30 * math.tanh(m["roc10"] / max(m["atr_pct"], 1e-6) * 0.55)
    brk = 0.0
    if m["dist_hi"] < 0.35:
        brk += 0.35
    if m["dist_lo"] < 0.35:
        brk -= 0.35
    reversion = 0.0
    if m["rsi"] > 74 or m["stretch"] > 2.0:
        reversion -= 0.30
    elif m["rsi"] < 26 or m["stretch"] < -2.0:
        reversion += 0.30
    quality = 0.25 * (m["efficiency"] - 0.35) - 0.2 * max(0.0, m["spread_ratio"] * 20 - 1)
    bias = float(np.clip(trend + momo + brk + reversion, -1.0, 1.0))
    parts_trend = trend_composite(m)
    parts = dict(trend=round(trend, 4), momentum=round(momo, 4), breakout=round(brk, 4),
                 mean_reversion=round(reversion, 4), quality=round(quality, 4),
                 composite=round(bias, 4), trend_composite=round(parts_trend, 4))
    return bias, parts


def build_signal_levels(m: Dict[str, float], direction: str, sl_atr: float = 1.00,
                        tp_atr: float = 2.20) -> Dict[str, float]:
    a = max(m["atr"], 1e-9)
    price = m["price"]
    if direction == "long":
        entry = price + a * 0.12
        sl = entry - a * sl_atr
        tp = entry + a * tp_atr
    else:
        entry = price - a * 0.12
        sl = entry + a * sl_atr
        tp = entry - a * tp_atr
    return dict(entry=entry, stop_loss=sl, take_profit=tp)
