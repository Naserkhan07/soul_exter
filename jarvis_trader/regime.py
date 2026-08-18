"""
MARKET REGIME DETECTION with adaptive parameters.

Classifies each asset's current market condition into 6 regimes
(ADX trend strength + EMA direction + volatility percentile) and
adapts HOW the bot trades in each:

  regime         detect                       trade adaptation
  -------------  ---------------------------  --------------------------------
  STRONG_BULL    ADX>25, trend up             ride winners: wider TP (2.5R),
                                              trend engines weighted up
  BULL_TREND     ADX 18-25, trend up          standard trend following (2R)
  BEAR_TREND     ADX 18-25, trend down        standard, shorts favored
  STRONG_BEAR    ADX>25, trend down           ride shorts: wider TP (2.5R)
  RANGING        ADX<18                       quick profits (1.4R), tighter
                                              targets, mean-reversion weighted
                                              up, breakout/trend weighted down
  HIGH_VOL       ATR% in top decile of        half size, fast exits (1.2R),
                 its own history              earlier partial

Each regime returns:
  strategy_bias : multipliers applied to strategy votes in the council
  tp_r          : take-profit in R multiples
  partial_at_r  : where the first partial profit is taken
  size_mult     : position size multiplier
"""

REGIME_PARAMS = {
    "STRONG_BULL": {"tp_r": 2.5, "partial_at_r": 1.2, "size_mult": 1.0,
                    "bias": {"TrendFollowing": 1.4, "Breakout": 1.3,
                             "VWAPPullback": 1.2, "MeanReversion": 0.5}},
    "BULL_TREND":  {"tp_r": 2.0, "partial_at_r": 1.0, "size_mult": 1.0,
                    "bias": {"TrendFollowing": 1.2, "Breakout": 1.1,
                             "MeanReversion": 0.7}},
    "BEAR_TREND":  {"tp_r": 2.0, "partial_at_r": 1.0, "size_mult": 1.0,
                    "bias": {"TrendFollowing": 1.2, "Breakout": 1.1,
                             "MeanReversion": 0.7}},
    "STRONG_BEAR": {"tp_r": 2.5, "partial_at_r": 1.2, "size_mult": 0.9,
                    "bias": {"TrendFollowing": 1.4, "Breakout": 1.3,
                             "MeanReversion": 0.5}},
    "RANGING":     {"tp_r": 1.4, "partial_at_r": 0.8, "size_mult": 0.9,
                    "bias": {"MeanReversion": 1.5, "VWAPPullback": 1.2,
                             "TrendFollowing": 0.6, "Breakout": 0.6,
                             "MACDCross": 0.8}},
    "HIGH_VOL":    {"tp_r": 1.2, "partial_at_r": 0.7, "size_mult": 0.5,
                    "bias": {"OrderFlow": 1.2, "MeanReversion": 0.8,
                             "Breakout": 0.8, "TrendFollowing": 0.8}},
}


def detect(candles, snap):
    """
    Classify the current regime for one asset.
    Returns {"regime", "params", "why"}.
    """
    adx = (snap.get("adx") or {}).get("adx")
    e20, e50 = snap.get("ema20"), snap.get("ema50")
    price = snap["price"]
    atr = snap.get("atr14") or price * 0.005

    # --- volatility percentile: current ATR% vs its own recent history ---
    n = len(candles)
    atrp_now = atr / price if price else 0
    high_vol = False
    if n >= 120:
        # rough historical ATR%: mean true range over rolling windows
        trs = []
        for i in range(1, n):
            h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)) /
                       max(candles[i]["c"], 1e-12))
        window = 14
        atrps = [sum(trs[i:i + window]) / window
                 for i in range(0, len(trs) - window, window)]
        if atrps:
            rank = sum(1 for x in atrps if x < atrp_now) / len(atrps)
            high_vol = rank >= 0.90

    trend_up = bool(e20 and e50 and e20 > e50 and price > e20)
    trend_dn = bool(e20 and e50 and e20 < e50 and price < e20)

    if high_vol:
        regime, why = "HIGH_VOL", "ATR% in top decile of its own history"
    elif adx is None or adx < 18:
        regime, why = "RANGING", f"ADX {adx:.0f} < 18 - no trend" if adx else "no ADX"
    elif adx > 25 and trend_up:
        regime, why = "STRONG_BULL", f"ADX {adx:.0f} > 25, EMAs stacked up"
    elif adx > 25 and trend_dn:
        regime, why = "STRONG_BEAR", f"ADX {adx:.0f} > 25, EMAs stacked down"
    elif trend_up:
        regime, why = "BULL_TREND", f"ADX {adx:.0f}, trend up"
    elif trend_dn:
        regime, why = "BEAR_TREND", f"ADX {adx:.0f}, trend down"
    else:
        regime, why = "RANGING", f"ADX {adx:.0f} but EMAs flat/conflicting"

    return {"regime": regime, "params": REGIME_PARAMS[regime], "why": why}


def confidence_size_mult(confidence, min_conf):
    """
    Confidence-based position sizing (0.5x .. 1.5x).
      at threshold      -> 0.5x (borderline setups risk half)
      threshold + 15    -> 1.0x
      threshold + 30+   -> 1.5x (monster setups risk more)
    """
    edge = confidence - min_conf
    mult = 0.5 + (edge / 30.0)
    return max(0.5, min(1.5, mult))
