"""
Rule-based trading strategies. Each returns a dict:
  {"name", "score" (-100..+100), "reason"}
The council aggregates these together with indicators, news, Jarvis, Gemini, Groq.
"""
from . import indicators as ind


def _closes(c): return [x["c"] for x in c]


def trend_following(candles, snap):
    """EMA stack + ADX confirmation."""
    e20, e50, e200 = snap.get("ema20"), snap.get("ema50"), snap.get("ema200")
    adx = snap.get("adx")
    if not (e20 and e50):
        return {"name": "TrendFollowing", "score": 0, "reason": "not enough data"}
    score = 0
    reason = []
    if e20 > e50:
        score += 40; reason.append("EMA20>EMA50 uptrend")
    else:
        score -= 40; reason.append("EMA20<EMA50 downtrend")
    if e200:
        if snap["price"] > e200:
            score += 20; reason.append("price above EMA200")
        else:
            score -= 20; reason.append("price below EMA200")
    if adx and adx["adx"] > 25:
        score = int(score * 1.3); reason.append(f"strong trend ADX={adx['adx']:.0f}")
    elif adx and adx["adx"] < 15:
        score = int(score * 0.5); reason.append("weak/choppy ADX")
    return {"name": "TrendFollowing", "score": max(-100, min(100, score)),
            "reason": "; ".join(reason)}


def mean_reversion(candles, snap):
    """RSI extremes + Bollinger band touches."""
    r = snap.get("rsi14")
    bb = snap.get("bollinger")
    price = snap["price"]
    if r is None or not bb:
        return {"name": "MeanReversion", "score": 0, "reason": "not enough data"}
    score = 0
    reason = []
    if r < 25:
        score += 60; reason.append(f"RSI deeply oversold ({r:.0f})")
    elif r < 32:
        score += 35; reason.append(f"RSI oversold ({r:.0f})")
    elif r > 75:
        score -= 60; reason.append(f"RSI deeply overbought ({r:.0f})")
    elif r > 68:
        score -= 35; reason.append(f"RSI overbought ({r:.0f})")
    if price <= bb["lower"]:
        score += 30; reason.append("price at lower Bollinger band")
    elif price >= bb["upper"]:
        score -= 30; reason.append("price at upper Bollinger band")
    if not reason:
        reason.append("price mid-range, no edge")
    return {"name": "MeanReversion", "score": max(-100, min(100, score)),
            "reason": "; ".join(reason)}


def momentum_breakout(candles, snap):
    """Donchian style breakout of last 40 candles + volume expansion."""
    if len(candles) < 45:
        return {"name": "Breakout", "score": 0, "reason": "not enough data"}
    window = candles[-41:-1]
    hh = max(x["h"] for x in window)
    ll = min(x["l"] for x in window)
    price = snap["price"]
    vols = [x["v"] for x in candles[-20:]]
    vol_ok = vols[-1] > 1.4 * (sum(vols[:-1]) / max(len(vols) - 1, 1)) if sum(vols) > 0 else False
    if price > hh:
        s = 65 + (15 if vol_ok else 0)
        return {"name": "Breakout", "score": s,
                "reason": f"breakout above 40-bar high {hh:.4g}" + (" with volume surge" if vol_ok else "")}
    if price < ll:
        s = -65 - (15 if vol_ok else 0)
        return {"name": "Breakout", "score": s,
                "reason": f"breakdown below 40-bar low {ll:.4g}" + (" with volume surge" if vol_ok else "")}
    pos = (price - ll) / (hh - ll) if hh != ll else 0.5
    return {"name": "Breakout", "score": round((pos - 0.5) * 30),
            "reason": f"inside range, {pos*100:.0f}% of 40-bar range"}


def macd_cross(candles, snap):
    m = snap.get("macd")
    if not m:
        return {"name": "MACDCross", "score": 0, "reason": "not enough data"}
    closes = _closes(candles)
    prev = ind.macd(closes[:-1])
    score = 0
    reason = []
    if prev:
        if prev["hist"] <= 0 < m["hist"]:
            score += 70; reason.append("fresh bullish MACD cross")
        elif prev["hist"] >= 0 > m["hist"]:
            score -= 70; reason.append("fresh bearish MACD cross")
    if not reason:
        scale = max(abs(m["macd"]), abs(m["signal"]), 1e-9)
        score = int(50 * m["hist"] / scale)
        reason.append("MACD histogram " + ("positive" if m["hist"] > 0 else "negative"))
    return {"name": "MACDCross", "score": max(-100, min(100, score)),
            "reason": "; ".join(reason)}


def vwap_pullback(candles, snap):
    vw = snap.get("vwap")
    e50 = snap.get("ema50")
    price = snap["price"]
    if not (vw and e50):
        return {"name": "VWAPPullback", "score": 0, "reason": "not enough data"}
    trend_up = price > e50
    dist = (price - vw) / vw
    score = 0
    reason = []
    if trend_up and -0.004 < dist < 0.001:
        score = 55; reason.append("uptrend pullback to VWAP - buy zone")
    elif (not trend_up) and -0.001 < dist < 0.004:
        score = -55; reason.append("downtrend pullback to VWAP - sell zone")
    else:
        score = int(max(-30, min(30, dist * 2500)))
        reason.append(f"price {'above' if dist>0 else 'below'} VWAP by {dist*100:.2f}%")
    return {"name": "VWAPPullback", "score": score, "reason": "; ".join(reason)}


ALL_STRATEGIES = [trend_following, mean_reversion, momentum_breakout, macd_cross, vwap_pullback]


def run_all(candles, snap):
    results = [fn(candles, snap) for fn in ALL_STRATEGIES]
    avg = sum(r["score"] for r in results) / max(len(results), 1)
    return {"strategies": results, "strategy_score": round(avg, 1)}
