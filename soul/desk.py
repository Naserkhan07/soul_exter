"""The paper trading desk.

Trades that walk through the ENTRY door become positions here. Position size
comes from the council: the desks' risk budget sets the base size and the
cabins' size multipliers scale it, so a "approve but only half size" verdict
actually means something.

Marked to market on every price tick. Stop and target both exit the position
and emit ``position_closed`` for the UI.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .config import Config
from .models import Position, TradeCandidate, clamp

log = logging.getLogger("soul.desk")


class PaperDesk:
    def __init__(self, cfg: Config, bus) -> None:
        self.cfg = cfg
        self.bus = bus
        self.starting_cash = cfg.starting_cash
        self.cash = cfg.starting_cash
        self.positions: Dict[str, Position] = {}
        self.closed: List[Position] = []
        self.equity_curve: List[Dict[str, float]] = []
        self.session_start = time.time()
        self.blocked: Dict[str, str] = {}     # symbol -> reason we cannot add risk

    # ------------------------------------------------------------------
    # sizing
    # ------------------------------------------------------------------
    def risk_budget(self) -> float:
        """Dollars this ONE trade may risk (per-trade budget)."""
        return self.equity() * self.cfg.risk_per_trade_pct / 100.0

    def session_risk_cap(self) -> float:
        """Dollars of open risk the whole book may carry at once."""
        return self.equity() * self.cfg.max_session_risk_pct / 100.0

    def planned_risk(self) -> float:
        """Dollar risk already committed by open positions."""
        total = 0.0
        for p in self.positions.values():
            total += abs(p.entry - p.stop) * p.qty
        return total

    def equity(self, prices: Optional[Dict[str, float]] = None) -> float:
        """Cash plus unrealised P&L.

        Deliberately margin-style accounting: opening a position does not move
        cash, it only commits risk, and the whole book is marked to market. That
        keeps longs and shorts symmetric (a spot-style "cash converts into an
        asset" model silently breaks shorts).
        """
        eq = self.cash
        for p in self.positions.values():
            price = (prices or {}).get(p.symbol, p.entry)
            eq += p.mark(price)
        return eq

    def gross_exposure(self, prices: Optional[Dict[str, float]] = None) -> float:
        return sum(p.qty * (prices or {}).get(p.symbol, p.entry) for p in self.positions.values())

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def open(self, trade: TradeCandidate, council_result, origin: str = "council") -> Optional[Position]:
        if trade.symbol in {p.symbol for p in self.positions.values()}:
            self.blocked[trade.id] = "already holding this symbol"
            await self.bus.publish("order_blocked", trade_id=trade.id, symbol=trade.symbol,
                                   reason="already holding this symbol")
            return None
        if len(self.positions) >= self.cfg.max_open_positions:
            self.blocked[trade.id] = "max open positions"
            await self.bus.publish("order_blocked", trade_id=trade.id, symbol=trade.symbol,
                                   reason="position limit reached")
            return None

        risk = abs(trade.entry - trade.stop)
        if risk <= 0:
            await self.bus.publish("order_blocked", trade_id=trade.id, symbol=trade.symbol,
                                   reason="zero stop distance")
            return None

        mult = 1.0
        for v in getattr(council_result, "verdicts", []):
            if v.verdict == "APPROVE":
                mult *= clamp(float(v.adjustment.get("size_multiplier", 1.0) or 1.0), 0.0, 1.5)
        if getattr(council_result, "ceo_verdict", None):
            mult *= clamp(float(council_result.ceo_verdict.adjustment.get("size_multiplier", 1.0) or 1.0), 0.0, 1.5)
        mult = clamp(mult, 0.15, 1.0)

        # Dollar risk this trade may take: the per-trade budget scaled by
        # whatever the cabins asked for, capped by what is left of the session
        # risk allowance after the positions already on the book.
        budget = self.risk_budget()
        remaining = self.session_risk_cap() - self.planned_risk()
        if remaining <= 0:
            await self.bus.publish("order_blocked", trade_id=trade.id, symbol=trade.symbol,
                                   reason="risk budget exhausted for this session")
            return None
        size = min(budget * mult, remaining)
        if size < 1.0:
            await self.bus.publish("order_blocked", trade_id=trade.id, symbol=trade.symbol,
                                   reason="position too small after cabin adjustments")
            return None

        qty = size / risk
        notional = qty * trade.entry
        # Exposure cap: a spot desk has no leverage, so the book may never be
        # worth more than equity. This is what actually gates new risk once the
        # first few positions are on.
        headroom = self.equity() * self.cfg.max_leverage - self.gross_exposure()
        if notional > headroom:
            qty = max(0.0, headroom) / trade.entry
            notional = qty * trade.entry
            size = qty * risk
        if qty <= 0 or size < 1.0:
            await self.bus.publish("order_blocked", trade_id=trade.id, symbol=trade.symbol,
                                   reason="gross exposure cap reached")
            return None

        pos = Position(
            trade_id=trade.id, symbol=trade.symbol, side=trade.side,
            entry=trade.entry, stop=trade.stop, target=trade.target,
            size=notional, qty=qty, risk=size,
            confidence=float(getattr(council_result, "confidence", 0.0) or 0.0),
            strategy=trade.strategy,
            reason=((council_result.ceo_verdict.reason if getattr(council_result, "ceo_verdict", None)
                     else "council approved")),
        )
        self.positions[trade.id] = pos
        await self.bus.publish("position_opened", **pos.as_dict(), origin=origin,
                               size_multiplier=round(mult, 3), rr=round(trade.rr, 2),
                               dollar_risk=round(size, 2),
                               approvals=getattr(council_result, "approvals", 0))
        log.info("desk: opened %s %s qty=%.6f @ %.6f (risk $%.2f)", trade.symbol, trade.side, qty, trade.entry, size)
        return pos

    async def mark(self, prices: Dict[str, float]) -> None:
        for pid, p in list(self.positions.items()):
            price = prices.get(p.symbol)
            if price is None:
                continue
            hit_stop = (price <= p.stop) if p.side == "LONG" else (price >= p.stop)
            hit_target = (price >= p.target) if p.side == "LONG" else (price <= p.target)
            if hit_stop or hit_target:
                await self._close(p, p.stop if hit_stop else p.target,
                                  "STOP" if hit_stop else "TARGET")
        self._sample_equity(prices)

    async def _close(self, p: Position, price: float, why: str) -> None:
        pnl = p.mark(price)
        p.status = "CLOSED"
        p.exit_price = price
        p.pnl = pnl
        p.closed_at = time.time()
        self.cash += pnl                # cash only moves on realised P&L
        self.positions.pop(p.trade_id, None)
        self.closed.append(p)
        self.closed = self.closed[-400:]
        await self.bus.publish("position_closed", **p.as_dict(), exit_reason=why,
                               pnl_pct=(pnl / p.size * 100.0) if p.size else 0.0,
                               equity=round(self.equity(), 2))

    async def force_close_all(self, prices: Dict[str, float], why: str = "MANUAL") -> int:
        n = 0
        for pid, p in list(self.positions.items()):
            await self._close(p, prices.get(p.symbol, p.entry), why)
            n += 1
        return n

    def _sample_equity(self, prices: Dict[str, float]) -> None:
        now = time.time()
        if self.equity_curve and now - self.equity_curve[-1]["t"] < 2.0:
            return
        eq = self.equity(prices)
        self.equity_curve.append({"t": now, "equity": round(eq, 2),
                                  "realised": round(eq - self.starting_cash, 2)})
        self.equity_curve = self.equity_curve[-2400:]

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------
    def stats(self, prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        prices = prices or {}
        wins = [p for p in self.closed if p.pnl > 0]
        losses = [p for p in self.closed if p.pnl <= 0]
        realised = sum(p.pnl for p in self.closed)
        equity = self.equity(prices)
        open_pnl = sum(p.mark(prices.get(p.symbol, p.entry)) for p in self.positions.values())
        gross = self.gross_exposure(prices)
        return {
            "starting_cash": round(self.starting_cash, 2),
            "cash": round(self.cash, 2),
            "equity": round(equity, 2),
            "open_pnl": round(open_pnl, 2),
            "realised_pnl": round(realised, 2),
            "return_pct": round((equity / self.starting_cash - 1) * 100.0, 2) if self.starting_cash else 0.0,
            "gross_exposure": round(gross, 2),
            "max_leverage": self.cfg.max_leverage,
            "leverage": round(gross / equity, 2) if equity else 0.0,
            "open_positions": len(self.positions),
            "max_positions": self.cfg.max_open_positions,
            "planned_risk_pct": round(self.planned_risk() / equity * 100.0, 2) if equity else 0.0,
            "risk_budget_pct": self.cfg.risk_per_trade_pct,
            "session_risk_pct": self.cfg.max_session_risk_pct,
            "session_risk_cap": round(self.session_risk_cap(), 2),
            "closed": len(self.closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(self.closed), 3) if self.closed else 0.0,
            "avg_win": round(sum(p.pnl for p in wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(p.pnl for p in losses) / len(losses), 2) if losses else 0.0,
            "best": round(max((p.pnl for p in self.closed), default=0.0), 2),
            "worst": round(min((p.pnl for p in self.closed), default=0.0), 2),
            "session_minutes": round((time.time() - self.session_start) / 60.0, 1),
        }

    def positions_view(self, prices: Dict[str, float]) -> List[Dict[str, Any]]:
        out = []
        for p in self.positions.values():
            price = prices.get(p.symbol, p.entry)
            d = p.as_dict()
            d["price"] = round(price, 8)
            d["pnl"] = round(p.mark(price), 2)
            d["pnl_pct"] = round((p.mark(price) / p.size * 100.0) if p.size else 0.0, 2)
            d["to_stop_pct"] = round(abs(price - p.stop) / price * 100.0, 2)
            d["to_target_pct"] = round(abs(p.target - price) / price * 100.0, 2)
            out.append(d)
        return out

    def closed_view(self, limit: int = 40) -> List[Dict[str, Any]]:
        return [p.as_dict() for p in self.closed[-limit:]][::-1]

    def context(self) -> Dict[str, Any]:
        """What the cabins are told about the book."""
        prices = {p.symbol: 0.0 for p in self.positions.values()}
        s = self.stats(prices)
        return {
            "equity": s["equity"], "cash": s["cash"], "open_pnl": s["open_pnl"],
            "leverage": s["leverage"], "max_leverage": s["max_leverage"],
            "closed": s["closed"], "win_rate": s["win_rate"],
            "realised_pnl": s["realised_pnl"], "gross_exposure": s["gross_exposure"],
            "max_positions": s["max_positions"], "planned_risk_pct": s["planned_risk_pct"],
            "risk_budget_pct": s["risk_budget_pct"],
            "session_risk_pct": s["session_risk_pct"],
            "positions": [{"symbol": p.symbol, "side": p.side,
                           "pnl_pct": 0.0, "trade_id": p.trade_id} for p in self.positions.values()],
        }
