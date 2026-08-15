"""
Technical indicators computed from raw candle lists.
Every indicator also emits a directional vote in [-100, +100]
(+ = bullish, - = bearish) so the AI council can score them.
"""
import math


def _closes(c):  return [x["c"] for x in c]
def _highs(c):   return [x["h"] for x in c]
def _lows(c):    return [x["l"] for x in c]
def _vols(c):    return [x["v"] for x in c]


def sma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def ema_series(vals, n):
    if len(vals) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(vals[:n]) / n]
    for v in vals[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(vals, n):
    s = ema_series(vals, n)
    return s[-1] if s else None


def rsi(vals, n=14):
    if len(vals) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - 100 / (1 + rs)


def macd(vals, fast=12, slow=26, signal=9):
    if len(vals) < slow + signal:
        return None
    ef = ema_series(vals, fast)
    es = ema_series(vals, slow)
    m = [a - b for a, b in zip(ef[-len(es):], es)]
    sig = ema_series(m, signal)
    if not sig:
        return None
    return {"macd": m[-1], "signal": sig[-1], "hist": m[-1] - sig[-1]}


def bollinger(vals, n=20, k=2.0):
    if len(vals) < n:
        return None
    mid = sma(vals, n)
    var = sum((v - mid) ** 2 for v in vals[-n:]) / n
    sd = math.sqrt(var)
    return {"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd, "width": 2 * k * sd}


def atr(candles, n=14):
    if len(candles) < n + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def stochastic(candles, n=14, d=3):
    if len(candles) < n + d:
        return None
    ks = []
    for i in range(n - 1, len(candles)):
        window = candles[i - n + 1:i + 1]
        hh = max(x["h"] for x in window)
        ll = min(x["l"] for x in window)
        c = candles[i]["c"]
        ks.append(100 * (c - ll) / (hh - ll) if hh != ll else 50)
    dv = sum(ks[-d:]) / d
    return {"k": ks[-1], "d": dv}


def adx(candles, n=14):
    if len(candles) < 2 * n + 1:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        up = candles[i]["h"] - candles[i - 1]["h"]
        dn = candles[i - 1]["l"] - candles[i]["l"]
        plus_dm.append(up if (up > dn and up > 0) else 0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0)
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    def smooth(x):
        s = [sum(x[:n])]
        for v in x[n:]:
            s.append(s[-1] - s[-1] / n + v)
        return s

    str_, spd, smd = smooth(trs), smooth(plus_dm), smooth(minus_dm)
    dxs = []
    for i in range(len(str_)):
        if str_[i] == 0:
            continue
        pdi = 100 * spd[i] / str_[i]
        mdi = 100 * smd[i] / str_[i]
        if pdi + mdi == 0:
            continue
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi))
    if len(dxs) < n:
        return None
    a = sum(dxs[:n]) / n
    for d in dxs[n:]:
        a = (a * (n - 1) + d) / n
    pdi = 100 * spd[-1] / str_[-1] if str_[-1] else 0
    mdi = 100 * smd[-1] / str_[-1] if str_[-1] else 0
    return {"adx": a, "pdi": pdi, "mdi": mdi}


def vwap(candles):
    num = den = 0.0
    for c in candles[-100:]:
        tp = (c["h"] + c["l"] + c["c"]) / 3
        num += tp * c["v"]
        den += c["v"]
    return num / den if den else None


def supertrend_dir(candles, n=10, mult=3.0):
    """Very light supertrend: returns +1 (up) / -1 (down) / 0."""
    a = atr(candles, n)
    if a is None or len(candles) < n + 2:
        return 0
    c = candles[-1]
    mid = (c["h"] + c["l"]) / 2
    upper = mid + mult * a
    lower = mid - mult * a
    price = c["c"]
    prev = candles[-2]["c"]
    if price > upper - mult * a * 1.5 and price > prev:
        return 1
    if price < lower + mult * a * 1.5 and price < prev:
        return -1
    return 1 if price > mid else -1


# --------------------------------------------------------------------------- #
#  Snapshot + directional votes
# --------------------------------------------------------------------------- #

def snapshot(candles):
    """Full indicator snapshot + per-indicator directional votes."""
    cl = _closes(candles)
    price = cl[-1]
    out = {"price": price}
    votes = {}

    r = rsi(cl)
    out["rsi14"] = r
    if r is not None:
        if r < 30:   votes["RSI"] = min(100, (30 - r) * 4)          # oversold -> bullish
        elif r > 70: votes["RSI"] = -min(100, (r - 70) * 4)         # overbought -> bearish
        else:        votes["RSI"] = (r - 50) * 1.2                  # momentum lean

    m = macd(cl)
    out["macd"] = m
    if m:
        scale = max(abs(m["macd"]), abs(m["signal"]), 1e-9)
        votes["MACD"] = max(-100, min(100, 100 * m["hist"] / scale))

    e20, e50, e200 = ema(cl, 20), ema(cl, 50), ema(cl, 200)
    out["ema20"], out["ema50"], out["ema200"] = e20, e50, e200
    if e20 and e50:
        v = 0
        v += 35 if e20 > e50 else -35
        if e200:
            v += 25 if price > e200 else -25
        v += 20 if price > e20 else -20
        votes["EMA_TREND"] = v

    bb = bollinger(cl)
    out["bollinger"] = bb
    if bb and bb["width"] > 0:
        pos = (price - bb["mid"]) / (bb["width"] / 2)   # -1 .. +1 approx
        # mean reversion vote at extremes, momentum in middle
        if pos > 0.95:    votes["BOLLINGER"] = -40
        elif pos < -0.95: votes["BOLLINGER"] = 40
        else:             votes["BOLLINGER"] = pos * 30

    st = stochastic(candles)
    out["stochastic"] = st
    if st:
        if st["k"] < 20:  votes["STOCH"] = 45 if st["k"] > st["d"] else 20
        elif st["k"] > 80: votes["STOCH"] = -45 if st["k"] < st["d"] else -20
        else:              votes["STOCH"] = (st["k"] - 50) * 0.6

    ax = adx(candles)
    out["adx"] = ax
    if ax:
        strength = min(1.5, ax["adx"] / 25)
        direction = 1 if ax["pdi"] > ax["mdi"] else -1
        votes["ADX_DMI"] = max(-100, min(100, direction * 40 * strength))

    vw = vwap(candles)
    out["vwap"] = vw
    if vw:
        votes["VWAP"] = max(-100, min(100, (price - vw) / vw * 4000))

    stdir = supertrend_dir(candles)
    out["supertrend"] = stdir
    votes["SUPERTREND"] = stdir * 50

    a = atr(candles)
    out["atr14"] = a

    out["votes"] = {k: round(v, 1) for k, v in votes.items()}
    out["indicator_score"] = round(sum(votes.values()) / max(len(votes), 1), 1)
    return out
