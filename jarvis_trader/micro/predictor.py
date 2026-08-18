"""
MICRO PREDICTOR - live inference for the trained microstructure model.

Loads <SYMBOL>_model.pkl and, given a live FeatureEngine state (fed by the
recorder running in-process) produces:

    {"signal": "BUY"|"SELL"|"NO-TRADE",
     "confidence": 0.91,            # calibrated
     "entry": ..., "tp": ..., "sl": ...,
     "probs": {...}, "shadow": True}

SHADOW MODE: predictions are logged to <SYMBOL>_shadow.jsonl together with
the later outcome so we can measure real precision BEFORE letting it trade.
The council exposes it as the MICRO member only when a model file exists.
"""
import json
import pickle
import time
from pathlib import Path

from .. import config

MICRO_DIR = config.DATA_DIR / "micro"

_models = {}


def load_model(symbol):
    if symbol in _models:
        return _models[symbol]
    path = MICRO_DIR / f"{symbol}_model.pkl"
    if not path.exists():
        _models[symbol] = None
        return None
    try:
        with open(path, "rb") as fh:
            _models[symbol] = pickle.load(fh)
    except Exception:
        _models[symbol] = None
    return _models[symbol]


def available(symbol):
    return load_model(symbol) is not None


def predict(symbol, feature_row):
    """feature_row = dict from FeatureEngine.features(). Returns dict or None."""
    bundle = load_model(symbol)
    if not bundle or not feature_row:
        return None
    import numpy as np
    X = np.array([[float(feature_row.get(c, 0) or 0) for c in bundle["cols"]]])
    proba = bundle["model"].predict_proba(X)[0]
    # calibrate
    cal = bundle.get("calibrators", {})
    p = []
    for cls in (0, 1, 2):
        v = float(proba[cls])
        if cls in cal:
            v = float(cal[cls].predict([v])[0])
        p.append(v)
    s = sum(p) or 1.0
    p = [x / s for x in p]
    cls = int(max(range(3), key=lambda i: p[i]))
    conf = p[cls]
    gate = bundle.get("conf_gate", 0.75)

    entry = feature_row["mid"]
    tp_bps = 12.0
    sl_bps = 8.0
    out = {"probs": {"SELL": round(p[0], 3), "NO-TRADE": round(p[1], 3),
                     "BUY": round(p[2], 3)},
           "confidence": round(conf, 3), "gate": gate,
           "entry": entry, "shadow": True, "t": feature_row["t"]}
    if cls == 2 and conf >= gate:
        out.update({"signal": "BUY",
                    "tp": entry * (1 + tp_bps / 1e4),
                    "sl": entry * (1 - sl_bps / 1e4)})
    elif cls == 0 and conf >= gate:
        out.update({"signal": "SELL",
                    "tp": entry * (1 - tp_bps / 1e4),
                    "sl": entry * (1 + sl_bps / 1e4)})
    else:
        out.update({"signal": "NO-TRADE", "tp": None, "sl": None})
    return out


def council_score(symbol, feature_row):
    """MICRO as a council member: -100..+100 vote + detail, or None."""
    r = predict(symbol, feature_row)
    if not r:
        return None
    p = r["probs"]
    score = (p["BUY"] - p["SELL"]) * 100
    return {"score": round(max(-100, min(100, score)), 1),
            "detail": {"signal": r["signal"], "confidence": r["confidence"],
                       "probs": p, "model": "micro-lgbm", "shadow": True}}


def log_shadow(symbol, prediction):
    """Append a shadow prediction for later outcome-scoring."""
    path = MICRO_DIR / f"{symbol}_shadow.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(prediction, separators=(",", ":")) + "\n")


def score_shadow(symbol, horizon=300, tp_bps=12.0, sl_bps=8.0, log=print):
    """Resolve past shadow predictions against recorded mids -> precision."""
    from .microfeatures import iter_records
    path = MICRO_DIR / f"{symbol}_shadow.jsonl"
    if not path.exists():
        return {"n": 0}
    preds = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                preds.append(json.loads(line))
            except Exception:
                pass
    mids = [(r["t"], (r["bids"][0][0] + r["asks"][0][0]) / 2)
            for r in iter_records(symbol) if r.get("type") == "snap"]
    right = wrong = pending = 0
    for pr in preds:
        if pr.get("signal") not in ("BUY", "SELL"):
            continue
        t0, entry = pr["t"], pr["entry"]
        path_mids = [(t, m) for t, m in mids if t0 < t <= t0 + horizon]
        if not path_mids:
            pending += 1
            continue
        d = 1 if pr["signal"] == "BUY" else -1
        tp_px = entry * (1 + d * tp_bps / 1e4)
        sl_px = entry * (1 - d * sl_bps / 1e4)
        hit = None
        for _, m in path_mids:
            if (d == 1 and m >= tp_px) or (d == -1 and m <= tp_px):
                hit = "tp"
                break
            if (d == 1 and m <= sl_px) or (d == -1 and m >= sl_px):
                hit = "sl"
                break
        if hit == "tp":
            right += 1
        elif hit == "sl":
            wrong += 1
        else:
            pending += 1
    n = right + wrong
    res = {"n": n, "right": right, "wrong": wrong, "pending": pending,
           "precision": round(100 * right / n, 1) if n else None}
    log(f"[shadow] {symbol}: {res}")
    return res
