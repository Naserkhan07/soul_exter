"""
MICRO MODEL TRAINER (spec sections 20-28).

  - LightGBM 3-class (SELL / NO-TRADE / BUY) on the labeled feature rows
    (falls back to sklearn GradientBoosting if lightgbm isn't installed)
  - CHRONOLOGICAL walk-forward validation (never shuffled)
  - probability CALIBRATION (isotonic, per class, on held-out folds)
  - HARD-EXAMPLE mining: misclassified high-confidence rows get weight
    boosted and the model is retrained (v1 -> v2 -> ...)
  - saves model + calibrators + feature list + metrics to
    data_store/micro/<SYMBOL>_model.pkl

Run:  python -m jarvis_trader.micro.train_micro BTCUSDT --rounds 3
"""
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

from .. import config

MICRO_DIR = config.DATA_DIR / "micro"

EXCLUDE = {"t", "mid", "y", "tp_bps", "sl_bps", "horizon"}
CLASSES = ["SELL", "NO-TRADE", "BUY"]


def load_dataset(symbol):
    path = MICRO_DIR / f"{symbol}_labeled.jsonl"
    X, y, ts = [], [], []
    cols = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if cols is None:
                cols = [k for k in r if k not in EXCLUDE]
            X.append([float(r.get(c, 0) or 0) for c in cols])
            y.append(int(r["y"]))
            ts.append(r["t"])
    return np.array(X), np.array(y), np.array(ts), cols


def make_model():
    try:
        import lightgbm as lgb
        return lgb.LGBMClassifier(
            objective="multiclass", num_class=3, n_estimators=400,
            learning_rate=0.05, num_leaves=63, min_child_samples=30,
            subsample=0.9, colsample_bytree=0.8, reg_lambda=1.0,
            verbose=-1), "lightgbm"
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, max_leaf_nodes=63,
            min_samples_leaf=30), "sklearn-hgb"


def walk_forward(X, y, n_folds=4):
    """Yield (train_idx, test_idx) chronological folds."""
    n = len(y)
    fold = n // (n_folds + 1)
    for k in range(1, n_folds + 1):
        tr_end = fold * k
        te_end = min(fold * (k + 1), n)
        if te_end - tr_end < 50 or tr_end < 100:
            continue
        yield np.arange(0, tr_end), np.arange(tr_end, te_end)


def evaluate(model, X_te, y_te, conf_gate=0.75):
    proba = model.predict_proba(X_te)
    pred = proba.argmax(axis=1)
    out = {}
    # directional precision (only BUY/SELL predictions count)
    for cls, name in ((0, "SELL"), (2, "BUY")):
        mask = pred == cls
        if mask.sum():
            out[f"precision_{name}"] = round(
                float((y_te[mask] == cls).mean()) * 100, 1)
            out[f"n_{name}"] = int(mask.sum())
    # gated: only act when max prob >= gate AND it's directional
    conf = proba.max(axis=1)
    gated = (conf >= conf_gate) & (pred != 1)
    out["gated_signals"] = int(gated.sum())
    if gated.sum():
        out["gated_precision"] = round(
            float((y_te[gated] == pred[gated]).mean()) * 100, 1)
    return out, proba, pred


def train(symbol, rounds=3, conf_gate=0.75, log=print):
    X, y, ts, cols = load_dataset(symbol)
    if len(y) < 300:
        log(f"[train] {symbol}: only {len(y)} rows - need 300+. "
            "Keep the recorder running longer.")
        return None
    log(f"[train] {symbol}: {len(y)} rows, {len(cols)} features "
        f"(BUY {int((y==2).sum())} / SELL {int((y==0).sum())} / "
        f"NO-TRADE {int((y==1).sum())})")

    weights = np.ones(len(y))
    model = None
    backend = None
    history = []

    for rnd in range(1, rounds + 1):
        fold_metrics = []
        hard_idx = []
        for tr, te in walk_forward(X, y):
            m, backend = make_model()
            try:
                m.fit(X[tr], y[tr], sample_weight=weights[tr])
            except TypeError:
                m.fit(X[tr], y[tr])
            met, proba, pred = evaluate(m, X[te], y[te], conf_gate)
            fold_metrics.append(met)
            # hard examples: confidently wrong on the test fold
            conf = proba.max(axis=1)
            wrong = (pred != y[te]) & (conf > 0.6)
            hard_idx.extend(te[wrong].tolist())

        # aggregate fold metrics
        agg = {}
        for k in set(k for f in fold_metrics for k in f):
            vals = [f[k] for f in fold_metrics if k in f]
            agg[k] = round(float(np.mean(vals)), 1) if vals else None
        history.append({"round": rnd, "metrics": agg,
                        "hard_examples": len(hard_idx)})
        log(f"[train] v{rnd}: {agg} | hard examples: {len(hard_idx)}")

        # boost hard-example weights for the next round (spec section 27-28)
        if hard_idx and rnd < rounds:
            weights[hard_idx] *= 2.0

    # final model on ALL data (with final weights) + isotonic calibration
    # on the last 20% chronological slice
    split = int(len(y) * 0.8)
    m, backend = make_model()
    try:
        m.fit(X[:split], y[:split], sample_weight=weights[:split])
    except TypeError:
        m.fit(X[:split], y[:split])
    proba_val = m.predict_proba(X[split:])

    from sklearn.isotonic import IsotonicRegression
    calibrators = {}
    for cls in (0, 1, 2):
        target = (y[split:] == cls).astype(float)
        p = proba_val[:, cls]
        if len(np.unique(target)) > 1 and len(p) > 40:
            ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            ir.fit(p, target)
            calibrators[cls] = ir

    # feature importance (top 12)
    imp = {}
    if hasattr(m, "feature_importances_"):
        order = np.argsort(m.feature_importances_)[::-1][:12]
        imp = {cols[i]: round(float(m.feature_importances_[i]), 1)
               for i in order}
        log(f"[train] top features: {list(imp)[:8]}")

    bundle = {"model": m, "backend": backend, "cols": cols,
              "calibrators": calibrators, "conf_gate": conf_gate,
              "classes": CLASSES, "history": history,
              "feature_importance": imp,
              "trained_at": time.time(), "n_rows": len(y),
              "symbol": symbol}
    out = MICRO_DIR / f"{symbol}_model.pkl"
    with open(out, "wb") as fh:
        pickle.dump(bundle, fh)
    log(f"[train] saved -> {out}")
    return bundle


if __name__ == "__main__":
    args = sys.argv[1:]
    rounds = 3
    if "--rounds" in args:
        i = args.index("--rounds")
        rounds = int(args[i + 1])
        del args[i:i + 2]
    for sym in (args or ["BTCUSDT"]):
        train(sym.upper(), rounds=rounds)
