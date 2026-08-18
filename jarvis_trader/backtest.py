"""
BACKTESTER - replays history through the full analysis stack
(indicators + 8 strategies + patterns + regime + Jarvis; LLMs excluded
for speed/costlessness) and simulates the COMPLETE trade lifecycle:

  signal (conf >= threshold, HTF-aligned) -> entry -> noise-floor SL /
  regime TP -> profit ladder (50% @ partial_r, 25% @ 2R) -> breakeven ->
  trail -> close -> journal into SQLite

Then the scoreboard reads the results and auto-tunes council weights
("self-healing backtest").

Run via /api/backtest or:
    python -m jarvis_trader.backtest BTCUSDT ETHUSDT --interval 5m
"""
import time
import uuid

from . import (config, feeds, indicators, strategies, patterns,
               regime as regime_mod, jarvis, memory, council)

MIN_SL_PCT = {"crypto": 0.0040, "forex": 0.0015, "stock": 0.0045,
              "index": 0.0030, "futures": 0.0035, "fund": 0.0040}


def _analyze_bar(asset, window, interval):
    """Council-lite verdict on a historical window (no LLMs, no news)."""
    snap = indicators.snapshot(window)
    strat = strategies.run_all(window, snap)
    swings = strategies.find_swings(window)
    pat = patterns.scan(window, swings)
    reg = regime_mod.detect(window, snap)

    bias = reg["params"]["bias"]
    for s in strat["strategies"]:
        mult = bias.get(s["name"])
        if mult:
            s["score"] = int(max(-100, min(100, s["score"] * mult)))
    strat["strategy_score"] = round(
        sum(s["score"] for s in strat["strategies"]) /
        max(len(strat["strategies"]), 1), 1)

    f = jarvis.build_features(snap, strat, 0.0, pat)
    jarvis.add_price_features(f, window)
    j_score, _ = jarvis.BRAIN.predict(f)

    members = {"indicators": snap["indicator_score"],
               "strategies": strat["strategy_score"],
               "patterns": pat["pattern_score"],
               "jarvis": j_score}
    num = den = 0.0
    votes = []
    for name, sc in members.items():
        w = council.WEIGHTS.get(name, 1.0)
        num += w * sc
        den += w
        votes.append(sc)
    final = num / den if den else 0.0
    direction = "UP" if final >= 0 else "DOWN"
    base = abs(final)
    same = [v for v in votes if (v >= 0) == (final >= 0) and abs(v) >= 5]
    agree = len(same) / len(votes) if votes else 0
    strongest = max((abs(v) for v in same), default=0)
    confidence = min(96.0, base * 0.55 + agree * 32 + strongest * 0.22)

    return {"direction": direction, "confidence": confidence,
            "score": final, "members": members, "snap": snap, "reg": reg}


def run(symbols=None, interval="5m", limit=500, min_conf=None,
        risk_pct=1.0, capital=10000.0, run_id=None, log=print):
    """
    Backtest the full pipeline over historical candles.
    Returns summary dict; writes every simulated trade into SQLite.
    """
    min_conf = min_conf if min_conf is not None else config.MIN_CONFIDENCE_TO_TRADE
    run_id = run_id or uuid.uuid4().hex[:8]
    assets = [a for a in config.WATCHLIST
              if not symbols or a["symbol"] in symbols]

    all_trades = []
    for asset in assets:
        candles, src = feeds.get_candles(asset, interval, limit)
        if len(candles) < 140:
            continue
        log(f"[backtest {run_id}] {asset['symbol']}: {len(candles)} bars ({src})")
        open_pos = None
        step = 3          # analyze every 3rd bar (council cadence)
        for i in range(100, len(candles) - 1, 1):
            bar = candles[i]
            price = bar["c"]

            # ---- manage open position on EVERY bar ----
            if open_pos:
                p = open_pos
                d = 1 if p["side"] == "BUY" else -1
                r_dist = abs(p["entry"] - p["initial_sl"])
                hi, lo = bar["h"], bar["l"]
                move_hi = (hi - p["entry"]) * d
                move_lo = (lo - p["entry"]) * d
                # ladder 1
                if not p["partial_done"] and move_hi >= p["partial_r"] * r_dist:
                    fill = p["entry"] + d * p["partial_r"] * r_dist
                    p["banked"] += (fill - p["entry"]) * d * p["qty"] * 0.5
                    p["qty"] *= 0.5
                    p["partial_done"] = True
                    p["sl"] = p["entry"]
                # ladder 2
                if p["partial_done"] and not p["partial2_done"] and \
                        move_hi >= 2.0 * r_dist:
                    fill = p["entry"] + d * 2.0 * r_dist
                    p["banked"] += (fill - p["entry"]) * d * p["qty"] * 0.5
                    p["qty"] *= 0.5
                    p["partial2_done"] = True
                    p["sl"] = p["entry"] + d * 1.0 * r_dist
                # exits (worst-case ordering: SL before TP within a bar)
                closed = None
                sl_hit = (lo <= p["sl"]) if d == 1 else (hi >= p["sl"])
                tp_hit = (hi >= p["tp"]) if d == 1 else (lo <= p["tp"])
                if sl_hit:
                    reason = ("Partial TP + stop at entry" if p["partial_done"]
                              else "SL hit")
                    closed = (p["sl"], reason)
                elif tp_hit:
                    closed = (p["tp"], "TP hit")
                if closed:
                    exit_px, reason = closed
                    pnl = (exit_px - p["entry"]) * d * p["qty"] + p["banked"]
                    rr = ((exit_px - p["entry"]) * d) / r_dist if r_dist else 0
                    t = {"id": uuid.uuid4().hex[:10], "symbol": asset["symbol"],
                         "asset_type": asset["type"], "side": p["side"],
                         "interval": interval,
                         "outcome": "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT"),
                         "pnl": round(pnl, 4), "r_multiple": round(rr, 2),
                         "entry_price": p["entry"], "exit_price": exit_px,
                         "tp": p["tp"], "sl": p["initial_sl"],
                         "close_reason": reason, "regime": p["regime"],
                         "confidence": p["confidence"],
                         "council_score": p["score"],
                         "member_votes": p["members"],
                         "opened_at": p["t_open"], "closed_at": bar["t"],
                         "held_seconds": int(bar["t"] - p["t_open"]),
                         "placed_by": "backtest"}
                    memory.record_trade(t, source="backtest", run_id=run_id)
                    all_trades.append(t)
                    open_pos = None
                continue   # while a position is open we don't stack entries

            # ---- look for new entries on council cadence ----
            if i % step:
                continue
            window = candles[:i + 1]
            v = _analyze_bar(asset, window, interval)
            if v["confidence"] < min_conf + 10:      # AUTO bar (+10)
                continue
            side = "BUY" if v["direction"] == "UP" else "SELL"
            snap = v["snap"]
            a = snap.get("atr14") or price * 0.005
            min_dist = price * MIN_SL_PCT.get(asset["type"], 0.0035)
            sw = strategies.find_swings(window)
            buf = 0.25 * a
            d = 1 if side == "BUY" else -1
            if d == 1:
                lows = [s["price"] for s in sw if s["type"] == "L"][-2:]
                struct = min(lows) - buf if lows else price - 2.2 * a
                sl = min(price - 1.6 * a, max(struct, price - 3.0 * a))
                sl = min(sl, price - min_dist)
            else:
                highs = [s["price"] for s in sw if s["type"] == "H"][-2:]
                struct = max(highs) + buf if highs else price + 2.2 * a
                sl = max(price + 1.6 * a, min(struct, price + 3.0 * a))
                sl = max(sl, price + min_dist)
            risk = abs(price - sl)
            if risk <= 0:
                continue
            tp = price + d * v["reg"]["params"]["tp_r"] * risk
            conf_mult = regime_mod.confidence_size_mult(v["confidence"], min_conf)
            risk_amt = capital * risk_pct / 100 * conf_mult \
                * v["reg"]["params"]["size_mult"]
            open_pos = {"side": side, "entry": price, "sl": sl,
                        "initial_sl": sl, "tp": tp,
                        "qty": risk_amt / risk, "banked": 0.0,
                        "partial_done": False, "partial2_done": False,
                        "partial_r": v["reg"]["params"]["partial_at_r"],
                        "regime": v["reg"]["regime"],
                        "confidence": round(v["confidence"], 1),
                        "score": round(v["score"], 1),
                        "members": v["members"], "t_open": bar["t"]}

    # ---- summary + self-healing weight tuning ----
    wins = [t for t in all_trades if t["outcome"] == "WIN"]
    losses = [t for t in all_trades if t["outcome"] == "LOSS"]
    total_pnl = sum(t["pnl"] for t in all_trades)
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    summary = {
        "run_id": run_id, "interval": interval,
        "assets": [a["symbol"] for a in assets],
        "trades": len(all_trades), "wins": len(wins), "losses": len(losses),
        "win_rate": round(100 * len(wins) / len(all_trades), 1) if all_trades else None,
        "total_pnl": round(total_pnl, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "expectancy": round(total_pnl / len(all_trades), 2) if all_trades else None,
    }
    tuned, notes = memory.tuned_weights(council.WEIGHTS, source="backtest",
                                        run_id=run_id)
    summary["tuned_weights"] = tuned
    summary["tuning_notes"] = notes
    memory.save_tuning(tuned, run_id=run_id,
                       reason=f"backtest {run_id}: {summary['trades']} trades, "
                              f"wr {summary['win_rate']}%")
    log(f"[backtest {run_id}] DONE: {summary['trades']} trades, "
        f"win rate {summary['win_rate']}%, PnL {summary['total_pnl']}, "
        f"PF {summary['profit_factor']}")
    return summary


def apply_tuned_weights(tuned):
    """Apply self-healed weights to the live council."""
    for k, v in tuned.items():
        if k in council.WEIGHTS:
            council.WEIGHTS[k] = float(v)
    return dict(council.WEIGHTS)


if __name__ == "__main__":
    import sys
    syms = [s for s in sys.argv[1:] if not s.startswith("-")] or None
    print(run(symbols=syms))
