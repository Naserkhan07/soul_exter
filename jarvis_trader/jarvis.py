"""
JARVIS - the self-training ML brain.

- Builds a feature vector from indicators / strategies / news sentiment.
- Predicts direction with an online logistic-regression (SGD) model.
- AUTO-TRAINS itself two ways:
    1. Bootstrap: on startup it replays historical candles of every watchlist
       asset and learns from thousands of "did price go up N bars later?"
       samples (this is the initial 'trading knowledge' training).
    2. Online: every closed trade and every resolved prediction is fed back
       so Jarvis keeps learning from the live market while running.
- Persists its weights to data_store/jarvis_brain.json so knowledge survives restarts.
"""
import json
import math
import random
import threading
import time

from . import config
from .knowledge import all_rules

BRAIN_PATH = config.DATA_DIR / "jarvis_brain.json"

FEATURES = [
    "rsi_norm", "macd_hist_norm", "ema_trend", "price_vs_ema200", "bb_pos",
    "stoch_k", "adx_strength", "dmi_dir", "vwap_dist", "supertrend",
    "strat_trend", "strat_meanrev", "strat_breakout", "strat_macd", "strat_vwap",
    "strat_abcd", "abcd_dist", "strat_orderflow", "strat_math",
    "pat_score", "pat_candle", "pat_chart", "pat_agreement",
    "news_sent", "vol_ratio", "ret_5", "ret_20", "ret_60", "range_pos", "bias",
]


def build_features(snap, strat, news_score, pat=None):
    """Map raw analysis into normalized features (-1..1)."""
    f = {}
    r = snap.get("rsi14")
    f["rsi_norm"] = ((r or 50) - 50) / 50
    m = snap.get("macd")
    if m:
        scale = max(abs(m["macd"]), abs(m["signal"]), 1e-9)
        f["macd_hist_norm"] = max(-1, min(1, m["hist"] / scale))
    else:
        f["macd_hist_norm"] = 0
    e20, e50, e200, price = snap.get("ema20"), snap.get("ema50"), snap.get("ema200"), snap["price"]
    f["ema_trend"] = 1 if (e20 and e50 and e20 > e50) else (-1 if e20 and e50 else 0)
    f["price_vs_ema200"] = 1 if (e200 and price > e200) else (-1 if e200 else 0)
    bb = snap.get("bollinger")
    f["bb_pos"] = max(-1, min(1, (price - bb["mid"]) / (bb["width"] / 2))) if bb and bb["width"] else 0
    st = snap.get("stochastic")
    f["stoch_k"] = ((st["k"] if st else 50) - 50) / 50
    ax = snap.get("adx")
    f["adx_strength"] = min(1, (ax["adx"] if ax else 0) / 50)
    f["dmi_dir"] = (1 if ax["pdi"] > ax["mdi"] else -1) if ax else 0
    vw = snap.get("vwap")
    f["vwap_dist"] = max(-1, min(1, (price - vw) / vw * 50)) if vw else 0
    f["supertrend"] = snap.get("supertrend", 0)

    by_name = {s["name"]: s["score"] / 100 for s in strat["strategies"]}
    f["strat_trend"] = by_name.get("TrendFollowing", 0)
    f["strat_meanrev"] = by_name.get("MeanReversion", 0)
    f["strat_breakout"] = by_name.get("Breakout", 0)
    f["strat_macd"] = by_name.get("MACDCross", 0)
    f["strat_vwap"] = by_name.get("VWAPPullback", 0)
    f["strat_abcd"] = by_name.get("ABCD_Projection", 0)
    f["strat_orderflow"] = by_name.get("OrderFlow", 0)
    f["strat_math"] = by_name.get("MathModel", 0)

    # signed, normalized distance to the projected A-B-C-D level (if any):
    # positive = D above price (upside magnet), negative = D below.
    abcd = strat.get("abcd")
    if abcd and price:
        f["abcd_dist"] = max(-1, min(1, (abcd["D"] - price) / price * 100))
    else:
        f["abcd_dist"] = 0.0

    # candlestick + chart pattern features
    if pat:
        f["pat_score"] = max(-1, min(1, pat["pattern_score"] / 100))
        candle_hits = [p for p in pat["patterns"] if p["kind"] == "candle"]
        chart_hits = [p for p in pat["patterns"] if p["kind"] == "chart"]
        f["pat_candle"] = max(-1, min(1, sum(p["score"] for p in candle_hits) / 150)) \
            if candle_hits else 0.0
        f["pat_chart"] = max(-1, min(1, sum(p["score"] for p in chart_hits) / 150)) \
            if chart_hits else 0.0
        total = pat["bullish_count"] + pat["bearish_count"]
        f["pat_agreement"] = ((pat["bullish_count"] - pat["bearish_count"]) / total) \
            if total else 0.0
    else:
        f["pat_score"] = f["pat_candle"] = f["pat_chart"] = f["pat_agreement"] = 0.0

    f["news_sent"] = max(-1, min(1, news_score / 100))
    f["vol_ratio"] = 0.0
    f["ret_5"] = 0.0
    f["ret_20"] = 0.0
    f["ret_60"] = 0.0
    f["range_pos"] = 0.0
    f["bias"] = 1.0
    return f


def add_price_features(f, candles):
    """Market-movement features extracted from raw live candles."""
    cl = [c["c"] for c in candles]
    if len(cl) > 21:
        f["ret_5"] = max(-1, min(1, (cl[-1] / cl[-6] - 1) * 40))
        f["ret_20"] = max(-1, min(1, (cl[-1] / cl[-21] - 1) * 20))
    if len(cl) > 61:
        f["ret_60"] = max(-1, min(1, (cl[-1] / cl[-61] - 1) * 12))
    # where price sits inside the recent 60-bar range (-1 = at low, +1 = at high)
    window = candles[-60:]
    hh = max(c["h"] for c in window)
    ll = min(c["l"] for c in window)
    if hh > ll:
        f["range_pos"] = (cl[-1] - ll) / (hh - ll) * 2 - 1
    vols = [c["v"] for c in candles[-20:]]
    avg = sum(vols[:-1]) / max(len(vols) - 1, 1)
    if avg > 0:
        f["vol_ratio"] = max(-1, min(1, vols[-1] / avg - 1))
    return f


class JarvisBrain:
    def __init__(self):
        self.lock = threading.Lock()
        self.w = {k: 0.0 for k in FEATURES}
        self.lr = 0.03
        self.samples_trained = 0
        self.bootstrap_done = False
        self.live_feedback = 0
        self.correct = 0
        self.total_scored = 0
        self._load()
        self._seed_knowledge_priors()

    # ------------------------------------------------------------- #
    def _seed_knowledge_priors(self):
        """Encode the knowledge base as prior weights (only if untrained)."""
        if self.samples_trained > 0:
            return
        priors = {
            "ema_trend": 0.5, "price_vs_ema200": 0.4, "macd_hist_norm": 0.45,
            "dmi_dir": 0.3, "adx_strength": 0.05, "supertrend": 0.35,
            "rsi_norm": -0.15, "bb_pos": -0.10, "stoch_k": -0.05,
            "vwap_dist": 0.15, "strat_trend": 0.5, "strat_meanrev": 0.3,
            "strat_breakout": 0.4, "strat_macd": 0.35, "strat_vwap": 0.25,
            "strat_abcd": 0.35, "abcd_dist": 0.15,
            "strat_orderflow": 0.45, "strat_math": 0.4,
            "pat_score": 0.45, "pat_candle": 0.3, "pat_chart": 0.4, "pat_agreement": 0.25,
            "news_sent": 0.5, "vol_ratio": 0.05, "ret_5": 0.15, "ret_20": 0.2,
            "ret_60": 0.15, "range_pos": 0.1, "bias": 0.0,
        }
        self.w.update(priors)

    def _load(self):
        try:
            data = json.loads(BRAIN_PATH.read_text())
            # brain version = the feature set; if features changed, retrain fresh
            if data.get("features") != FEATURES:
                return
            self.w.update(data.get("w", {}))
            self.samples_trained = data.get("samples_trained", 0)
            self.bootstrap_done = data.get("bootstrap_done", False)
            self.live_feedback = data.get("live_feedback", 0)
            self.correct = data.get("correct", 0)
            self.total_scored = data.get("total_scored", 0)
        except Exception:
            pass

    def save(self):
        with self.lock:
            BRAIN_PATH.write_text(json.dumps({
                "features": FEATURES,
                "w": self.w, "samples_trained": self.samples_trained,
                "bootstrap_done": self.bootstrap_done,
                "live_feedback": self.live_feedback,
                "correct": self.correct, "total_scored": self.total_scored,
                "knowledge_rules": len(all_rules()),
            }, indent=1))

    # ------------------------------------------------------------- #
    def predict(self, f):
        """Returns (score -100..100, prob_up)."""
        with self.lock:
            z = sum(self.w[k] * f.get(k, 0.0) for k in FEATURES)
        p = 1 / (1 + math.exp(-max(-30, min(30, z))))
        return round((p - 0.5) * 200, 1), p

    def train_sample(self, f, went_up, weight=1.0):
        """One SGD step of logistic regression."""
        y = 1.0 if went_up else 0.0
        with self.lock:
            z = sum(self.w[k] * f.get(k, 0.0) for k in FEATURES)
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            err = (p - y) * weight
            for k in FEATURES:
                self.w[k] -= self.lr * (err * f.get(k, 0.0) + 0.0005 * self.w[k])
            self.samples_trained += 1

    def feedback(self, f, went_up, was_prediction_up):
        """Live feedback from a resolved prediction or closed trade."""
        self.train_sample(f, went_up, weight=2.0)
        with self.lock:
            self.live_feedback += 1
            self.total_scored += 1
            if went_up == was_prediction_up:
                self.correct += 1
        self.save()

    @property
    def accuracy(self):
        return round(100 * self.correct / self.total_scored, 1) if self.total_scored else None

    # ------------------------------------------------------------- #
    def bootstrap_train(self, get_candles_fn, watchlist, log=None):
        """
        Auto-train on history: for each asset, slide a window through its
        candles on multiple timeframes and horizons and learn
        "did close rise `horizon` bars later?".
        """
        from . import indicators as ind
        from . import strategies as strat_mod
        from . import patterns as pat_mod

        total = 0
        plans = [("5m", 300, (3, 6, 12)),      # short/medium/longer intraday moves
                 ("15m", 200, (4, 8))]
        for asset in watchlist:
            for interval, limit, horizons in plans:
                try:
                    candles, src = get_candles_fn(asset, interval, limit)
                except Exception:
                    continue
                if len(candles) < 120:
                    continue
                for horizon in horizons:
                    step = max(1, (len(candles) - 80 - horizon) // 30)
                    for i in range(80, len(candles) - horizon, step):
                        window = candles[:i]
                        try:
                            snap = ind.snapshot(window)
                            st = strat_mod.run_all(window, snap)
                            sw = strat_mod.find_swings(window)
                            pt = pat_mod.scan(window, sw)
                            f = build_features(snap, st, 0.0, pt)
                            add_price_features(f, window)
                            went_up = candles[i + horizon - 1]["c"] > window[-1]["c"]
                            self.train_sample(f, went_up)
                            total += 1
                        except Exception:
                            continue
            if log:
                log(f"Jarvis bootstrap: multi-timeframe training on {asset['symbol']}")
        with self.lock:
            self.bootstrap_done = True
        self.save()
        return total


BRAIN = JarvisBrain()
