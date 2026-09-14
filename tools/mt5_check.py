#!/usr/bin/env python3
"""Local MetaTrader 5 readiness check — run this on the machine with the terminal.

    python3 tools/mt5_check.py --login 112594843 --password '…' --server MetaQuotes-Demo
    python3 tools/mt5_check.py --login … --server … --place EURUSD   # try one live order

It walks the same steps the floor's Broker → RUN DIAGNOSTICS uses, so a green run
here means PLACE TRADE will reach your account.
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="MT5 readiness check")
    ap.add_argument("--login", type=int, default=0)
    ap.add_argument("--password", default="")
    ap.add_argument("--server", default="")
    ap.add_argument("--path", default="", help="terminal64.exe (optional)")
    ap.add_argument("--suffix", default="", help="symbol suffix, e.g. .m")
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY,AUDUSD")
    ap.add_argument("--place", default="", help="send a 0.01 lot market order for this symbol")
    ap.add_argument("--lots", type=float, default=0.01)
    args = ap.parse_args()

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "backend"))
    from soul_exter.broker.mt5 import MT5Broker          # noqa: E402

    broker = MT5Broker(login=args.login, password=args.password, server=args.server,
                       path=args.path, symbol_suffix=args.suffix)
    steps = broker.diagnose([s for s in args.symbols.split(",") if s])
    width = max(len(s["step"]) for s in steps) if steps else 10
    failed = 0
    print("SOUL EXTER · MetaTrader 5 check\n")
    for s in steps:
        mark = "OK  " if s["ok"] else "FAIL"
        failed += 0 if s["ok"] else 1
        print(f"  [{mark}] {s['step']:<{width}}  {s['detail']}")
    if args.place and not failed:
        res = broker.place(dict(id="CHECK", symbol=args.place, asset_class="forex",
                                direction="long", entry=0.0), args.lots)
        print(f"\n  test order {args.place}: ok={res.ok} ticket={res.ticket} "
              f"price={res.price} — {res.message}")
        if res.ok:
            close = broker.book(dict(id="CHECK", symbol=args.place, asset_class="forex",
                                     direction="long", entry=res.price), args.lots)
            print(f"  test close: ok={close.ok} price={close.price} — {close.message}")
    print("\n" + ("all checks passed — PLACE TRADE in the floor will hit this account"
                  if not failed else
                  f"{failed} check(s) failed — fix those before placing orders"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
