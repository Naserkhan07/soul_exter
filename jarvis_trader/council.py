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

from . import config, feeds, indicators, strategies, news, jarvis
from .knowledge import as_prompt_context

TIMEOUT = 25

WEIGHTS = {
    "indicators": 1.0,
    "strategies": 1.0,
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


def _build_llm_prompt(asset, snap, strat, news_score, news_titles, jarvis_score):
    ctx = as_prompt_context(1800)
    ind_lines = json.dumps({k: v for k, v in snap.items() if k not in ("votes",)},
                           default=lambda o: round(o, 5) if isinstance(o, float) else str(o))[:900]
    strat_lines = "; ".join(f"{s['name']}={s['score']} ({s['reason'][:60]})"
                            for s in strat["strategies"])
    titles = " | ".join(news_titles[:4]) if news_titles else "no fresh relevant headlines"
    return f"""You are JARVIS, an elite quantitative trading analyst.

EXPERT KNOWLEDGE:
{ctx}

TASK: Analyze {asset['name']} ({asset['symbol']}, type={asset['type']}) and decide if price will go UP or DOWN in the next 30-60 minutes.

CURRENT TECHNICALS (5m candles): {ind_lines}
STRATEGY SIGNALS: {strat_lines}
NEWS SENTIMENT SCORE: {news_score} (-100 bearish .. +100 bullish)
RECENT HEADLINES: {titles}
JARVIS ML MODEL SCORE: {jarvis_score}

Respond with ONLY a JSON object, no markdown:
{{"direction": "UP" or "DOWN", "score": <integer -100 to 100, negative=down conviction, positive=up conviction>, "confidence": <0-100>, "reason": "<one concise sentence>"}}"""


def ask_gemini(prompt):
    if not config.GEMINI_API_KEY:
        return None, "no API key configured"
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}")
        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}],
                                     "generationConfig": {"temperature": 0.2,
                                                          "maxOutputTokens": 200}},
                          timeout=TIMEOUT)
        if r.status_code != 200:
            _llm_status["gemini"] = f"HTTP {r.status_code}"
            return None, f"HTTP {r.status_code}: {r.text[:120]}"
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        js = _extract_json(text)
        if js:
            _llm_status["gemini"] = "ok"
            return js, None
        return None, "unparseable reply"
    except Exception as e:
        _llm_status["gemini"] = "unreachable"
        return None, str(e)[:120]


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


def analyze(asset, use_llms=True):
    """Full council analysis for one asset. Returns a big verdict dict."""
    t0 = time.time()
    candles, source = feeds.get_candles(asset, "5m", 220)
    snap = indicators.snapshot(candles)
    strat = strategies.run_all(candles, snap)

    news.ENGINE.refresh()
    news_score, n_rel, titles = news.ENGINE.asset_sentiment(asset["symbol"])

    f = jarvis.build_features(snap, strat, news_score)
    jarvis.add_price_features(f, candles)
    jarvis_score, prob_up = jarvis.BRAIN.predict(f)

    members = {
        "indicators": {"score": snap["indicator_score"], "detail": snap["votes"]},
        "strategies": {"score": strat["strategy_score"],
                       "detail": {s["name"]: s["score"] for s in strat["strategies"]}},
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
        prompt = _build_llm_prompt(asset, snap, strat, news_score, titles, jarvis_score)
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
    for name, m in members.items():
        if m["score"] is None:
            continue
        w = WEIGHTS.get(name, 1.0)
        num += w * m["score"]
        den += w
    final = num / den if den else 0.0
    direction = "UP" if final >= 0 else "DOWN"
    confidence = round(abs(final), 1)

    price = snap["price"]
    a = snap.get("atr14") or price * 0.005
    if direction == "UP":
        entry, sl, tp = price, price - 1.5 * a, price + 3.0 * a
    else:
        entry, sl, tp = price, price + 1.5 * a, price - 3.0 * a

    return {
        "symbol": asset["symbol"], "name": asset["name"], "type": asset["type"],
        "price": price, "data_source": source,
        "verdict": {"direction": direction, "score": round(final, 1),
                    "confidence": confidence},
        "members": members,
        "plan": {"entry": round(entry, 6), "tp": round(tp, 6), "sl": round(sl, 6),
                 "atr": round(a, 6), "rr": 2.0},
        "features": f,
        "elapsed_sec": round(time.time() - t0, 2),
        "ts": time.time(),
    }
