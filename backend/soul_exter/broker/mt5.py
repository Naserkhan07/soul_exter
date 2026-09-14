"""Paper + MetaTrader 5 execution adapters."""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# rough contract sizes so a paper fill reports a realistic notional
CONTRACTS = {"forex": 100_000.0, "indices": 10.0, "futures": 50.0, "stocks": 1.0,
             "crypto": 1.0, "options": 100.0}


def contract_size(symbol: str, asset_class: str = "forex") -> float:
    if asset_class == "forex" or (len(symbol) == 6 and symbol.isalpha()):
        return 100_000.0
    return CONTRACTS.get(asset_class, 1.0)


@dataclass
class OrderResult:
    ok: bool
    mode: str                       # paper | mt5
    message: str
    ticket: Optional[str] = None
    price: Optional[float] = None
    lots: float = 0.0
    pnl_usd: float = 0.0
    pnl_r: float = 0.0
    detail: Dict[str, Any] = field(default_factory=dict)

    def dict(self) -> dict:
        return dict(ok=self.ok, mode=self.mode, message=self.message, ticket=self.ticket,
                    price=self.price, lots=self.lots, pnl_usd=round(self.pnl_usd, 2),
                    pnl_r=round(self.pnl_r, 3), detail=self.detail)


class Broker:
    """Common interface."""

    mode = "paper"

    def status(self) -> dict:
        raise NotImplementedError

    def place(self, trade: dict, lots: float) -> OrderResult:
        raise NotImplementedError

    def book(self, trade: dict, lots: float = 0.0) -> OrderResult:
        raise NotImplementedError

    def open_positions(self, prices: Optional[Dict[str, float]] = None) -> List[dict]:
        """Live positions at the venue, so the operator can *see* what is working."""
        raise NotImplementedError

    def diagnose(self, probe_symbols: Optional[List[str]] = None) -> List[dict]:
        """Step-by-step readiness check, rendered as a checklist in the UI."""
        return []


class PaperBroker(Broker):
    mode = "paper"

    def __init__(self) -> None:
        self.positions: Dict[str, dict] = {}
        self.history: List[dict] = []
        self.reason = "paper mode — no venue orders are transmitted (set Broker to MT5 to trade live)"

    def open_positions(self, prices: Optional[Dict[str, float]] = None) -> List[dict]:
        prices = prices or {}
        out = []
        for pid, pos in self.positions.items():
            price = float(prices.get(pos["symbol"], pos["entry"]) or pos["entry"])
            sgn = 1.0 if pos["direction"] == "long" else -1.0
            out.append(dict(ticket=f"PAPER-{pid}", trade_id=pid, mode="paper",
                            symbol=pos["symbol"], direction=pos["direction"],
                            lots=pos["lots"], entry=pos["entry"], price=price,
                            pnl_usd=(price - pos["entry"]) * sgn * pos["lots"] * pos["contract"],
                            opened=pos["opened"]))
        return out

    def status(self) -> dict:
        return dict(mode="paper", connected=False, message=self.reason,
                    positions=len(self.positions), closed=len(self.history),
                    account=None)

    def diagnose(self, probe_symbols: Optional[List[str]] = None) -> List[dict]:
        return [dict(step="routing mode", ok=True,
                     detail="paper broker — fills are simulated on this host. "
                            "Choose mt5 (terminal on this machine) or mt5-bridge "
                            "(terminal on your PC) to trade a real account."),
                dict(step="credentials", ok=True,
                     detail="not needed in paper mode")]

    def place(self, trade: dict, lots: float) -> OrderResult:
        entry = float(trade.get("entry") or 0.0)
        self.positions[trade["id"]] = dict(
            id=trade["id"], symbol=trade["symbol"], direction=trade["direction"],
            entry=entry, lots=lots, opened=time.time(),
            contract=contract_size(trade["symbol"], trade.get("asset_class", "forex")))
        return OrderResult(True, "paper", f"paper fill @ {entry:.5g} ({lots} lots)",
                           ticket=f"PAPER-{trade['id']}", price=entry, lots=lots)

    def book(self, trade: dict, lots: float = 0.0) -> OrderResult:
        pos = self.positions.pop(trade["id"], None)
        price = float(trade.get("exit_price") or trade.get("entry") or 0.0)
        entry = float(trade.get("entry") or 0.0)
        size = float((pos or {}).get("lots") or lots or 0.0)
        contract = float((pos or {}).get("contract") or contract_size(
            trade["symbol"], trade.get("asset_class", "forex")))
        sgn = 1.0 if trade.get("direction") == "long" else -1.0
        pnl_usd = (price - entry) * sgn * size * contract
        self.history.append(dict(id=trade["id"], symbol=trade["symbol"], price=price,
                                 lots=size, pnl_usd=pnl_usd, closed=time.time()))
        return OrderResult(True, "paper", f"paper close @ {price:.5g}", ticket=f"PAPER-{trade['id']}",
                           price=price, lots=size, pnl_usd=pnl_usd)


class MT5Broker(Broker):
    """Routes orders to a running MetaTrader 5 terminal."""

    mode = "mt5"

    def __init__(self, login: int = 0, password: str = "", server: str = "",
                 path: str = "", symbol_suffix: str = "", deviation: int = 20) -> None:
        self.login = int(login or 0)
        self.password = password or ""
        self.server = server or ""
        self.path = path or ""
        self.suffix = symbol_suffix or ""
        self.deviation = deviation
        self.connected = False
        self.reason = "not initialised"
        self._mt5 = None
        self.tickets: Dict[str, str] = {}
        self._last_attempt = 0.0
        self.retry_after = 20.0        # do not hammer a missing terminal

    # ---------------------------------------------------------------- connect
    def connect(self, force: bool = False) -> bool:
        now = time.time()
        if not force and self._last_attempt and now - self._last_attempt < self.retry_after:
            return False
        self._last_attempt = now
        try:
            import MetaTrader5 as mt5            # type: ignore
        except Exception as exc:
            self.reason = (f"MetaTrader5 package unavailable ({type(exc).__name__}). "
                           "Install it on the machine running the MT5 terminal: "
                           "pip install MetaTrader5")
            return False
        self._mt5 = mt5
        kwargs: Dict[str, Any] = {}
        if self.path:
            kwargs["path"] = self.path
        if self.login:
            kwargs["login"] = self.login
        if self.password:
            kwargs["password"] = self.password
        if self.server:
            kwargs["server"] = self.server
        try:
            ok = mt5.initialize(**kwargs) if kwargs else mt5.initialize()
            if not ok:
                self.reason = f"initialize failed: {mt5.last_error()}"
                return False
            info = mt5.account_info()
            if info is None:
                self.reason = "logged in but no account_info available"
                return False
            if self.login and int(info.login) != self.login:
                self.reason = (f"terminal is logged into account {info.login}, "
                               f"not the configured {self.login}")
                return False
            self.connected = True
            self.reason = (f"connected · account {info.login} on {info.server} · "
                           f"balance {info.balance:.2f} {info.currency} · "
                           f"{'DEMO' if getattr(info, 'trade_mode', 0) == 0 else 'LIVE'}")
            return True
        except Exception as exc:
            self.reason = f"{type(exc).__name__}: {exc}"
            return False

    def status(self) -> dict:
        if not self.connected:
            self.connect()
        account = None
        if self.connected and self._mt5 is not None:
            try:
                info = self._mt5.account_info()
                account = dict(login=int(info.login), server=info.server,
                               currency=info.currency, balance=round(info.balance, 2),
                               equity=round(info.equity, 2), leverage=info.leverage,
                               demo=(getattr(info, "trade_mode", 0) == 0),
                               name=info.name)
            except Exception:
                account = None
        positions = self.open_positions() if self.connected else []
        return dict(mode="mt5", connected=self.connected, message=self.reason,
                    login=self.login or None, server=self.server or None,
                    symbol_suffix=self.suffix, account=account,
                    positions=len(positions), tickets=dict(self.tickets))

    # ------------------------------------------------------------ diagnostics
    def diagnose(self, probe_symbols: Optional[List[str]] = None) -> List[dict]:
        """Checklist: package → terminal → login → trading → symbols → ticks."""
        out: List[dict] = []
        try:
            import MetaTrader5 as mt5            # type: ignore
            out.append(dict(step="MetaTrader5 package", ok=True,
                            detail=f"imported (build {getattr(mt5, '__version__', '?')})"))
        except Exception as exc:
            out.append(dict(step="MetaTrader5 package", ok=False,
                            detail=f"{type(exc).__name__}: {exc}. Install it on the machine that "
                                   f"runs the terminal: pip install MetaTrader5"))
            out.append(dict(step="everything else", ok=False,
                            detail="cannot continue without the package"))
            return out
        terminal = None
        try:
            terminal = mt5.terminal_info()
        except Exception:
            terminal = None
        if terminal is None:
            self._last_attempt = 0.0
            ok = self.connect(force=True)
            terminal = mt5.terminal_info() if ok else None
        out.append(dict(step="terminal running", ok=terminal is not None,
                        detail=(f"found at {getattr(terminal, 'path', '?')}" if terminal else
                                f"no running terminal for this user ({self.reason}). Start "
                                f"MetaTrader 5, log in, and keep it open.")))
        info = mt5.account_info()
        want = self.login
        match = bool(info) and (not want or int(info.login) == int(want))
        out.append(dict(step="account login", ok=match,
                        detail=(f"logged in as {info.login} on {info.server} · balance "
                                f"{info.balance:.2f} {info.currency} · "
                                f"{'DEMO' if getattr(info, 'trade_mode', 0) == 0 else 'LIVE'}"
                                if info else
                                f"no account_info (configured login {want or 'any'})")))
        if info:
            allowed = bool(getattr(terminal, "trade_allowed", True))
            connected = bool(getattr(terminal, "connected", True))
            out.append(dict(step="trading enabled", ok=allowed and connected,
                            detail=(f"terminal connected={connected}, algo trading "
                                    f"allowed={allowed}. If algo trading is off, enable the "
                                    f"'Algo Trading' button in the terminal toolbar.")))
        symbols = list(probe_symbols or ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"])
        resolved, missing, ticks = [], [], []
        for sym in symbols:
            got = self._resolve(sym)
            if got is None:
                missing.append(sym)
                continue
            resolved.append(got)
            tick = mt5.symbol_info_tick(got)
            if tick and (tick.bid or tick.ask):
                spread = (tick.ask - tick.bid) if (tick.ask and tick.bid) else 0.0
                ticks.append(f"{got} {tick.bid}/{tick.ask} (spread {spread:.5g})")
            else:
                ticks.append(f"{got} — no tick (market closed or symbol not subscribed)")
        out.append(dict(step="symbol mapping", ok=not missing,
                        detail=(f"resolved {', '.join(resolved) or 'nothing'}"
                                + (f" · missing {', '.join(missing)} — set the symbol suffix "
                                   f"(e.g. '.m') to match your broker" if missing else ""))))
        out.append(dict(step="ticks / market open", ok=bool(ticks),
                        detail="; ".join(ticks[:4]) or "no symbols to probe"))
        out.append(dict(step="volume step", ok=True,
                        detail=f"orders will be sent at the configured clip "
                               f"(check the symbol's volume_min/step before sizing up)"))
        self.connected = bool(info) and match
        return out

    # ------------------------------------------------------------------ order
    def _resolve(self, symbol: str) -> Optional[str]:
        """Map an instrument onto a broker symbol (handles suffixes like EURUSD.m)."""
        mt5 = self._mt5
        if mt5 is None:
            return None
        direct = f"{symbol}{self.suffix}"
        if mt5.symbol_info(direct) is not None:
            return direct
        for candidate in (symbol, symbol.replace("-", ""), symbol[:6] + self.suffix):
            if mt5.symbol_info(candidate) is not None:
                return candidate
        return None

    def place(self, trade: dict, lots: float) -> OrderResult:
        if not self.connected and not self.connect():
            return OrderResult(False, "mt5", self.reason)
        mt5 = self._mt5
        symbol = self._resolve(trade["symbol"])
        if symbol is None:
            return OrderResult(False, "mt5",
                               f"broker has no symbol matching {trade['symbol']} "
                               f"(suffix '{self.suffix}')")
        info = mt5.symbol_info(symbol)
        if info is not None and not info.visible:
            mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(False, "mt5", f"no tick for {symbol}")
        long = trade["direction"] == "long"
        price = tick.ask if long else tick.bid
        request = dict(action=mt5.TRADE_ACTION_DEAL, symbol=symbol, volume=float(lots),
                       type=mt5.ORDER_TYPE_BUY if long else mt5.ORDER_TYPE_SELL,
                       price=price, deviation=self.deviation, magic=770001,
                       comment=f"SOUL-EXTER {trade['id']}",
                       type_time=mt5.ORDER_TIME_GTC, type_filling=mt5.ORDER_FILLING_IOC)
        res = mt5.order_send(request)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            err = mt5.last_error()
            return OrderResult(False, "mt5",
                               f"order rejected: retcode {getattr(res, 'retcode', '?')} "
                               f"({getattr(res, 'comment', err)})")
        self.tickets[trade["id"]] = str(res.order)
        return OrderResult(True, "mt5", f"filled {lots} {symbol} @ {res.price}",
                           ticket=str(res.order), price=float(res.price or price), lots=float(lots),
                           detail=dict(symbol=symbol, retcode=res.retcode,
                                       deal=str(getattr(res, "deal", ""))))

    def open_positions(self, prices: Optional[Dict[str, float]] = None) -> List[dict]:
        """Pull the terminal's own position list (magic 770001 / SOUL-EXTER comments)."""
        if not self.connected and not self.connect():
            return []
        mt5 = self._mt5
        try:
            positions = mt5.positions_get() or []
        except Exception:
            return []
        by_ticket = {str(v): k for k, v in self.tickets.items()}
        out = []
        for pos in positions:
            tag = str(getattr(pos, "comment", "") or "")
            trade_id = by_ticket.get(str(pos.ticket))
            if trade_id is None and "SOUL-EXTER" in tag:
                parts = tag.split()
                trade_id = parts[1] if len(parts) > 1 else tag
            if trade_id is None and int(getattr(pos, "magic", 0)) != 770001:
                continue
            direction = "long" if pos.type == mt5.POSITION_TYPE_BUY else "short"
            out.append(dict(ticket=str(pos.ticket), trade_id=trade_id, mode="mt5",
                            symbol=pos.symbol, direction=direction, lots=float(pos.volume),
                            entry=float(pos.price_open), price=float(pos.price_current),
                            sl=float(pos.sl), tp=float(pos.tp), pnl_usd=float(pos.profit),
                            swap=float(getattr(pos, "swap", 0.0)),
                            opened=float(getattr(pos, "time", 0.0))))
        return out

    def deal_history(self, limit: int = 25) -> List[dict]:
        if not self.connected and not self.connect():
            return []
        mt5 = self._mt5
        try:
            import datetime as _dt
            frm = _dt.datetime.now() - _dt.timedelta(days=3)
            deals = mt5.history_deals_get(frm, _dt.datetime.now()) or []
        except Exception:
            return []
        out = []
        for d in list(deals)[-limit:]:
            if int(getattr(d, "magic", 0)) != 770001:
                continue
            out.append(dict(ticket=str(d.ticket), order=str(getattr(d, "order", "")),
                            symbol=d.symbol, volume=float(d.volume), price=float(d.price),
                            profit=float(getattr(d, "profit", 0.0)),
                            comment=str(getattr(d, "comment", "")),
                            time=float(getattr(d, "time", 0.0))))
        return out

    def book(self, trade: dict, lots: float = 0.0) -> OrderResult:
        if not self.connected and not self.connect():
            return OrderResult(False, "mt5", self.reason)
        mt5 = self._mt5
        symbol = self._resolve(trade["symbol"])
        if symbol is None:
            return OrderResult(False, "mt5", f"broker has no symbol matching {trade['symbol']}")
        wanted = str(self.tickets.get(trade["id"], ""))
        positions = mt5.positions_get(symbol=symbol) or []
        target = None
        for pos in positions:
            if wanted and str(pos.ticket) == wanted:
                target = pos
                break
            if not wanted and trade["id"] in (pos.comment or ""):
                target = pos
                break
        if target is None:
            return OrderResult(False, "mt5", f"no open position for {trade['id']} on {symbol}")
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(False, "mt5", f"no tick for {symbol}")
        closing_long = target.type == mt5.POSITION_TYPE_BUY
        request = dict(action=mt5.TRADE_ACTION_DEAL, symbol=symbol, volume=float(target.volume),
                       type=mt5.ORDER_TYPE_SELL if closing_long else mt5.ORDER_TYPE_BUY,
                       position=target.ticket,
                       price=tick.bid if closing_long else tick.ask,
                       deviation=self.deviation, magic=770001,
                       comment=f"SOUL-EXTER close {trade['id']}",
                       type_time=mt5.ORDER_TIME_GTC, type_filling=mt5.ORDER_FILLING_IOC)
        res = mt5.order_send(request)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            err = mt5.last_error()
            return OrderResult(False, "mt5",
                               f"close rejected: retcode {getattr(res, 'retcode', '?')} "
                               f"({getattr(res, 'comment', err)})")
        return OrderResult(True, "mt5", f"closed {target.volume} {symbol} @ {res.price}",
                           ticket=str(target.ticket), price=float(res.price), lots=float(target.volume),
                           pnl_usd=float(getattr(target, "profit", 0.0)))


def get_broker(mode: str = "paper", **kwargs: Any) -> Broker:
    """Build the adapter for the configured mode, falling back to paper."""
    if (mode or "paper").lower() == "mt5":
        broker = MT5Broker(**{k: v for k, v in kwargs.items()
                              if k in ("login", "password", "server", "path",
                                       "symbol_suffix", "deviation")})
        if broker.connect():
            return broker
        paper = PaperBroker()
        paper.reason = f"MT5 unavailable → paper fills. {broker.reason}"
        return paper
    return PaperBroker()
