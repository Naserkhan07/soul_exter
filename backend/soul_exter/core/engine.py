"""
Floor engine — the live simulation.

Wires together: market feed -> fly brain hunt -> trade intake through the welcome
gate -> desk seating -> five cabin hearings (each with an LLM judge) -> council
tally -> executive review -> walk out of either the entry door (goes live) or the
exit door (rejected). Every walk is an A* route on the navigation mesh, so bodies
stay on the pathways and physically enter each cabin through its door.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..agents.schemas import (Direction, Outcome, Signal, Stage, Trade, TradeState, Verdict_,
                              new_id)
from ..brain.flybrain import FlyBrain
from ..brain.scanner import FlyScanner
from ..llm.engine import CouncilEngine
from ..llm.playbook import Playbook
from ..llm.registry import LLMSeat
from ..market.feed import MarketFeed
from ..market.universe import UNIVERSE
from .layout import WALK_SPEED, FloorPlan, NavGrid, get_nav, get_plan
from .settings import Settings

CABINS = [1, 2, 3, 4, 5]


@dataclass
class Walker:
    id: str
    kind: str                       # trade | npc
    x: float
    z: float
    yaw: float = 0.0
    speed: float = WALK_SPEED
    path: List[Tuple[float, float]] = field(default_factory=list)
    seg: int = 0
    pause_left: float = 0.0
    seated: bool = False
    carry: bool = True
    trade_id: Optional[str] = None
    label: str = ""
    sub: str = ""
    accent: str = "#38bdf8"
    phase: float = 0.0
    stride: float = 0.0
    home: Optional[str] = None
    dead: bool = False
    trail: List[Tuple[float, float]] = field(default_factory=list)

    @property
    def remaining(self) -> float:
        if self.seg >= len(self.path) - 1:
            return 0.0
        d = 0.0
        for i in range(self.seg, len(self.path) - 1):
            d += math.dist(self.path[i], self.path[i + 1])
        return d

    def set_path(self, path: Sequence[Tuple[float, float]]) -> None:
        self.path = [(float(a), float(b)) for a, b in path]
        self.seg = 0
        if len(self.path) >= 1:
            self.x, self.z = self.path[0]

    def step(self, dt: float) -> None:
        self.phase += dt
        if self.strike_pause():
            return
        if self.pause_left > 0:
            self.pause_left = max(0.0, self.pause_left - dt)
            self.stride *= 0.86
            return
        if self.seg >= len(self.path) - 1:
            return
        target = self.path[self.seg + 1]
        dx, dz = target[0] - self.x, target[1] - self.z
        dist = math.hypot(dx, dz)
        if dist < 1e-4:
            self.seg += 1
            return
        move = min(self.speed * dt, dist)
        nx = self.x + dx / dist * move
        nz = self.z + dz / dist * move
        # smooth turn
        want = math.atan2(dx, dz)
        diff = (want - self.yaw + math.pi) % (2 * math.pi) - math.pi
        self.yaw += max(-2.6 * dt, min(2.6 * dt, diff))
        self.x, self.z = nx, nz
        self.stride += dt * 6.2
        if math.dist((nx, nz), target) < 0.06:
            self.seg += 1
        if self.seg % 2 == 0 and len(self.trail) and math.dist(self.trail[-1], (nx, nz)) < 0.5:
            pass
        if not self.trail or math.dist(self.trail[-1], (nx, nz)) > 0.45:
            self.trail.append((round(nx, 2), round(nz, 2)))
            self.trail = self.trail[-48:]

    def strike_pause(self) -> bool:
        return self.pause_left > 0 and False  # never skip path following; pause handled above

    def arrived(self) -> bool:
        return self.seg >= len(self.path) - 1


class FloorEngine:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings.load()
        self.plan: FloorPlan = get_plan()
        self.nav: NavGrid = get_nav()
        self.rng = random.Random(20250914)
        self.brain = FlyBrain(seed=self.rng.randint(1, 10**6))
        self.feed = MarketFeed(self.settings.enabled_symbols or list(UNIVERSE)[:40])
        self.scanner = FlyScanner(self.feed, self.brain,
                                  strike_score=self.settings.strike_score,
                                  cooldown_s=self.settings.cooldown_s,
                                  per_tick=self.settings.scan_batch)
        self.playbook = Playbook()
        self.council = CouncilEngine(self.settings.to_seats(), self.playbook, self.rng)
        self.trades: Dict[str, Trade] = {}
        self.walkers: Dict[str, Walker] = {}
        self.events: List[dict] = []
        self.clock = 0.0
        self.tick_hz = 20.0
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._scan_acc = 0.0
        self._frame_acc = 0.0
        self.stats = dict(spawned=0, accepted=0, rejected=0, exited=0, wins=0, losses=0,
                          pnl_r=0.0, llm_calls=0, live_feed=False, up=time.time())
        self.free_desks: List[int] = [d.index for d in self.plan.desks]
        self.rng.shuffle(self.free_desks)
        self.desk_owner: Dict[int, str] = {}
        self.outcomes: List[Outcome] = []
        self.pending_outcomes: Dict[str, dict] = {}
        self.npcs: List[Walker] = []
        self._fly_target: Optional[Tuple[float, float]] = None
        self._fly_dive_left = 0.0
        self.last_debate = 0.0
        self.live_status: Dict[str, Any] = dict(enabled=self.settings.live_venues, ok=False,
                                                updated=None, error="", symbols=[])
        self.broker = self._make_broker()
        self._spawn_npcs()

    # ---------------------------------------------------------------- broker
    def _make_broker(self):
        from ..broker import get_broker
        st = self.settings
        return get_broker(st.broker_mode, login=st.mt5_login, password=st.mt5_password,
                          server=st.mt5_server, path=st.mt5_path,
                          symbol_suffix=st.mt5_symbol_suffix)

    def broker_status(self) -> dict:
        status = self.broker.status()
        status["lots"] = self.settings.lots
        status["auto_place"] = self.settings.auto_place
        status["configured_login"] = self.settings.mt5_login or None
        status["configured_server"] = self.settings.mt5_server or None
        return status

    def _trade_brief(self, trade) -> dict:
        sig = trade.signal or {}
        return dict(id=trade.id, symbol=trade.symbol, asset_class=trade.asset_class,
                    direction=trade.direction, entry=sig.get("entry"),
                    exit_price=self.feed.tickers[trade.symbol].last_price
                    if trade.symbol in self.feed.tickers else sig.get("entry"))

    def place_trade(self, trade_id: str, lots: Optional[float] = None) -> dict:
        """Operator clicked PLACE — clear the ticket and route it to the market."""
        trade = self.trades.get(trade_id)
        if trade is None:
            return dict(ok=False, message="unknown ticket")
        if trade.state == TradeState.EXITED.value:
            return dict(ok=False, message="ticket already closed")
        w = self.walkers.get(f"W-{trade.id}")
        # a forced placement bypasses a pending hearing: the council is recorded as
        # overruled by the operator, which is visible in the ticket history.
        if trade.outcome == "pending":
            if w is not None:
                w.pause_left = 0.0
            self._finalize(trade, accepted=True, manual=True)
        size = float(lots if lots is not None else self.settings.lots)
        res = self.broker.place(self._trade_brief(trade), size)
        trade.broker_ticket = res.ticket
        trade.broker_mode = res.mode
        if w is not None:
            self._walk_out(trade, "entry")
        self.emit("trade_placed", trade=dict(id=trade.id, symbol=trade.symbol, lots=size),
                  verdict="placed", message=dict(text=f"Operator placed {trade.symbol} "
                                                 f"({res.mode}) — {res.message}"))
        return dict(ok=True, order=res.dict(), trade=trade.dict())

    def book_trade(self, trade_id: str, lots: Optional[float] = None) -> dict:
        """Operator clicked BOOK — close the position now and realise the P&L."""
        trade = self.trades.get(trade_id)
        if trade is None:
            return dict(ok=False, message="unknown ticket")
        brief = self._trade_brief(trade)
        res = self.broker.book(brief, float(lots if lots is not None else self.settings.lots))
        sig = trade.signal or {}
        entry = float(sig.get("entry") or 0.0)
        sl = float(sig.get("stop_loss") or 0.0)
        risk = max(abs(entry - sl), 1e-9)
        price = float(brief.get("exit_price") or res.price or entry)
        sgn = 1.0 if trade.direction == "long" else -1.0
        pnl_r = (price - entry) * sgn / risk
        if trade.outcome == "pending":
            self._finalize(trade, accepted=True, manual=True)
        if trade.pnl_r == 0.0:
            self._record_outcome(trade, pnl_r, True)
        else:
            trade.pnl_r = round(pnl_r, 2)
        trade.state = TradeState.EXITED.value
        trade.closed_manual = True
        w = self.walkers.get(f"W-{trade.id}")
        if w is not None:
            self._route(w, "exit_outside")
            w.carry = False
        self.emit("trade_booked",
                  trade=dict(id=trade.id, symbol=trade.symbol, pnl_r=round(pnl_r, 2)),
                  verdict="booked",
                  message=dict(text=f"Operator booked {trade.symbol} at {price:.5g} "
                                    f"for {pnl_r:+.2f}R ({res.mode})"))
        return dict(ok=True, order=res.dict(), trade=trade.dict())

    def _auto_place(self, trade) -> None:
        if not self.settings.auto_place:
            return
        res = self.broker.place(self._trade_brief(trade), float(self.settings.lots))
        trade.broker_ticket = res.ticket
        trade.broker_mode = res.mode
        self.emit("order_routed", trade=dict(id=trade.id, symbol=trade.symbol),
                  message=dict(text=f"{'Filled' if res.ok else 'Not routed'} {trade.symbol}: "
                                    f"{res.message}"))

    # ------------------------------------------------------------------ boot
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.loop_errors = 0
        self.last_error = ""
        self._tasks = [asyncio.create_task(self._tick_loop()),
                       asyncio.create_task(self._scan_loop()),
                       asyncio.create_task(self._debate_loop())]
        if self.settings.live_venues:
            self._tasks.append(asyncio.create_task(self._live_loop()))

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    # ------------------------------------------------------------- main loop
    async def _tick_loop(self) -> None:
        last = time.time()
        while self._running:
            await asyncio.sleep(1.0 / self.tick_hz)
            now = time.time()
            dt = min(0.5, now - last)
            last = now
            if self.settings.paused:
                continue
            self.tick(dt * self.settings.speed)

    def tick(self, dt: float) -> None:
        self.clock += dt
        self.feed.advance(dt)
        for w in list(self.walkers.values()):
            w.step(dt)
            if w.arrived() and w.pause_left <= 0.0:
                self._on_arrive(w)
        self._npc_tick(dt)
        self._fly_tick(dt)
        self._outcome_tick(dt)

    # --------------------------------------------------------------- spawning
    def _spawn_trade(self, signal: Signal) -> Optional[Trade]:
        if self.in_flight() >= self.settings.max_trades_in_pipe:
            return None
        desk_index = self.free_desks.pop() if self.free_desks else \
            (self.rng.randrange(1, len(self.plan.desks) + 1))
        desk = self.plan.desks[desk_index - 1]
        trade = Trade(id=new_id("TRD"), symbol=signal.symbol, asset_class=signal.asset_class,
                      direction=signal.direction, desk_id=desk.id, desk_index=desk_index,
                      confidence=signal.score, signal=signal.dict(),
                      thesis=self._fly_thesis(signal))
        ex, ez = self.nav.free_at(*self.plan.nodes["entry_outside"])
        walker = Walker(id=f"W-{trade.id}", kind="trade", x=ex, z=ez, carry=True, trade_id=trade.id,
                        label=f"{trade.id} · {trade.symbol}", sub=f"{signal.direction.upper()} · {signal.asset_class}",
                        accent="#facc15" if signal.direction == "long" else "#fb7185")
        # enter through the welcome gate, then sit at the assigned desk
        self._route(walker, f"desk_{desk_index}_seat")
        self.walkers[walker.id] = walker
        self.trades[trade.id] = trade
        self.desk_owner[desk_index] = trade.id
        trade.state = TradeState.ENTERING.value
        self.stats["spawned"] += 1
        self.emit("trade_spawn", trade=dict(id=trade.id, symbol=trade.symbol,
                                            direction=trade.direction, desk=desk.id,
                                            confidence=round(signal.score, 2),
                                            asset_class=signal.asset_class))
        # the fly dives to inspect the desk it just filled
        self._fly_target = (desk.x, desk.z)
        self._fly_dive_left = 4.0
        return trade

    def _fly_thesis(self, signal: Signal) -> str:
        f = signal.features
        return (f"Fly-brain strike on {signal.symbol} ({signal.asset_class}) with conviction "
                f"{signal.score:.2f}; ATR {signal.atr:.4g} ({f.get('atr_pct',0)*100:.2f}% of price), "
                f"efficiency {f.get('efficiency',0):.2f}, vol percentile {f.get('atr_rank',0)*100:.0f}, "
                f"session factor {f.get('session',1):.2f}.")

    # ------------------------------------------------------------ path helper
    def _route(self, w: Walker, node: str) -> None:
        target = self.plan.nodes.get(node)
        if target is None:
            return
        self._route_to(w, target)

    def _route_to(self, w: Walker, xz: Tuple[float, float]) -> None:
        """Path to a target, snapped onto the navmesh first (never off-mesh)."""
        safe = self.nav.free_at(xz[0], xz[1])
        path = self.nav.find_path((w.x, w.z), safe)
        if not path:                       # fall back to a direct hop if A* fails
            path = [safe]
        w.set_path(path)

    # ------------------------------------------------------------- arrivals
    def _on_arrive(self, w: Walker) -> None:
        if w.kind == "npc":
            # idle a moment, then pick a new destination
            w.pause_left = self.rng.uniform(1.4, 5.0)
            self._npc_pick_destination(w)
            return
        trade = self.trades.get(w.trade_id or "")
        if trade is None:
            w.dead = True
            return
        state = trade.state
        if state == TradeState.ENTERING.value:
            w.seated = True
            w.pause_left = self.rng.uniform(2.4, 4.2) * self.settings.cabin_dwell_scale
            trade.state = TradeState.SEATED.value
            self.emit("trade_seated", trade=dict(id=trade.id, desk=trade.desk_id))
            return
        if state == TradeState.SEATED.value:
            trade.state = TradeState.WALKING_TO_CABIN.value
            self._begin_cabin(trade, 1)
            return
        if state == TradeState.WALKING_TO_CABIN.value:
            idx = getattr(trade, "_cabin", 1)
            trade.state = TradeState.IN_CABIN.value
            w.pause_left = 999.0        # released when the verdict lands
            w.seated = False
            self.emit("trade_in_cabin", trade=dict(id=trade.id, cabin=idx))
            asyncio.create_task(self._run_cabin(trade, idx))
            return
        if state == TradeState.IN_CABIN.value:
            # verdict returned: leave the cabin and move on
            idx = getattr(trade, "_cabin", 1)
            if idx < 5:
                self._begin_cabin(trade, idx + 1)
            else:
                self._after_cabins(trade)
            return
        if state == TradeState.TO_EXECUTIVE.value:
            trade.state = TradeState.IN_EXECUTIVE.value
            w.pause_left = 999.0
            self.emit("trade_in_exec", trade=dict(id=trade.id))
            asyncio.create_task(self._run_executive(trade))
            return
        if state == TradeState.IN_EXECUTIVE.value:
            if trade.outcome == "accepted":
                self._walk_out(trade, "entry")
            else:
                self._walk_out(trade, "exit")
            return
        if state in (TradeState.EXITING.value,):
            w.dead = True
            trade.state = TradeState.EXITED.value
            self.stats["exited"] += 1
            self.desk_owner.pop(trade.desk_index, None)
            if trade.desk_index not in self.free_desks and trade.desk_index <= len(self.plan.desks):
                self.free_desks.append(trade.desk_index)
            self.emit("trade_exited", trade=dict(id=trade.id, outcome=trade.outcome))

    # --------------------------------------------------------------- cabins
    def _begin_cabin(self, trade: Trade, idx: int) -> None:
        w = self.walkers.get(f"W-{trade.id}")
        if w is None:
            return
        setattr(trade, "_cabin", idx)
        trade.state = TradeState.WALKING_TO_CABIN.value
        judge = self.council.judge_for_cabin(idx)
        stage = Stage(id=f"{trade.id}-C{idx}", kind="cabin", cabin_index=idx,
                      judge_id=(judge.id if judge else f"judge_{idx}"),
                      judge_name=(judge.name if judge else f"CABIN {idx}"),
                      stage_index=len(trade.stages))
        trade.stages.append(stage)
        self._route(w, f"cabin_{idx}_hear")
        self.emit("trade_walking", trade=dict(id=trade.id, cabin=idx, judge=stage.judge_name))

    async def _run_cabin(self, trade: Trade, idx: int) -> None:
        w = self.walkers.get(f"W-{trade.id}")
        stage = trade.stages[-1] if trade.stages else None
        judge = self.council.judge_for_cabin(idx)
        if judge is None or stage is None:
            if w:
                w.pause_left = 0.4
            self._release_cabin(trade)
            return
        stage.state = "hearing"
        stage.started_at = time.time()
        prior = [s.verdict for s in trade.stages if s.verdict]
        pace = min(9.0, max(2.2, 0.35 * self.settings.cabin_dwell_scale *
                           ((w.remaining if w else 12.0) / max(WALK_SPEED, 0.1))))
        transcript = [dict(kind="pitch", seat_id="hunter", name="DROSOPHILA",
                           text=self._pitch_text(trade),
                           ts=time.time())]
        try:
            verdict = await self.council.adjudicate(judge, trade, prior, pace_s=pace * 0.45,
                                                    market=self._market_note(trade.symbol))
        except Exception as exc:  # never let a cabin kill the floor
            verdict = Verdict_(judge_id=judge.id, judge_name=judge.name, verdict="abstain",
                               confidence=0.3, score=0.0, engine="error",
                               reasoning=f"{judge.name} could not complete the hearing ({exc}); "
                                         f"the ticket passes with an abstention.")
        latency = verdict.latency_ms / 1000.0
        hold = max(1.0, min(pace - latency, 9.0)) * self.settings.cabin_dwell_scale
        await asyncio.sleep(hold)
        stage.verdict = verdict
        stage.state = "voted"
        stage.ended_at = time.time()
        transcript += self._hearing_lines(trade, judge, verdict, idx)
        stage.transcript = transcript
        self._tally(trade)
        self.emit("verdict", trade=dict(id=trade.id, symbol=trade.symbol), cabin=idx,
                  judge=verdict.judge_name, verdict=verdict.verdict,
                  confidence=round(verdict.confidence, 2), reasoning=verdict.reasoning[:400])
        if w:
            w.pause_left = 0.2
        # verdict cast inside the cabin -> the walker walks back out
        self._release_cabin(trade)

    def _release_cabin(self, trade: Trade) -> None:
        w = self.walkers.get(f"W-{trade.id}")
        if w is None:
            return
        w.pause_left = min(w.pause_left, 0.5)
        idx = getattr(trade, "_cabin", 1)
        if idx < 5:
            self._route(w, f"cabin_{idx + 1}_hear")
        else:
            self._route(w, "cabin_5_hear")
        w.seg = max(0, w.seg)

    def _tally(self, trade: Trade) -> None:
        verdicts = [s.verdict for s in trade.stages if s.verdict]
        trade.votes_for = sum(1 for v in verdicts if v.verdict == "approve")
        trade.votes_against = sum(1 for v in verdicts if v.verdict == "reject")
        confs = [v.confidence for v in verdicts]
        trade.avg_confidence = sum(confs) / len(confs) if confs else 0.0

    def _pitch_text(self, trade: Trade) -> str:
        s = trade.signal
        return (f"Ticket {trade.id}: {trade.symbol} {trade.direction.upper()} ({trade.asset_class}), "
                f"entry {s['entry']:.4g}, stop {s['stop_loss']:.4g}, target {s['take_profit']:.4g}, "
                f"{s['rr']:.2f}R, horizon {s['horizon']}. {trade.thesis}")

    def _hearing_lines(self, trade: Trade, judge: LLMSeat, v: Verdict_, idx: int) -> List[dict]:
        ts = time.time()
        lines = [dict(kind="verdict", seat_id=judge.id, name=judge.name, verdict=v.verdict,
                      confidence=round(v.confidence, 2),
                      text=f"[{v.verdict.upper()}] {v.reasoning}", ts=ts,
                      points=v.key_points, risks=v.risks, engine=v.engine, model=v.model)]
        if v.risks:
            question = ("Walk me through your mitigation for this: " + v.risks[0])
            answer = self._trade_answer(trade, judge, v, question)
            lines.append(dict(kind="question", seat_id=judge.id, name=judge.name,
                              text=question, ts=ts + 0.4))
            lines.append(dict(kind="answer", seat_id="hunter", name="DROSOPHILA",
                              text=answer, ts=ts + 0.8))
        return lines

    def _trade_answer(self, trade: Trade, judge: LLMSeat, v: Verdict_, question: str) -> str:
        s = trade.signal
        f = s["features"]
        if "spread" in question.lower() or "cost" in question.lower():
            return (f"Costs are inside tolerance: spread is {f.get('spread_ratio',0)*100:.4f}% of "
                    f"price against an ATR of {f.get('atr_pct',0)*100:.3f}%, so drag is "
                    f"{f.get('spread_ratio',0)/max(f.get('atr_pct',1e-9),1e-9)*100:.1f}% of the stop.")
        if "vol" in question.lower():
            return (f"Realised vol sits at the {f.get('atr_rank',0)*100:.0f}th percentile with a "
                    f"{f.get('vol_ratio',1):.2f}× participation ratio; I am not paying the top of "
                    f"the range for this expression.")
        if "mean" in question.lower() or "stretch" in question.lower():
            return (f"The ticket enters {abs(f.get('stretch',0)):.2f}σ from the 20-bar mean, inside "
                    f"the 2.4σ exhaustion band, with RSI at {f.get('rsi',50):.0f}.")
        if "liquidity" in question.lower() or "session" in question.lower():
            return (f"Session factor is {f.get('session',1):.2f} with {f.get('tick_rate',0):.1f} "
                    f"ticks/s of flow on the venue, so the clip can be worked without impact.")
        return (f"Stops are placed at {s['stop_loss']:.4g}, 1.15×ATR from entry, and the first "
                f"partial at {s['entry'] + (s['take_profit'] - s['entry']) * 0.55:.4g}.")

    def _after_cabins(self, trade: Trade) -> None:
        self._tally(trade)
        if len([s for s in trade.stages if s.kind == "cabin" and s.verdict]) < 5:
            return
        if trade.votes_for >= 5:
            # unanimous board: the ticket clears straight to the entry gate
            trade.exec_note = ("Unanimous council — all five cabins approved. The ticket clears "
                               "straight to the entry gate; no executive review was needed.")
            self.emit("council_unanimous", trade=dict(id=trade.id, votes_for=trade.votes_for))
            self._finalize(trade, accepted=True)
            self._walk_out(trade, "entry")
            return
        if trade.votes_for <= 2:
            trade.outcome = "rejected"
            trade.exec_note = (f"Council veto: {trade.votes_for}/5 cabins approved. "
                               f"Ticket exits without reaching the executive chamber.")
            self.emit("council_veto", trade=dict(id=trade.id, votes_for=trade.votes_for,
                                                 votes_against=trade.votes_against))
            self._finalize(trade, accepted=False)
            self._walk_out(trade, "exit")
            return
        w = self.walkers.get(f"W-{trade.id}")
        if w:
            trade.state = TradeState.TO_EXECUTIVE.value
            self._route(w, "exec_stand")
            self.emit("trade_escalated", trade=dict(id=trade.id, votes_for=trade.votes_for,
                                                    votes_against=trade.votes_against))

    async def _run_executive(self, trade: Trade) -> None:
        ceo = self.council.by_id.get("ceo")
        prior = [s.verdict for s in trade.stages if s.verdict]
        w = self.walkers.get(f"W-{trade.id}")
        if ceo is None or not prior:
            self._finalize(trade, accepted=trade.votes_for >= 3)
            if w:
                w.pause_left = 0.5
            return
        stage = Stage(id=f"{trade.id}-EXEC", kind="executive", cabin_index=0,
                      judge_id=ceo.id, judge_name=ceo.name, stage_index=len(trade.stages))
        trade.stages.append(stage)
        stage.state = "hearing"
        stage.started_at = time.time()
        try:
            verdict = await self.council.executive(trade, prior, pace_s=1.2,
                                                   market=self._market_note(trade.symbol))
        except Exception as exc:
            verdict = Verdict_(judge_id=ceo.id, judge_name=ceo.name, verdict="reject",
                               confidence=0.4, score=-0.2, engine="error",
                               reasoning=f"{ceo.name} could not rule ({exc}); capital is not deployed.")
        await asyncio.sleep(1.6)
        stage.verdict = verdict
        stage.state = "voted"
        stage.ended_at = time.time()
        stage.transcript = [
            dict(kind="brief", seat_id="hunter", name="DROSOPHILA",
                 text=(f"Executive summary for {trade.id}: {trade.votes_for}/5 cabinets approved "
                       f"(mean confidence {trade.avg_confidence:.2f}). Cabin record: "
                       + " · ".join(f"{s.judge_name}={s.verdict.verdict if s.verdict else '?'}"
                                    for s in trade.stages[:-1])),
                 ts=time.time()),
            dict(kind="ruling", seat_id=ceo.id, name=ceo.name, verdict=verdict.verdict,
                 confidence=round(verdict.confidence, 2),
                 text=f"[{verdict.verdict.upper()}] {verdict.reasoning}", ts=time.time(),
                 points=verdict.key_points, risks=verdict.risks, engine=verdict.engine,
                 model=verdict.model),
        ]
        accepted = verdict.verdict == "approve"
        trade.exec_note = (verdict.key_points[-1] if verdict.key_points else verdict.reasoning[:200])
        self.emit("exec_ruling", trade=dict(id=trade.id, symbol=trade.symbol),
                  verdict=verdict.verdict, confidence=round(verdict.confidence, 2),
                  reasoning=verdict.reasoning[:400])
        if w:
            w.pause_left = 0.5
        self._finalize(trade, accepted=accepted)

    # --------------------------------------------------------------- desks
    def desk_context(self, seat_id: Optional[str] = None) -> dict:
        """Live context every desk answers from: book, tape, its own rulings."""
        import time as _time
        now = _time.time()
        cache = getattr(self, "_desk_ctx_cache", None)
        if cache and now - cache[0] < 4.0:
            markets = cache[1]
        else:
            from ..brain.features import compute_metrics
            snap = {row["symbol"]: row for row in self.feed.snapshot()}
            markets = []
            for sym, row in snap.items():
                m = compute_metrics(self.feed.tickers.get(sym))
                if m:
                    tc = 0.62 * math.tanh(m.get("slope21", 0.0) * 120.0) + \
                         0.38 * math.tanh(m.get("slope50", 0.0) * 60.0)
                    row["features"] = dict(trend_composite=round(tc, 3),
                                           efficiency=round(m.get("efficiency", 0.0), 3),
                                           rsi=round(m.get("rsi", 50.0), 1),
                                           atr_pct=round(m.get("atr_pct", 0.0), 5),
                                           atr_rank=round(m.get("atr_rank", 0.5), 3))
                markets.append(row)
            self._desk_ctx_cache = (now, markets)
        recent = []
        for t in sorted(self.trades.values(), key=lambda x: x.created_at, reverse=True)[:24]:
            recent.append(dict(ticket=t.id, symbol=t.symbol, asset_class=t.asset_class,
                               direction=t.direction, outcome=t.outcome, state=t.state,
                               votes_for=t.votes_for, votes_against=t.votes_against,
                               pnl_r=t.pnl_r, cf_r=t.cf_r, label=t.label,
                               verdicts=[dict(judge=st.judge_name,
                                              judge_id=st.judge_id,
                                              verdict=(st.verdict.verdict if st.verdict else None),
                                              confidence=round(st.verdict.confidence, 2)
                                              if st.verdict else None,
                                              reasoning=(st.verdict.reasoning[:260]
                                                         if st.verdict else ""))
                                         for st in t.stages if st.verdict]))
        own = []
        if seat_id:
            for t in sorted(self.trades.values(), key=lambda x: x.created_at, reverse=True):
                for st in t.stages:
                    if st.verdict and st.judge_id == seat_id:
                        own.append(dict(ticket=t.id, symbol=t.symbol, direction=t.direction,
                                        verdict=st.verdict.verdict,
                                        confidence=round(st.verdict.confidence, 2),
                                        reasoning=st.verdict.reasoning,
                                        key_points=list(st.verdict.key_points or []),
                                        risks=list(st.verdict.risks or []),
                                        stop_loss=(t.signal or {}).get("stop_loss"),
                                        take_profit=(t.signal or {}).get("take_profit"),
                                        entry=(t.signal or {}).get("entry"),
                                        outcome=t.outcome, pnl_r=t.pnl_r, ts=st.ended_at))
                if len(own) >= 14:
                    break
        opinions = self.seat_opinions(seat_id) if seat_id else []
        return dict(stats=dict(self.stats), markets=markets[:48], recent=recent, own=own,
                    opinions=opinions,
                    lessons=[dict(l) for l in self.playbook.lessons[-6:]],
                    seats=[s.dict() for s in self.council.seats])

    def seat_opinions(self, seat_id: str, limit: int = 6) -> List[dict]:
        """Score the freshest tickets through one desk's *own* model.

        Every desk therefore always has a reasoned opinion on the live tickets,
        even for tickets that have not physically reached its cabin yet — the
        numbers it would have used are the same ones the floor is trading.
        """
        seat = self.council.by_id.get(seat_id)
        if seat is None:
            return []
        out: List[dict] = []
        recent = sorted(self.trades.values(), key=lambda x: x.created_at, reverse=True)[:limit * 2]
        for t in recent:
            try:
                from ..agents.schemas import Signal
                from ..llm.analyst import StageContext, evaluate as builtin_evaluate
                sig = Signal(**{k: v for k, v in (t.signal or {}).items()
                                if k in Signal.__dataclass_fields__})
                ctx = StageContext(sig, history=[], playbook=self.playbook.lookup(sig),
                                   desk_name=seat.name)
                v = builtin_evaluate(seat, ctx)
                out.append(dict(ticket=t.id, symbol=t.symbol, direction=t.direction,
                                state=t.state, outcome=t.outcome, entry=sig.entry,
                                stop_loss=sig.stop_loss, take_profit=sig.take_profit, rr=sig.rr,
                                verdict=v.get("verdict"), confidence=round(float(v.get("confidence", 0.0)), 3),
                                reasoning=v.get("reasoning", ""),
                                key_points=list(v.get("key_points") or [])[:3],
                                risks=list(v.get("risks") or [])[:3],
                                expectancy=v.get("expectancy"), live_read=True))
            except Exception:
                continue
            if len(out) >= limit:
                break
        return out

    async def ask_desk(self, seat_id: str, question: str,
                       trade_id: Optional[str] = None) -> dict:
        """Operator asks any desk anything — always comes back with an answer."""
        trade = self.trades.get(trade_id) if trade_id else None
        ctx = self.desk_context(seat_id)
        self.emit("desk_chat", trade=dict(seat=seat_id, question=question[:160]))
        return await self.council.ask_any(seat_id, question, context=ctx, trade=trade)

    def seat_rulings(self) -> dict:
        """Most recent verdict *and reason* per desk.

        A desk that has not physically heard a ticket yet still has a reasoned
        opinion: its own model scored the freshest tickets against the same tape,
        so the answer to "why would you pass or reject this trade?" is never empty.
        """
        out: Dict[str, dict] = {}
        for t in sorted(self.trades.values(), key=lambda x: x.created_at, reverse=True):
            for st in t.stages:
                if not st.verdict or st.judge_id in out:
                    continue
                out[st.judge_id] = dict(ticket=t.id, symbol=t.symbol, direction=t.direction,
                                        verdict=st.verdict.verdict,
                                        confidence=round(st.verdict.confidence, 2),
                                        reasoning=st.verdict.reasoning,
                                        key_points=list(st.verdict.key_points or [])[:3],
                                        risks=list(st.verdict.risks or [])[:3],
                                        pnl_r=t.pnl_r, outcome=t.outcome, ts=st.ended_at,
                                        live_read=False)
        for seat in self.council.seats:
            if seat.id in out:
                continue
            for row in self.seat_opinions(seat.id, limit=1):
                out[seat.id] = row
                break
        return out

    # ------------------------------------------------------------- finalize
    def _finalize(self, trade: Trade, accepted: bool, manual: bool = False) -> None:
        if trade.finalized_at is not None:
            return
        trade.outcome = "accepted" if accepted else "rejected"
        trade.finalized_at = time.time()
        self._tally(trade)
        if accepted:
            self.stats["accepted"] += 1
        else:
            self.stats["rejected"] += 1
        if self.settings.auto_trade_eval:
            self.pending_outcomes[trade.id] = dict(
                entry=trade.signal["entry"], sl=trade.signal["stop_loss"],
                tp=trade.signal["take_profit"], direction=trade.direction,
                symbol=trade.symbol, deadline=self.clock + self.settings.outcome_horizon_s,
                accepted=accepted,
                risk=max(abs(trade.signal["entry"] - trade.signal["stop_loss"]), 1e-9))
        if manual:
            trade.manual = True
        self.emit("trade_finalized", trade=dict(id=trade.id, symbol=trade.symbol,
                                                accepted=accepted, votes_for=trade.votes_for,
                                                votes_against=trade.votes_against, manual=manual))
        if accepted:
            self._auto_place(trade)

    def _walk_out(self, trade: Trade, gate: str) -> None:
        w = self.walkers.get(f"W-{trade.id}")
        if w is None:
            return
        trade.state = TradeState.EXITING.value
        node_out = "entry_outside" if gate == "entry" else "exit_outside"
        self._route(w, node_out)
        # ensure the route actually uses the gate node (so bodies pass through the doorway)
        gate_node = self.plan.nodes.get("entry_gate" if gate == "entry" else "exit_gate")
        if gate_node:
            path = self.nav.find_path((w.x, w.z), gate_node) + \
                self.nav.find_path(gate_node, self.plan.nodes[node_out])[1:]
            w.set_path(path)
        w.carry = True
        self.emit("trade_exiting", trade=dict(id=trade.id, gate=gate, outcome=trade.outcome))

    # ------------------------------------------------------------- outcomes
    def _outcome_tick(self, dt: float) -> None:
        if not self.pending_outcomes:
            return
        for t_id, p in list(self.pending_outcomes.items()):
            trade = self.trades.get(t_id)
            if trade is None:
                self.pending_outcomes.pop(t_id, None)
                continue
            price = self.feed.tickers[p["symbol"]].last_price or p["entry"]
            risk = p["risk"]
            r = ((price - p["entry"]) if p["direction"] == "long" else (p["entry"] - price)) / risk
            hit_tp = (r >= (p["tp"] - p["entry"]) / risk * (1 if p["direction"] == "long" else -1)) \
                if p["direction"] == "long" else (r >= (p["entry"] - p["tp"]) / risk)
            if p["direction"] == "long":
                hit_sl = price <= p["sl"]
                hit_tp = price >= p["tp"]
            else:
                hit_sl = price >= p["sl"]
                hit_tp = price <= p["tp"]
            done = hit_sl or hit_tp or self.clock >= p["deadline"]
            if not done:
                continue
            pnl_r = r if not hit_sl else -1.0
            if hit_tp:
                pnl_r = abs(p["tp"] - p["entry"]) / risk
            self.pending_outcomes.pop(t_id, None)
            self._record_outcome(trade, pnl_r, p["accepted"])

    def _record_outcome(self, trade: Trade, pnl_r: float, accepted: bool) -> None:
        if accepted:
            trade.pnl_r = round(pnl_r, 2)
        else:
            trade.cf_r = round(pnl_r, 2)          # what the veto actually saved/cost
        signal = Signal(**{k: v for k, v in trade.signal.items()
                           if k in Signal.__dataclass_fields__})
        res = self.playbook.record(signal, accepted=accepted, pnl_r=pnl_r)
        # the fly learns from what the market actually did with its strike
        reward = math.tanh(pnl_r * 1.3) if accepted else math.tanh(-pnl_r * 0.5)
        kc = None
        self.brain.reinforce(reward)
        if accepted:
            self.stats["wins" if pnl_r > 0 else "losses"] += 1
            self.stats["pnl_r"] = round(self.stats["pnl_r"] + pnl_r, 2)
        outcome = Outcome(trade_id=trade.id, symbol=trade.symbol, accepted=accepted,
                          votes_for=trade.votes_for, votes_against=trade.votes_against,
                          avg_confidence=trade.avg_confidence, eval_pnl_r=round(pnl_r, 2),
                          note=(f"{'Filled' if accepted else 'Vetoed'} · realised {pnl_r:+.2f}R · "
                                f"bucket {res['key']}"))
        self.outcomes.append(outcome)
        self.outcomes = self.outcomes[-200:]
        self.emit("outcome", trade=dict(id=trade.id, symbol=trade.symbol, pnl_r=round(pnl_r, 2),
                                        accepted=accepted))
        if abs(pnl_r) > 1.2:
            self.playbook.add_lesson(
                f"{trade.symbol} {'filled' if accepted else 'vetoed'} for {pnl_r:+.2f}R — "
                f"bucket {res['key']} now at "
                f"{(res.get('hit_rate') or 0)*100:.0f}% over {res.get('sample',0)} samples.",
                tags=[trade.asset_class, "outcome"], source="outcome")

    # ------------------------------------------------------------------ fly
    def _fly_tick(self, dt: float) -> None:
        loop = getattr(self.plan, "fly_loop", [])
        self.scanner.wander(dt, loop)
        if self._fly_dive_left > 0:
            self._fly_dive_left -= dt
            if self._fly_target:
                tx, tz = self._fly_target
                pos = self.scanner.agent.pos
                k = min(1.0, dt * 2.4)
                pos["x"] += (tx - pos["x"]) * k
                pos["z"] += (tz - pos["z"]) * k
                pos["y"] += (3.2 - pos["y"]) * k

    def in_flight(self) -> int:
        return sum(1 for t in self.trades.values() if t.state != TradeState.EXITED.value)

    async def _scan_loop(self) -> None:
        while self._running:
            await asyncio.sleep(max(0.25, self.settings.scan_interval))
            if self.settings.paused:
                continue
            try:
                await self._scan_once()
            except Exception as exc:      # never let one bad tick kill the hunt
                self.loop_errors = getattr(self, "loop_errors", 0) + 1
                self.last_error = f"scan: {type(exc).__name__}: {exc}"
                continue

    async def _scan_once(self) -> None:
        if self.in_flight() >= self.settings.max_trades_in_pipe:
            return        # floor is full: hold the signals rather than burn cooldowns
        # keep the scanner in sync with the operator's market selection
        self.scanner.strike_score = self.settings.strike_score
        self.scanner.cooldown_s = self.settings.cooldown_s
        self.scanner.per_tick = self.settings.scan_batch
        self.scanner.min_efficiency = self.settings.min_efficiency
        self.scanner.min_trend = self.settings.min_trend
        self.scanner.sl_atr = self.settings.sl_atr
        self.scanner.tp_atr = self.settings.tp_atr
        for signal in self.scanner.scan(self.settings.enabled_symbols, now=self.clock):
            if self.in_flight() >= self.settings.max_trades_in_pipe:
                break
            if self._spawn_trade(signal) is None:
                self.scanner.funnel["capped"] += 1

    async def _debate_loop(self) -> None:
        while self._running:
            await asyncio.sleep(max(3.0, 9.0 / max(self.settings.speed, 0.15)))
            if self.settings.paused:
                continue
            try:
                await self._debate_once()
            except Exception as exc:
                self.loop_errors = getattr(self, "loop_errors", 0) + 1
                self.last_error = f"debate: {type(exc).__name__}: {exc}"
                continue

    async def _debate_once(self) -> None:
        ctx = dict(lessons=self.playbook.lessons[-6:],
                   buckets=self.playbook.snapshot()["buckets"][:6],
                   recent_trades=[t.dict() for t in list(self.trades.values())[-6:]],
                   markets=self.feed.snapshot(self.settings.enabled_symbols[:8]),
                   topic=self._debate_topic())
        msg = self.council.debate_turn(ctx)
        self.emit("debate", message=msg)

    def _debate_topic(self) -> str:
        recent = [t for t in self.trades.values() if t.finalized_at]
        recent.sort(key=lambda t: t.finalized_at or 0)
        if recent:
            t = recent[-1]
            return f"{t.id} ({t.symbol} {t.direction}) closing {t.outcome}"
        spots = self.feed.snapshot(self.settings.enabled_symbols[:4])
        if spots:
            m = max(spots, key=lambda s: abs(s.get("change_pct", 0)))
            return f"{m['symbol']} moving {m['change_pct']:+.2f}%"
        return "positioning into the next session"

    async def _live_loop(self) -> None:
        """Merge real venue prices into the tape when the internet allows it."""
        from ..market.live import poll_symbols
        while self._running:
            syms = [s for s in self.settings.enabled_symbols
                    if s in UNIVERSE][: max(1, self.settings.live_symbols_max)]
            ok, err, count = await poll_symbols(self.feed, syms)
            self.live_status = dict(enabled=True, ok=ok, updated=time.time(), error=err,
                                    symbols=syms[:count], count=count)
            self.stats["live_feed"] = ok
            await asyncio.sleep(20.0)

    # ------------------------------------------------------------------ npcs
    def _spawn_npcs(self) -> None:
        homes = ["desk_14_stand", "desk_21_stand", "desk_28_stand", "desk_6_stand", "desk_11_stand",
                 "desk_18_stand", "desk_25_stand", "desk_32_stand", "desk_35_stand", "desk_40_stand",
                 "desk_3_stand", "desk_9_stand", "desk_16_stand", "desk_23_stand"]
        roles = ["SENIOR TRADER", "EXECUTION", "RISK OFFICER", "QUANT ANALYST", "SALES TRADER",
                 "PORTFOLIO MANAGER", "COMPLIANCE", "MARKET MAKER"]
        for i in range(self.settings.ambient_traders):
            home = homes[i % len(homes)]
            xz = self.nav.free_at(*self.plan.nodes.get(home, (0.0, 0.0)))
            book = self.settings.enabled_symbols or ["EURUSD"]
            symbol = book[(i * 7 + self.rng.randrange(len(book))) % len(book)]
            w = Walker(id=f"NPC-{i:02d}", kind="npc", x=xz[0], z=xz[1], speed=WALK_SPEED * 0.86,
                       carry=self.rng.random() < 0.7, label=symbol,
                       sub=f"{roles[i % len(roles)]} · {self.rng.choice(['TIER 1','TIER 2','RISK','OPS'])}",
                       accent="#cbd5e1", home=home)
            w.set_path([xz])
            self.walkers[w.id] = w
            self.npcs.append(w)
            self._npc_pick_destination(w)

    def _npc_pick_destination(self, w: Walker) -> None:
        spots = ["desk_14_stand", "desk_21_stand", "desk_28_stand", "desk_35_stand",
                 "concourse_lobby", "lobby_center", "vault_door", "debate_outside",
                 "cabin_1_outside", "cabin_3_outside", "cabin_5_outside", "pit_north_gate",
                 "water_cooler" if "water_cooler" in self.plan.nodes else "lobby_center"]
        if w.pause_left > 0:
            return
        spot = self.rng.choice(spots)
        target = self.plan.nodes.get(spot)
        if target is None:
            return
        if self.rng.random() < 0.35:
            self._route(w, w.home or "lobby_center")
        else:
            self._route_to(w, target)

    def _npc_tick(self, dt: float) -> None:
        for w in self.npcs:
            if w.arrived() and w.pause_left <= 0:
                self._npc_pick_destination(w)

    # ------------------------------------------------------------- utilities
    def _market_note(self, symbol: str) -> dict:
        t = self.feed.tickers.get(symbol)
        if t is None or not t.close:
            return {}
        closes = list(t.close)[-6:]
        return dict(symbol=symbol, last=round(closes[-1], 6),
                    change_pct=round((closes[-1] / closes[0] - 1) * 100, 3) if closes[0] else 0.0,
                    bars=len(t.close))

    def emit(self, kind: str, **payload: Any) -> None:
        self.events.append(dict(kind=kind, ts=time.time(), clock=round(self.clock, 2), **payload))
        if len(self.events) > 700:
            self.events = self.events[-500:]

    def drain_events(self, limit: int = 120) -> List[dict]:
        out = self.events[-limit:]
        self.events = []
        return out

    # ---------------------------------------------------------------- control
    def force_strike(self, symbol: Optional[str] = None) -> Optional[Trade]:
        syms = [symbol] if symbol else self.settings.enabled_symbols
        for s in syms[:40]:
            sig = self.scanner.evaluate(s, now=self.clock)
            if sig is None:
                t = self.feed.tickers.get(s)
                from ..brain.features import (build_signal_levels, compute_metrics,
                                              encode_glomeruli, strategy_bias, trend_composite)
                m = compute_metrics(t) if t else None
                if not m:
                    continue
                m["spread_ratio"] = UNIVERSE[s].spread / max(m["price"], 1e-9)
                bias, _ = strategy_bias(m)
                tc = trend_composite(m)
                direction = "long" if tc >= 0 else "short"
                levels = build_signal_levels(m, direction, sl_atr=self.settings.sl_atr,
                                             tp_atr=self.settings.tp_atr)
                sig = Signal(symbol=s, asset_class=UNIVERSE[s].asset_class, direction=direction,
                             score=0.5, entry=levels["entry"], stop_loss=levels["stop_loss"],
                             take_profit=levels["take_profit"], atr=m["atr"], horizon="intraday",
                             features={k: round(float(v), 6) for k, v in m.items()},
                             neural=dict(forced=True))
            tr = self._spawn_trade(sig)
            if tr:
                return tr
        return None

    def apply_settings(self, patch: dict) -> Settings:
        old_syms = list(self.settings.enabled_symbols)
        self.settings.apply_patch(patch)
        if list(self.settings.enabled_symbols) != old_syms:
            # add tickers for anything newly selected
            for s in self.settings.enabled_symbols:
                if s not in self.feed.tickers and s in UNIVERSE:
                    from ..brain.features import Ticker
                    from ..market.feed import InstrumentState
                    st = InstrumentState(UNIVERSE[s], random.Random(hash(s) % 10**6))
                    self.feed.states[s] = st
                    t = Ticker(s)
                    self.feed._seed_history(UNIVERSE[s], t, 300)
                    self.feed.tickers[s] = t
            self.feed.symbols = [s for s in self.settings.enabled_symbols if s in self.feed.tickers]
        self.council.seats = self.settings.to_seats()
        self.council.by_id = {s.id: s for s in self.council.seats}
        self.settings.save()
        return self.settings

    def reset(self) -> None:
        self.trades.clear()
        self.walkers.clear()
        self.events.clear()
        self.desk_owner.clear()
        self.free_desks = [d.index for d in self.plan.desks]
        self.rng.shuffle(self.free_desks)
        self.npcs.clear()
        self.broker = self._make_broker()
        self._spawn_npcs()
        self.stats.update(spawned=0, accepted=0, rejected=0, exited=0, wins=0, losses=0, pnl_r=0.0)

    # -------------------------------------------------------------- snapshot
    def walker_payload(self) -> List[dict]:
        out = []
        for w in self.walkers.values():
            if w.dead:
                continue
            trade = self.trades.get(w.trade_id or "")
            label = w.label
            sub = w.sub
            if trade is not None:
                label = f"{trade.id} · {trade.symbol}"
                sub = f"{trade.direction.upper()} · {trade.asset_class} · {trade.state.replace('_',' ')}"
            out.append(dict(id=w.id, kind=w.kind, x=round(w.x, 3), z=round(w.z, 3),
                            yaw=round(w.yaw, 3), seated=w.seated, carrying=w.carry,
                            stride=round(w.stride, 2), label=label, sub=sub, accent=w.accent,
                            trade_id=w.trade_id, state=trade.state if trade else "npc",
                            confidence=round(trade.confidence, 2) if trade else 0.0,
                            trail=[list(p) for p in w.trail[-24:]]))
        return out

    def snapshot(self, full: bool = True) -> dict:
        trades = sorted(self.trades.values(), key=lambda t: t.created_at, reverse=True)
        counts = {}
        for t in self.trades.values():
            counts[t.state] = counts.get(t.state, 0) + 1
        return dict(
            clock=round(self.clock, 2), speed=self.settings.speed, paused=self.settings.paused,
            stats=self.stats,
            fly=self.scanner.snapshot(),
            walkers=self.walker_payload(),
            trades=[t.dict() for t in trades[:60]],
            counts=counts,
            debate=self.council.debate_snapshot(48),
            playbook=self.playbook.snapshot(),
            outcomes=[o.dict() for o in self.outcomes[-24:]],
            seats=[s.dict() for s in self.council.seats],
            live=self.live_status,
            enabled=self.settings.enabled_symbols,
            markets=self.feed.snapshot(self.settings.enabled_symbols[:24]) if full else [],
            nav=dict(cell=self.nav.cell, cols=self.nav.cols, rows=self.nav.rows),
        )

    def trade_detail(self, trade_id: str) -> Optional[dict]:
        t = self.trades.get(trade_id)
        if t is None:
            return None
        d = t.dict(with_transcript=True)
        d["chat"] = self.council.chat_log.get(trade_id, [])
        return d
