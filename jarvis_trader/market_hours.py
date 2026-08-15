"""
Market session engine - the bot knows the trading timings of every asset.

  crypto    : 24/7, never closes
  forex     : Sun 22:00 UTC -> Fri 21:00 UTC (24/5)
  us stocks : Mon-Fri 13:30-20:00 UTC (09:30-16:00 ET)
  us index  : same as US stocks cash session
  nse india : Mon-Fri 03:45-10:00 UTC (09:15-15:30 IST)
  futures   : Sun 22:00 UTC -> Fri 21:00 UTC with a daily 21:00-22:00 UTC break

The engine only ANALYZES and PLACES trades on assets whose market is OPEN.
Closed assets keep showing their last price but are marked CLOSED.
"""
import time
from datetime import datetime, timezone

# symbol -> venue override (defaults come from asset type)
VENUE = {
    "NIFTY50": "nse", "BANKNIFTY": "nse",
    "DAX": "eu", "FTSE": "eu", "N225": "jp",
}

TYPE_DEFAULT = {"crypto": "crypto", "forex": "forex", "stock": "us",
                "index": "us", "futures": "futures", "fund": "us"}


def _venue_for(asset):
    sym = asset["symbol"]
    if sym in VENUE:
        return VENUE[sym]
    # NSE stocks are declared with a .NS yahoo symbol
    if asset.get("yahoo", "").endswith(".NS"):
        return "nse"
    return TYPE_DEFAULT.get(asset["type"], "us")


def _mins(dt):
    return dt.hour * 60 + dt.minute


def market_status(asset, now_ts=None):
    """Returns {open, venue, session, note} for an asset right now (UTC logic)."""
    now = datetime.fromtimestamp(now_ts or time.time(), tz=timezone.utc)
    venue = _venue_for(asset)
    wd = now.weekday()          # 0=Mon .. 6=Sun
    m = _mins(now)

    if venue == "crypto":
        return {"open": True, "venue": "Crypto 24/7", "session": "always open",
                "note": "crypto never closes"}

    if venue == "forex":
        # open from Sun 22:00 UTC to Fri 21:00 UTC
        is_open = not (
            (wd == 4 and m >= 21 * 60) or wd == 5 or (wd == 6 and m < 22 * 60))
        sess = ("Asia" if m < 7 * 60 else "London" if m < 12 * 60
                else "London/NY overlap" if m < 16 * 60 else "New York")
        return {"open": is_open, "venue": "Forex 24/5",
                "session": sess if is_open else "weekend",
                "note": "most volume in London/NY overlap 12:00-16:00 UTC"}

    if venue == "futures":
        # Sun 22:00 -> Fri 21:00 UTC, daily break 21:00-22:00 UTC
        weekend = (wd == 4 and m >= 21 * 60) or wd == 5 or (wd == 6 and m < 22 * 60)
        daily_break = (21 * 60 <= m < 22 * 60) and wd not in (5, 6)
        is_open = not weekend and not daily_break
        return {"open": is_open, "venue": "Futures (CME hours)",
                "session": "electronic session" if is_open
                else ("daily break 21-22 UTC" if daily_break else "weekend"),
                "note": "nearly 24h Sun 22:00 - Fri 21:00 UTC"}

    if venue == "nse":
        is_open = wd < 5 and (3 * 60 + 45) <= m < (10 * 60)
        return {"open": is_open, "venue": "NSE India",
                "session": "cash 09:15-15:30 IST" if is_open else "closed",
                "note": "Mon-Fri 09:15-15:30 IST (03:45-10:00 UTC)"}

    if venue == "eu":
        is_open = wd < 5 and (8 * 60) <= m < (16 * 60 + 30)
        return {"open": is_open, "venue": "European market",
                "session": "cash 09:00-17:30 CET" if is_open else "closed",
                "note": "Mon-Fri ~08:00-16:30 UTC"}

    if venue == "jp":
        is_open = wd < 5 and ((0 <= m < 2 * 60 + 30) or (3 * 60 + 30 <= m < 6 * 60))
        return {"open": is_open, "venue": "Tokyo market",
                "session": "TSE 09:00-15:00 JST" if is_open else "closed",
                "note": "Mon-Fri 00:00-06:00 UTC with lunch break"}

    # default: US cash session
    is_open = wd < 5 and (13 * 60 + 30) <= m < (20 * 60)
    return {"open": is_open, "venue": "US market",
            "session": "cash 09:30-16:00 ET" if is_open else "closed",
            "note": "Mon-Fri 09:30-16:00 ET (13:30-20:00 UTC)"}
