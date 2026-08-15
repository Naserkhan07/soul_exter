"""
SQLite trade memory - scalable storage for live trades, backtest trades
and strategy performance. Replaces JSON for anything that grows.

Tables:
  trades         every closed trade (live + backtest), full context
  scoreboard     per-strategy/member per-asset aggregates (win rate, pnl, R)
  weight_tuning  history of auto-tuned council weights

Thread-safe: one connection per call (SQLite handles file locking).
DB file: data_store/jarvis_memory.db
"""
import json
import sqlite3
import time
from contextlib import contextmanager

from . import config

DB_PATH = config.DATA_DIR / "jarvis_memory.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id            TEXT PRIMARY KEY,
    source        TEXT,               -- 'live' | 'backtest'
    run_id        TEXT,               -- backtest run id ('' for live)
    symbol        TEXT,
    asset_type    TEXT,
    side          TEXT,
    interval      TEXT,
    outcome       TEXT,               -- WIN | LOSS | FLAT
    pnl           REAL,
    r_multiple    REAL,
    entry_price   REAL,
    exit_price    REAL,
    tp            REAL,
    sl            REAL,
    close_reason  TEXT,
    regime        TEXT,
    confidence    REAL,
    council_score REAL,
    member_votes  TEXT,               -- json {member: score}
    opened_at     REAL,
    closed_at     REAL,
    held_seconds  INTEGER,
    placed_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_sym ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_src ON trades(source, run_id);

CREATE TABLE IF NOT EXISTS weight_tuning (
    ts        REAL,
    run_id    TEXT,
    weights   TEXT,                   -- json {member: weight}
    reason    TEXT
);
"""


@contextmanager
def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with _db() as c:
        c.executescript(_SCHEMA)


def record_trade(t, source="live", run_id=""):
    """t = journal-entry-like dict."""
    init()
    with _db() as c:
        c.execute("""INSERT OR REPLACE INTO trades VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            f"{source}:{run_id}:{t.get('id', '')}" if run_id else t.get("id", ""),
            source, run_id,
            t.get("symbol"), t.get("asset_type", ""), t.get("side"),
            t.get("interval", ""), t.get("outcome"),
            float(t.get("pnl") or 0), t.get("r_multiple"),
            t.get("entry_price"), t.get("exit_price"),
            t.get("tp"), t.get("sl") or t.get("initial_sl"),
            t.get("close_reason"), t.get("regime_at_entry") or t.get("regime", ""),
            t.get("confidence_at_entry") or t.get("confidence"),
            t.get("council_score_at_entry") or t.get("council_score"),
            json.dumps(t.get("member_votes_at_entry") or t.get("member_votes") or {}),
            t.get("opened_at"), t.get("closed_at"),
            t.get("held_seconds"), t.get("placed_by", "")))


def scoreboard(source=None, run_id=None, min_trades=3):
    """
    Per-member and per-strategy performance: for every council member,
    was its vote pointing the right way when trades won/lost?
    Also per-symbol and per-regime aggregates.
    """
    init()
    where, args = [], []
    if source:
        where.append("source=?"); args.append(source)
    if run_id:
        where.append("run_id=?"); args.append(run_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with _db() as c:
        rows = [dict(r) for r in c.execute(
            f"SELECT * FROM trades {w}", args).fetchall()]

    if not rows:
        return {"members": {}, "symbols": {}, "regimes": {}, "total": 0}

    # member accuracy: vote direction agreed with trade direction AND trade won
    members = {}
    for r in rows:
        try:
            votes = json.loads(r["member_votes"] or "{}")
        except Exception:
            votes = {}
        won = r["outcome"] == "WIN"
        side_up = r["side"] == "BUY"
        for m, v in votes.items():
            if v is None:
                continue
            st = members.setdefault(m, {"right": 0, "wrong": 0, "pnl_when_agreed": 0.0})
            agreed = (v > 0) == side_up
            if agreed:
                st["pnl_when_agreed"] += r["pnl"] or 0
                if won:
                    st["right"] += 1
                else:
                    st["wrong"] += 1

    for m, st in members.items():
        n = st["right"] + st["wrong"]
        st["n"] = n
        st["hit_rate"] = round(100 * st["right"] / n, 1) if n else None
        st["pnl_when_agreed"] = round(st["pnl_when_agreed"], 2)

    def agg(key):
        out = {}
        for r in rows:
            k = r[key] or "?"
            s = out.setdefault(k, {"n": 0, "wins": 0, "pnl": 0.0, "r_sum": 0.0})
            s["n"] += 1
            s["wins"] += 1 if r["outcome"] == "WIN" else 0
            s["pnl"] += r["pnl"] or 0
            s["r_sum"] += r["r_multiple"] or 0
        for k, s in out.items():
            s["win_rate"] = round(100 * s["wins"] / s["n"], 1)
            s["pnl"] = round(s["pnl"], 2)
            s["avg_r"] = round(s["r_sum"] / s["n"], 2)
            del s["r_sum"]
        return {k: v for k, v in out.items() if v["n"] >= min_trades}

    return {"members": members, "symbols": agg("symbol"),
            "regimes": agg("regime"), "reasons": agg("close_reason"),
            "total": len(rows)}


def tuned_weights(base_weights, source=None, run_id=None,
                  min_n=10, max_shift=0.4):
    """
    SELF-HEALING: derive tuned council weights from the scoreboard.
    Members with hit_rate above 50% get boosted, below get trimmed,
    bounded to +/- max_shift of the base weight. Requires min_n samples.
    """
    sb = scoreboard(source=source, run_id=run_id, min_trades=1)
    tuned = dict(base_weights)
    notes = []
    for m, base in base_weights.items():
        st = sb["members"].get(m)
        if not st or st["n"] < min_n or st["hit_rate"] is None:
            continue
        edge = (st["hit_rate"] - 50.0) / 50.0        # -1 .. +1
        factor = 1.0 + max(-max_shift, min(max_shift, edge * max_shift * 2))
        tuned[m] = round(base * factor, 3)
        notes.append(f"{m}: hit {st['hit_rate']}% (n={st['n']}) "
                     f"-> weight {base} -> {tuned[m]}")
    return tuned, notes


def save_tuning(weights, run_id="", reason=""):
    init()
    with _db() as c:
        c.execute("INSERT INTO weight_tuning VALUES (?,?,?,?)",
                  (time.time(), run_id, json.dumps(weights), reason))


def export_journal_for_training(limit=2000):
    """Export closed trades as chat-format training samples (Option C)."""
    init()
    with _db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?",
            (limit,)).fetchall()]
    samples = []
    for r in rows:
        try:
            votes = json.loads(r["member_votes"] or "{}")
        except Exception:
            votes = {}
        vote_txt = ", ".join(f"{k}={v:+.0f}" for k, v in votes.items()
                             if v is not None)
        user = (f"Market: {r['symbol']} ({r['asset_type']}) on {r['interval'] or '5m'} "
                f"candles. Regime: {r['regime'] or 'unknown'}. "
                f"Council votes: {vote_txt}. Confidence {r['confidence']}%. "
                f"Should I {r['side']} here with TP {r['tp']} and SL {r['sl']}?")
        outcome_txt = ("This setup WON" if r["outcome"] == "WIN" else
                       "This setup LOST" if r["outcome"] == "LOSS" else
                       "This setup was flat")
        assistant = (f"{outcome_txt} ({r['r_multiple']}R, closed by "
                     f"{r['close_reason']}). "
                     + ("The confluence was valid - similar setups are worth taking."
                        if r["outcome"] == "WIN" else
                        "Similar setups should be avoided or need stronger confirmation."))
        samples.append({"messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant}]})
    return samples
