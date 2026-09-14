"""Train the desks' weights on evidence instead of intuition.

Samples every ticket the calibrated entry gate would emit, walks each to first
touch, then measures which pieces of tape evidence actually predict the realised
R. Writes `soul_exter_scorecard_weights.json` — the desks load it at boot, so the
council argues from coefficients it has earned rather than from vibes, and the
live playbook keeps updating them from realised trades afterwards.

Usage (backend/):
    python3 scripts/train_scorecards.py --symbols 24 --cycles 40
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from typing import Dict, List

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_exter.agents.schemas import Signal
from soul_exter.brain.features import (build_signal_levels, compute_metrics, trend_composite)
from soul_exter.market.feed import MarketFeed
from soul_exter.market.universe import UNIVERSE, default_enabled, horizon_for

STEP = 6.0
MIN_EFF, MIN_TREND = 0.32, 0.30
SL_ATR, TP_ATR, HORIZON = 1.00, 2.20, 600.0
WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "soul_exter_scorecard_weights.json")

TERMS = ["align", "eff_adj", "extended", "chase", "rank", "cost_adj", "rr_adj",
         "vol_ratio", "session_adj", "room_hi", "room_lo", "bb_chase"]


def pieces(m: Dict[str, float], direction: str, rr: float) -> Dict[str, float]:
    sgn = 1.0 if direction == "long" else -1.0
    tc = trend_composite(m)
    stretch = m.get("stretch", 0.0) * sgn
    cost = m.get("spread_ratio", 0.0) / max(m.get("atr_pct", 1e-9), 1e-9)
    clip = lambda x, lo, hi: max(lo, min(hi, x))
    return dict(
        align=clip(tc * sgn, -1, 1),
        eff_adj=clip((m.get("efficiency", 0) - 0.30) * 3.2, -1, 1),
        extended=clip((abs(stretch) - 0.9) / 1.4, 0, 1),
        chase=clip((stretch - 0.9) / 1.4, 0, 1),
        rank=m.get("atr_rank", 0.5),
        cost_adj=clip((cost - 0.04) / 0.08, 0, 1),
        rr_adj=clip((rr - 1.6) / 1.6, -1, 1),
        vol_ratio=clip((m.get("vol_ratio", 1.0) - 1.0) / 1.5, -1, 1),
        session_adj=clip((m.get("session", 1.0) - 0.9) / 0.9, -1, 1),
        room_hi=clip((m.get("dist_hi", 3.0) - 0.5) / 3.0, -1, 1) * sgn,
        room_lo=clip((m.get("dist_lo", 3.0) - 0.5) / 3.0, -1, 1) * sgn,
        bb_chase=clip((m.get("bb_pos", 0.5) - 0.5) * 2.0, -1, 1) * sgn,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=24)
    ap.add_argument("--cycles", type=int, default=40)
    ap.add_argument("--seeds", default="20250914,777")
    args = ap.parse_args()

    syms = default_enabled()[: max(4, args.symbols)]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    rows: List[Dict] = []

    for seed in seeds:
        feed = MarketFeed(syms, seed=seed)
        pend: List[dict] = []
        for _cycle in range(args.cycles):
            for _ in range(int(60.0 / STEP)):
                feed.advance(STEP)
                for p in list(pend):
                    price = feed.tickers[p["sym"]].last_price
                    move = (price - p["entry"]) * p["sgn"]
                    p["age"] += STEP
                    if move <= -p["atr"] * SL_ATR:
                        p["r"] = -1.0
                    elif move >= p["atr"] * TP_ATR:
                        p["r"] = TP_ATR / SL_ATR
                    elif p["age"] >= HORIZON:
                        p["r"] = move / (p["atr"] * SL_ATR)
                    else:
                        continue
                    rows.append(p)
                    pend.remove(p)
            for sym in syms:
                m = compute_metrics(feed.tickers[sym])
                if m is None:
                    continue
                tc = trend_composite(m)
                if m["efficiency"] < MIN_EFF or abs(tc) < MIN_TREND:
                    continue
                direction = "long" if tc >= 0 else "short"
                m["spread_ratio"] = UNIVERSE[sym].spread / max(m["price"], 1e-9)
                levels = build_signal_levels(m, direction, sl_atr=SL_ATR, tp_atr=TP_ATR)
                risk = abs(levels["entry"] - levels["stop_loss"]) / max(levels["entry"], 1e-9)
                pend.append(dict(sym=sym, sgn=1.0 if direction == "long" else -1.0,
                                 atr=max(m["atr"], 1e-9), entry=levels["entry"], age=0.0,
                                 r=0.0, f=pieces(m, direction, TP_ATR / SL_ATR)))

    print(f"training samples: {len(rows)}")
    X = np.array([[r["f"][t] for t in TERMS] for r in rows], dtype=float)
    y = np.array([r["r"] for r in rows], dtype=float)
    print(f"mean R {y.mean():+.3f} · win rate {(y > 0).mean():.2f}\n")

    print(f"{'term':12s} {'corr':>7s}  {'mean R | low':>12s} {'high':>8s}")
    for i, t in enumerate(TERMS):
        col = X[:, i]
        corr = float(np.corrcoef(col, y)[0, 1]) if col.std() > 1e-9 else 0.0
        lo, hi = y[col <= np.quantile(col, 0.33)], y[col >= np.quantile(col, 0.67)]
        print(f"{t:12s} {corr:+7.3f}  {lo.mean():+12.3f} {hi.mean():+8.3f}")

    # ---- robust fit ------------------------------------------------------ #
    # terms with no dispersion in the sample carry no information (a frozen
    # sim clock makes "session" constant, for example) and would otherwise
    # produce wild z-scores. Keep only informative, non-degenerate columns.
    mu, sd = X.mean(axis=0), X.std(axis=0)
    corrs = []
    for i in range(X.shape[1]):
        corrs.append(float(np.corrcoef(X[:, i], y)[0, 1]) if sd[i] > 1e-9 else 0.0)
    keep = [i for i, t in enumerate(TERMS) if sd[i] > 0.05 and abs(corrs[i]) > 0.04]
    dropped = [TERMS[i] for i in range(len(TERMS)) if i not in keep]
    print(f"\nkept {len(keep)}/{len(TERMS)} terms · dropped {dropped}")

    Z = np.clip((X[:, keep] - mu[keep]) / np.maximum(sd[keep], 1e-9), -2.0, 2.0)
    Z = np.hstack([np.ones((len(Z), 1)), Z])
    n_feat = Z.shape[1] - 1
    ridge = 0.05 * len(Z) * np.eye(n_feat + 1)
    ridge[0, 0] = 0.0                                   # do not shrink the intercept
    coef = np.linalg.solve(Z.T @ Z + ridge, Z.T @ y)
    pred = Z @ coef

    # out-of-sample check: fit on the first half of the samples, test on the rest
    half = len(y) // 2
    Za, ya, Zb, yb = Z[:half], y[:half], Z[half:], y[half:]
    coef_a = np.linalg.solve(Za.T @ Za + 0.05 * len(Za) * np.eye(n_feat + 1), Za.T @ ya)
    pred_b = Zb @ coef_a
    print(f"\nridge fit: intercept {coef[0]:+.3f}R · residual std {np.std(y - pred):.3f}R · "
          f"corr(pred, realised) {np.corrcoef(pred, y)[0,1]:+.3f}")
    print(f"out-of-sample (2nd half): corr {np.corrcoef(pred_b, yb)[0,1]:+.3f} · "
          f"mean pred {pred_b.mean():+.3f}R vs realised {yb.mean():+.3f}R")

    weights = {}
    for j, i in enumerate(keep):
        weights[TERMS[i]] = round(float(coef[j + 1]), 4)
    ranked = sorted(weights.items(), key=lambda kv: -abs(kv[1]))
    print("\nstandardised weights (R per 1σ of the term, z clipped at ±2):")
    for k, v in ranked:
        print(f"  {k:12s} {v:+7.3f}")

    for name, p_, y_ in (("in-sample", pred, y), ("out-of-sample", pred_b, yb)):
        deciles = np.argsort(np.argsort(p_)) // max(1, len(p_) // 5)
        print(f"\nquintiles ({name}) of fitted score → realised R")
        for q in range(5):
            mask = deciles == q
            if mask.sum():
                print(f"  Q{q+1} n={mask.sum():4d} mean {y_[mask].mean():+.3f}R "
                      f"win {(y_[mask] > 0).mean():.2f}")

    with open(WEIGHTS_PATH, "w") as fh:
        json.dump(dict(terms=[TERMS[i] for i in keep], weights=weights,
                       intercept=round(float(coef[0]), 4),
                       mu=[round(float(mu[i]), 6) for i in keep],
                       sd=[round(float(sd[i]), 6) for i in keep], z_clip=2.0,
                       samples=len(rows), mean_r=round(float(y.mean()), 4),
                       baseline_win=round(float((y > 0).mean()), 3)), fh, indent=2)
    print(f"\nwrote {WEIGHTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
