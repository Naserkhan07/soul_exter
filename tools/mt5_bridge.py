#!/usr/bin/env python3
"""SOUL EXTER ↔ MetaTrader 5 bridge.

Run this **on the machine where the MetaTrader 5 terminal is installed and logged
in** (Windows, or Linux under Wine). The floor itself can keep running anywhere —
Kaggle, a VPS, this sandbox — because orders travel over plain HTTP:

    floor (anywhere)                      your PC
    ┌────────────────┐   GET /api/exec/queue   ┌──────────────────────┐
    │ ORDERS desk    │ ◄────────────────────── │ mt5_bridge.py        │
    │ PLACE / BOOK   │ ──────────────────────► │  MetaTrader5 package │
    └────────────────┘   POST /api/exec/report └──────────┬───────────┘
                                                          │ order_send
                                                   MetaTrader 5 terminal

Usage
-----
    pip install MetaTrader5 requests
    python3 tools/mt5_bridge.py \
        --floor http://127.0.0.1:8000 \
        --login 112594843 --password 'your-password' --server MetaQuotes-Demo \
        --suffix '' --lots-timeout 15

Leave it running. Every PLACE TRADE you click in the floor's ORDERS desk is
executed here as a real market order and the resulting ticket is reported back,
so the floor shows the true MT5 ticket, fill price and position.

Testing without a terminal (proves the pipe):
    python3 tools/mt5_bridge.py --floor http://127.0.0.1:8000 --dry-run --once
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DRY = False


def http(url: str, payload: dict | None = None, timeout: float = 20.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        body = fh.read().decode() or "{}"
    return json.loads(body)


class Executor:
    """Thin wrapper so dry-run and real MT5 behave identically."""

    def __init__(self, login: int, password: str, server: str, path: str,
                 suffix: str, deviation: int, dry: bool) -> None:
        self.dry = dry
        self.dry_positions: dict[str, dict] = {}
        self.seq = 0
        self.mt5 = None
        self.broker = None
        if dry:
            print("[bridge] DRY RUN — no terminal needed, orders are simulated and reported back")
            return
        try:
            import MetaTrader5 as mt5
        except Exception as exc:
            sys.exit(f"[bridge] MetaTrader5 package is not importable here ({exc}).\n"
                     f"          Run this script on the machine with the terminal "
                     f"(Windows, or Linux/Wine): pip install MetaTrader5")
        self.mt5 = mt5
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "backend"))
        from soul_exter.broker.mt5 import MT5Broker
        self.broker = MT5Broker(login=login, password=password, server=server,
                                path=path, symbol_suffix=suffix, deviation=deviation)
        if not self.broker.connect(force=True):
            sys.exit(f"[bridge] could not attach to the terminal: {self.broker.reason}")
        print(f"[bridge] {self.broker.reason}")

    # ------------------------------------------------------------------ actions
    def place(self, ins: dict) -> dict:
        if self.dry:
            time.sleep(0.2)
            self.seq += 1
            ticket = f"DRY-{int(time.time())}-{self.seq}"
            self.dry_positions[ticket] = dict(ticket=ticket, trade_id=ins.get("trade_id"),
                                              mode="mt5", symbol=ins.get("symbol"),
                                              direction=ins.get("direction"),
                                              lots=float(ins.get("lots") or 0.1),
                                              entry=float(ins.get("entry") or 0.0),
                                              price=float(ins.get("entry") or 0.0), pnl_usd=0.0,
                                              opened=time.time())
            return dict(ok=True, ticket=ticket, price=ins.get("entry"),
                        lots=ins.get("lots"), message="dry-run fill")
        res = self.broker.place(dict(id=ins["trade_id"], symbol=ins["symbol"],
                                     asset_class=ins.get("asset_class", "forex"),
                                     direction=ins["direction"], entry=ins.get("entry"),
                                     exit_price=ins.get("entry")), float(ins.get("lots") or 0.1))
        return dict(ok=res.ok, ticket=res.ticket, price=res.price, lots=res.lots,
                    pnl_usd=res.pnl_usd, message=res.message)

    def book(self, ins: dict) -> dict:
        if self.dry:
            time.sleep(0.2)
            pos = self.dry_positions.pop(str(ins.get("ticket")), None)
            entry = float((pos or {}).get("entry") or ins.get("entry") or 0.0)
            price = float(ins.get("market") or ins.get("entry") or entry)
            lots = float(ins.get("lots") or 0.1)
            sgn = 1.0 if str(ins.get("direction")) == "long" else -1.0
            contract = 100_000.0 if len(str(ins.get("symbol") or "")) == 6 else 10.0
            return dict(ok=True, ticket=ins.get("ticket"), price=price,
                        lots=lots, pnl_usd=(price - entry) * sgn * lots * contract,
                        message=f"dry-run close @ {price}")
        res = self.broker.book(dict(id=ins["trade_id"], symbol=ins["symbol"],
                                    asset_class=ins.get("asset_class", "forex"),
                                    direction=ins["direction"], entry=ins.get("entry"),
                                    exit_price=ins.get("entry")), float(ins.get("lots") or 0.1))
        return dict(ok=res.ok, ticket=res.ticket or ins.get("ticket"), price=res.price,
                    lots=res.lots, pnl_usd=res.pnl_usd, message=res.message)

    def positions(self, ins: dict | None = None) -> list:
        if self.dry:
            return list(self.dry_positions.values())
        try:
            return self.broker.open_positions()
        except Exception:
            return []

    def status(self) -> dict:
        if self.dry:
            return dict(user="dry-run", terminal="simulated", account="DRY-DEMO")
        info = self.mt5.account_info() if self.mt5 else None
        if self.broker and getattr(self.broker, "connected", False):
            return dict(user="mt5", terminal=self.broker.reason,
                        account=str(getattr(info, "login", "")) if info else "")
        return dict(user="mt5", terminal="disconnected", account="")


def main() -> int:
    ap = argparse.ArgumentParser(description="SOUL EXTER MT5 execution bridge")
    ap.add_argument("--floor", default="http://127.0.0.1:8000", help="floor base url")
    ap.add_argument("--login", type=int, default=0)
    ap.add_argument("--password", default="")
    ap.add_argument("--server", default="")
    ap.add_argument("--path", default="", help="terminal64.exe path (optional)")
    ap.add_argument("--suffix", default="", help="broker symbol suffix, e.g. .m")
    ap.add_argument("--deviation", type=int, default=20, help="max slippage in points")
    ap.add_argument("--interval", type=float, default=1.5, help="poll seconds")
    ap.add_argument("--dry-run", action="store_true", help="simulate fills (no terminal)")
    ap.add_argument("--once", action="store_true", help="one poll, then exit")
    args = ap.parse_args()

    global DRY
    DRY = args.dry_run
    base = args.floor.rstrip("/")
    ex = Executor(args.login, args.password, args.server, args.path, args.suffix,
                  args.deviation, args.dry_run)
    print(f"[bridge] floor {base} · polling /api/exec/queue every {args.interval}s "
          f"(ctrl-c to stop)")
    done: set[str] = set()
    while True:
        try:
            data = http(f"{base}/api/exec/queue")
        except urllib.error.URLError as exc:
            print(f"[bridge] floor unreachable ({exc}); retrying")
            if args.once:
                return 1
            time.sleep(max(2.0, args.interval))
            continue
        for ins in data.get("instructions", []):
            ex_id = str(ins.get("id"))
            if ex_id in done:
                continue
            action = str(ins.get("action"))
            print(f"[bridge] {action.upper()} {ins.get('symbol')} {ins.get('direction')} "
                  f"{ins.get('lots')} lots ({ex_id}, attempt {ins.get('attempts')})")
            try:
                result = ex.place(ins) if action == "place" else ex.book(ins)
            except Exception as exc:
                result = dict(ok=False, message=f"{type(exc).__name__}: {exc}")
            report = dict(id=ex_id, trade_id=ins.get("trade_id"), action=action,
                          symbol=ins.get("symbol"), bridge=ex.status(),
                          positions=ex.positions(ins), **result)
            try:
                http(f"{base}/api/exec/report", report)
                done.add(ex_id)
                flag = "OK " if result.get("ok") else "FAIL"
                print(f"[bridge] {flag} {ins.get('symbol')} → {result.get('ticket')} "
                      f"@ {result.get('price')} · {result.get('message')}")
            except urllib.error.URLError as exc:
                print(f"[bridge] could not report back ({exc}); will retry")
        if not data.get("instructions"):
            # heartbeat: keeps the floor's bridge indicator green and mirrors the
            # terminal's live position list into the ORDERS desk
            try:
                http(f"{base}/api/exec/report", dict(id="", action="heartbeat",
                                                     bridge=ex.status(),
                                                     positions=ex.positions()))
            except urllib.error.URLError:
                pass
        if args.once:
            return 0
        time.sleep(max(0.3, args.interval))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
