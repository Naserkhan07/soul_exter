"""
The AI COUNCIL.

For a selected asset it asks, in detail, "will this go UP or DOWN?" to:
  - Technical indicators   (vote -100..+100)
  - Rule-based strategies  (vote -100..+100)
  - News sentiment engine  (vote -100..+100)
  - JARVIS ML brain        (vote -100..+100, self-trained)
  - Gemini (Google LLM)    (vote -100..+100 + reasoning)
  - Groq   (Llama-3.3 70B) (vote -100..+100 + reasoning)

then combines all scores into a weighted VERDICT with confidence,
direction, suggested entry / TP / SL (ATR-based).
"""
import json
import re
import threading
import time

import requests

from . import config, feeds, indicators, strategies, patterns, news, jarvis
from .knowledge import as_prompt_context

TIMEOUT = 25

WEIGHTS = {
    "indicators": 1.0,
    "strategies": 1.0,
    "patterns": 1.1,
    "news": 0.8,
    "jarvis": 1.4,
    "gemini": 1.1,
    "groq": 1.1,
}

_llm_status = {"gemini": "untested", "groq": "untested"}


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0).replace("'", '"'))
        except Exception:
            return None


def _build_llm_prompt(asset, snap, strat, pat, news_score, news_titles, jarvis_score, interval="5m"):
    ctx = as_prompt_context(3400)
    ind_lines = json.dumps({k: v for k, v in snap.items() if k not in ("votes",)},
                           default=lambda o: round(o, 5) if isinstance(o, float) else str(o))[:900]
    strat_lines = "; ".join(f"{s['name']}={s['score']} ({s['reason'][:60]})"
                            for s in strat["strategies"])
    pat_lines = "; ".join(f"{p['name']}({p['direction']},{p['score']:+d} bars_ago={p.get('age',0)})"
                          if isinstance(p['score'], int) else
                          f"{p['name']}({p['direction']},{p['score']:+.0f})"
                          for p in pat["patterns"][:10]) or "none detected"
    abcd = strat.get("abcd")
    abcd_line = ""
    if abcd:
        abcd_line = (f"\nA-B-C-D PROJECTION: {abcd['direction']} structure, "
                     f"A={abcd['A']} B={abcd['B']} C={abcd['C']} -> projected D level = {abcd['D']} "
                     f"(D=(BxC)/A; a reaction/target zone, not an automatic signal)")
    titles = " | ".join(news_titles[:4]) if news_titles else "no fresh relevant headlines"
    return f"""You are JARVIS, an elite quantitative trading analyst.

EXPERT KNOWLEDGE:
{ctx}

TASK: Analyze {asset['name']} ({asset['symbol']}, type={asset['type']}) and decide if price will go UP or DOWN over the next 5-15 {interval} candles.

CURRENT TECHNICALS ({interval} candles): {ind_lines}
STRATEGY SIGNALS: {strat_lines}{abcd_line}
LIVE CANDLESTICK & CHART PATTERNS DETECTED: {pat_lines} (aggregate pattern score {pat['pattern_score']})
NEWS SENTIMENT SCORE: {news_score} (-100 bearish .. +100 bullish)
RECENT HEADLINES: {titles}
JARVIS ML MODEL SCORE: {jarvis_score}

Respond with ONLY a JSON object, no markdown:
{{"direction": "UP" or "DOWN", "score": <integer -100 to 100, negative=down conviction, positive=up conviction>, "confidence": <0-100>, "reason": "<one concise sentence>"}}"""


GEMINI_MODEL_FALLBACKS = ["gemini-2.0-flash", "gemini-2.5-flash",
                          "gemini-1.5-flash", "gemini-flash-latest"]
_gemini_model_idx = 0


def ask_gemini(prompt):
    global _gemini_model_idx
    if not config.GEMINI_API_KEY:
        return None, "no API key configured"
    last_err = "unknown"
    # try model names in order; remember the first that works
    for i in range(len(GEMINI_MODEL_FALLBACKS)):
        idx = (_gemini_model_idx + i) % len(GEMINI_MODEL_FALLBACKS)
        model = GEMINI_MODEL_FALLBACKS[idx]
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={config.GEMINI_API_KEY}")
            r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}],
                                         "generationConfig": {"temperature": 0.2,
                                                              "maxOutputTokens": 200}},
                              timeout=TIMEOUT)
            if r.status_code == 404:
                last_err = f"{model}: HTTP 404 (model not available for this key)"
                continue
            if r.status_code != 200:
                _llm_status["gemini"] = f"HTTP {r.status_code}"
                return None, f"{model}: HTTP {r.status_code}: {r.text[:100]}"
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            js = _extract_json(text)
            if js:
                _llm_status["gemini"] = "ok"
                _gemini_model_idx = idx
                return js, None
            return None, "unparseable reply"
        except Exception as e:
            last_err = str(e)[:100]
            _llm_status["gemini"] = "unreachable"
            return None, last_err
    _llm_status["gemini"] = "HTTP 404 all models"
    return None, last_err


def ask_groq(prompt):
    if not config.GROQ_API_KEY:
        return None, "no API key configured"
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                          json={"model": config.GROQ_MODEL,
                                "messages": [{"role": "user", "content": prompt}],
                                "temperature": 0.2, "max_tokens": 200},
                          timeout=TIMEOUT)
        if r.status_code != 200:
            _llm_status["groq"] = f"HTTP {r.status_code}"
            return None, f"HTTP {r.status_code}: {r.text[:120]}"
        text = r.json()["choices"][0]["message"]["content"]
        js = _extract_json(text)
        if js:
            _llm_status["groq"] = "ok"
            return js, None
        return None, "unparseable reply"
    except Exception as e:
        _llm_status["groq"] = "unreachable"
        return None, str(e)[:120]


def llm_status():
    return dict(_llm_status)


def _llm_vote(js):
    """Normalize an LLM JSON reply into a -100..100 score."""
    if not js:
        return None
    score = js.get("score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = None
    direction = str(js.get("direction", "")).upper()
    conf = js.get("confidence", 50)
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 50
    if score is None:
        score = conf if direction == "UP" else -conf
    if direction == "DOWN" and score > 0:
        score = -abs(score)
    if direction == "UP" and score < 0:
        score = abs(score)
    return max(-100, min(100, score))


HTF_MAP = {"1m": "15m", "2m": "15m", "5m": "30m", "10m": "1h",
           "15m": "1h", "30m": "1h", "1h": "1h"}


def _htf_bias(asset, interval):
    """Higher-timeframe trend bias: +1 up / -1 down / 0 flat, with strength."""
    htf = HTF_MAP.get(interval, "30m")
    if htf == interval:
        return 0, 0.0, htf
    try:
        candles, _ = feeds.get_candles(asset, htf, 120)
        snap = indicators.snapshot(candles)
        e20, e50 = snap.get("ema20"), snap.get("ema50")
        price = snap["price"]
        score = 0.0
        if e20 and e50:
            score += 1.0 if e20 > e50 else -1.0
            score += 0.5 if price > e20 else -0.5
        ax = snap.get("adx")
        strength = min(1.0, (ax["adx"] / 30) if ax else 0.5)
        bias = 1 if score > 0 else (-1 if score < 0 else 0)
        return bias, strength, htf
    except Exception:
        return 0, 0.0, htf


def analyze(asset, use_llms=True, interval="5m"):
    """Full council analysis for one asset on the chosen timeframe."""
    t0 = time.time()
    candles, source = feeds.get_candles(asset, interval, 220)
    snap = indicators.snapshot(candles)
    strat = strategies.run_all(candles, snap)
    swings = strategies.find_swings(candles)
    pat = patterns.scan(candles, swings)

    # refresh news in background (news loop keeps it warm); read current cache
    threading.Thread(target=news.ENGINE.refresh, daemon=True).start()
    news_score, n_rel, titles = news.ENGINE.asset_sentiment(asset["symbol"])

    f = jarvis.build_features(snap, strat, news_score, pat)
    jarvis.add_price_features(f, candles)
    jarvis_score, prob_up = jarvis.BRAIN.predict(f)

    members = {
        "indicators": {"score": snap["indicator_score"], "detail": snap["votes"]},
        "strategies": {"score": strat["strategy_score"],
                       "detail": {s["name"]: s["score"] for s in strat["strategies"]}},
        "patterns": {"score": pat["pattern_score"],
                     "detail": {"found": [{"name": p["name"], "dir": p["direction"],
                                           "score": p["score"], "bars_ago": p.get("age", 0),
                                           "note": p.get("note", "")}
                                          for p in pat["patterns"]],
                                "bullish": pat["bullish_count"],
                                "bearish": pat["bearish_count"]}},
        "news": {"score": news_score,
                 "detail": {"relevant_headlines": n_rel, "titles": titles[:3]}},
        "jarvis": {"score": jarvis_score,
                   "detail": {"prob_up": round(prob_up, 3),
                              "samples_trained": jarvis.BRAIN.samples_trained,
                              "live_feedback": jarvis.BRAIN.live_feedback,
                              "accuracy": jarvis.BRAIN.accuracy}},
    }

    gem_reason = groq_reason = None
    if use_llms:
        prompt = _build_llm_prompt(asset, snap, strat, pat, news_score, titles, jarvis_score, interval)
        results = {}

        def run(name, fn):
            results[name] = fn(prompt)

        tg = threading.Thread(target=run, args=("gemini", ask_gemini))
        tq = threading.Thread(target=run, args=("groq", ask_groq))
        tg.start(); tq.start(); tg.join(); tq.join()

        gjs, gerr = results.get("gemini", (None, "skipped"))
        qjs, qerr = results.get("groq", (None, "skipped"))
        gv, qv = _llm_vote(gjs), _llm_vote(qjs)
        if gv is not None:
            gem_reason = (gjs or {}).get("reason", "")
            members["gemini"] = {"score": gv, "detail": {"reason": gem_reason}}
        else:
            members["gemini"] = {"score": None, "detail": {"error": gerr}}
        if qv is not None:
            groq_reason = (qjs or {}).get("reason", "")
            members["groq"] = {"score": qv, "detail": {"reason": groq_reason}}
        else:
            members["groq"] = {"score": None, "detail": {"error": qerr}}

    # weighted verdict over members that voted
    num = den = 0.0
    votes = []
    for name, m in members.items():
        if m["score"] is None:
            continue
        w = WEIGHTS.get(name, 1.0)
        num += w * m["score"]
        den += w
        votes.append(m["score"])
    final = num / den if den else 0.0
    direction = "UP" if final >= 0 else "DOWN"

    # ---- higher-timeframe confirmation (accuracy filter) ----
    htf_bias, htf_strength, htf = _htf_bias(asset, interval)
    htf_aligned = (htf_bias > 0 and direction == "UP") or \
                  (htf_bias < 0 and direction == "DOWN")

    # ---- confidence calibration ----
    # raw |weighted avg| under-reads conviction when many members agree
    # mildly. Blend magnitude with AGREEMENT (how many members point the
    # same way) and the strength of the strongest agreeing member.
    base = abs(final)
    if votes:
        same = [v for v in votes if (v >= 0) == (final >= 0) and abs(v) >= 5]
        agree_ratio = len(same) / len(votes)
        strongest = max((abs(v) for v in same), default=0)
        confidence = base * 0.55 + agree_ratio * 32 + strongest * 0.22
        # HTF confluence: trading WITH the higher timeframe = boost,
        # AGAINST it = cut (counter-trend trades are lower probability)
        if htf_bias != 0:
            if htf_aligned:
                confidence += 8 * htf_strength
            else:
                confidence -= 14 * htf_strength
        # quality gates: chop filter + minimum agreement
        adx_v = (snap.get("adx") or {}).get("adx", 20)
        if adx_v < 13 and agree_ratio < 0.8:
            confidence *= 0.75          # dead chop, weak consensus
        if agree_ratio < 0.5:
            confidence *= 0.7           # council split down the middle
        # DON'T-CHASE filter: if price already ran hard in the trade
        # direction over the last few bars, entering NOW usually buys the
        # top / sells the bottom of the move -> instant SL. Penalize it.
        atr_q = snap.get("atr14") or (snap["price"] * 0.005)
        cl5 = [c["c"] for c in candles[-6:]]
        if len(cl5) >= 6 and atr_q > 0:
            run = (cl5[-1] - cl5[0]) / atr_q     # move in ATRs over 5 bars
            chasing = (direction == "UP" and run > 2.5) or \
                      (direction == "DOWN" and run < -2.5)
            if chasing:
                confidence *= 0.55           # overextended - wait for pullback
        # RSI extreme against entry: buying into 80+ / selling into 20- is late
        rsi_q = snap.get("rsi14")
        if rsi_q is not None:
            if (direction == "UP" and rsi_q > 76) or \
               (direction == "DOWN" and rsi_q < 24):
                confidence *= 0.7
        confidence = max(0.0, min(96.0, confidence))
    else:
        confidence = base
    confidence = round(confidence, 1)

    price = snap["price"]
    a = snap.get("atr14") or price * 0.005

    # ---- SL/TP engineering (accuracy fix) ----
    # Stops must sit BEHIND structure AND outside spread/noise range.
    # MIN_SL_PCT: in quiet markets ATR gets tiny (BTC 5m ATR can be 0.02%!)
    # and any ATR-multiple stop lands inside noise -> instant SL hits.
    # Floor the stop distance at a per-asset-type minimum % of price.
    MIN_SL_PCT = {"crypto": 0.0040, "forex": 0.0015, "stock": 0.0045,
                  "index": 0.0030, "futures": 0.0035, "fund": 0.0040}
    min_dist = price * MIN_SL_PCT.get(asset["type"], 0.0035)
    swings = strategies.find_swings(candles)
    buffer_ = 0.25 * a
    if direction == "UP":
        swing_lows = [s["price"] for s in swings if s["type"] == "L"][-2:]
        struct_sl = min(swing_lows) - buffer_ if swing_lows else price - 2.2 * a
        sl = min(price - 1.6 * a, max(struct_sl, price - 3.0 * a))
        sl = min(sl, price - min_dist)          # enforce noise floor
        risk = price - sl
        entry, tp = price, price + 2.0 * risk
    else:
        swing_highs = [s["price"] for s in swings if s["type"] == "H"][-2:]
        struct_sl = max(swing_highs) + buffer_ if swing_highs else price + 2.2 * a
        sl = max(price + 1.6 * a, min(struct_sl, price + 3.0 * a))
        sl = max(sl, price + min_dist)          # enforce noise floor
        risk = sl - price
        entry, tp = price, price - 2.0 * risk

    # If a valid A-B-C-D projection agrees with the verdict, use D as the
    # take-profit target (capped so R:R never drops below ~1.2).
    abcd = strat.get("abcd")
    tp_source = "ATR x2R"
    if abcd:
        D = abcd["D"]
        risk = abs(entry - sl)
        if direction == "UP" and abcd["direction"] == "bullish" and D > entry + 1.2 * risk:
            tp = min(D, entry + 4.0 * a)
            tp_source = f"ABCD D-level {D:.6g}"
        elif direction == "DOWN" and abcd["direction"] == "bearish" and D < entry - 1.2 * risk:
            tp = max(D, entry - 4.0 * a)
            tp_source = f"ABCD D-level {D:.6g}"

    return {
        "symbol": asset["symbol"], "name": asset["name"], "type": asset["type"],
        "price": price, "data_source": source, "interval": interval,
        "verdict": {"direction": direction, "score": round(final, 1),
                    "confidence": confidence,
                    "htf": {"tf": htf, "bias": htf_bias,
                            "aligned": htf_aligned,
                            "strength": round(htf_strength, 2)}},
        "members": members,
        "plan": {"entry": round(entry, 6), "tp": round(tp, 6), "sl": round(sl, 6),
                 "atr": round(a, 6),
                 "rr": round(abs(tp - entry) / max(abs(entry - sl), 1e-9), 2),
                 "tp_source": tp_source},
        "abcd": abcd,
        "features": f,
        "elapsed_sec": round(time.time() - t0, 2),
        "ts": time.time(),
    }
