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


def find_swings(candles, k=3, max_swings=12):
    """
    Detect swing highs/lows using fractal pivots:
    a swing high is a candle whose high is the highest of k candles either side
    (swing low is the mirror). Returns newest-last list of
    {"type": "H"|"L", "price", "idx", "t"}.
    """
    swings = []
    n = len(candles)
    for i in range(k, n - k):
        hi = candles[i]["h"]
        lo = candles[i]["l"]
        if all(hi >= candles[j]["h"] for j in range(i - k, i + k + 1) if j != i):
            swings.append({"type": "H", "price": hi, "idx": i, "t": candles[i]["t"]})
        elif all(lo <= candles[j]["l"] for j in range(i - k, i + k + 1) if j != i):
            swings.append({"type": "L", "price": lo, "idx": i, "t": candles[i]["t"]})
    # collapse consecutive same-type swings, keep the more extreme one
    clean = []
    for s in swings:
        if clean and clean[-1]["type"] == s["type"]:
            if (s["type"] == "H" and s["price"] > clean[-1]["price"]) or \
               (s["type"] == "L" and s["price"] < clean[-1]["price"]):
                clean[-1] = s
        else:
            clean.append(s)
    return clean[-max_swings:]


def abcd_projection(candles, snap):
    """
    Mathematical price-projection strategy (A-B-C -> D).

    From live swing structure pick:
      A = starting swing point, B = next major swing, C = pullback after B
    then project the 4th level:   D = (B x C) / A
    and mark it as a reaction / target zone.

    Bullish structure  (A=low, B=high, C=higher-low pullback): D projects above.
    Bearish structure  (A=high, B=low, C=lower-high pullback): D projects below.

    Scoring (level is NOT an automatic signal - it needs confirmation):
      - valid structure and price still travelling toward D  -> vote WITH the
        structure direction (D acts as target / draw on liquidity)
      - price within 0.15% of D                              -> expect a
        reaction: vote fades to ~0 (wait & watch, per the strategy rules)
      - price cleanly beyond D                                -> level burned,
        small momentum vote only
    """
    swings = find_swings(candles)
    price = snap["price"]
    if len(swings) < 3:
        return {"name": "ABCD_Projection", "score": 0,
                "reason": "no clear A-B-C swing structure yet", "abcd": None}

    A, B, C = swings[-3], swings[-2], swings[-1]

    bullish = A["type"] == "L" and B["type"] == "H" and C["type"] == "L"
    bearish = A["type"] == "H" and B["type"] == "L" and C["type"] == "H"
    if not (bullish or bearish):
        return {"name": "ABCD_Projection", "score": 0,
                "reason": "swing sequence not an A-B-C structure", "abcd": None}

    # validate the pullback: C must sit between A and B (a real retracement)
    lo, hi = min(A["price"], B["price"]), max(A["price"], B["price"])
    if not (lo < C["price"] < hi) or A["price"] <= 0:
        return {"name": "ABCD_Projection", "score": 0,
                "reason": "pullback C not inside A-B range, structure invalid", "abcd": None}

    D = (B["price"] * C["price"]) / A["price"]
    abcd = {"A": round(A["price"], 6), "B": round(B["price"], 6),
            "C": round(C["price"], 6), "D": round(D, 6),
            "direction": "bullish" if bullish else "bearish"}

    dist = (D - price) / price          # signed distance to the projected level
    near = abs(dist) < 0.0015           # within 0.15% of D = reaction zone

    if bullish:
        if near:
            score = 5
            reason = f"price AT bullish D level {D:.6g} - watch for reaction, need confirmation"
        elif price < D:
            # still travelling up toward D; closer = stronger conviction (cap)
            score = int(min(65, 20 + 4500 * min(abs(dist), 0.01)))
            reason = (f"bullish A-B-C ({A['price']:.6g}->{B['price']:.6g}->{C['price']:.6g}), "
                      f"projected D={D:.6g} above, price magnetized toward it")
        else:
            score = 15
            reason = f"price broke above D {D:.6g}, projection met - momentum only"
    else:
        if near:
            score = -5
            reason = f"price AT bearish D level {D:.6g} - watch for reaction, need confirmation"
        elif price > D:
            score = -int(min(65, 20 + 4500 * min(abs(dist), 0.01)))
            reason = (f"bearish A-B-C ({A['price']:.6g}->{B['price']:.6g}->{C['price']:.6g}), "
                      f"projected D={D:.6g} below, price drawn toward it")
        else:
            score = -15
            reason = f"price broke below D {D:.6g}, projection met - momentum only"

    return {"name": "ABCD_Projection", "score": score, "reason": reason, "abcd": abcd}


ALL_STRATEGIES = [trend_following, mean_reversion, momentum_breakout, macd_cross,
                  vwap_pullback, abcd_projection]


def run_all(candles, snap):
    results = [fn(candles, snap) for fn in ALL_STRATEGIES]
    avg = sum(r["score"] for r in results) / max(len(results), 1)
    abcd = next((r.get("abcd") for r in results if r["name"] == "ABCD_Projection"), None)
    return {"strategies": results, "strategy_score": round(avg, 1), "abcd": abcd}
