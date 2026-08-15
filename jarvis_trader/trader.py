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
import json
import threading
import time
import uuid

from . import config, feeds, council, jarvis, news

STATE_PATH = config.DATA_DIR / "trader_state.json"


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
        self.logs = []
        self.commands = []               # queue for MT5 / TradingView executors
        self.lock = threading.Lock()
        self.running = False
        self.scan_idx = 0
        self.jarvis_bootstrapping = False
        self.pending_predictions = []    # live-learning: predictions awaiting resolution
        self.live_lessons = 0
        self._load()

    # -------------------------------------------------------------- #
    def log(self, msg):
        with self.lock:
            self.logs.append({"ts": time.time(), "msg": msg})
            self.logs = self.logs[-400:]
        print(f"[jarvis-trader] {msg}", flush=True)

    def _load(self):
        try:
            d = json.loads(STATE_PATH.read_text())
            self.broker.balance = d.get("balance", self.broker.balance)
            self.broker.history = d.get("history", [])
        except Exception:
            pass

    def save(self):
        try:
            STATE_PATH.write_text(json.dumps({
                "balance": self.broker.balance,
                "history": self.broker.history[-200:],
            }, indent=1))
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
                news.ENGINE.refresh(force=True)
                ok = len(news.ENGINE.sources_ok)
                if ok:
                    self.log(f"News refreshed: {len(news.ENGINE.headlines)} headlines "
                             f"from {ok} sources")
            except Exception as e:
                self.log(f"news error: {e}")
            time.sleep(240)

    def _price_loop(self):
        """Fast loop: track every asset's live price + manage open positions."""
        while self.running:
            for asset in config.WATCHLIST:
                try:
                    candles, source = feeds.get_candles(asset, "5m", 60)
                    price = candles[-1]["c"]
                    prev = candles[-2]["c"] if len(candles) > 1 else price
                    day_open = candles[0]["c"]
                    with self.lock:
                        self.market[asset["symbol"]] = {
                            "symbol": asset["symbol"], "name": asset["name"],
                            "type": asset["type"], "price": price,
                            "change_pct": round((price / day_open - 1) * 100, 3),
                            "tick": "up" if price >= prev else "down",
                            "source": source, "ts": time.time(),
                        }
                    self._manage_positions(asset["symbol"], price, candles)
                except Exception as e:
                    self.log(f"price loop error {asset['symbol']}: {e}")
            self.broker.equity = self.broker.balance + sum(
                p["pnl"] for p in self.broker.positions.values())
            time.sleep(3)

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
                    to_close.append((p["id"], p["sl"], "SL hit"))
            else:
                if price <= p["tp"]:
                    to_close.append((p["id"], p["tp"], "TP hit"))
                elif price >= p["sl"]:
                    to_close.append((p["id"], p["sl"], "SL hit"))
        for pid, px, reason in to_close:
            self._close_and_learn(pid, px, reason)

    def _close_and_learn(self, pid, price, reason):
        p = self.broker.close(pid, price, reason)
        if not p:
            return
        won = p["pnl"] > 0
        self.log(f"CLOSED {p['symbol']} {p['side']} @ {price:.5g} | {reason} | "
                 f"PnL {p['pnl']:+.2f} | balance {self.broker.balance:.2f}")
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
                use_llms = (self.scan_idx % 3 == 1)   # LLM votes every 3rd pass per asset
                verdict = council.analyze(asset, use_llms=use_llms)
                with self.lock:
                    prev = self.last_analysis.get(asset["symbol"])
                    if prev and not use_llms:
                        # keep previous LLM votes visible
                        for k in ("gemini", "groq"):
                            if k in prev.get("members", {}) and k not in verdict["members"]:
                                verdict["members"][k] = prev["members"][k]
                    self.last_analysis[asset["symbol"]] = verdict
                v = verdict["verdict"]
                self.log(f"Council {asset['symbol']}: {v['direction']} "
                         f"score={v['score']} conf={v['confidence']}")
                self._register_prediction(verdict)
                if self.auto_trade:
                    self._maybe_trade(asset, verdict)
            except Exception as e:
                self.log(f"council error {asset['symbol']}: {e}")
            time.sleep(max(4, config.SCAN_INTERVAL_SEC // len(config.WATCHLIST)))

    def _maybe_trade(self, asset, verdict):
        v = verdict["verdict"]
        sym = asset["symbol"]
        if v["confidence"] < self.min_conf:
            return
        with self.lock:
            open_same = [p for p in self.broker.positions.values() if p["symbol"] == sym]
            if open_same:
                return
            if len(self.broker.positions) >= 6:
                return
        plan = verdict["plan"]
        side = "BUY" if v["direction"] == "UP" else "SELL"
        entry, tp, sl = plan["entry"], plan["tp"], plan["sl"]
        risk_amount = self.broker.equity * self.risk_pct / 100
        stop_dist = abs(entry - sl)
        if stop_dist <= 0:
            return
        qty = max(risk_amount / stop_dist, 1e-9)
        # cap notional at 20% of equity for sanity
        max_qty = (self.broker.equity * 0.2 * 10) / entry   # allow some leverage
        qty = min(qty, max_qty)
        pid = self.broker.open(sym, side, qty, entry, tp, sl, meta={
            "confidence": v["confidence"], "score": v["score"],
            "features": verdict.get("features"),
            "members": {k: m["score"] for k, m in verdict["members"].items()},
        })
        self.log(f"AUTO-TRADE {side} {sym} qty={qty:.6g} @ {entry:.5g} "
                 f"TP={tp:.5g} SL={sl:.5g} (conf {v['confidence']}%)")
        # queue command for external executors (MT5 EA / TradingView bridge)
        with self.lock:
            self.commands.append({
                "id": pid, "action": "OPEN", "symbol": sym, "side": side,
                "qty": round(qty, 6), "entry": entry, "tp": tp, "sl": sl,
                "confidence": v["confidence"], "ts": time.time(), "delivered": False,
            })
            self.commands = self.commands[-100:]

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

    def status(self):
        with self.lock:
            return {
                "running": self.running,
                "auto_trade": self.auto_trade,
                "min_confidence": self.min_conf,
                "risk_pct": self.risk_pct,
                "balance": round(self.broker.balance, 2),
                "equity": round(self.broker.equity, 2),
                "open_positions": list(self.broker.positions.values()),
                "closed_trades": self.broker.history[-40:][::-1],
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
