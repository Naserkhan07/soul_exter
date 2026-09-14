"""Live venue bridge — free, key-less endpoints (Binance spot + Yahoo Finance).

Both are best-effort: the floor keeps running on the synthetic tape whatever the
network does, and the Settings panel shows which symbols are currently anchored
to a real venue print.
"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Tuple

import httpx

from ..market.feed import MarketFeed
from .universe import BINANCE_MAP, UNIVERSE, YAHOO_MAP

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; soul-exter/1.0)",
                "Accept": "application/json"}


async def fetch_binance(client: httpx.AsyncClient, symbol: str, limit: int = 120) -> Optional[list]:
    pair = BINANCE_MAP.get(symbol)
    if not pair:
        return None
    try:
        r = await client.get("https://api.binance.com/api/v3/klines",
                             params=dict(symbol=pair, interval="1m", limit=limit))
        if r.status_code != 200:
            return None
        bars = []
        for k in r.json():
            bars.append((float(k[0]) / 1000.0, float(k[1]), float(k[2]), float(k[3]),
                         float(k[4]), float(k[5])))
        return bars
    except Exception:
        return None


async def fetch_yahoo(client: httpx.AsyncClient, symbol: str, rng: str = "1d") -> Optional[list]:
    ticker = YAHOO_MAP.get(symbol)
    if not ticker:
        return None
    try:
        r = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                             params=dict(range=rng, interval="1m"), headers=HTTP_HEADERS)
        if r.status_code != 200:
            return None
        data = r.json()
        res = (data.get("chart") or {}).get("result") or []
        if not res:
            return None
        res = res[0]
        ts = res.get("timestamp") or []
        q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        o, h, l, c, v = (q.get("open") or [], q.get("high") or [], q.get("low") or [],
                         q.get("close") or [], q.get("volume") or [])
        bars = []
        for i in range(len(ts)):
            if i >= len(c) or c[i] is None:
                continue
            bars.append((float(ts[i]), float(o[i] or c[i]), float(h[i] or c[i]),
                         float(l[i] or c[i]), float(c[i]), float(v[i] or 0)))
        return bars or None
    except Exception:
        return None


async def poll_symbols(feed: MarketFeed, symbols: List[str]) -> Tuple[bool, str, int]:
    ok = 0
    err = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=5.0),
                                 headers=HTTP_HEADERS) as client:
        sem = asyncio.Semaphore(4)

        async def one(sym: str) -> None:
            nonlocal ok, err
            async with sem:
                inst = UNIVERSE.get(sym)
                if inst is None:
                    return
                bars = None
                if sym in BINANCE_MAP:
                    bars = await fetch_binance(client, sym)
                if bars is None and sym in YAHOO_MAP:
                    bars = await fetch_yahoo(client, sym)
                if not bars:
                    if not err:
                        err = f"no venue data for {sym}"
                    return
                anchor = bars[-1][4]
                feed.upsert_history(sym, bars, anchor_price=anchor)
                ok += 1

        await asyncio.gather(*(one(s) for s in symbols), return_exceptions=True)
    return ok > 0, err, ok
