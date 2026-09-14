"""The FX data path: a keyless ECB reference table, and badges that tell the truth.

Nothing here touches the network. The table is injected, which is the point:
the feed has to behave the same whether it is on a Kaggle box with egress or a
locked-down container with none.
"""
from __future__ import annotations

import pytest

from soul import universe as book
from soul.config import Config
from soul.market import MarketFeed

# a few lines of the real payload shape (EUR base, quotes per EUR)
TABLE = {"USD": 1.08, "GBP": 0.85, "JPY": 163.0, "CHF": 0.95, "SEK": 11.4,
         "INR": 90.0, "PLN": 4.3, "TRY": 34.0}


def feed(*symbols: str) -> MarketFeed:
    cfg = Config()
    cfg.universe = list(symbols) or ["EUR/USD"]
    return MarketFeed(cfg)


@pytest.mark.parametrize(
    "hint,expected",
    [
        ("EUR-USD", 1.08),          # quoted straight off the table
        ("USD-JPY", 163.0 / 1.08),  # crossed through the EUR
        ("SEK-USD", 1.08 / 11.4),   # and inverted
        ("EUR-EUR", 1.0),
    ],
)
def test_rate_price_crosses_the_table(hint: str, expected: float) -> None:
    f = feed()
    f._rates, f._rates_ok = dict(TABLE) | {"EUR": 1.0}, True
    got = f._rate_price(hint)
    assert got == pytest.approx(expected, rel=1e-9)


def test_rate_price_refuses_what_it_cannot_price() -> None:
    f = feed()
    f._rates, f._rates_ok = {"EUR": 1.0, "USD": 1.08}, True
    assert f._rate_price("USD-ZZZ") is None
    assert f._rate_price("nonsense") is None
    f._rates_ok = False
    assert f._rate_price("EUR-USD") is None


def test_badge_follows_the_data_not_the_wish() -> None:
    f = feed("EUR/USD", "BTC/USDT", "XAU/USD", "AAPL")
    # nothing loaded -> nothing may claim a live feed
    assert f.source_of("EUR/USD") == "sim"
    assert f.source_of("BTC/USDT") == "sim"     # no venue without ccxt
    f._rates, f._rates_ok = dict(TABLE) | {"EUR": 1.0}, True
    assert f.source_of("EUR/USD") == "rates"
    assert f.source_of("XAU/USD") == "sim"      # metals stay honest
    assert f.source_of("AAPL") == "sim"


def test_fx_is_anchored_on_the_fix() -> None:
    f = feed("EUR/USD", "USD/JPY")
    f._rates, f._rates_ok = dict(TABLE) | {"EUR": 1.0}, True
    f._seed_simulator()
    eur = f.prices["EUR/USD"].price
    jpy = f.prices["USD/JPY"].price
    assert eur == pytest.approx(1.08, rel=0.02)     # real level, not a guess
    assert jpy == pytest.approx(163.0 / 1.08, rel=0.02)


def test_catalogue_reports_the_live_source() -> None:
    cat = book.catalogue(lambda sym: "rates" if sym == "EUR/USD" else "sim")
    forex = next(c for c in cat["classes"] if c["key"] == "forex")
    eur = next(s for s in forex["symbols"] if s["symbol"] == "EUR/USD")
    assert eur["kind"] == "rates" and eur["live"] == "rates"
    assert forex["symbols"][0]["live"] == "sim"


def test_forex_book_is_wide_enough_to_pick_from() -> None:
    """'every pair' means a real board, not four majors."""
    book_forex = [i for i in book.INSTRUMENTS if i.klass == "forex"]
    assert len(book_forex) >= 30
    assert all(i.kind == "rates" for i in book_forex)
    assert all(i.rate and "-" in i.rate for i in book_forex)
    classes = {i.klass for i in book.INSTRUMENTS}
    assert classes == set(book.CLASSES)
    assert book.catalogue()["total"] == len(book.INSTRUMENTS)
