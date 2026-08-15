"""
Execution engine.

- Scans the whole watchlist continuously (live tracking of all markets).
- When the AI council's confidence >= threshold, auto-places a trade with
  auto TP / SL (ATR based), breakeven move at +1R and ATR trailing stop.
- Paper broker executes against live prices; every closed trade is fed
  back into Jarvis's brain (online self-training).
- Emits a command queue for external executors:
    * TradingView alert/webhook bridge
    * MT5 Expert Advisor bridge (polls /mt5/commands)
  so the same signals can drive real accounts when you connect them.
"""
import copy
import json
import threading
import time
import uuid

from . import config, feeds, council, jarvis, news, market_hours

STATE_PATH = config.DATA_DIR / "trader_state.json"
JOURNAL_PATH = config.DATA_DIR / "trade_journal.json"


class PaperBroker:
    def __init__(self, balance):
        self.balance = balance
        self.equity = balance
        self.positions = {}      # id -> position dict
        self.history = []        # closed trades

    def open(self, symbol, side, qty, entry, tp, sl, meta):
        pid = uuid.uuid4().hex[:10]
        self.positions[pid] = {
            "id": pid, "symbol": symbol, "side": side, "qty": qty,
            "entry": entry, "tp": tp, "sl": sl, "initial_sl": sl,
            "opened": time.time(), "meta": meta, "be_moved": False,
            "pnl": 0.0,
        }
        return pid

    def mark(self, symbol, price):
        for p in self.positions.values():
            if p["symbol"] != symbol:
                continue
            d = 1 if p["side"] == "BUY" else -1
            p["pnl"] = (price - p["entry"]) * d * p["qty"]
        self.equity = self.balance + sum(p["pnl"] for p in self.positions.values())

    def close(self, pid, price, reason):
        p = self.positions.pop(pid, None)
        if not p:
            return None
        d = 1 if p["side"] == "BUY" else -1
        pnl = (price - p["entry"]) * d * p["qty"]
        self.balance += pnl
        p.update({"exit": price, "pnl": round(pnl, 4), "closed": time.time(),
                  "reason": reason})
        self.history.append(p)
        self.history = self.history[-300:]
        return p


class TradingEngine:
    def __init__(self):
        self.broker = PaperBroker(config.PAPER_START_BALANCE)
        self.auto_trade = config.AUTO_TRADE
        self.min_conf = config.MIN_CONFIDENCE_TO_TRADE
        self.risk_pct = config.RISK_PER_TRADE_PCT
        self.market = {}                 # symbol -> latest quote/mini-analysis
        self.last_analysis = {}          # symbol -> latest full council verdict
        self.signals = {}                # symbol -> scanned trade setup awaiting YOUR click
        self.signals_scanned = 0         # total setups found since start
        self.journal = []                # full closed-trade journal (persisted)
        self.logs = []
        self.commands = []               # queue for MT5 / TradingView executors
        self.lock = threading.RLock()
        self.running = False
        self.scan_idx = 0
        self.jarvis_bootstrapping = False
        self.pending_predictions = []    # live-learning: predictions awaiting resolution
        self.live_lessons = 0
        self.activity = []               # live "what am I doing right now" feed
        self.counters = {"price_ticks": 0, "council_runs": 0, "news_refreshes": 0,
                         "patterns_seen": 0, "llm_calls": 0, "skipped_closed": 0}
        self.interval = "5m"             # selected analysis timeframe
        self.final_setup = None          # the ONE best trade setup right now
        self._load()

    def set_interval(self, interval):
        from . import feeds
        if interval not in feeds.VALID_INTERVALS:
            return False
        if interval != self.interval:
            self.interval = interval
            with self.lock:
                # timeframe changed -> stale signals/analysis no longer valid
                for s in self.signals.values():
                    if s["status"] == "waiting":
                        s["status"] = "expired"
                self.final_setup = None
            self.log(f"Timeframe switched to {interval} - re-analyzing all markets "
                     "on this timeframe only")
            self.act("analyze", f"timeframe set to {interval}: all analysis, signals "
                     "and TP/SL now computed on {0} candles".format(interval))
        return True

    def act(self, kind, msg):
        """Record a live activity event (the bot narrating what it's doing)."""
        with self.lock:
            self.activity.append({"ts": time.time(), "kind": kind, "msg": msg})
            self.activity = self.activity[-250:]

    # -------------------------------------------------------------- #
    def log(self, msg):
        with self.lock:
            self.logs.append({"ts": time.time(), "msg": msg})
            self.logs = self.logs[-400:]
        print(f"[jarvis-trader] {msg}", flush=True)

    def _load(self):
        try:
            d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self.broker.balance = d.get("balance", self.broker.balance)
            self.broker.history = d.get("history", [])
        except Exception:
            pass
        try:
            self.journal = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
        except Exception:
            self.journal = []

    def save(self):
        try:
            STATE_PATH.write_text(json.dumps({
                "balance": self.broker.balance,
                "history": self.broker.history[-200:],
            }, indent=1), encoding="utf-8")
            JOURNAL_PATH.write_text(json.dumps(self.journal[-500:], indent=1),
                                    encoding="utf-8")
        except Exception:
            pass

    # -------------------------------------------------------------- #
    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._bootstrap_jarvis, daemon=True).start()
        threading.Thread(target=self._price_loop, daemon=True).start()
        threading.Thread(target=self._council_loop, daemon=True).start()
        threading.Thread(target=self._news_loop, daemon=True).start()
        threading.Thread(target=self._live_learn_loop, daemon=True).start()
        self.log("Engine started: live tracking " +
                 f"{len(config.WATCHLIST)} assets across crypto/stocks/forex/futures/indices/funds")

    def _bootstrap_jarvis(self):
        if jarvis.BRAIN.bootstrap_done and jarvis.BRAIN.samples_trained > 200:
            self.log(f"Jarvis brain loaded: {jarvis.BRAIN.samples_trained} samples, "
                     f"live feedback={jarvis.BRAIN.live_feedback}, accuracy={jarvis.BRAIN.accuracy}%")
            return
        self.jarvis_bootstrapping = True
        self.log("Jarvis AUTO-TRAIN: bootstrapping on historical candles of all watchlist assets...")
        n = jarvis.BRAIN.bootstrap_train(feeds.get_candles, config.WATCHLIST, log=self.log)
        self.jarvis_bootstrapping = False
        self.log(f"Jarvis AUTO-TRAIN complete: learned from {n} historical samples "
                 f"(total {jarvis.BRAIN.samples_trained}) + built-in knowledge base")

    # -------------------------------------------------------------- #
    def _news_loop(self):
        while self.running:
            try:
                self.act("news", f"scraping {len(news.FEEDS)} news sources "
                         "(Yahoo, CNBC, Bloomberg, NSE, BSE, Investing, Nasdaq, "
                         "MarketWatch, Koyfin, StockAnalysis, ForexFactory...)")
                news.ENGINE.refresh(force=True)
                with self.lock:
                    self.counters["news_refreshes"] += 1
                ok = len(news.ENGINE.sources_ok)
                if ok:
                    self.log(f"News refreshed: {len(news.ENGINE.headlines)} headlines "
                             f"from {ok} sources")
                    self.act("news", f"got {len(news.ENGINE.headlines)} headlines "
                             f"from {ok}/{len(news.FEEDS)+1} sources")
                else:
                    self.act("news", "all news sources unreachable from this network "
                             "- sentiment neutral until they respond")
            except Exception as e:
                self.log(f"news error: {e}")
            time.sleep(240)

    def _price_loop(self):
        """Fast loop: track every asset's live price + manage open positions."""
        cycle = 0
        while self.running:
            cycle += 1
            fetched = 0
            for asset in config.WATCHLIST:
                try:
                    mh = market_hours.market_status(asset)
                    if not mh["open"]:
                        # CLOSED market: do NOT fetch/scan - keep last known quote
                        with self.lock:
                            q = self.market.get(asset["symbol"])
                            if q:
                                q["market_open"] = False
                                q["session"] = mh["session"]
                            else:
                                self.market[asset["symbol"]] = {
                                    "symbol": asset["symbol"], "name": asset["name"],
                                    "type": asset["type"], "price": None,
                                    "change_pct": 0.0, "tick": "down",
                                    "source": "-", "ts": time.time(),
                                    "market_open": False, "venue": mh["venue"],
                                    "session": mh["session"],
                                }
                        continue
                    candles, source = feeds.get_candles(asset, self.interval, 60)
                    fetched += 1
                    price = candles[-1]["c"]
                    prev = candles[-2]["c"] if len(candles) > 1 else price
                    day_open = candles[0]["c"]
                    with self.lock:
                        self.counters["price_ticks"] += 1
                        self.market[asset["symbol"]] = {
                            "symbol": asset["symbol"], "name": asset["name"],
                            "type": asset["type"], "price": price,
                            "change_pct": round((price / day_open - 1) * 100, 3),
                            "tick": "up" if price >= prev else "down",
                            "source": source, "ts": time.time(),
                            "market_open": mh["open"], "venue": mh["venue"],
                            "session": mh["session"],
                        }
                    if mh["open"]:
                        self._manage_positions(asset["symbol"], price, candles)
                except Exception as e:
                    self.log(f"price loop error {asset['symbol']}: {e}")
            self.broker.equity = self.broker.balance + sum(
                p["pnl"] for p in self.broker.positions.values())
            if cycle % 3 == 1:
                open_n = sum(1 for m in self.market.values() if m.get("market_open"))
                self.act("track", f"tick cycle #{cycle}: fetched {fetched} OPEN-market "
                         f"prices ({open_n}/{len(config.WATCHLIST)} markets open, "
                         f"closed markets not scanned), managing "
                         f"{len(self.broker.positions)} positions")
            time.sleep(4)

    def _manage_positions(self, symbol, price, candles):
        """Auto TP/SL hit detection + breakeven + ATR trailing."""
        from . import indicators as ind
        self.broker.mark(symbol, price)
        a = ind.atr(candles) or price * 0.005
        to_close = []
        with self.lock:
            positions = [p for p in self.broker.positions.values() if p["symbol"] == symbol]
        for p in positions:
            d = 1 if p["side"] == "BUY" else -1
            r_dist = abs(p["entry"] - p["initial_sl"])
            move = (price - p["entry"]) * d
            # breakeven at +1R
            if not p["be_moved"] and r_dist > 0 and move >= r_dist:
                p["sl"] = p["entry"]
                p["be_moved"] = True
                self.log(f"{symbol} {p['side']} moved SL to breakeven @ {p['entry']:.5g}")
            # ATR trail after 1.5R
            if r_dist > 0 and move >= 1.5 * r_dist:
                new_sl = price - d * 1.2 * a
                if (d == 1 and new_sl > p["sl"]) or (d == -1 and new_sl < p["sl"]):
                    p["sl"] = new_sl
            # TP / SL hits
            if d == 1:
                if price >= p["tp"]:
                    to_close.append((p["id"], p["tp"], "TP hit"))
                elif price <= p["sl"]:
                    to_close.append((p["id"], p["sl"],
                                     "Breakeven stop hit" if p["be_moved"] else "SL hit"))
            else:
                if price <= p["tp"]:
                    to_close.append((p["id"], p["tp"], "TP hit"))
                elif price >= p["sl"]:
                    to_close.append((p["id"], p["sl"],
                                     "Breakeven stop hit" if p["be_moved"] else "SL hit"))
        for pid, px, reason in to_close:
            self._close_and_learn(pid, px, reason)

    def _close_and_learn(self, pid, price, reason):
        p = self.broker.close(pid, price, reason)
        if not p:
            return
        self.log(f"CLOSED {p['symbol']} {p['side']} @ {price:.5g} | {reason} | "
                 f"PnL {p['pnl']:+.2f} | balance {self.broker.balance:.2f}")
        self.act("trade", f"CLOSED {p['symbol']} {p['side']}: {reason}, "
                 f"PnL {p['pnl']:+.2f} -> journaled")
        self._journal_trade(p, price, reason)
        # feed the outcome back into Jarvis (online self-training)
        feats = p["meta"].get("features")
        if feats:
            went_up = (price > p["entry"])
            pred_up = p["side"] == "BUY"
            jarvis.BRAIN.feedback(feats, went_up, pred_up)
            self.log(f"Jarvis learned from trade outcome "
                     f"(live feedback #{jarvis.BRAIN.live_feedback}, "
                     f"accuracy {jarvis.BRAIN.accuracy}%)")
        self.save()

    def _journal_trade(self, p, exit_price, reason):
        """Write the complete story of a closed trade into the journal."""
        meta = p.get("meta", {})
        d = 1 if p["side"] == "BUY" else -1
        risk = abs(p["entry"] - p["initial_sl"])
        r_multiple = round(((exit_price - p["entry"]) * d) / risk, 2) if risk else None
        held = p["closed"] - p["opened"]
        outcome = "WIN" if p["pnl"] > 0 else ("LOSS" if p["pnl"] < 0 else "FLAT")
        why_closed = {
            "TP hit": "Price reached the take-profit target",
            "SL hit": "Price hit the stop-loss - setup failed",
            "Breakeven stop hit": "Trade went 1R in profit, stop moved to entry, "
                                  "then price came back - closed at ~breakeven",
            "manual close": "You closed it manually from the dashboard",
        }.get(reason, reason)
        entry = {
            "id": p["id"],
            "signal_id": meta.get("signal_id"),
            "symbol": p["symbol"], "side": p["side"],
            "outcome": outcome, "pnl": round(p["pnl"], 2),
            "r_multiple": r_multiple,
            "entry_price": round(p["entry"], 6),
            "exit_price": round(exit_price, 6),
            "tp": round(p["tp"], 6), "sl": round(p["sl"], 6),
            "initial_sl": round(p["initial_sl"], 6),
            "sl_moved_to_breakeven": p.get("be_moved", False),
            "qty": round(p["qty"], 6),
            "close_reason": reason,
            "close_explanation": why_closed,
            "opened_at": p["opened"], "closed_at": p["closed"],
            "held_seconds": int(held),
            "held_human": f"{int(held//3600)}h {int(held%3600//60)}m" if held >= 3600
                          else f"{int(held//60)}m {int(held%60)}s",
            "placed_by": meta.get("placed_by", "auto"),
            "confidence_at_entry": meta.get("confidence"),
            "council_score_at_entry": meta.get("score"),
            "member_votes_at_entry": meta.get("members"),
            "why_entered": meta.get("reasons", []),
        }
        with self.lock:
            self.journal.append(entry)
            self.journal = self.journal[-500:]

    # -------------------------------------------------------------- #
    def _live_learn_loop(self):
        """
        Continuous live-market training: every council analysis registers a
        prediction (features + direction + price). ~30 minutes later Jarvis
        checks what the live market actually did and trains on the outcome -
        so Jarvis keeps learning from real market movements even when no
        trade was placed.
        """
        while self.running:
            now = time.time()
            due = []
            with self.lock:
                still_waiting = []
                for pr in self.pending_predictions:
                    if now - pr["ts"] >= pr["horizon_sec"]:
                        due.append(pr)
                    else:
                        still_waiting.append(pr)
                self.pending_predictions = still_waiting[-200:]
            for pr in due:
                q = self.market.get(pr["symbol"])
                if not q:
                    continue
                went_up = q["price"] > pr["price"]
                pred_up = pr["direction"] == "UP"
                jarvis.BRAIN.feedback(pr["features"], went_up, pred_up)
                self.live_lessons += 1
                move = (q["price"] / pr["price"] - 1) * 100
                hit = "correct" if went_up == pred_up else "wrong"
                self.log(f"Jarvis live-lesson #{self.live_lessons}: {pr['symbol']} "
                         f"predicted {pr['direction']}, market moved {move:+.2f}% "
                         f"({hit}) - accuracy now {jarvis.BRAIN.accuracy}%")
                self.act("jarvis", f"live-lesson #{self.live_lessons}: {pr['symbol']} "
                         f"prediction {pr['direction']} was {hit} "
                         f"(market {move:+.2f}%) - brain retrained, "
                         f"accuracy {jarvis.BRAIN.accuracy}%")
            time.sleep(20)

    def _register_prediction(self, verdict):
        """Queue a council prediction for later outcome-checking."""
        if not verdict.get("features"):
            return
        v = verdict["verdict"]
        if v["confidence"] < 10:      # skip no-conviction calls
            return
        with self.lock:
            # one pending prediction per symbol at a time
            if any(p["symbol"] == verdict["symbol"] for p in self.pending_predictions):
                return
            self.pending_predictions.append({
                "symbol": verdict["symbol"], "direction": v["direction"],
                "price": verdict["price"], "features": verdict["features"],
                "ts": time.time(), "horizon_sec": 1800,
            })

    # -------------------------------------------------------------- #
    def _council_loop(self):
        """Slow loop: run full AI-council analysis asset-by-asset, auto trade."""
        time.sleep(8)
        while self.running:
            asset = config.WATCHLIST[self.scan_idx % len(config.WATCHLIST)]
            self.scan_idx += 1
            try:
                # market timing check: skip analysis when the market is CLOSED
                mh = market_hours.market_status(asset)
                if not mh["open"]:
                    with self.lock:
                        self.counters["skipped_closed"] += 1
                        # retire any waiting signal on a closed market
                        sig = self.signals.get(asset["symbol"])
                        if sig and sig["status"] == "waiting":
                            sig["status"] = "expired"
                    # throttled narration (avoid spamming with ~90 assets)
                    if self.counters["skipped_closed"] % 25 == 1:
                        self.act("skip", f"{asset['symbol']} and other CLOSED markets "
                                 "skipped - scanning OPEN markets only")
                    continue
                use_llms = (self.scan_idx % 2 == 1)   # LLM votes every 2nd pass per asset
                self.act("analyze", f"{asset['symbol']} [{self.interval}]: running AI "
                         f"council (indicators + 8 strategies + patterns + news + Jarvis"
                         + (" + Gemini + Groq" if use_llms else "") + ")")
                verdict = council.analyze(asset, use_llms=use_llms, interval=self.interval)
                with self.lock:
                    self.counters["council_runs"] += 1
                    if use_llms:
                        self.counters["llm_calls"] += 2
                    pats = verdict["members"].get("patterns", {}).get("detail", {})
                    self.counters["patterns_seen"] += len(pats.get("found", []))
                with self.lock:
                    prev = self.last_analysis.get(asset["symbol"])
                    if prev and not use_llms:
                        # keep previous LLM votes visible
                        for k in ("gemini", "groq"):
                            if k in prev.get("members", {}) and k not in verdict["members"]:
                                verdict["members"][k] = prev["members"][k]
                    self.last_analysis[asset["symbol"]] = verdict
                v = verdict["verdict"]
                self.log(f"Council {asset['symbol']} [{self.interval}]: {v['direction']} "
                         f"score={v['score']} conf={v['confidence']}")
                self._register_prediction(verdict)
                self._maybe_signal(asset, verdict)
                self._update_final_setup()
                time.sleep(2)
            except Exception as e:
                self.log(f"council error {asset['symbol']}: {e}")
                time.sleep(1)

    def _maybe_signal(self, asset, verdict):
        """Council found a setup -> publish it as a clickable SIGNAL.
        If auto_trade is ON it is also placed immediately."""
        v = verdict["verdict"]
        sym = asset["symbol"]
        if v["confidence"] < self.min_conf:
            with self.lock:
                # confidence dropped below threshold -> retire stale signal
                if sym in self.signals and self.signals[sym]["status"] == "waiting":
                    if v["confidence"] < self.min_conf * 0.7:
                        self.signals.pop(sym, None)
            return
        plan = verdict["plan"]
        side = "BUY" if v["direction"] == "UP" else "SELL"
        top_reasons = self._signal_reasons(verdict)
        with self.lock:
            existing = self.signals.get(sym)
            fresh = (existing is None or existing["status"] != "waiting"
                     or existing["side"] != side)
            self.signals[sym] = {
                "id": uuid.uuid4().hex[:8] if fresh else existing["id"],
                "symbol": sym, "name": asset["name"], "type": asset["type"],
                "side": side, "entry": plan["entry"], "tp": plan["tp"],
                "sl": plan["sl"], "rr": plan.get("rr"), "tp_source": plan.get("tp_source"),
                "confidence": v["confidence"], "score": v["score"],
                "reasons": top_reasons,
                "members": {k: m["score"] for k, m in verdict["members"].items()},
                "features": verdict.get("features"),
                "ts": time.time() if fresh else existing["ts"],
                "updated": time.time(),
                "expires": time.time() + config.SIGNAL_TTL_SEC,
                "status": "waiting",           # waiting -> placed / expired
            }
            if fresh:
                self.signals_scanned += 1
        if fresh:
            self.log(f"SIGNAL #{self.signals_scanned} scanned: {side} {sym} "
                     f"@ {plan['entry']:.6g} TP={plan['tp']:.6g} SL={plan['sl']:.6g} "
                     f"(conf {v['confidence']}%) - waiting for your click"
                     + (" [auto_trade ON -> placing]" if self.auto_trade else ""))
            self.act("signal", f"TRADE FOUND: {side} {sym} conf {v['confidence']}% "
                     f"entry {plan['entry']:.6g} TP {plan['tp']:.6g} SL {plan['sl']:.6g}"
                     + ("" if self.auto_trade else " - waiting for YOUR click"))
        if self.auto_trade and fresh:
            self.place_trade(sym, source="auto")

    def _update_final_setup(self):
        """
        After collecting scores from EVERYTHING (indicators, strategies,
        patterns, news, Jarvis, Gemini, Groq) across all OPEN markets,
        generate ONE final trade setup - the single best BUY or SELL
        right now on the selected timeframe, with its TP and SL.
        """
        with self.lock:
            waiting = [s for s in self.signals.values() if s["status"] == "waiting"]
            if not waiting:
                # fall back to the strongest fresh analysis even below threshold
                fresh = [a for a in self.last_analysis.values()
                         if time.time() - a["ts"] < 300
                         and a.get("interval") == self.interval]
                if not fresh:
                    self.final_setup = None
                    return
                best_a = max(fresh, key=lambda a: a["verdict"]["confidence"])
                v = best_a["verdict"]
                p = best_a["plan"]
                self.final_setup = {
                    "grade": "WATCH",       # not strong enough to arm
                    "symbol": best_a["symbol"], "name": best_a["name"],
                    "side": "BUY" if v["direction"] == "UP" else "SELL",
                    "confidence": v["confidence"], "score": v["score"],
                    "entry": p["entry"], "tp": p["tp"], "sl": p["sl"],
                    "rr": p["rr"], "tp_source": p.get("tp_source"),
                    "interval": self.interval,
                    "members": {k: m["score"] for k, m in best_a["members"].items()},
                    "reasons": self._signal_reasons(best_a),
                    "ts": time.time(),
                }
                return
            best = max(waiting, key=lambda s: s["confidence"])
            prev = self.final_setup
            self.final_setup = {
                "grade": "READY",           # armed - one click places it
                "symbol": best["symbol"], "name": best.get("name", best["symbol"]),
                "side": best["side"], "confidence": best["confidence"],
                "score": best["score"], "entry": best["entry"], "tp": best["tp"],
                "sl": best["sl"], "rr": best.get("rr"),
                "tp_source": best.get("tp_source"), "interval": self.interval,
                "members": best.get("members"), "reasons": best.get("reasons"),
                "signal_id": best["id"], "ts": time.time(),
            }
            announce = (not prev or prev.get("signal_id") != best["id"])
        if announce:
            self.act("signal", f"FINAL SETUP [{self.interval}]: {best['side']} "
                     f"{best['symbol']} conf {best['confidence']:.0f}% - "
                     f"entry {best['entry']:.6g} TP {best['tp']:.6g} "
                     f"SL {best['sl']:.6g}")

    @staticmethod
    def _signal_reasons(verdict):
        """Human-readable 'why this trade' bullets from council members."""
        reasons = []
        m = verdict.get("members", {})
        v = verdict["verdict"]
        d = v["direction"]
        htf = v.get("htf") or {}
        if htf.get("bias"):
            if htf.get("aligned"):
                reasons.append(f"HTF {htf['tf']} trend CONFIRMS {d} "
                               f"(strength {htf.get('strength', 0):.1f})")
            else:
                reasons.append(f"⚠ counter-trend vs {htf['tf']} - reduced confidence")
        for name in ("jarvis", "gemini", "groq", "patterns", "strategies",
                     "indicators", "news"):
            mem = m.get(name)
            if not mem or mem.get("score") is None:
                continue
            sc = mem["score"]
            agrees = (sc > 0) == (d == "UP")
            det = mem.get("detail") or {}
            if name in ("gemini", "groq") and det.get("reason"):
                reasons.append(f"{name.title()}: {det['reason'][:110]}")
            elif name == "patterns" and det.get("found"):
                top = det["found"][0]
                reasons.append(f"Pattern: {top['name']} ({top['dir']}, {top['score']:+.0f})")
            elif name == "jarvis":
                reasons.append(f"Jarvis ML: {'agrees' if agrees else 'disagrees'} "
                               f"({sc:+.0f}, prob_up {det.get('prob_up', '?')})")
            elif name == "news" and det.get("titles"):
                reasons.append(f"News: {det['titles'][0][:100]}")
            elif name in ("strategies", "indicators"):
                reasons.append(f"{name.title()}: {sc:+.0f}")
        return reasons[:6]

    # -------------------------------------------------------------- #
    def place_trade(self, symbol, source="manual"):
        """Place the scanned signal for `symbol` - called when YOU click it."""
        with self.lock:
            sig = self.signals.get(symbol)
            if not sig or sig["status"] != "waiting":
                return {"ok": False, "error": "no waiting signal for this symbol"}
            if time.time() > sig["expires"]:
                sig["status"] = "expired"
                return {"ok": False, "error": "signal expired - wait for a fresh scan"}
            open_same = [p for p in self.broker.positions.values()
                         if p["symbol"] == symbol]
            if open_same:
                return {"ok": False, "error": "position already open on this symbol"}
            if len(self.broker.positions) >= 6:
                return {"ok": False, "error": "max 6 open positions reached"}

        # execute at CURRENT live price (not the scan price)
        q = self.market.get(symbol)
        entry = q["price"] if q else sig["entry"]
        side, tp, sl = sig["side"], sig["tp"], sig["sl"]
        # shift TP/SL by the slippage between scan price and live price
        drift = entry - sig["entry"]
        tp, sl = tp + drift, sl + drift
        risk_amount = self.broker.equity * self.risk_pct / 100
        stop_dist = abs(entry - sl)
        if stop_dist <= 0:
            return {"ok": False, "error": "invalid stop distance"}
        qty = max(risk_amount / stop_dist, 1e-9)
        max_qty = (self.broker.equity * 0.2 * 10) / entry
        qty = min(qty, max_qty)

        pid = self.broker.open(symbol, side, qty, entry, tp, sl, meta={
            "confidence": sig["confidence"], "score": sig["score"],
            "features": sig.get("features"), "members": sig.get("members"),
            "reasons": sig.get("reasons"), "signal_id": sig["id"],
            "placed_by": source, "signal_ts": sig["ts"],
        })
        with self.lock:
            sig["status"] = "placed"
            sig["position_id"] = pid
            self.commands.append({
                "id": pid, "action": "OPEN", "symbol": symbol, "side": side,
                "qty": round(qty, 6), "entry": entry, "tp": tp, "sl": sl,
                "confidence": sig["confidence"], "ts": time.time(),
                "delivered": False,
            })
            self.commands = self.commands[-100:]
        self.log(f"TRADE PLACED ({source}): {side} {symbol} qty={qty:.6g} "
                 f"@ {entry:.6g} TP={tp:.6g} SL={sl:.6g}")
        self.act("trade", f"PLACED ({source}): {side} {symbol} @ {entry:.6g} "
                 f"TP {tp:.6g} / SL {sl:.6g} qty {qty:.6g}")
        return {"ok": True, "position_id": pid, "entry": entry, "tp": tp, "sl": sl,
                "qty": qty}

    # -------------------------------------------------------------- #
    def manual_close(self, pid):
        with self.lock:
            p = self.broker.positions.get(pid)
        if not p:
            return None
        q = self.market.get(p["symbol"])
        price = q["price"] if q else p["entry"]
        self._close_and_learn(pid, price, "manual close")
        return True

    def pending_commands(self):
        with self.lock:
            out = [c for c in self.commands if not c["delivered"]]
            for c in out:
                c["delivered"] = True
            return out

    def get_signals(self):
        """All scanned setups: waiting (clickable), placed, expired."""
        now = time.time()
        with self.lock:
            for s in self.signals.values():
                if s["status"] == "waiting" and now > s["expires"]:
                    s["status"] = "expired"
            sigs = sorted((copy.deepcopy(s) for s in self.signals.values()),
                          key=lambda s: (-abs(s["confidence"]), s["symbol"]))
            return {"signals": sigs, "total_scanned": self.signals_scanned,
                    "auto_trade": self.auto_trade}

    def get_journal(self, limit=100):
        with self.lock:
            entries = copy.deepcopy(self.journal[-limit:][::-1])
            wins = [j for j in self.journal if j["outcome"] == "WIN"]
            losses = [j for j in self.journal if j["outcome"] == "LOSS"]
            stats = {
                "total": len(self.journal),
                "wins": len(wins), "losses": len(losses),
                "win_rate": round(100 * len(wins) / len(self.journal), 1)
                            if self.journal else None,
                "total_pnl": round(sum(j["pnl"] for j in self.journal), 2),
                "by_reason": {},
            }
            for j in self.journal:
                stats["by_reason"][j["close_reason"]] = \
                    stats["by_reason"].get(j["close_reason"], 0) + 1
        return {"journal": entries, "stats": stats}

    def get_activity(self):
        with self.lock:
            return {"activity": copy.deepcopy(self.activity[-120:][::-1]),
                    "counters": dict(self.counters),
                    "markets": {s: {"open": m.get("market_open"),
                                    "venue": m.get("venue"),
                                    "session": m.get("session")}
                                for s, m in self.market.items()}}

    def status(self):
        with self.lock:
            waiting = [s for s in self.signals.values() if s["status"] == "waiting"]
            return {
                "running": self.running,
                "interval": self.interval,
                "final_setup": copy.deepcopy(self.final_setup),
                "signals_waiting": len(waiting),
                "signals_scanned": self.signals_scanned,
                "counters": dict(self.counters),
                "auto_trade": self.auto_trade,
                "min_confidence": self.min_conf,
                "risk_pct": self.risk_pct,
                "balance": round(self.broker.balance, 2),
                "equity": round(self.broker.equity, 2),
                "open_positions": copy.deepcopy(list(self.broker.positions.values())),
                "closed_trades": copy.deepcopy(self.broker.history[-40:][::-1]),
                "jarvis": {
                    "samples_trained": jarvis.BRAIN.samples_trained,
                    "live_feedback": jarvis.BRAIN.live_feedback,
                    "live_lessons": self.live_lessons,
                    "pending_predictions": len(self.pending_predictions),
                    "accuracy": jarvis.BRAIN.accuracy,
                    "bootstrapping": self.jarvis_bootstrapping,
                },
                "llm_status": council.llm_status(),
                "news_sources_ok": news.ENGINE.sources_ok,
                "news_sources_fail": news.ENGINE.sources_fail,
            }


ENGINE = TradingEngine()
