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


def order_flow(candles, snap):
    """
    Order-flow proxy strategy (works from OHLCV without tick data).

    Reads WHO is in control from candle anatomy + volume:
      - Buying/selling pressure: close position inside each bar's range
        weighted by volume  ->  cumulative delta proxy.
      - Absorption: huge volume but tiny range = passive side absorbing
        aggression (reversal warning).
      - Imbalance: volume-weighted delta of last 10 bars vs prior 10.
      - Wick rejection: long wicks on high volume = stop hunts / rejection.
    """
    if len(candles) < 30:
        return {"name": "OrderFlow", "score": 0, "reason": "not enough data"}
    score = 0.0
    reason = []

    # volume-weighted close-position delta (buying vs selling pressure)
    def bar_delta(c):
        rng = c["h"] - c["l"]
        if rng <= 0:
            return 0.0
        pos = (2 * c["c"] - c["h"] - c["l"]) / rng     # -1 (close at low) .. +1
        return pos * c["v"]

    recent = candles[-10:]
    prior = candles[-20:-10]
    d_recent = sum(bar_delta(c) for c in recent)
    d_prior = sum(bar_delta(c) for c in prior)
    v_recent = sum(c["v"] for c in recent) or 1e-9

    delta_norm = d_recent / v_recent                   # -1..1 net aggression
    score += delta_norm * 55
    if delta_norm > 0.15:
        reason.append(f"buyers aggressive (delta {delta_norm:+.2f})")
    elif delta_norm < -0.15:
        reason.append(f"sellers aggressive (delta {delta_norm:+.2f})")

    # delta shift: flow flipping direction
    if d_prior != 0 and (d_recent > 0) != (d_prior > 0) and abs(d_recent) > abs(d_prior) * 0.7:
        shift = 20 if d_recent > 0 else -20
        score += shift
        reason.append("order flow flipped " + ("bullish" if shift > 0 else "bearish"))

    # absorption: last bar volume >2x avg but range <0.6x avg range
    avg_v = sum(c["v"] for c in candles[-20:-1]) / 19 or 1e-9
    avg_r = sum(c["h"] - c["l"] for c in candles[-20:-1]) / 19 or 1e-9
    last = candles[-1]
    if last["v"] > 2 * avg_v and (last["h"] - last["l"]) < 0.6 * avg_r:
        # absorption against the recent move
        absorb = -25 if delta_norm > 0 else 25
        score += absorb
        reason.append("absorption: big volume, tiny range - passive side defending")

    # wick rejection on above-average volume
    rng = last["h"] - last["l"]
    if rng > 0 and last["v"] > 1.3 * avg_v:
        up_wick = (last["h"] - max(last["c"], last["o"])) / rng
        dn_wick = (min(last["c"], last["o"]) - last["l"]) / rng
        if up_wick > 0.55:
            score -= 20; reason.append("high-volume upper-wick rejection")
        if dn_wick > 0.55:
            score += 20; reason.append("high-volume lower-wick rejection")

    if not reason:
        reason.append("balanced two-sided flow")
    return {"name": "OrderFlow", "score": int(max(-100, min(100, score))),
            "reason": "; ".join(reason)}


def math_model(candles, snap):
    """
    Pure-mathematics strategy bundle:
      1. Linear regression channel: slope direction + z-score of price vs the
         regression line (statistical stretch).
      2. Momentum z-score: current return vs distribution of past returns.
      3. Hurst-like persistence: variance ratio test - trending vs mean
         reverting regime decides HOW the stretch is traded.
      4. Fibonacci retracement confluence on the last major swing.
    """
    cl = [c["c"] for c in candles]
    n = len(cl)
    if n < 60:
        return {"name": "MathModel", "score": 0, "reason": "not enough data"}
    score = 0.0
    reason = []

    # 1) linear regression channel over last 60 closes
    win = cl[-60:]
    m_ = len(win)
    xs = range(m_)
    mx = (m_ - 1) / 2
    my = sum(win) / m_
    cov = sum((i - mx) * (y - my) for i, y in zip(xs, win))
    varx = sum((i - mx) ** 2 for i in xs) or 1e-12
    slope = cov / varx
    resid = [y - (my + slope * (i - mx)) for i, y in zip(xs, win)]
    sd = (sum(r * r for r in resid) / m_) ** 0.5 or 1e-12
    z = resid[-1] / sd                              # price z-score vs regression
    slope_norm = slope * m_ / my                     # % move over window

    # 3) variance ratio (trend persistence): Var(5-bar) / (5 * Var(1-bar))
    rets = [cl[i] - cl[i - 1] for i in range(1, n)]
    r5 = [cl[i] - cl[i - 5] for i in range(5, n)]
    v1 = sum(r * r for r in rets[-50:]) / min(50, len(rets)) or 1e-12
    v5 = sum(r * r for r in r5[-46:]) / min(46, len(r5)) or 1e-12
    vr = v5 / (5 * v1)                               # >1 trending, <1 mean-reverting
    trending = vr > 1.1
    reverting = vr < 0.85

    trend_score = max(-40, min(40, slope_norm * 900))
    score += trend_score
    if abs(slope_norm) > 0.004:
        reason.append(f"regression slope {'up' if slope>0 else 'down'} "
                      f"({slope_norm*100:+.2f}%/60 bars)")

    if trending:
        # in trending regime, z-stretch is momentum: go WITH it mildly
        score += max(-20, min(20, z * 8))
        reason.append(f"variance ratio {vr:.2f} = trending regime")
    elif reverting and abs(z) > 1.6:
        # in mean-reverting regime fade the stretch
        score += -z * 22
        reason.append(f"z={z:+.1f} stretched in mean-reverting regime (VR {vr:.2f}) - fade")

    # 2) momentum z-score of the last 5-bar return
    mu = sum(rets[-50:]) / min(50, len(rets))
    sdr = (sum((r - mu) ** 2 for r in rets[-50:]) / min(50, len(rets))) ** 0.5 or 1e-12
    zmom = (cl[-1] - cl[-6]) / (5 ** 0.5 * sdr)
    if abs(zmom) > 2.2:
        score += max(-15, min(15, zmom * 5))
        reason.append(f"momentum z-score {zmom:+.1f}")

    # 4) fibonacci retracement of last major swing (60-bar high/low)
    hh = max(c["h"] for c in candles[-60:])
    ll = min(c["l"] for c in candles[-60:])
    if hh > ll:
        lvl = (cl[-1] - ll) / (hh - ll)
        for fib, name in ((0.382, "38.2%"), (0.5, "50%"), (0.618, "61.8%")):
            if abs(lvl - fib) < 0.03:
                # bounce zone: direction depends on which end the swing started
                up_swing = cl[-1] > (hh + ll) / 2 or slope > 0
                fs = 18 if up_swing else -18
                score += fs
                reason.append(f"price at {name} fib retracement")
                break

    if not reason:
        reason.append("no statistical edge detected")
    return {"name": "MathModel", "score": int(max(-100, min(100, score))),
            "reason": "; ".join(reason)}


ALL_STRATEGIES = [trend_following, mean_reversion, momentum_breakout, macd_cross,
                  vwap_pullback, abcd_projection, order_flow, math_model]


def run_all(candles, snap):
    results = [fn(candles, snap) for fn in ALL_STRATEGIES]
    avg = sum(r["score"] for r in results) / max(len(results), 1)
    abcd = next((r.get("abcd") for r in results if r["name"] == "ABCD_Projection"), None)
    return {"strategies": results, "strategy_score": round(avg, 1), "abcd": abcd}
