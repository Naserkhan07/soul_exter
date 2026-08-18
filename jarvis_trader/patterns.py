"""
LIVE PATTERN RECOGNITION ENGINE.

Scans live candles for the full pattern deck:

CANDLESTICK PATTERNS (candle anatomy):
  Hammer, Inverted Hammer, Hanging Man, Shooting Star,
  Doji, Gravestone Doji, Dragonfly Doji,
  Bullish/Bearish Engulfing, Piercing Line, Dark Cloud Cover,
  Morning Star, Evening Star, Morning Doji Star, Evening Doji Star,
  Three White Soldiers, Three Black Crows,
  Bullish/Bearish Harami, Bullish/Bearish Harami Cross,
  Tweezer Top, Tweezer Bottom, Bullish/Bearish Kicker,
  Rising Window (gap up), Falling Window (gap down),
  Upside/Downside Tasuki Gap, Rising/Falling Three Methods,
  Bullish/Bearish Separating Lines, Bullish/Bearish Inside Bar,
  Bullish Side-by-Side White Lines, Bearish Side-by-Side White Line

CHART PATTERNS (swing structure):
  Double Top/Bottom, Triple Top/Bottom,
  Head & Shoulders, Inverse Head & Shoulders,
  Rising/Falling Wedge, Ascending/Descending/Symmetrical Triangle,
  Bullish/Bearish Flag, Bullish/Bearish Pennant,
  Bullish/Bearish Rectangle, Cup & Handle, Rounding Bottom,
  Broadening Formation, Diamond Top/Bottom

Every hit returns: {name, kind, direction, score(-100..100), age(bars back), note}
Aggregate pattern_score is the council's "patterns" vote.
"""


# ------------------------------------------------------------------ #
#  candle anatomy helpers
# ------------------------------------------------------------------ #
def _body(c):      return abs(c["c"] - c["o"])
def _range(c):     return max(c["h"] - c["l"], 1e-12)
def _upper(c):     return c["h"] - max(c["c"], c["o"])
def _lower(c):     return min(c["c"], c["o"]) - c["l"]
def _green(c):     return c["c"] > c["o"]
def _red(c):       return c["c"] < c["o"]
def _mid(c):       return (c["o"] + c["c"]) / 2


def _avg_body(candles, n=14):
    xs = candles[-n:]
    return sum(_body(c) for c in xs) / max(len(xs), 1)


def _trend_before(candles, i, look=8):
    """Rough trend into bar i: +1 up, -1 down, 0 flat."""
    if i < look:
        return 0
    a, b = candles[i - look]["c"], candles[i - 1]["c"]
    chg = (b - a) / max(abs(a), 1e-12)
    if chg > 0.0025:
        return 1
    if chg < -0.0025:
        return -1
    return 0


def _is_doji(c, tol=0.12):
    return _body(c) <= tol * _range(c)


# ------------------------------------------------------------------ #
#  CANDLESTICK DETECTORS - each checks the pattern ENDING at index i
# ------------------------------------------------------------------ #
def _detect_candles_at(candles, i):
    """Return list of candlestick pattern hits ending at bar i.

    TRIPLE+ CANDLE PATTERNS ONLY (per user decision): single- and
    double-candle patterns (hammer, doji, engulfing, harami, tweezers,
    kickers, windows, piercing, dark cloud...) fire constantly on intraday
    charts and carry little edge alone - removed. Multi-bar sequences
    encode real structure and stay:
      Morning/Evening Star (+ Doji Star), Three White Soldiers,
      Three Black Crows, Upside/Downside Tasuki Gap,
      Side-by-Side White Lines, Rising/Falling Three Methods.
    """
    hits = []
    if i < 2:
        return hits
    c0 = candles[i]
    c1 = candles[i - 1]
    c2 = candles[i - 2]
    ab = _avg_body(candles[:i + 1])
    tr = _trend_before(candles, i)

    def add(name, direction, score, note=""):
        hits.append({"name": name, "kind": "candle", "direction": direction,
                     "score": score, "note": note})

    # --- three candle ---
    # morning / evening star (+ doji variants)
    if _red(c2) and _body(c2) > ab and _body(c1) < 0.5 * ab \
            and _green(c0) and c0["c"] > _mid(c2):
        nm = "Morning Doji Star" if _is_doji(c1) else "Morning Star"
        add(nm, "bullish", 60)
    if _green(c2) and _body(c2) > ab and _body(c1) < 0.5 * ab \
            and _red(c0) and c0["c"] < _mid(c2):
        nm = "Evening Doji Star" if _is_doji(c1) else "Evening Star"
        add(nm, "bearish", -60)

    # three soldiers / crows
    if all(_green(x) for x in (c2, c1, c0)) and \
            c0["c"] > c1["c"] > c2["c"] and \
            all(_body(x) > 0.6 * ab for x in (c2, c1, c0)):
        add("Three White Soldiers", "bullish", 65)
    if all(_red(x) for x in (c2, c1, c0)) and \
            c0["c"] < c1["c"] < c2["c"] and \
            all(_body(x) > 0.6 * ab for x in (c2, c1, c0)):
        add("Three Black Crows", "bearish", -65)

    # tasuki gaps
    if c1["l"] > c2["h"] and _green(c2) and _green(c1) and _red(c0) \
            and c0["o"] > c1["o"] and c0["c"] < c1["o"] and c0["c"] > c2["h"]:
        add("Upside Tasuki Gap", "bullish", 40, "gap holds, uptrend continues")
    if c1["h"] < c2["l"] and _red(c2) and _red(c1) and _green(c0) \
            and c0["o"] < c1["o"] and c0["c"] > c1["o"] and c0["c"] < c2["l"]:
        add("Downside Tasuki Gap", "bearish", -40, "gap holds, downtrend continues")

    # side-by-side white lines
    if c1["l"] > c2["h"] and _green(c1) and _green(c0) \
            and abs(c0["o"] - c1["o"]) <= 0.3 * _range(c1) \
            and abs(_body(c0) - _body(c1)) <= 0.5 * max(_body(c1), 1e-12):
        add("Bullish Side-by-Side White Lines", "bullish", 40)
    if c1["h"] < c2["l"] and _green(c1) and _green(c0) \
            and abs(c0["o"] - c1["o"]) <= 0.3 * _range(c1):
        add("Bearish Side-by-Side White Line", "bearish", -35,
            "white lines below gap = continuation down")

    # rising / falling three methods (5 bars)
    if i >= 4:
        c3, c4 = candles[i - 3], candles[i - 4]
        if _green(c4) and _body(c4) > ab and _green(c0) and c0["c"] > c4["c"] \
                and all(_red(x) or _body(x) < 0.5 * ab for x in (c3, c2, c1)) \
                and all(x["l"] > c4["l"] and x["h"] < c4["h"] * 1.002 for x in (c3, c2, c1)):
            add("Rising Three Methods", "bullish", 50, "pause then continuation up")
        if _red(c4) and _body(c4) > ab and _red(c0) and c0["c"] < c4["c"] \
                and all(_green(x) or _body(x) < 0.5 * ab for x in (c3, c2, c1)) \
                and all(x["h"] < c4["h"] and x["l"] > c4["l"] * 0.998 for x in (c3, c2, c1)):
            add("Falling Three Methods", "bearish", -50, "pause then continuation down")

    return hits


def detect_candlestick_patterns(candles, lookback=6):
    """Scan the last `lookback` bars; newer hits weigh more (age recorded)."""
    out = []
    n = len(candles)
    for age in range(0, min(lookback, n - 10)):
        i = n - 1 - age
        for h in _detect_candles_at(candles, i):
            h["age"] = age
            out.append(h)
    # dedupe by name keeping newest
    seen, dedup = set(), []
    for h in out:
        if h["name"] in seen:
            continue
        seen.add(h["name"])
        dedup.append(h)
    return dedup


# ------------------------------------------------------------------ #
#  CHART PATTERN DETECTORS - swing structure based
# ------------------------------------------------------------------ #
def _fit_slope(points):
    """Least-squares slope of (idx, price) points, normalized by price."""
    n = len(points)
    if n < 2:
        return 0.0
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in points)
    den = sum((p[0] - mx) ** 2 for p in points) or 1e-12
    return (num / den) / max(abs(my), 1e-12)


def detect_chart_patterns(candles, swings):
    """Detect swing-structure chart patterns from pivots (newest last)."""
    hits = []
    price = candles[-1]["c"]

    def add(name, direction, score, note=""):
        hits.append({"name": name, "kind": "chart", "direction": direction,
                     "score": score, "age": 0, "note": note})

    highs = [s for s in swings if s["type"] == "H"]
    lows = [s for s in swings if s["type"] == "L"]
    if len(swings) < 4:
        return hits

    def near(a, b, tol=0.004):
        return abs(a - b) / max(abs(b), 1e-12) <= tol

    # ---- double / triple top & bottom ----
    if len(highs) >= 2 and near(highs[-1]["price"], highs[-2]["price"]):
        if len(highs) >= 3 and near(highs[-2]["price"], highs[-3]["price"]):
            add("Triple Top", "bearish", -60, f"three equal highs ~{highs[-1]['price']:.6g}")
        else:
            neck = min((l["price"] for l in lows if l["idx"] > highs[-2]["idx"]),
                       default=None)
            broke = neck is not None and price < neck
            add("Double Top", "bearish", -55 if broke else -35,
                "neckline broken" if broke else "watch neckline")
    if len(lows) >= 2 and near(lows[-1]["price"], lows[-2]["price"]):
        if len(lows) >= 3 and near(lows[-2]["price"], lows[-3]["price"]):
            add("Triple Bottom", "bullish", 60, f"three equal lows ~{lows[-1]['price']:.6g}")
        else:
            neck = max((h["price"] for h in highs if h["idx"] > lows[-2]["idx"]),
                       default=None)
            broke = neck is not None and price > neck
            add("Double Bottom", "bullish", 55 if broke else 35,
                "neckline broken" if broke else "watch neckline")

    # ---- head & shoulders / inverse ----
    if len(highs) >= 3:
        l_, h_, r_ = highs[-3]["price"], highs[-2]["price"], highs[-1]["price"]
        if h_ > l_ * 1.004 and h_ > r_ * 1.004 and near(l_, r_, 0.012):
            add("Head & Shoulders", "bearish", -60,
                f"head {h_:.6g}, shoulders ~{l_:.6g}")
    if len(lows) >= 3:
        l_, h_, r_ = lows[-3]["price"], lows[-2]["price"], lows[-1]["price"]
        if h_ < l_ * 0.996 and h_ < r_ * 0.996 and near(l_, r_, 0.012):
            add("Inverse Head & Shoulders", "bullish", 60,
                f"head {h_:.6g}, shoulders ~{l_:.6g}")

    # ---- trendline geometry: wedges / triangles / rectangles / broadening ----
    if len(highs) >= 3 and len(lows) >= 3:
        hs = _fit_slope([(s["idx"], s["price"]) for s in highs[-3:]])
        ls = _fit_slope([(s["idx"], s["price"]) for s in lows[-3:]])
        FLAT, S = 6e-5, 1.6

        if hs > FLAT and ls > FLAT:
            if ls > hs * 1.15:
                add("Rising Wedge", "bearish", -45, "converging up-sloping lines")
        if hs < -FLAT and ls < -FLAT:
            if hs < ls * 1.15:
                add("Falling Wedge", "bullish", 45, "converging down-sloping lines")
        if abs(hs) <= FLAT and ls > FLAT:
            add("Ascending Triangle", "bullish", 50, "flat top, rising lows")
        if abs(ls) <= FLAT and hs < -FLAT:
            add("Descending Triangle", "bearish", -50, "flat bottom, falling highs")
        if hs < -FLAT and ls > FLAT:
            add("Symmetrical Triangle", "neutral", 0, "coiling - trade the break")
        if abs(hs) <= FLAT and abs(ls) <= FLAT:
            top = sum(s["price"] for s in highs[-3:]) / 3
            bot = sum(s["price"] for s in lows[-3:]) / 3
            if top > bot:
                if price > top:
                    add("Bullish Rectangle", "bullish", 45, "range break up")
                elif price < bot:
                    add("Bearish Rectangle", "bearish", -45, "range break down")
                else:
                    add("Rectangle (Range)", "neutral", 0, "inside the box")
        if hs > S * FLAT and ls < -S * FLAT:
            add("Broadening Formation", "neutral", -10,
                "expanding volatility, unstable")

    # ---- flags & pennants: sharp pole then tight drift against it ----
    if len(candles) >= 30:
        pole = (candles[-8]["c"] - candles[-28]["c"]) / max(candles[-28]["c"], 1e-12)
        drift = (candles[-1]["c"] - candles[-8]["c"]) / max(candles[-8]["c"], 1e-12)
        rng_recent = (max(c["h"] for c in candles[-8:]) -
                      min(c["l"] for c in candles[-8:])) / price
        tight = rng_recent < abs(pole) * 0.55
        if pole > 0.012 and -0.006 < drift <= 0.002 and tight:
            add("Bullish Flag", "bullish", 50, "pole + tight pullback")
        if pole < -0.012 and -0.002 <= drift < 0.006 and tight:
            add("Bearish Flag", "bearish", -50, "pole + tight pullback")
        if pole > 0.012 and tight and rng_recent < abs(pole) * 0.35:
            add("Bullish Pennant", "bullish", 45, "tiny coil after pole up")
        if pole < -0.012 and tight and rng_recent < abs(pole) * 0.35:
            add("Bearish Pennant", "bearish", -45, "tiny coil after pole down")

    # ---- rounding bottom / cup & handle ----
    if len(candles) >= 60:
        seg = candles[-60:]
        cl = [c["c"] for c in seg]
        third = len(cl) // 3
        left = sum(cl[:third]) / third
        mid = sum(cl[third:2 * third]) / third
        right = sum(cl[2 * third:]) / (len(cl) - 2 * third)
        if mid < left * 0.995 and mid < right * 0.995 and near(left, right, 0.01):
            rim = max(cl[0], cl[-1])
            recent_dip = min(c["c"] for c in seg[-10:])
            if recent_dip < rim * 0.998 and price > recent_dip:
                add("Cup & Handle", "bullish", 50, f"rim {rim:.6g}, handle forming")
            else:
                add("Rounding Bottom", "bullish", 40, "saucer base")

    # ---- diamond: broadening then narrowing around a peak/trough ----
    if len(swings) >= 6:
        w1 = abs(swings[-6]["price"] - swings[-5]["price"])
        w2 = abs(swings[-4]["price"] - swings[-3]["price"])
        w3 = abs(swings[-2]["price"] - swings[-1]["price"])
        if w2 > w1 * 1.25 and w2 > w3 * 1.25:
            mean_sw = sum(s["price"] for s in swings[-6:]) / 6
            if price < mean_sw:
                add("Diamond Top", "bearish", -45, "expand-contract at highs")
            else:
                add("Diamond Bottom", "bullish", 45, "expand-contract at lows")

    return hits


# ------------------------------------------------------------------ #
#  MASTER SCAN
# ------------------------------------------------------------------ #
def scan(candles, swings):
    """Run all detectors. Returns {patterns:[...], pattern_score, bullish, bearish}."""
    hits = detect_candlestick_patterns(candles)
    hits += detect_chart_patterns(candles, swings)

    # weight: chart patterns full, candles decay with age
    num = den = 0.0
    for h in hits:
        w = 1.0 if h["kind"] == "chart" else max(0.35, 1.0 - 0.18 * h.get("age", 0))
        num += h["score"] * w
        den += w
    score = round(num / den, 1) if den else 0.0
    # emphasize agreement: if many patterns point one way, push the score
    bulls = [h for h in hits if h["score"] > 0]
    bears = [h for h in hits if h["score"] < 0]
    if len(bulls) >= 3 and len(bulls) >= 2 * max(len(bears), 1):
        score = min(100, score * 1.3)
    if len(bears) >= 3 and len(bears) >= 2 * max(len(bulls), 1):
        score = max(-100, score * 1.3)

    hits.sort(key=lambda h: (h.get("age", 0), -abs(h["score"])))
    return {"patterns": hits[:14], "pattern_score": round(score, 1),
            "bullish_count": len(bulls), "bearish_count": len(bears)}
