"""Where a trade actually goes: the user's MetaTrader 5 terminal, or paper.

The floor decides; this module executes. Two venues sit behind one interface:

* **MetaTrader 5** — the operator's own terminal (server, login, password).
  Forex goes here. The adapter is written against the real MetaTrader5 API and
  handles the things that actually break live order flow: broker symbol renames
  (``EURUSD`` is ``EURUSD.a`` / ``EURUSDm`` / ``EURUSD.raw`` on many servers),
  volume normalisation to the broker's own lot step, filling-mode fallback
  (IOC -> FOK -> RETURN, the usual cause of retcode 10030), and a close that is
  *verified* against ``positions_get`` instead of assumed to have happened.
* **the paper venue** — the same order book filled off the market feed the floor
  is already streaming, with the same one-click place/close path. It is what
  runs where no terminal exists (this sandbox, Kaggle, tests) and every badge in
  the UI says so rather than pretending.

Credentials live in the environment or in ``artifacts/broker/mt5.json``
(gitignored, 0600). A password is never returned by the API, never logged, never
rendered into a page and never written into the repository.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import universe as book

log = logging.getLogger("soul.broker")

#: classes a venue can hold, and the ones we can actually reach today
FOREX = "forex"
FOREX_LIKE = ("forex", "metals")


class BrokerError(Exception):
    """An order the venue would not take, with a reason the UI can show."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------
@dataclass
class BrokerCreds:
    login: str = ""
    password: str = ""
    server: str = ""
    path: str = ""
    mode: str = "auto"          # auto | mt5 | paper
    bridge: str = ""            # host:port of an mt5linux/RPyC bridge, optional

    def ready(self) -> bool:
        return bool(self.login and self.password and self.server)

    def masked(self) -> Dict[str, Any]:
        """What the API is allowed to say about the credentials."""
        return {
            "login": self.login,
            "server": self.server,
            "path": self.path,
            "mode": self.mode,
            "bridge": self.bridge,
            "has_password": bool(self.password),
            "password": "••••••••" if self.password else "",
        }


class CredStore:
    """Small local store for the terminal login. Never inside the repo tree."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> BrokerCreds:
        data: Dict[str, Any] = {}
        try:
            if self.path.is_file():
                data = json.loads(self.path.read_text())
        except Exception as exc:                            # pragma: no cover
            log.warning("broker store unreadable: %s", exc)
        env = {
            "login": os.environ.get("SOUL_MT5_LOGIN", ""),
            "password": os.environ.get("SOUL_MT5_PASSWORD", ""),
            "server": os.environ.get("SOUL_MT5_SERVER", ""),
            "path": os.environ.get("SOUL_MT5_PATH", ""),
            "mode": os.environ.get("SOUL_BROKER_MODE", ""),
            "bridge": os.environ.get("SOUL_MT5_BRIDGE", ""),
        }
        merged = {k: (v or data.get(k, "")) for k, v in env.items()}
        if not merged["mode"]:
            merged["mode"] = "auto"
        return BrokerCreds(**merged)

    def save(self, creds: BrokerCreds) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"login": creds.login, "password": creds.password, "server": creds.server,
             "path": creds.path, "mode": creds.mode, "bridge": creds.bridge,
             "note": "local terminal login — gitignored, never sent anywhere else"},
            indent=2))
        try:
            os.chmod(self.path, 0o600)
        except Exception:                                   # pragma: no cover
            pass

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------
# contract specs & sizing
# --------------------------------------------------------------------------
@dataclass
class Spec:
    """What one lot/unit of an instrument is worth, for sizing."""

    contract: float = 100_000.0
    pip: float = 0.0001
    pip_value: float = 10.0        # account currency per pip per lot
    volume_min: float = 0.01
    volume_step: float = 0.01
    volume_max: float = 100.0
    digits: int = 5
    unit: str = "lots"
    source: str = "estimate"

    def round_volume(self, volume: float) -> float:
        """Down to the broker's lot step, without float error eating a step."""
        step = self.volume_step or 0.01
        steps = math.floor(max(0.0, volume) / step + 1e-9)
        return round(steps * step, 8)

    def clamp(self, volume: float) -> float:
        v = min(max(volume, self.volume_min), self.volume_max)
        return self.round_volume(v) or self.volume_min


def _split_fx(symbol: str) -> Tuple[str, str]:
    clean = symbol.replace("/", "").replace("_", "").replace("-", "").upper()
    if symbol == "XAU/USD":
        return "XAU", "USD"
    if symbol == "XAG/USD":
        return "XAG", "USD"
    if len(clean) >= 6:
        return clean[:3], clean[3:6]
    return clean[:3], clean[3:] or "USD"


#: Contract sizes for the classes the paper venue can price. Forex is exact
#: (100k units, 10 USD per pip on a USD-quoted pair); the rest are honest
#: approximations used only until a real broker spec arrives for that class.
CONTRACTS: Dict[str, float] = {
    "forex": 100_000.0, "metals": 100.0, "crypto": 1.0, "indices": 1.0,
    "stocks": 1.0, "futures": 1.0, "options": 1.0,
}


#: How to turn one unit of a quote currency into USD, when we can see the rate.
#: ``True`` means the pair is quoted the other way round (USD per unit = 1/price).
QUOTE_LEGS: Dict[str, Tuple[str, bool]] = {
    "JPY": ("USD/JPY", True), "CHF": ("USD/CHF", True), "CAD": ("USD/CAD", True),
    "GBP": ("GBP/USD", False), "EUR": ("EUR/USD", False), "AUD": ("AUD/USD", False),
    "NZD": ("NZD/USD", False),
}


def quote_in_usd(quote: str, rate_of: Optional[Callable[[str], Optional[float]]] = None) -> Optional[float]:
    """USD value of one unit of ``quote``, or None when we cannot see a rate."""
    if quote == "USD":
        return 1.0
    leg = QUOTE_LEGS.get(quote)
    if leg is None or rate_of is None:
        return None
    pair, invert = leg
    price = rate_of(pair)
    if not price:
        return None
    return (1.0 / price) if invert else float(price)


def spec_for(symbol: str, price: float = 0.0, klass: Optional[str] = None,
             rate_of: Optional[Callable[[str], Optional[float]]] = None) -> Spec:
    """Contract facts for one instrument.

    Size = dollars at risk / (stop in pips x value of a pip per lot), so the pip
    value is the number that has to be right. For a pair quoted in USD it is
    just contract x pip; for USD/JPY it is contract x pip / price; for a cross
    it is contract x pip converted at the quote currency's own USD rate — and
    when that rate cannot be read, the estimate says so instead of pretending.
    """
    klass = klass or book.instrument(symbol).klass
    price = float(price or book.instrument(symbol).base or 1.0)
    if klass in FOREX_LIKE:
        base, quote = _split_fx(symbol)
        pip = 0.01 if quote == "JPY" else 0.0001
        if symbol == "XAU/USD":
            pip, contract = 0.01, 100.0
        else:
            contract = 100_000.0
        raw = contract * pip
        rate = quote_in_usd(quote, rate_of)
        if quote == "USD":
            pip_value, source = raw, "standard FX contract"
        elif base == "USD":
            # the pip is paid in the quote currency: convert it at this pair's price
            pip_value, source = (raw / price if price else raw), "standard FX contract"
        elif rate is not None:
            pip_value, source = raw * rate, "standard FX contract, cross converted at the live quote"
        else:
            # a cross with no visible USD leg: the standard major value, labelled
            pip_value, source = 10.0, "estimate — no USD rate visible for " + quote
        return Spec(contract=contract, pip=pip, pip_value=pip_value, digits=5 if pip < 0.005 else 3,
                    volume_min=0.01, volume_step=0.01, volume_max=50.0, unit="lots", source=source)
    if klass == "metals":
        return Spec(contract=100.0, pip=0.01, pip_value=1.0, digits=2, volume_min=0.01,
                    volume_step=0.01, volume_max=200.0, unit="lots", source="estimate")
    # everything else on the paper venue: one unit is one coin / share / contract,
    # sizeable in fractions the way an exchange would let you
    contract = CONTRACTS.get(klass, 1.0)
    pip = max(price * 0.0001, 1e-9)          # one basis point of the price
    return Spec(contract=contract, pip=pip, pip_value=contract * pip,
                digits=6, volume_min=0.0001, volume_step=0.0001, volume_max=1_000_000.0,
                unit="units", source="one unit = one contract/coin, priced off the last")


def lots_for_risk(risk_dollars: float, stop_distance: float, spec: Spec) -> float:
    """Volume such that the stop costs roughly ``risk_dollars``.

    The whole point of a stop is that the loss is known in advance, so size is
    derived from the stop rather than picked: dollars / (stop in pips * value of
    a pip per lot).
    """
    if stop_distance <= 0 or spec.pip <= 0 or spec.pip_value <= 0:
        raise BrokerError("no_stop", "the signal has no stop, so there is no size to take")
    pips = stop_distance / spec.pip
    return spec.round_volume(risk_dollars / (pips * spec.pip_value))


# --------------------------------------------------------------------------
# venue: MetaTrader 5
# --------------------------------------------------------------------------
_SUFFIXES = ("", ".a", "m", ".raw", ".pro", ".ecn", ".std", "c", "#", "_", ".m", "-ECN")


def _load_mt5(creds: BrokerCreds):
    """Import the MetaTrader5 module, or a bridge that speaks the same API.

    Returns ``(module, note)``; ``module`` is None when there is no terminal
    package on this machine at all, which is the normal case on Linux/Kaggle.
    """
    if creds.bridge:
        try:                                                # pragma: no cover
            from mt5linux import MetaTrader5 as MT5          # type: ignore
            host, _, port = creds.bridge.partition(":")
            return MT5(host=host or "localhost", port=int(port or 18812)), f"mt5linux bridge {creds.bridge}"
        except Exception as exc:
            return None, f"bridge unavailable: {exc}"
    try:
        import MetaTrader5 as MT5                            # type: ignore
        return MT5, "MetaTrader5 terminal package"
    except Exception as exc:
        return None, f"no MetaTrader5 package on this machine ({exc.__class__.__name__})"


class Mt5Venue:
    """Live execution against the operator's terminal."""

    name = "mt5"

    def __init__(self, creds: BrokerCreds) -> None:
        self.creds = creds
        self.mt5: Any = None
        self.note = ""
        self.connected = False
        self.last_error = ""
        self._symbols: List[str] = []
        self._symbols_at = 0.0
        self._resolved: Dict[str, str] = {}

    # ---- lifecycle ---------------------------------------------------
    def connect(self) -> bool:
        self.mt5, self.note = _load_mt5(self.creds)
        if self.mt5 is None:
            self.last_error = self.note
            self.connected = False
            return False
        try:
            kwargs: Dict[str, Any] = {"timeout": 20000}
            if self.creds.path:
                kwargs["path"] = self.creds.path
            if self.creds.login:
                kwargs["login"] = int(self.creds.login)
                kwargs["password"] = self.creds.password
                kwargs["server"] = self.creds.server
            ok = self.mt5.initialize(**kwargs)
            if not ok and self.creds.login:
                ok = self.mt5.initialize(**kwargs)           # one retry: cold terminal
            if not ok:
                err = self._last_error()
                self.last_error = f"terminal refused the login: {err}"
                self.connected = False
                return False
            self.connected = True
            self.last_error = ""
            acct = self.mt5.account_info()
            log.info("mt5: connected as %s on %s (%s)", self.creds.login, self.creds.server,
                     getattr(acct, "currency", "?"))
            return True
        except Exception as exc:
            self.last_error = f"{exc.__class__.__name__}: {exc}"
            self.connected = False
            return False

    def disconnect(self) -> None:
        try:
            if self.mt5 is not None:
                self.mt5.shutdown()
        except Exception:                                   # pragma: no cover
            pass
        self.connected = False

    def _last_error(self) -> str:
        try:
            code, msg = self.mt5.last_error()
            return f"[{code}] {msg}"
        except Exception:                                   # pragma: no cover
            return "unknown"

    # ---- symbols -----------------------------------------------------
    def symbols(self) -> List[str]:
        if not self.connected:
            return []
        if self._symbols and time.time() - self._symbols_at < 300:
            return self._symbols
        try:
            found = self.mt5.symbols_get() or []
            self._symbols = [s.name for s in found]
            self._symbols_at = time.time()
        except Exception as exc:                            # pragma: no cover
            log.warning("mt5 symbols_get failed: %s", exc)
        return self._symbols

    def resolve(self, symbol: str) -> str:
        """Map an internal symbol ("EUR/USD") to this broker's own name."""
        if symbol in self._resolved:
            return self._resolved[symbol]
        base = symbol.replace("/", "").replace("_", "").upper()
        have = set(self.symbols())
        candidates = [base + s for s in _SUFFIXES]
        chosen = ""
        for cand in candidates:
            if cand in have:
                chosen = cand
                break
        if not chosen and have:
            near = sorted(s for s in have if s.upper().startswith(base))
            chosen = near[0] if near else ""
        if not chosen:
            chosen = base                     # let the terminal say no, with its reason
        self._resolved[symbol] = chosen
        return chosen

    def spec(self, symbol: str, price: float, klass: Optional[str]) -> Spec:
        base = spec_for(symbol, price, klass)
        if not self.connected:
            return base
        try:
            info = self.mt5.symbol_info(self.resolve(symbol))
            if info is None:
                return base
            tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
            tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
            if tick_value > 0 and tick_size > 0:
                # value of one whole price unit, i.e. what 1.00 of stop costs
                per_unit = tick_value / tick_size
                pip = 0.01 if (klass in FOREX_LIKE and str(symbol).endswith("JPY")) else base.pip
                if klass not in FOREX_LIKE:
                    pip = tick_size
                base = Spec(
                    contract=float(getattr(info, "trade_contract_size", base.contract) or base.contract),
                    pip=pip, pip_value=per_unit * pip,
                    volume_min=float(getattr(info, "volume_min", base.volume_min) or base.volume_min),
                    volume_step=float(getattr(info, "volume_step", base.volume_step) or base.volume_step),
                    volume_max=float(getattr(info, "volume_max", base.volume_max) or base.volume_max),
                    digits=int(getattr(info, "digits", base.digits) or base.digits),
                    unit="lots", source="broker contract spec")
            self.mt5.symbol_select(self.resolve(symbol), True)
        except Exception as exc:                            # pragma: no cover
            log.warning("mt5 spec for %s failed: %s", symbol, exc)
        return base

    def price(self, symbol: str) -> Optional[float]:
        if not self.connected:
            return None
        try:
            tick = self.mt5.symbol_info_tick(self.resolve(symbol))
            if tick is None:
                return None
            bid, ask = float(tick.bid or 0.0), float(tick.ask or 0.0)
            return (bid + ask) / 2 if bid and ask else (ask or bid or None)
        except Exception:                                   # pragma: no cover
            return None

    # ---- orders ------------------------------------------------------
    def _fillings(self) -> List[Any]:
        m = self.mt5
        modes = [getattr(m, "ORDER_FILLING_IOC", None), getattr(m, "ORDER_FILLING_FOK", None),
                 getattr(m, "ORDER_FILLING_RETURN", None)]
        return [x for x in modes if x is not None]

    def place(self, symbol: str, side: str, volume: float, spec: Spec,
              stop: float, target: float, comment: str, magic: int, deviation: int,
              dry: bool = False) -> Dict[str, Any]:
        if not self.connected:
            raise BrokerError("not_connected", self.last_error or "the terminal is not connected")
        m = self.mt5
        name = self.resolve(symbol)
        m.symbol_select(name, True)
        info = m.symbol_info(name)
        if info is None:
            raise BrokerError("symbol_unknown", f"{symbol} is not offered by this broker (tried {name})")
        tick = m.symbol_info_tick(name)
        if tick is None:
            raise BrokerError("no_tick", f"no quote for {name} — market closed or symbol not subscribed")
        is_buy = side.upper() == "LONG"
        price = float(tick.ask if is_buy else tick.bid)
        volume = spec.clamp(volume)
        if volume < spec.volume_min:
            raise BrokerError("volume_too_small",
                              f"{volume} is under the broker minimum of {spec.volume_min} lots")
        digits = int(getattr(info, "digits", spec.digits) or spec.digits)
        req: Dict[str, Any] = {
            "action": m.TRADE_ACTION_DEAL,
            "symbol": name,
            "volume": float(volume),
            "type": m.ORDER_TYPE_BUY if is_buy else m.ORDER_TYPE_SELL,
            "price": round(price, digits),
            "sl": round(float(stop), digits) if stop else 0.0,
            "tp": round(float(target), digits) if target else 0.0,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": comment[:31],
            "type_time": m.ORDER_TIME_GTC,
        }
        if dry:
            return {"dry": True, "request": req, "symbol": name, "price": round(price, digits)}
        last = ""
        for filling in self._fillings():
            req["type_filling"] = filling
            try:
                res = m.order_send(req)
            except Exception as exc:                        # pragma: no cover
                last = f"{exc.__class__.__name__}: {exc}"
                continue
            retcode = int(getattr(res, "retcode", 0) or 0)
            if retcode in (m.TRADE_RETCODE_DONE, m.TRADE_RETCODE_PLACED, 10010):
                return {
                    "ticket": str(getattr(res, "order", "") or getattr(res, "deal", "")),
                    "deal": str(getattr(res, "deal", "") or ""),
                    "symbol": name,
                    "price": float(getattr(res, "price", 0.0) or price),
                    "volume": float(getattr(res, "volume", volume) or volume),
                    "retcode": retcode,
                    "filling": filling,
                    "comment": str(getattr(res, "comment", "") or ""),
                }
            last = f"[{retcode}] {getattr(res, 'comment', '')}"
            if retcode not in (10030, 10004, 10021):        # only filling/requote are worth retrying
                break
        raise BrokerError("rejected", f"{name} order rejected: {last}")

    def close(self, ticket: str, symbol: str, side: str, volume: float,
              deviation: int, magic: int) -> Dict[str, Any]:
        if not self.connected:
            raise BrokerError("not_connected", self.last_error or "the terminal is not connected")
        m = self.mt5
        name = self.resolve(symbol)
        positions = m.positions_get(ticket=int(ticket)) or []
        if not positions:
            raise BrokerError("unknown_ticket", f"no open position with ticket {ticket}")
        pos = positions[0]
        closing_buy = int(getattr(pos, "type", 1)) == 1     # closing a sell is a buy
        tick = m.symbol_info_tick(name)
        if tick is None:
            raise BrokerError("no_tick", f"no quote for {name} to close against")
        price = float(tick.ask if closing_buy else tick.bid)
        info = m.symbol_info(name)
        digits = int(getattr(info, "digits", 5) or 5)
        req: Dict[str, Any] = {
            "action": m.TRADE_ACTION_DEAL,
            "symbol": name,
            "volume": float(getattr(pos, "volume", volume) or volume),
            "position": int(ticket),
            "type": m.ORDER_TYPE_BUY if closing_buy else m.ORDER_TYPE_SELL,
            "price": round(price, digits),
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": "desk close",
            "type_time": m.ORDER_TIME_GTC,
        }
        last = ""
        for filling in self._fillings():
            req["type_filling"] = filling
            try:
                res = m.order_send(req)
            except Exception as exc:                        # pragma: no cover
                last = f"{exc.__class__.__name__}: {exc}"
                continue
            retcode = int(getattr(res, "retcode", 0) or 0)
            if retcode in (m.TRADE_RETCODE_DONE, 10010):
                still = m.positions_get(ticket=int(ticket)) or []
                profit = float(getattr(pos, "profit", 0.0) or 0.0)
                if still:                                   # partial: say what is left
                    return {"ticket": ticket, "price": float(getattr(res, "price", price) or price),
                            "closed": False, "partial": True, "remaining": float(still[0].volume),
                            "profit": profit, "retcode": retcode}
                return {"ticket": ticket, "price": float(getattr(res, "price", price) or price),
                        "closed": True, "profit": profit, "retcode": retcode,
                        "entry": float(getattr(pos, "price_open", 0.0) or 0.0)}
            last = f"[{retcode}] {getattr(res, 'comment', '')}"
            if retcode not in (10030, 10004, 10021):
                break
        raise BrokerError("rejected", f"close of {ticket} rejected: {last}")

    def positions(self) -> List[Dict[str, Any]]:
        if not self.connected:
            return []
        out: List[Dict[str, Any]] = []
        try:
            for p in self.mt5.positions_get() or []:
                out.append({
                    "ticket": str(p.ticket), "symbol_mt5": p.symbol,
                    "side": "LONG" if int(p.type) == 0 else "SHORT",
                    "volume": float(p.volume), "entry": float(p.price_open),
                    "stop": float(p.sl or 0.0), "target": float(p.tp or 0.0),
                    "price": float(p.price_current), "pnl": float(p.profit),
                    "opened_at": float(getattr(p, "time", 0) or 0), "comment": p.comment,
                })
        except Exception as exc:                            # pragma: no cover
            log.warning("mt5 positions_get failed: %s", exc)
        return out

    def account(self) -> Dict[str, Any]:
        if not self.connected:
            return {}
        try:
            a = self.mt5.account_info()
            if a is None:
                return {}
            return {"login": str(getattr(a, "login", "")), "server": str(getattr(a, "server", "")),
                    "currency": str(getattr(a, "currency", "USD")),
                    "balance": round(float(getattr(a, "balance", 0.0) or 0.0), 2),
                    "equity": round(float(getattr(a, "equity", 0.0) or 0.0), 2),
                    "margin_free": round(float(getattr(a, "margin_free", 0.0) or 0.0), 2),
                    "leverage": int(getattr(a, "leverage", 0) or 0),
                    "demo": bool(getattr(a, "trade_mode", 1) == 0) if hasattr(a, "trade_mode") else True,
                    "company": str(getattr(a, "company", ""))}
        except Exception as exc:                            # pragma: no cover
            log.warning("mt5 account_info failed: %s", exc)
            return {}


# --------------------------------------------------------------------------
# venue: paper
# --------------------------------------------------------------------------
class PaperVenue:
    """The same order book, filled off the feed the floor already streams.

    Sizing, stops, targets and P&L behave like a broker's, and every row says
    "paper" so nothing is mistaken for a live fill.
    """

    name = "paper"

    def __init__(self, price_fn: Callable[[str], Optional[float]]) -> None:
        self.price_fn = price_fn
        self.note = "simulated fills off the floor's own market feed"

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        return None

    def resolve(self, symbol: str) -> str:
        return symbol.replace("/", "")

    def spec(self, symbol: str, price: float, klass: Optional[str]) -> Spec:
        # the quote conversion reads the floor's own feed, so a cross is sized
        # with the same rates the council is looking at
        return spec_for(symbol, price, klass, rate_of=self.price_fn)

    def price(self, symbol: str) -> Optional[float]:
        return self.price_fn(symbol)

    def place(self, symbol: str, side: str, volume: float, spec: Spec, stop: float,
              target: float, comment: str, magic: int, deviation: int,
              dry: bool = False) -> Dict[str, Any]:
        price = self.price(symbol)
        if not price:
            raise BrokerError("no_quote", f"no market price for {symbol} yet — try again in a second")
        volume = spec.clamp(volume)
        if volume < spec.volume_min:
            raise BrokerError("volume_too_small",
                              f"{volume} is under the venue minimum of {spec.volume_min}")
        import uuid
        ticket = f"P{uuid.uuid4().hex[:6].upper()}"
        if dry:
            return {"dry": True, "symbol": symbol, "price": price, "volume": volume}
        return {"ticket": ticket, "symbol": symbol, "price": float(price), "volume": volume,
                "retcode": 0, "filling": "sim", "comment": "paper fill"}

    def close(self, ticket: str, symbol: str, side: str, volume: float,
              deviation: int, magic: int) -> Dict[str, Any]:
        price = self.price(symbol)
        if not price:
            raise BrokerError("no_quote", f"no market price for {symbol} to book against")
        return {"ticket": ticket, "price": float(price), "closed": True, "retcode": 0}


# --------------------------------------------------------------------------
# the hub: routing, the order book, one-click placement, auto-trade
# --------------------------------------------------------------------------
class BrokerHub:
    def __init__(self, cfg, bus, price_fn: Callable[[str], Optional[float]]) -> None:
        self.cfg = cfg
        self.bus = bus
        self.store = CredStore(getattr(cfg, "broker_store", "artifacts/broker/mt5.json"))
        self.paper = PaperVenue(price_fn)
        self.creds = self.store.load()
        self.mt5: Optional[Mt5Venue] = None
        self.orders: Dict[str, Dict[str, Any]] = {}      # ticket -> order (open + closed)
        self.order_seq: List[str] = []
        self.last_error = ""
        self.autotrade = {
            "on": bool(getattr(cfg, "autotrade", False)),
            "classes": list(getattr(cfg, "autotrade_classes", [FOREX])),
            "risk_pct": float(getattr(cfg, "broker_risk_pct", 0.5)),
            "max_open": int(getattr(cfg, "broker_max_open", 4)),
            "min_confidence": float(getattr(cfg, "autotrade_min_confidence", 60.0)),
            "placed": 0, "skipped": 0, "last": "",
        }
        self.equity_hint = float(getattr(cfg, "starting_cash", 15000.0))

    # ---- connection --------------------------------------------------
    @property
    def mode(self) -> str:
        return self.creds.mode or "auto"

    @property
    def mt5_live(self) -> bool:
        return bool(self.mt5 and self.mt5.connected)

    def configure(self, payload: Dict[str, Any], save: bool = True) -> Dict[str, Any]:
        """Take the terminal login from the settings panel and try to use it."""
        for key in ("login", "password", "server", "path", "mode", "bridge"):
            if payload.get(key) is not None:
                setattr(self.creds, key, str(payload[key]).strip())
        if self.creds.mode not in ("auto", "mt5", "paper"):
            self.creds.mode = "auto"
        if save and self.creds.ready():
            self.store.save(self.creds)
        return self.connect()

    def connect(self) -> Dict[str, Any]:
        if self.creds.mode == "paper":
            self.last_error = ""
            return self.status()
        if not self.creds.ready():
            self.last_error = "login, password and server are all needed for MetaTrader 5"
            return self.status()
        if self.mt5 is not None:
            self.mt5.disconnect()
        self.mt5 = Mt5Venue(self.creds)
        ok = self.mt5.connect()
        self.last_error = "" if ok else self.mt5.last_error
        if not ok:
            log.warning("mt5 unavailable, staying on the paper venue: %s", self.last_error)
        else:
            self.creds.mode = "mt5"
        return self.status()

    def autoconnect(self) -> None:
        """Called once at boot: use saved credentials if there are any."""
        if self.creds.ready() and self.creds.mode in ("auto", "mt5"):
            self.connect()

    def disconnect(self, forget: bool = False) -> Dict[str, Any]:
        if self.mt5 is not None:
            self.mt5.disconnect()
            self.mt5 = None
        if forget:
            self.creds = BrokerCreds(mode=self.creds.mode, bridge=self.creds.bridge)
            self.store.clear()
        self.last_error = ""
        return self.status()

    # ---- routing -----------------------------------------------------
    def venue_for(self, klass: str) -> str:
        """The destination for this asset class — never a silent substitution.

        A class pinned to the terminal (``SOUL_BROKER_FOREX=mt5``, or the
        operator choosing mode=mt5) stays pinned: if the terminal is not there,
        the order is *refused with a reason* rather than quietly filled on the
        paper venue, because a paper fill reported as a live one is the one bug
        that costs real money.
        """
        wanted = str(getattr(self.cfg, "broker_venues", {}).get(klass, "")).lower()
        if wanted in ("mt5", "paper"):
            return wanted
        if self.creds.mode == "paper":
            return "paper"
        if klass in FOREX_LIKE:
            if self.mt5_live:
                return "mt5"
            return "mt5" if self.creds.mode == "mt5" else "paper"
        return "paper"

    def route_detail(self, klass: str) -> str:
        venue = self.venue_for(klass)
        if venue == "mt5":
            if self.mt5_live:
                return f"MetaTrader 5 · {self.creds.server or 'terminal'} · account {self.creds.login}"
            return (f"MetaTrader 5 {self.creds.server or ''} — terminal not connected here"
                    f"{(': ' + self.last_error) if self.last_error else ''}")
        if klass in FOREX_LIKE:
            return "paper — the MetaTrader 5 terminal is not connected on this machine"
        if not getattr(self.cfg, "broker_venues", {}).get(klass):
            return "paper — no broker wired for this asset class yet (tell me the broker)"
        return "paper"

    def routing(self) -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}
        for key, meta in book.CLASSES.items():
            out[key] = {"label": str(meta.get("label", key)), "venue": self.venue_for(key),
                        "detail": self.route_detail(key)}
        return out

    def account(self) -> Dict[str, Any]:
        if self.mt5_live and self.mt5 is not None:
            acct = self.mt5.account()
            if acct:
                self.equity_hint = float(acct.get("equity") or acct.get("balance") or self.equity_hint)
                return acct
        return {"login": self.creds.login, "server": self.creds.server or "paper",
                "currency": "USD", "balance": round(self.equity_hint, 2),
                "equity": round(self.equity_hint, 2), "margin_free": round(self.equity_hint, 2),
                "leverage": 0, "demo": True, "company": "paper venue"}

    def venue(self, klass: str):
        """The venue that will take this order — or an honest refusal."""
        if self.venue_for(klass) == "mt5":
            if self.mt5 is None or not self.mt5.connected:
                raise BrokerError(
                    "not_connected",
                    f"MetaTrader 5 {self.creds.server or ''} is not connected"
                    f"{(': ' + self.last_error) if self.last_error else ''} — order not sent")
            return self.mt5
        return self.paper

    # ---- sizing ------------------------------------------------------
    def sizing(self, signal: Dict[str, Any], risk_pct: Optional[float] = None) -> Dict[str, Any]:
        klass = signal.get("class") or book.instrument(signal.get("symbol", "")).klass
        entry = float(signal.get("entry") or 0.0)
        stop = float(signal.get("stop") or 0.0)
        try:
            venue = self.venue(klass)
        except BrokerError as exc:
            # the destination is the terminal and it is not here: show the size
            # the standard contract implies, but say whose numbers these are
            venue = self.paper
            spec = venue.spec(signal.get("symbol", ""), entry, klass)
            risk_dollars = max(0.0, self.account().get("equity", 0.0)) * float(
                risk_pct if risk_pct is not None else self.autotrade["risk_pct"]) / 100.0
            try:
                volume = lots_for_risk(risk_dollars, abs(entry - stop), spec)
            except BrokerError as inner:
                return {"ok": False, "reason": inner.reason, "message": inner.message,
                        "venue": self.venue_for(klass), "connected": False}
            return {"ok": True, "volume": volume, "unit": spec.unit,
                    "risk_dollars": round(risk_dollars, 2),
                    "risk_pct": float(risk_pct if risk_pct is not None else self.autotrade["risk_pct"]),
                    "pips": round(abs(entry - stop) / spec.pip, 1) if spec.pip else 0.0,
                    "value_per_pip": round(spec.pip_value, 4), "venue": self.venue_for(klass),
                    "connected": False, "spec_source": f"standard contract — {exc.message}",
                    "description": f"{volume} {spec.unit} of {signal.get('symbol','')}"}
        spec = venue.spec(signal.get("symbol", ""), entry, klass)
        pct = float(risk_pct if risk_pct is not None else self.autotrade["risk_pct"])
        risk_dollars = max(0.0, self.account().get("equity", 0.0)) * pct / 100.0
        try:
            volume = lots_for_risk(risk_dollars, abs(entry - stop), spec)
        except BrokerError as exc:
            return {"ok": False, "reason": exc.reason, "message": exc.message,
                    "risk_dollars": round(risk_dollars, 2), "unit": spec.unit,
                    "venue": venue.name, "spec_source": spec.source}
        return {"ok": True, "volume": volume, "unit": spec.unit, "risk_dollars": round(risk_dollars, 2),
                "risk_pct": pct, "priced_at": round(entry, 8), "stop_distance": round(abs(entry - stop), 8),
                "pips": round(abs(entry - stop) / spec.pip, 1) if spec.pip else 0.0,
                "value_per_pip": round(spec.pip_value, 4), "venue": venue.name,
                "connected": True, "spec_source": spec.source,
                "description": f"{volume} {spec.unit} of {signal.get('symbol','')}"}

    # ---- placing -----------------------------------------------------
    async def place(self, signal: Dict[str, Any], volume: Optional[float] = None,
                    risk_pct: Optional[float] = None, source: str = "manual") -> Dict[str, Any]:
        symbol = str(signal.get("symbol") or "")
        klass = str(signal.get("class") or book.instrument(symbol).klass)
        side = str(signal.get("side") or "LONG").upper()
        entry, stop, target = (float(signal.get("entry") or 0.0), float(signal.get("stop") or 0.0),
                               float(signal.get("target") or 0.0))
        if not symbol or entry <= 0:
            raise BrokerError("bad_signal", "that signal has no symbol or no entry price")
        if side not in ("LONG", "SHORT"):
            raise BrokerError("bad_side", f"{side} is not a direction")
        # one live order per symbol: doubling up on the same pair is a position
        # the desk did not size and cannot see
        for o in self.orders.values():
            if o["status"] == "OPEN" and o["symbol"] == symbol:
                raise BrokerError("already_open", f"{symbol} already has a live order ({o['ticket']})")
        if self.autotrade["max_open"] and len(self.open_orders()) >= int(self.autotrade["max_open"]):
            raise BrokerError("max_open", f"already holding {len(self.open_orders())} live orders")

        venue = self.venue(klass)
        spec = venue.spec(symbol, entry, klass)
        # The plan was priced a scan ago. Orders fill at the market, so the size
        # is derived from the price the venue is actually quoting: sizing off a
        # stale entry is how a "0.5% risk" trade quietly becomes a 1% one.
        live = None
        try:
            live = venue.price(symbol)
        except Exception:                                   # pragma: no cover
            live = None
        live = float(live or entry)
        if stop:
            through = (live <= stop) if side == "LONG" else (live >= stop)
            if through:
                raise BrokerError(
                    "invalidated",
                    f"the market is already through the stop ({live:g} vs {stop:g}) — "
                    "the setup is gone, not late")
        if target:
            # ...and the same at the other end: a long that fills above its own
            # target has no reward left to take. Filling there and then closing at
            # "target" is how a plan quietly becomes a loss.
            exhausted = (live >= target) if side == "LONG" else (live <= target)
            if exhausted:
                raise BrokerError(
                    "target_reached",
                    f"the market has already traded through the target ({live:g} vs "
                    f"{target:g}) — the move is behind us, not ahead of us")
        if volume is None:
            sized = self.sizing({**signal, "entry": live, "class": klass}, risk_pct)
            if not sized.get("ok"):
                raise BrokerError(str(sized.get("reason")), str(sized.get("message")))
            volume = float(sized["volume"])
        fill = venue.place(symbol, side, float(volume), spec, stop, target,
                           comment=f"SOUL-{signal.get('id', 'manual')}"[:31],
                           magic=int(getattr(self.cfg, "broker_magic", 770001)),
                           deviation=int(getattr(self.cfg, "broker_deviation", 20)))
        risk = (abs(fill["price"] - stop) / spec.pip * spec.pip_value * float(fill["volume"])
                if spec.pip else abs(fill["price"] - stop) * spec.contract * float(fill["volume"]))
        plan_entry = entry
        # the reward that is actually left from the fill we got
        rr_at_fill = (abs(target - fill["price"]) / abs(fill["price"] - stop)
                      if target and stop and abs(fill["price"] - stop) > 0 else 0.0)
        order = {
            "ticket": str(fill["ticket"]), "ref": str(signal.get("id", "")),
            "plan_entry": round(plan_entry, 8),
            "rr_at_fill": round(rr_at_fill, 2),
            "slippage_pips": round((fill["price"] - plan_entry) / spec.pip, 1) if spec.pip else 0.0,
            "symbol": symbol, "name": book.instrument(symbol).name,
            "venue_symbol": fill.get("symbol", symbol), "class": klass,
            "side": side, "volume": float(fill["volume"]), "unit": spec.unit,
            "entry": round(float(fill["price"]), 8), "stop": round(stop, 8), "target": round(target, 8),
            "venue": venue.name, "status": "OPEN", "opened_at": time.time(), "closed_at": 0.0,
            "pnl": 0.0, "pnl_pct": 0.0, "exit_price": 0.0, "exit_reason": "",
            "risk": round(risk, 2), "risk_pct_account": round(
                risk / max(1e-9, self.account().get("equity", 1.0)) * 100.0, 3),
            "confidence": float(signal.get("confidence") or 0.0),
            "strategy": str(signal.get("strategy") or ""), "source": source,
            "approvals": int(signal.get("approvals") or 0),
            "spec_source": spec.source, "comment": str(fill.get("comment") or ""),
            "account": self.account().get("login", ""), "currency": self.account().get("currency", "USD"),
            "error": "",
        }
        self.orders[order["ticket"]] = order
        self.order_seq.append(order["ticket"])
        self.order_seq = self.order_seq[-500:]
        if source == "autotrade":
            self.autotrade["placed"] += 1
            self.autotrade["last"] = f"{symbol} {side} {order['volume']} {order['unit']} @ {order['entry']}"
        await self.bus.publish("broker_order", **order)
        log.info("broker: placed %s %s %s %s @ %s (%s)", venue.name, symbol, side,
                 order["volume"], order["entry"], source)
        return order

    async def close(self, ticket: str, reason: str = "MANUAL") -> Dict[str, Any]:
        order = self.orders.get(str(ticket))
        if order is None:
            raise BrokerError("unknown_ticket", f"no order {ticket} in this session")
        if order["status"] != "OPEN":
            raise BrokerError("already_closed", f"{order['symbol']} order {ticket} is already booked")
        venue = self.venue(order["class"])
        price = venue.price(order["symbol"])
        fill = venue.close(str(ticket), order["symbol"], order["side"], order["volume"],
                           deviation=int(getattr(self.cfg, "broker_deviation", 20)),
                           magic=int(getattr(self.cfg, "broker_magic", 770001)))
        exit_price = float(fill.get("price") or price or order["entry"])
        spec = venue.spec(order["symbol"], order["entry"], order["class"])
        pnl = float(fill.get("profit") or 0.0)
        if not pnl:
            # paper (and any venue that does not report profit): mark it out
            direction = 1.0 if order["side"] == "LONG" else -1.0
            move = (exit_price - order["entry"]) * direction
            pips = move / spec.pip if spec.pip else 0.0
            pnl = pips * spec.pip_value * order["volume"]
        order.update({
            "status": "CLOSED", "closed_at": time.time(), "exit_price": round(exit_price, 8),
            "pnl": round(pnl, 2), "exit_reason": reason,
            "pnl_pct": round(pnl / max(1e-9, order["risk"]) * 100.0, 2) if order["risk"] else 0.0,
            "partial": bool(fill.get("partial")),
        })
        if venue.name == "paper":
            self.equity_hint += pnl
        await self.bus.publish("broker_closed", **order)
        log.info("broker: closed %s %s for %+.2f (%s)", order["symbol"], ticket, pnl, reason)
        return order

    async def close_all(self, reason: str = "MANUAL") -> Dict[str, Any]:
        done, failed = [], []
        for order in list(self.orders.values()):
            if order["status"] != "OPEN":
                continue
            try:
                done.append((await self.close(order["ticket"], reason))["ticket"])
            except BrokerError as exc:
                failed.append({"ticket": order["ticket"], "reason": exc.reason})
        return {"closed": done, "failed": failed}

    async def mark(self, prices: Dict[str, float]) -> None:
        """Book paper orders whose stop or target has been touched."""
        for order in list(self.orders.values()):
            if order["status"] != "OPEN" or order["venue"] != "paper":
                continue
            price = prices.get(order["symbol"])
            if not price:
                continue
            long = order["side"] == "LONG"
            if order["stop"] and ((price <= order["stop"]) if long else (price >= order["stop"])):
                await self.close(order["ticket"], "STOP")
            elif order["target"] and ((price >= order["target"]) if long else (price <= order["target"])):
                await self.close(order["ticket"], "TARGET")

    # ---- the book ----------------------------------------------------
    def open_orders(self) -> List[Dict[str, Any]]:
        return [o for o in self.orders.values() if o["status"] == "OPEN"]

    def positions_view(self, prices: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        prices = prices or {}
        live = {}
        if self.mt5_live and self.mt5 is not None:
            live = {p["ticket"]: p for p in self.mt5.positions()}
        out = []
        for order in self.open_orders():
            row = dict(order)
            price = (live.get(order["ticket"], {}).get("price")
                     or prices.get(order["symbol"]) or self.venue(order["class"]).price(order["symbol"])
                     or order["entry"])
            spec = self.venue(order["class"]).spec(order["symbol"], order["entry"], order["class"])
            direction = 1.0 if order["side"] == "LONG" else -1.0
            pnl = live.get(order["ticket"], {}).get("pnl")
            if pnl is None:
                pips = ((price - order["entry"]) * direction) / spec.pip if spec.pip else 0.0
                pnl = pips * spec.pip_value * order["volume"]
            row.update({"price": round(float(price), 8), "pnl": round(float(pnl), 2),
                        "pnl_pct": round(float(pnl) / order["risk"] * 100.0, 2) if order["risk"] else 0.0,
                        "to_stop_pct": round(abs(price - order["stop"]) / price * 100.0, 2) if order["stop"] and price else 0.0,
                        "to_target_pct": round(abs(order["target"] - price) / price * 100.0, 2) if order["target"] and price else 0.0})
            out.append(row)
        return out

    def history_view(self, limit: int = 60) -> List[Dict[str, Any]]:
        closed = [o for o in self.orders.values() if o["status"] == "CLOSED"]
        closed.sort(key=lambda o: o["closed_at"], reverse=True)
        return [dict(o) for o in closed[:limit]]

    def stats(self) -> Dict[str, Any]:
        closed = [o for o in self.orders.values() if o["status"] == "CLOSED"]
        wins = [o for o in closed if o["pnl"] > 0]
        return {
            "orders_total": len(self.orders), "open": len(self.open_orders()),
            "closed": len(closed), "wins": len(wins),
            "realised": round(sum(o["pnl"] for o in closed), 2),
            "open_risk": round(sum(o["risk"] for o in self.open_orders()), 2),
            "live_venue_orders": len([o for o in self.open_orders() if o["venue"] == "mt5"]),
            "paper_orders": len([o for o in self.open_orders() if o["venue"] == "paper"]),
        }

    def status(self) -> Dict[str, Any]:
        acct = self.account()
        return {
            "mode": self.mode, "venue": "mt5" if self.mt5_live else "paper",
            "connected": self.mt5_live, "detail": (self.mt5.note if self.mt5 is not None
                                                   else self.store.__class__.__name__),
            "terminal": {"note": (self.mt5.note if self.mt5 is not None else ""),
                         "error": self.last_error,
                         "symbols_known": len(self.mt5.symbols()) if self.mt5_live and self.mt5 else 0},
            "creds": self.creds.masked(), "account": acct, "routing": self.routing(),
            "autotrade": dict(self.autotrade), "stats": self.stats(),
            "store": str(self.store.path), "ready": self.creds.ready(),
            "note": ("MetaTrader 5 terminal connected: forex orders go to the live account."
                     if self.mt5_live else
                     "No MetaTrader 5 terminal here — orders are filled on the paper venue. "
                     "Enter the terminal login in Settings → Broker to reach the real account."),
        }
