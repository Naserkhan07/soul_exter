"""The engine: wires market -> scanner -> council -> doors -> paper desk.

Nothing here knows about the UI. It publishes events and answers state
queries; the 3D floor is just one possible subscriber.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from .brains import brain_registry, build_brains, vram_estimate
from .broker import BrokerError, BrokerHub
from .bus import EventBus
from .council import Council
from . import universe as book
from .config import Config
from .knowledge import SEED_LESSONS
from .training import TrainingBook
from .debate import DebateRoom, packet
from .desk import PaperDesk
from .market import MarketFeed
from .models import TradeCandidate
from .scanner import Scanner
from .scout import FlyScout

log = logging.getLogger("soul.engine")


class Engine:
    def __init__(self, cfg: Config, bus: Optional[EventBus] = None) -> None:
        self.cfg = cfg
        self.bus = bus or EventBus()
        self.market = MarketFeed(cfg)
        self.scanner = Scanner(cfg, self.market)
        # The scout is cheap (~5 ms/symbol) and fully offline, so it is built
        # eagerly; if it ever fails the engine runs without it rather than dying.
        self.scout: Optional[FlyScout] = None
        if cfg.scout_enabled:
            try:
                self.scout = FlyScout(cfg)
            except Exception as exc:                       # pragma: no cover
                log.warning("scout unavailable: %s", exc)
        self.desk = PaperDesk(cfg, self.bus)
        # where a placed trade actually goes: the operator's MetaTrader 5
        # terminal for forex, the paper venue everywhere else. Nothing connects
        # until there are credentials, so a fresh checkout boots offline.
        self.broker = BrokerHub(cfg, self.bus, self._price_of)
        self.council: Optional[Council] = None
        self.training: Optional[TrainingBook] = None
        self.debate: Optional[DebateRoom] = None
        self.brains: Dict[str, Any] = {}
        self.registry: Dict[str, dict] = {}
        self.started_at = time.time()
        self.paused = False
        self.scan_seconds = cfg.scan_seconds
        self.min_score = cfg.min_score
        self.in_flight = 0
        self._tasks: List[asyncio.Task] = []
        self._stopping = asyncio.Event()
        self._flight = asyncio.Semaphore(max(1, cfg.max_trades_in_flight))
        self.llm_mode = "unknown"
        self.cuda = False
        self.trade_log: List[Dict[str, Any]] = []
        self.spawned = 0

    # ------------------------------------------------------------------
    # context handed to the cabins
    # ------------------------------------------------------------------
    def _price_of(self, symbol: str) -> Optional[float]:
        """The live price the broker layer sizes and books against."""
        tick = self.market.tick(symbol)
        return float(tick.price) if tick else None

    def _market_ctx(self, symbol: str, features: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        tick = self.market.tick(symbol)
        board = {b["symbol"]: b for b in self.market.board()}
        btc = board.get("BTC/USDT", {}).get("change_pct", 0.0)
        change = tick.change_pct if tick else 0.0
        regime = "risk-on" if btc > 0.4 else ("risk-off" if btc < -0.4 else "range")
        vol_rank = float(features.get("atr_rank", 50.0)) if features else 50.0
        return {
            "price": tick.price if tick else 0.0,
            "change_pct": change,
            "high": tick.high if tick else 0.0,
            "low": tick.low if tick else 0.0,
            "regime": regime,
            "btc_change_pct": btc,
            "vol_rank": vol_rank,
            "spread_bps": float(features.get("spread_proxy_bps", 3.0)) if features else 3.0,
        }

    def ctx_fn(self, trade: TradeCandidate):
        def _ctx() -> Dict[str, Any]:
            return {
                "market": self._market_ctx(trade.symbol, trade.features),
                "portfolio": self.desk.context(),
                # What the table has already taught itself, read back into every
                # verdict: the debate room is the training channel, so its rules
                # are part of the packet, not a footnote to it. The house
                # curriculum sits underneath them, so a desk on its first trade
                # of a session is not a desk with nothing on file.
                "memory": {"lessons": self.lessons()},
                "now": time.time(),
            }
        return _ctx

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def start(self, seed: Optional[int] = None) -> None:
        try:
            import torch

            self.cuda = bool(torch.cuda.is_available())
            if self.cuda:
                names = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
                log.info("GPU: %s", ", ".join(names))
        except Exception:
            self.cuda = False

        await self.market.start()
        self.brains = await asyncio.to_thread(build_brains, self.cfg, self.cuda)
        self.council = Council(self.cfg, self.brains, self.bus)
        self.registry = brain_registry(self.brains, self.cfg.model_profile,
                                       adapters_dir=getattr(self.cfg, "adapters_dir", None))
        # the training book: the curriculum, the room's rules and every settled
        # decision, kept as a supervised dataset (see `python -m soul.train`)
        self.training = TrainingBook(self.cfg, self.brains)
        if self.cfg.debate_enabled:
            self.debate = DebateRoom(self.cfg, self.brains, self.bus, self.registry)
        self.llm_mode = "mock" if all(getattr(b, "kind", "") == "mock" for b in self.brains.values()) else "local-hf"

        log.info("engine: market=%s brains=%s vram~%.1fGB", self.market.mode, self.llm_mode,
                 vram_estimate(self.cfg.model_profile))

        # saved terminal credentials (if any) are tried once, off the event
        # loop: a broker that is not there must not hold up the floor
        await asyncio.to_thread(self.broker.autoconnect)

        self._tasks = [
            asyncio.create_task(self.market.run(), name="market"),
            asyncio.create_task(self._scan_loop(), name="scanner"),
            asyncio.create_task(self._mark_loop(), name="mark"),
            asyncio.create_task(self._broadcast_loop(), name="broadcast"),
        ]
        if self.debate is not None:
            self._tasks.append(asyncio.create_task(self._debate_loop(), name="debate"))
        if self.scout is not None:
            self._tasks.append(asyncio.create_task(self._scout_listener(), name="scout-learner"))
        if seed is None:
            seed = self.cfg.seed_demo_trades
        if seed:
            asyncio.create_task(self.seed_demo(seed), name="seed")

    async def stop(self) -> None:
        self._stopping.set()
        await self.market.stop()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    # loops
    # ------------------------------------------------------------------
    async def _scan_loop(self) -> None:
        await asyncio.sleep(2.0)
        while not self._stopping.is_set():
            try:
                if not self.paused:
                    await self.run_scan()
            except Exception as exc:                       # pragma: no cover
                log.warning("scan loop error: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.scan_seconds)
            except asyncio.TimeoutError:
                pass

    async def run_scan(self, force: bool = False) -> List[TradeCandidate]:
        if force:
            self.cfg.min_score = min(self.cfg.min_score, 0.05)
        candidates = await self.scanner.scan(force=force)
        found = len(candidates)

        # The fly screens before the council: it reads the same feature block the
        # cabins will get, expressed in the frame of the proposed trade, and only
        # the setups it confirms walk in through the welcome door.
        if self.scout is not None and candidates:
            picks = self.scout.screen(candidates)
            await self.bus.publish(
                "scout",
                judged=found,
                admitted=len(picks),
                confirmed=self.scout.confirmed,
                waited=self.scout.waited,
                contradicted=self.scout.contradicted,
                batch=self.scout.last_batch,
                picks=[p.as_dict() for p in picks],
            )
            candidates = [p.candidate for p in picks]

        await self.bus.publish("scan", count=len(candidates), found=found,
                               scan_index=self.scanner.scan_count,
                               paused=self.paused,
                               scanned=self.scout is not None,
                               symbols=[c.symbol for c in candidates])
        for cand in candidates:
            cand.desk = self._assign_desk(cand)
            asyncio.create_task(self._process(cand), name=f"trade-{cand.id}")
        return candidates

    def _assign_desk(self, cand: TradeCandidate) -> Dict[str, int]:
        idx = self.spawned % max(1, self.cfg.desks)
        self.spawned += 1
        return {"index": idx, "row": idx // 8, "col": idx % 8}

    async def _process(self, trade: TradeCandidate) -> None:
        async with self._flight:
            self.in_flight += 1
            try:
                result = await self.council.review(trade, self.ctx_fn(trade))
                entry = {
                    "trade_id": trade.id, "symbol": trade.symbol, "side": trade.side,
                    "strategy": trade.strategy, "score": trade.score,
                    "approvals": result.approvals, "rejections": result.rejections,
                    "route": result.route, "decision": result.decision,
                    "confidence": round(result.confidence, 1),
                    "entry": trade.entry, "stop": trade.stop, "target": trade.target,
                    "rr": round(trade.rr, 2), "ts": time.time(),
                    "verdicts": [v.as_dict() for v in result.verdicts],
                    "ceo": result.ceo_verdict.as_dict() if result.ceo_verdict else None,
                    "opened": False, "blocked": None,
                }
                if result.decision == "ENTER":
                    pos = await self.desk.open(trade, result)
                    entry["opened"] = pos is not None
                    if pos is None:
                        entry["blocked"] = self.desk.blocked.get(trade.id, "not opened")
                self.trade_log.append(entry)
                self.trade_log = self.trade_log[-300:]
                # ...and if the operator has armed auto-trade for this asset
                # class, the approved trade goes to the broker as well as the
                # paper book. The council proposes; the arming is theirs.
                await self._maybe_autotrade(entry, trade)
                # the decision is recorded with the packet it was made on; the
                # outcome arrives when the position closes and only then does it
                # become a training row
                if self.training is not None:
                    self.training.note(trade, result, self.ctx_fn(trade)())
                if self.debate is not None:
                    self.debate.queue_trade(trade, result, extra={
                        "open_positions": len(self.desk.positions),
                        "equity": round(self.desk.equity(self.prices()), 2),
                        "lesson": (result.ceo_verdict.reason[:180]
                                   if result.ceo_verdict else ""),
                    })
            except Exception as exc:                       # pragma: no cover
                log.exception("trade %s failed: %s", trade.id, exc)
                await self.bus.publish("error", trade_id=trade.id, message=str(exc))
            finally:
                self.in_flight -= 1

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    async def _maybe_autotrade(self, entry: Dict[str, Any], trade: TradeCandidate) -> None:
        auto = self.broker.autotrade
        signal = self._signal_of(entry, trade)
        entry["signal"] = {"class": signal["class"], "venue": signal["venue"]}
        if not auto["on"] or entry.get("decision") != "ENTER" or entry.get("broker_ticket"):
            return
        if signal["class"] not in auto["classes"]:
            auto["skipped"] += 1
            auto["last"] = f"{trade.symbol}: {signal['class']} is not armed"
            return
        if signal["confidence"] < float(auto["min_confidence"]):
            auto["skipped"] += 1
            auto["last"] = f"{trade.symbol}: confidence {signal['confidence']:.0f} under the floor"
            return
        try:
            order = await self.broker.place(signal, source="autotrade")
            entry["broker_ticket"] = order["ticket"]
        except BrokerError as exc:
            auto["skipped"] += 1
            auto["last"] = f"{trade.symbol}: {exc.message}"
            await self.bus.publish("broker_skipped", trade_id=trade.id, symbol=trade.symbol,
                                   reason=exc.reason, message=exc.message)

    def _signal_of(self, entry: Dict[str, Any], trade: TradeCandidate) -> Dict[str, Any]:
        """One scanned trade, in the shape the order panel and the broker read."""
        inst = book.instrument(trade.symbol)
        return {
            "id": entry.get("trade_id") or trade.id, "symbol": trade.symbol,
            "name": inst.name, "class": inst.klass, "side": entry.get("side") or trade.side,
            "strategy": entry.get("strategy") or trade.strategy,
            "score": entry.get("score"), "decision": entry.get("decision"),
            "route": entry.get("route"), "approvals": entry.get("approvals"),
            "rejections": entry.get("rejections"), "confidence": entry.get("confidence"),
            "entry": entry.get("entry") or trade.entry, "stop": entry.get("stop") or trade.stop,
            "target": entry.get("target") or trade.target, "rr": entry.get("rr"),
            "desk": entry.get("desk"), "ts": entry.get("ts"),
            "verdicts": entry.get("verdicts") or [], "ceo": entry.get("ceo"),
            "venue": self.broker.venue_for(inst.klass),
            "venue_detail": self.broker.route_detail(inst.klass),
        }

    def signals_view(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Everything the six desks have scanned, newest first.

        Every council verdict the floor has taken, with the six opinions on it
        and whether it can be placed — this is the list the operator works from.
        """
        placed = {o["ref"]: o for o in self.broker.orders.values() if o.get("ref")}
        out: List[Dict[str, Any]] = []
        for entry in list(reversed(self.trade_log))[:limit]:
            trade = None
            cand = None
            for h in (self.council.history if self.council else []):
                if getattr(h.trade, "id", "") == entry.get("trade_id"):
                    cand = h.trade
                    break
            signal = self._signal_of(entry, cand) if cand is not None else {
                "id": entry.get("trade_id"), "symbol": entry.get("symbol"),
                "name": book.instrument(entry.get("symbol", "")).name,
                "class": book.instrument(entry.get("symbol", "")).klass,
                "side": entry.get("side"), "strategy": entry.get("strategy"), "score": entry.get("score"),
                "decision": entry.get("decision"), "route": entry.get("route"),
                "approvals": entry.get("approvals"), "rejections": entry.get("rejections"),
                "confidence": entry.get("confidence"), "entry": entry.get("entry"),
                "stop": entry.get("stop"), "target": entry.get("target"), "rr": entry.get("rr"),
                "desk": entry.get("desk"), "ts": entry.get("ts"),
                "verdicts": entry.get("verdicts") or [], "ceo": entry.get("ceo"),
                "venue": self.broker.venue_for(book.instrument(entry.get("symbol", "")).klass),
                "venue_detail": self.broker.route_detail(book.instrument(entry.get("symbol", "")).klass),
            }
            order = placed.get(signal["id"])
            signal["ticket"] = order["ticket"] if order else None
            signal["order_status"] = order["status"] if order else None
            signal["placed_venue"] = order["venue"] if order else None
            if signal["decision"] != "ENTER":
                signal["placeable"] = False
                signal["blocked"] = "the council said no"
            elif order:
                signal["placeable"] = False
                signal["blocked"] = f"already placed ({order['ticket']})"
            else:
                signal["placeable"] = True
                signal["blocked"] = None
            if signal["placeable"] and len(out) < 8:
                try:
                    signal["sizing"] = self.broker.sizing(signal)
                except Exception as exc:                    # pragma: no cover
                    signal["sizing"] = {"ok": False, "message": str(exc)}
            out.append(signal)
        return out

    async def place_signal(self, signal_id: str, volume: Optional[float] = None,
                           risk_pct: Optional[float] = None, source: str = "manual") -> Dict[str, Any]:
        signal = next((s for s in self.signals_view(limit=200) if str(s.get("id")) == str(signal_id)), None)
        if signal is None:
            raise BrokerError("unknown_signal", f"no scanned trade {signal_id}")
        if signal.get("ticket"):
            raise BrokerError("already_open", f"that trade is already placed ({signal['ticket']})")
        return await self.broker.place(signal, volume=volume, risk_pct=risk_pct, source=source)

    def lessons(self) -> List[Dict[str, Any]]:
        """The rules in force: the session's debate lessons over the curriculum.

        The ten seed lessons used to be dead code — written, never read — which
        left a fresh session with an empty DESK MEMORY block and six desks
        reasoning from their playbook alone. They are staff training, so they
        belong in the packet from turn one.
        """
        seeds = [
            {"topic": "house curriculum", "speaker": "HOUSE", "round": 0, "ts": 0.0,
             "speaker_label": f"House playbook — {name}", "text": text}
            for name, text in SEED_LESSONS.items()
        ]
        return seeds + list(self.debate.lessons if self.debate else [])

    async def ask_desk(self, key: str, question: str, trade_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Ask one cabin why it voted the way it did. Returns the turn it said."""
        if self.debate is None:
            return None
        inner: Dict[str, Any] = {}
        if trade_id:
            rec = next((h for h in reversed(self.council.history)
                        if getattr(h.trade, "id", None) == trade_id), None)
            if rec is not None:
                inner = packet(rec.trade, rec)
        return await self.debate.ask(key, question, trade_id, inner)

    async def _debate_loop(self) -> None:
        """Run the debate room: a review of the last decision, then a lesson.

        The desks talk on a timer rather than after every council: a review
        meeting that follows every single trade is noise, and the whole point of
        the room is that the conclusions outlive the trade they came from.
        """
        await asyncio.sleep(6.0)
        while not self._stopping.is_set():
            try:
                if self.debate is not None and not self.paused:
                    await self.debate.run_round()
                if self.debate is not None:
                    # the room says when it will speak next, so the floor can
                    # show a live pulse instead of a panel that looks dead
                    self.debate.next_round_at = time.time() + self.cfg.debate_seconds
            except Exception as exc:                       # pragma: no cover
                log.warning("debate round failed: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.cfg.debate_seconds)
            except asyncio.TimeoutError:
                pass

    async def _mark_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                prices = {b["symbol"]: b["price"] for b in self.market.board()}
                await self.desk.mark(prices)
                # live orders are marked too: a paper order whose stop or target
                # is touched books itself, exactly like the desk's own book
                await self.broker.mark(prices)
            except Exception as exc:                       # pragma: no cover
                log.warning("mark loop error: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.cfg.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _scout_listener(self) -> None:
        """Feed realised P&L back into the fly's mushroom body.

        A trade the scout confirmed that then closed in profit is a reward for
        the Kenyon cells that were active when it made that call; a loser is a
        punishment. This is the third factor in the three-factor rule.
        """
        queue = self.bus.subscribe()
        try:
            while not self._stopping.is_set():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if event.get("type") != "position_closed" or self.scout is None:
                    continue
                payload = event.get("payload", {})
                try:
                    self.scout.learn(str(payload.get("trade_id", "")),
                                     float(payload.get("pnl_pct", 0.0) or 0.0))
                except Exception as exc:                # pragma: no cover
                    log.warning("scout learning failed: %s", exc)
                # ...and the six desks are marked too: a closed trade is the
                # only honest scorecard a council can have.
                if self.council is not None:
                    try:
                        self.council.settle(str(payload.get("trade_id", "")),
                                            float(payload.get("pnl", 0.0) or 0.0),
                                            float(payload.get("risk", 0.0) or 0.0))
                    except Exception as exc:            # pragma: no cover
                        log.warning("scoreboard settle failed: %s", exc)
                # ...and the desks' verdicts become supervised training rows
                trade_id = str(payload.get("trade_id", ""))
                if self.training is not None:
                    try:
                        self.training.settle(trade_id,
                                             float(payload.get("pnl", 0.0) or 0.0),
                                             float(payload.get("risk", 0.0) or 0.0),
                                             float(payload.get("pnl_pct", 0.0) or 0.0))
                    except Exception as exc:            # pragma: no cover
                        log.warning("training settle failed: %s", exc)
                # ...and the same lesson is said out loud by a desk that was on
                # the wrong side of it, so the room shows how the desks get
                # trained rather than only reporting a row count
                if self.debate is not None:
                    try:
                        record = self.council.get(trade_id) if self.council else None
                        await self.debate.post_mortem(
                            trade_id, record,
                            float(payload.get("pnl", 0.0) or 0.0),
                            float(payload.get("pnl_pct", 0.0) or 0.0),
                            exit_reason=str(payload.get("exit_reason", "") or ""))
                    except Exception as exc:            # pragma: no cover
                        log.warning("post-mortem failed: %s", exc)
        finally:
            self.bus.unsubscribe(queue)

    async def _broadcast_loop(self) -> None:
        """Throttled price + equity stream for the HUD."""
        while not self._stopping.is_set():
            try:
                board = self.market.board()
                prices = {b["symbol"]: b["price"] for b in board}
                await self.bus.publish("tick", board=board,
                                       equity=self.desk.stats(prices)["equity"])
            except Exception:                              # pragma: no cover
                pass
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # operator hooks
    # ------------------------------------------------------------------
    async def seed_demo(self, n: int = 5) -> None:
        """Push a handful of candidates through the floor immediately."""
        await asyncio.sleep(0.5)
        candidates = await self.scanner.scan(force=True)
        if not candidates:
            candidates = await self.scanner.scan(force=True)
        for cand in candidates[:n]:
            cand.desk = self._assign_desk(cand)
            asyncio.create_task(self._process(cand), name=f"demo-{cand.id}")
            await asyncio.sleep(0.4)

    async def inject_volatility(self) -> None:
        self.market.inject_volatility()
        await self.bus.publish("market_shock", note="volatility injected by operator")

    async def set_instruments(self, symbols: List[str]) -> List[str]:
        """Point the scanner, the scout and the floor at a new instrument book."""
        chosen = self.market.set_universe(symbols)
        self.cfg.universe = chosen
        classes = book.classes_of(chosen)
        await self.bus.publish("universe_changed", symbols=chosen, classes=classes,
                               count=len(chosen))
        log.info("universe: %d instruments across %s", len(chosen), ", ".join(classes) or "none")
        return chosen

    async def close_all(self) -> int:
        prices = {b["symbol"]: b["price"] for b in self.market.board()}
        return await self.desk.force_close_all(prices, "MANUAL")

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def prices(self) -> Dict[str, float]:
        return {b["symbol"]: b["price"] for b in self.market.board()}

    def state(self) -> Dict[str, Any]:
        prices = self.prices()
        return {
            "engine": {
                "started_at": self.started_at,
                "uptime_s": round(time.time() - self.started_at, 1),
                "llm_mode": self.llm_mode,
                "cuda": self.cuda,
                "model_profile": self.cfg.model_profile,
                "vram_estimate_gb": vram_estimate(self.cfg.model_profile),
                "paused": self.paused,
                "scan_seconds": self.scan_seconds,
                "min_score": round(self.min_score, 3),
                "in_flight": self.in_flight,
                "desks": self.cfg.desks,
                "timeframe": self.cfg.candle_timeframe,
                "version": __import__("soul").__version__,
            },
            "market": self.market.snapshot(),
            "council": self.council.snapshot() if self.council else {},
            "desk": self.desk.stats(prices),
            "positions": self.desk.positions_view(prices),
            "closed": self.desk.closed_view(30),
            "equity_curve": self.desk.equity_curve[-600:],
            "registry": self.registry,
            "cabins": [r for r in self.registry.values() if not r["is_ceo"]],
            "ceo": next((r for r in self.registry.values() if r["is_ceo"]), None),
            "recent_councils": self.council.recent(20) if self.council else [],
            "training": self.training.stats(self.lessons()) if self.training else None,
            "trade_log": self.trade_log[-60:],
            "scan_index": self.scanner.scan_count,
            "scout": self.scout.stats() if self.scout else {"enabled": False},
            # execution: the scanned trades the six desks have ruled on, the
            # orders that resulted, and where each asset class is routed
            "signals": self.signals_view(30),
            "orders": {"open": self.broker.positions_view(prices),
                       "closed": self.broker.history_view(40)},
            "broker": self.broker.status(),
            "debate": self.debate.snapshot() if self.debate else {"enabled": False},
            "instruments": {
                "selected": list(self.cfg.universe),
                "count": len(self.cfg.universe),
                "classes": book.classes_of(list(self.cfg.universe)),
            },
        }
