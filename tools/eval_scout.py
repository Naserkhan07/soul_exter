"""Does the fly scout actually pick winners?

A filter that says "yes" to everything is worth nothing, and a filter that says
"no" is only worth something if what it rejects is worse than what it keeps. This
script answers that empirically instead of by assertion.

It is fully offline and deterministic:

  1. generate regime-switching GBM price paths with the same process the live
     simulator uses (soul/market.py), for a handful of seeds;
  2. walk each path bar by bar and run the REAL scanner strategies over the
     window ending at that bar, exactly as the server does;
  3. label every candidate with its realised outcome by walking the price
     forward until the trade hits its stop, its target, or its horizon;
  4. ask the fly for its verdict on the same feature block the server feeds it;
  5. report the hit rate of everything the scanner found, and of what the fly
     confirmed, keeping, and rejecting — plus a threshold sweep so the gate can
     be set from evidence rather than taste.

    python tools/eval_scout.py                 # default: 8 seeds, 1500 bars
    python tools/eval_scout.py --seeds 4 --bars 900
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from soul.config import load_config
from soul.flybrain import FlyBrain, FlyConfig
from soul.market import BETA, DEFAULT_BETA, SEED_PRICES
from soul.scanner import STRATEGIES, Scanner
from soul.scanner import Scanner as _Scanner  # noqa: F401  (kept for readability)

BAR = "─" * 78
HORIZON = 60          # bars a trade is allowed to live (sim bars, 8 s each)


def path(seed: int, bars: int, symbols: List[str]) -> Dict[str, np.ndarray]:
    """Regime-switching correlated GBM, the same generator as the live sim."""
    rng = np.random.default_rng(seed)
    out: Dict[str, np.ndarray] = {}
    btc_drift = 0.0
    for symbol in symbols:
        beta = BETA.get(symbol, DEFAULT_BETA) * (0.9 + 0.2 * rng.random())
        price = SEED_PRICES.get(symbol, 1.0) * (0.9 + 0.2 * rng.random())
        rows = np.zeros((bars, 6), dtype=float)
        drift, vol_mult = 0.0, 1.0
        for i in range(bars):
            if i % 35 == 0:
                drift = rng.normal(0, 0.0011)
                vol_mult = 0.6 + 1.1 * rng.random()
            sigma = 0.0042 * vol_mult
            ret = drift + beta * rng.normal(0, 0.0028) + rng.normal(0, sigma)
            openp = price
            price = max(1e-8, price * (1.0 + ret))
            wick = abs(price) * sigma * (0.4 + 1.6 * rng.random())
            hi = max(openp, price) + wick * rng.random()
            lo = min(openp, price) - wick * rng.random()
            vol = SEED_PRICES.get(symbol, 1.0) * (500 + 1500 * rng.random()) * (1 + 5 * abs(ret) / sigma)
            rows[i] = (i * 8.0, openp, hi, lo, price, vol)
        out[symbol] = rows
    return out


def outcome(cand, rows: np.ndarray, t: int, horizon: int = HORIZON) -> Tuple[float, str]:
    """Walk the trade forward: stop, target, or horizon close. Returns (pnl%, how)."""
    entry = float(rows[t, 4])
    stop, target = float(cand.stop), float(cand.target)
    long = cand.side == "LONG"
    for j in range(t + 1, min(len(rows), t + 1 + horizon)):
        hi, lo = float(rows[j, 2]), float(rows[j, 3])
        if long:
            if lo <= stop:
                return ((stop / entry) - 1.0) * 100.0, "stop"
            if hi >= target:
                return ((target / entry) - 1.0) * 100.0, "target"
        else:
            if hi >= stop:
                return (1.0 - (stop / entry)) * 100.0, "stop"
            if lo <= target:
                return (1.0 - (target / entry)) * 100.0, "target"
    last = float(rows[min(len(rows) - 1, t + horizon), 4])
    pnl = ((last / entry) - 1.0) * 100.0
    return (pnl if long else -pnl), "horizon"


def deck(seeds: int, bars: int, cfg) -> List[Dict]:
    """Every candidate the real scanner strategies would have raised."""
    symbols = list(cfg.universe[:8])
    scanner = Scanner(cfg, market=None)          # only static helpers are used
    out: List[Dict] = []
    for seed in range(1, seeds + 1):
        data = path(seed, bars, symbols)
        btc = data.get("BTC/USDT")
        for symbol in symbols:
            rows = data[symbol]
            o, h, l, c, v = rows[:, 1], rows[:, 2], rows[:, 3], rows[:, 4], rows[:, 5]
            for t in range(120, bars - HORIZON - 1):
                if btc is not None:
                    ret12 = (btc[t, 4] / max(1e-9, btc[t - 12, 4]) - 1.0) * 100.0
                else:
                    ret12 = 0.0
                regime = "risk-on" if ret12 > 0.35 else ("risk-off" if ret12 < -0.35 else "range")
                local = {"btc_ret": round(float(ret12), 3), "regime": regime, "tf": cfg.candle_timeframe,
                         "beta": BETA.get(symbol, DEFAULT_BETA),
                         "change_pct": float((c[t] / max(1e-9, c[t - 24]) - 1.0) * 100.0)}
                lo = max(0, t - cfg.candle_limit + 1)
                s = slice(lo, t + 1)
                for strat in STRATEGIES:
                    cand = strat.evaluate(
                        symbol, o[s], h[s], l[s], c[s], v[s], local)
                    if cand is None:
                        continue
                    common = Scanner.common_features(o[s], h[s], l[s], c[s], v[s], local, cand.side)
                    cand.features = {**common, **cand.features, "strategy": strat.name}
                    score = Scanner.score_candidate(cand, common)
                    if score < cfg.min_score:
                        continue
                    pnl, how = outcome(cand, rows, t)
                    out.append({"symbol": symbol, "side": cand.side, "strategy": strat.name,
                                "score": round(score, 3), "pnl": pnl, "how": how,
                                "features": cand.features, "seed": seed, "t": t})
    return out


def rate(rows: List[Dict]) -> str:
    if not rows:
        return "  n=0"
    wins = sum(1 for r in rows if r["pnl"] > 0)
    mean = float(np.mean([r["pnl"] for r in rows]))
    return f"n={len(rows):<5} hit {wins / len(rows) * 100:5.1f}%  mean {mean:+.3f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--bars", type=int, default=1500)
    args = ap.parse_args()

    cfg = load_config()
    print(f"generating {args.seeds} paths x {args.bars} bars ...")
    rows = deck(args.seeds, args.bars, cfg)
    print(f"candidates the scanner would raise: {len(rows)}")
    if not rows:
        print("no candidates — nothing to evaluate")
        return 1

    print(BAR)
    print(f"every candidate          {rate(rows)}")
    print(f"  by outcome             {dict(collections.Counter(r['how'] for r in rows))}")
    print(f"  by side                " + "  ".join(
        f"{s}: {rate([r for r in rows if r['side'] == s])}" for s in ("LONG", "SHORT")))

    # the scanner's own ranking, for comparison: its score is what usually
    # decides which candidates reach the council
    sc = sorted(rows, key=lambda r: r["score"], reverse=True)
    for name, part in (("scanner score: top third", sc[: len(sc) // 3]),
                       ("scanner score: rest", sc[len(sc) // 3:])):
        print(f"  {name:<22} {rate(part)}")

    brain = FlyBrain(FlyConfig(seed=cfg.scout_seed))
    print(BAR)
    for r in rows:
        feats = dict(r["features"])
        feats["side_long"] = 1.0 if r["side"] == "LONG" else 0.0
        sig = brain.judge(r["symbol"], feats, side=r["side"], threshold=cfg.scout_min_z)
        r["z"] = sig.rates.get("z_confirm", 0.0)
        r["z_x"] = sig.rates.get("z_contradict", 0.0)
        r["verdict"] = sig.direction
    import time as _t
    t0 = _t.time()
    print(f"fly judged {len(rows)} candidates in {_t.time() - t0:.1f}s")

    print(f"fly CONFIRM              {rate([r for r in rows if r['verdict'] == 'CONFIRM'])}")
    print(f"fly WAIT                 {rate([r for r in rows if r['verdict'] == 'WAIT'])}")
    print(f"fly CONTRADICT           {rate([r for r in rows if r['verdict'] == 'CONTRADICT'])}")
    print(BAR)
    print("hit rate by the fly's confirm read (z_confirm), the ranking it passes upstream:")
    order = sorted(rows, key=lambda r: r["z"], reverse=True)
    q = max(1, len(order) // 5)
    for i in range(5):
        part = order[i * q:(i + 1) * q] or order[-1:]
        lo_z = min(r["z"] for r in part)
        print(f"  quintile {i + 1} (z_confirm >= {lo_z:5.2f})  {rate(part)}")

    print(BAR)
    print("threshold sweep — what the gate would admit:")
    print(f"  {'min_z':>6} {'kept':>6} {'kept hit':>9} {'kept mean':>10} {'cut hit':>9} {'cut mean':>10}")
    for thr in (0.0, 0.5, 0.8, 1.0, 1.3, 1.6, 2.0, 2.5, 3.0):
        kept = [r for r in rows if r["z"] >= thr and r["z"] >= r["z_x"]]
        cut = [r for r in rows if not (r["z"] >= thr and r["z"] >= r["z_x"])]
        kf = (sum(1 for r in kept if r["pnl"] > 0) / len(kept) * 100) if kept else float("nan")
        km = float(np.mean([r["pnl"] for r in kept])) if kept else float("nan")
        cf = (sum(1 for r in cut if r["pnl"] > 0) / len(cut) * 100) if cut else float("nan")
        cm = float(np.mean([r["pnl"] for r in cut])) if cut else float("nan")
        print(f"  {thr:6.1f} {len(kept):6d} {kf:8.1f}% {km:+9.3f}% {cf:8.1f}% {cm:+9.3f}%")

    print(BAR)
    print("per-strategy (kept vs cut at min_z = %.1f):" % cfg.scout_min_z)
    for strat in sorted({r["strategy"] for r in rows}):
        part = [r for r in rows if r["strategy"] == strat]
        kept = [r for r in part if r["z"] >= cfg.scout_min_z]
        print(f"  {strat:<20} all {rate(part)}")
        print(f"  {'':<20} kept {rate(kept)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
