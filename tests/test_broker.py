"""Execution: sizing off the stop, one-click place, one-click close.

The broker layer is the one piece of this system that can move real money, so
the tests are about the things that go wrong in production, not about happy
paths: a size that ignores the stop, an order that doubles up on a pair, a
venue that quietly substitutes paper for a live account, a password that leaks
into a response, an auto-trade that fires when it was never armed.
"""
import asyncio
import json
from pathlib import Path

import pytest

from soul.broker import (BrokerError, BrokerHub, CredStore, lots_for_risk, spec_for)
from soul.bus import EventBus
from soul.config import Config


PRICES = {"EUR/USD": 1.0850, "USD/JPY": 148.20, "XAU/USD": 2380.0, "GBP/JPY": 188.40,
          "BTC/USDT": 61000.0, "AAPL": 224.0}


@pytest.fixture(autouse=True)
def _clean_prices():
    """The feed is shared state: a test that moves the market must not move it
    for the next one."""
    snapshot = dict(PRICES)
    yield
    PRICES.clear()
    PRICES.update(snapshot)


def hub(tmp_path: Path, mode: str = "auto", **env) -> BrokerHub:
    cfg = Config()
    cfg.mock_llm = True
    cfg.broker_store = str(tmp_path / "mt5.json")
    cfg.broker_mode = mode
    for k, v in env.items():
        setattr(cfg, k, v)
    return BrokerHub(cfg, EventBus(), lambda s: PRICES.get(s))


def signal(**over) -> dict:
    base = {"id": "T-1", "symbol": "EUR/USD", "class": "forex", "side": "LONG",
            "entry": 1.0850, "stop": 1.0820, "target": 1.0912, "strategy": "trend_pullback",
            "confidence": 71.0, "approvals": 4}
    base.update(over)
    return base


# ---------------------------------------------------------------- contracts
def test_forex_lot_maths_is_the_real_thing():
    """100k units, $10 a pip on a USD-quoted major; a JPY cross pays in yen."""
    eur = spec_for("EUR/USD", 1.085)
    assert (eur.contract, eur.pip, eur.pip_value, eur.unit) == (100_000.0, 0.0001, 10.0, "lots")
    assert lots_for_risk(75.0, 0.0030, eur) == 0.25          # 30 pips * $10/pip -> $300/lot
    jpy = spec_for("USD/JPY", 148.20)
    assert jpy.pip == 0.01 and jpy.pip_value == pytest.approx(6.75, abs=0.05)
    # a cross is converted at the quote currency's own USD rate; without a rate
    # to read it says "estimate" rather than inventing one
    rates = {"USD/JPY": 148.20}.get
    cross = spec_for("GBP/JPY", 188.40, "forex", rate_of=rates)
    assert cross.pip_value == pytest.approx(6.75, abs=0.05)
    assert "cross converted" in cross.source
    blind = spec_for("GBP/JPY", 188.40, "forex")
    assert blind.pip_value == 10.0 and blind.source.startswith("estimate")
    # gold is a 100oz contract, so a $2 stop is $200 a lot
    gold = spec_for("XAU/USD", 2380.0)
    assert (gold.contract, gold.pip, gold.pip_value) == (100.0, 0.01, 1.0)


def test_a_volume_is_floored_to_the_brokers_lot_step():
    spec = spec_for("EUR/USD", 1.085)
    assert spec.round_volume(0.257) == 0.25
    assert spec.round_volume(0.25000001) == 0.25             # float error must not cost a step
    assert spec.clamp(0.001) == 0.01                          # under the minimum goes to the minimum
    assert spec.clamp(9999.0) == 50.0


def test_a_stop_is_required_because_size_comes_from_it():
    spec = spec_for("EUR/USD", 1.085)
    with pytest.raises(BrokerError) as err:
        lots_for_risk(75.0, 0.0, spec)
    assert err.value.reason == "no_stop"


# ---------------------------------------------------------------- placing
def test_one_click_places_and_the_stop_sets_the_size(tmp_path):
    h = hub(tmp_path)
    order = asyncio.run(h.place(signal()))
    assert order["status"] == "OPEN" and order["venue"] == "paper"
    assert order["volume"] == 0.25                            # $75 / (30 pips * $10)
    assert order["risk"] == pytest.approx(75.0)               # 0.25 * 30 pips * $10 = exactly the budget
    assert order["name"] == "Euro / US Dollar"                # the pair's name travels with it
    assert order["ticket"].startswith("P")
    # a second order on the same pair is refused: the desk did not size that position
    with pytest.raises(BrokerError) as err:
        asyncio.run(h.place(signal(id="T-2")))
    assert err.value.reason == "already_open"


def test_the_order_is_sized_to_the_asked_risk_not_a_number_someone_liked(tmp_path):
    h = hub(tmp_path)
    a = asyncio.run(h.place(signal(id="T-A"), risk_pct=0.5))
    b = asyncio.run(h.place(signal(id="T-B", symbol="GBP/JPY", entry=188.40, stop=187.80,
                                   target=189.60), risk_pct=1.0))
    assert a["risk"] == pytest.approx(75.0)                   # 0.5% of the account
    assert b["risk"] == pytest.approx(150.0, rel=0.01)        # twice the money, twice the size


def test_market_target_books_the_order_without_anyone_touching_it(tmp_path):
    h = hub(tmp_path)
    asyncio.run(h.place(signal()))
    PRICES["EUR/USD"] = 1.0912
    asyncio.run(h.mark(dict(PRICES)))
    closed = h.history_view()
    assert closed and closed[0]["exit_reason"] == "TARGET"
    assert closed[0]["pnl"] == pytest.approx(155.0)           # 62 pips * 0.25 lots * $10
    assert h.stats()["open"] == 0 and h.stats()["realised"] == pytest.approx(155.0)


def test_a_stop_takes_the_loss_the_size_promised(tmp_path):
    h = hub(tmp_path)
    asyncio.run(h.place(signal()))
    PRICES["EUR/USD"] = 1.0820
    asyncio.run(h.mark(dict(PRICES)))
    closed = h.history_view()[0]
    assert closed["exit_reason"] == "STOP"
    assert closed["pnl"] == pytest.approx(-75.0)              # the size was the risk, exactly


def test_one_click_close_books_it_immediately(tmp_path):
    h = hub(tmp_path)
    order = asyncio.run(h.place(signal()))
    PRICES["EUR/USD"] = 1.0875                                # 25 pips up
    out = asyncio.run(h.close(order["ticket"]))
    assert out["status"] == "CLOSED" and out["exit_reason"] == "MANUAL"
    assert out["pnl"] == pytest.approx(62.5)                  # 25 pips * 0.25 lots * $10
    assert h.open_orders() == []
    with pytest.raises(BrokerError) as err:
        asyncio.run(h.close(order["ticket"]))
    assert err.value.reason == "already_closed"


def test_close_everything_flattens_the_book(tmp_path):
    h = hub(tmp_path)
    asyncio.run(h.place(signal(id="T-A")))
    asyncio.run(h.place(signal(id="T-B", symbol="USD/JPY", entry=148.20, stop=147.60, target=149.40)))
    out = asyncio.run(h.close_all())
    assert len(out["closed"]) == 2 and out["failed"] == []
    assert h.stats()["open"] == 0


# ---------------------------------------------------------------- venues
def test_forex_is_routed_to_metatrader_and_elsewhere_says_so(tmp_path):
    h = hub(tmp_path)
    routing = h.routing()
    assert routing["forex"]["venue"] == "paper"               # no terminal on this machine
    assert "MetaTrader 5" in routing["forex"]["detail"]
    assert routing["crypto"]["venue"] == "paper"
    assert "no broker wired" in routing["crypto"]["detail"]


def test_a_pinned_terminal_refuses_instead_of_silently_filling_on_paper(tmp_path):
    """The one bug that costs real money: a paper fill reported as a live one."""
    h = hub(tmp_path, mode="mt5")
    h.creds = h.creds.__class__(login="112594843", password="x", server="MetaQuotes-Demo", mode="mt5")
    assert h.routing()["forex"]["venue"] == "mt5"
    with pytest.raises(BrokerError) as err:
        asyncio.run(h.place(signal()))
    assert err.value.reason == "not_connected"
    assert h.stats()["orders_total"] == 0                     # nothing was sent, nothing booked
    sized = h.sizing(signal())                                # but the size is still answerable
    assert sized["ok"] and sized["venue"] == "mt5" and sized["connected"] is False
    assert "not connected" in sized["spec_source"]


def test_a_login_with_no_terminal_is_reported_not_hidden(tmp_path):
    h = hub(tmp_path)
    status = h.configure({"login": "112594843", "password": "hunter2",
                          "server": "MetaQuotes-Demo", "mode": "mt5"})
    assert status["ready"] is True and status["connected"] is False
    assert status["terminal"]["error"]                         # the reason is shown, not swallowed
    assert "hunter2" not in json.dumps(status)                 # ...and the password never is
    assert status["creds"]["password"] == "••••••••"


def test_the_login_is_stored_locally_and_forgettable(tmp_path):
    store = CredStore(str(tmp_path / "broker" / "mt5.json"))
    h = hub(tmp_path)
    h.configure({"login": "112594843", "password": "hunter2", "server": "MetaQuotes-Demo"})
    saved = Path(h.store.path)
    assert saved.is_file()
    assert oct(saved.stat().st_mode)[-3:] == "600"             # not world-readable
    assert "hunter2" in saved.read_text()                      # local store, gitignored tree
    again = CredStore(str(saved)).load()
    assert again.login == "112594843" and again.ready()
    h.disconnect(forget=True)
    assert not saved.exists() and h.creds.login == ""
    assert store.load().login == ""                            # nothing left behind


def test_paper_sizing_works_for_the_other_classes_too(tmp_path):
    h = hub(tmp_path)
    sized = h.sizing({"symbol": "BTC/USDT", "class": "crypto", "entry": 61000.0, "stop": 59500.0})
    assert sized["ok"] and sized["unit"] == "units"
    assert sized["volume"] == pytest.approx(0.05, abs=0.001)   # $75 over a $1500 stop
    order = asyncio.run(h.place({"symbol": "AAPL", "class": "stocks", "side": "LONG",
                                 "entry": 224.0, "stop": 219.0, "target": 236.0, "id": "T-EQ"}))
    assert order["venue"] == "paper" and order["unit"] == "units" and order["volume"] > 0


# ---------------------------------------------------------------- auto-trade
def test_auto_trade_is_off_until_it_is_armed(tmp_path):
    h = hub(tmp_path)
    assert h.autotrade["on"] is False
    assert h.autotrade["classes"] == ["forex"]
    assert h.status()["autotrade"]["on"] is False


def test_only_the_armed_classes_are_placed_automatically(tmp_path):
    from soul.engine import Engine
    cfg = Config()
    cfg.mock_llm = True
    cfg.broker_store = str(tmp_path / "mt5.json")
    cfg.scout_enabled = False
    cfg.debate_enabled = False
    engine = Engine(cfg, EventBus())
    engine.broker = hub(tmp_path, autotrade=True, autotrade_classes=["forex"])
    entry = {"trade_id": "T-9", "symbol": "BTC/USDT", "side": "LONG", "decision": "ENTER",
             "entry": 61000.0, "stop": 59500.0, "target": 64000.0, "confidence": 70.0}
    trade = type("T", (), {"id": "T-9", "symbol": "BTC/USDT", "side": "LONG", "strategy": "breakout",
                           "entry": 61000.0, "stop": 59500.0, "target": 64000.0,
                           "score": 0.8, "rr": 2.0, "features": {}, "desk": None})()
    asyncio.run(engine._maybe_autotrade(entry, trade))
    assert engine.broker.stats()["orders_total"] == 0          # crypto is not armed
    assert "not armed" in engine.broker.autotrade["last"]

    entry2 = dict(entry, trade_id="T-10", symbol="EUR/USD", entry=1.0850, stop=1.0820, target=1.0912)
    trade2 = type("T", (), {"id": "T-10", "symbol": "EUR/USD", "side": "LONG", "strategy": "trend",
                            "entry": 1.0850, "stop": 1.0820, "target": 1.0912,
                            "score": 0.8, "rr": 2.0, "features": {}, "desk": None})()
    asyncio.run(engine._maybe_autotrade(entry2, trade2))
    assert engine.broker.stats()["open"] == 1                  # armed class went through
    assert entry2["broker_ticket"]
    assert engine.broker.autotrade["placed"] == 1


def test_a_refused_auto_place_does_not_crash_the_floor(tmp_path):
    from soul.engine import Engine
    cfg = Config()
    cfg.mock_llm = True
    cfg.broker_store = str(tmp_path / "mt5.json")
    cfg.scout_enabled = False
    cfg.debate_enabled = False
    engine = Engine(cfg, EventBus())
    engine.broker = hub(tmp_path, mode="mt5", autotrade=True)
    engine.broker.creds = engine.broker.creds.__class__(
        login="1", password="p", server="MetaQuotes-Demo", mode="mt5")
    entry = {"trade_id": "T-11", "symbol": "EUR/USD", "side": "LONG", "decision": "ENTER",
             "entry": 1.0850, "stop": 1.0820, "target": 1.0912, "confidence": 70.0}
    trade = type("T", (), {"id": "T-11", "symbol": "EUR/USD", "side": "LONG", "strategy": "trend",
                           "entry": 1.0850, "stop": 1.0820, "target": 1.0912,
                           "score": 0.8, "rr": 2.0, "features": {}, "desk": None})()
    asyncio.run(engine._maybe_autotrade(entry, trade))         # must not raise
    assert engine.broker.autotrade["skipped"] == 1
    assert "not connected" in engine.broker.autotrade["last"]


# ---------------------------------------------------------------- the list
def test_the_scanned_list_carries_the_votes_and_the_name(tmp_path):
    from soul.engine import Engine
    cfg = Config()
    cfg.mock_llm = True
    cfg.broker_store = str(tmp_path / "mt5.json")
    cfg.scout_enabled = False
    cfg.debate_enabled = False
    engine = Engine(cfg, EventBus())
    engine.broker = hub(tmp_path)
    trade = type("T", (), {"id": "T-12", "symbol": "EUR/USD", "side": "LONG", "strategy": "trend",
                           "entry": 1.0850, "stop": 1.0820, "target": 1.0912,
                           "score": 0.8, "rr": 2.0, "features": {}, "desk": None})()
    engine.trade_log = [{"trade_id": "T-12", "symbol": "EUR/USD", "side": "LONG",
                         "strategy": "trend", "decision": "ENTER", "approvals": 4, "rejections": 1,
                         "confidence": 68.4, "entry": 1.0850, "stop": 1.0820, "target": 1.0912,
                         "rr": 2.07, "ts": 1.0, "verdicts": [], "ceo": None}]
    rows = engine.signals_view()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Euro / US Dollar" and row["class"] == "forex"
    assert row["placeable"] is True and row["venue"] == "paper"
    assert row["sizing"]["ok"] and row["sizing"]["volume"] > 0
    order = asyncio.run(engine.place_signal("T-12"))
    assert order["symbol"] == "EUR/USD"
    rows = engine.signals_view()
    assert rows[0]["ticket"] == order["ticket"]
    assert rows[0]["placeable"] is False and "already placed" in rows[0]["blocked"]
    with pytest.raises(BrokerError):
        asyncio.run(engine.place_signal("T-12"))


def test_a_rejected_trade_is_not_placeable(tmp_path):
    from soul.engine import Engine
    cfg = Config()
    cfg.mock_llm = True
    cfg.broker_store = str(tmp_path / "mt5.json")
    cfg.scout_enabled = False
    cfg.debate_enabled = False
    engine = Engine(cfg, EventBus())
    engine.broker = hub(tmp_path)
    engine.trade_log = [{"trade_id": "T-13", "symbol": "GBP/JPY", "side": "SHORT",
                         "decision": "SKIP", "approvals": 1, "rejections": 4, "confidence": 30.0,
                         "entry": 188.40, "stop": 189.00, "target": 187.20, "rr": 2.0,
                         "ts": 1.0, "verdicts": [], "ceo": None}]
    row = engine.signals_view()[0]
    assert row["placeable"] is False and row["blocked"] == "the council said no"
    order = asyncio.run(engine.place_signal("T-13"))
    # the operator can still take a trade the council refused — it is their
    # account — but the button is disabled and the row says why
    assert order["symbol"] == "GBP/JPY" and order["venue"] == "paper"


def test_the_engine_snapshot_carries_execution(tmp_path):
    from soul.engine import Engine
    cfg = Config()
    cfg.mock_llm = True
    cfg.broker_store = str(tmp_path / "mt5.json")
    cfg.scout_enabled = False
    cfg.debate_enabled = False
    engine = Engine(cfg, EventBus())
    state = engine.state()
    assert "orders" in state and "open" in state["orders"] and "closed" in state["orders"]
    assert state["broker"]["venue"] == "paper"
    assert state["broker"]["routing"]["forex"]["venue"] == "paper"
    assert state["signals"] == []


def test_the_size_is_taken_from_the_price_the_order_actually_fills_at(tmp_path):
    """A scan ages. Sizing off the plan's entry is how a 0.5% trade becomes a 1% one."""
    h = hub(tmp_path)
    plan = signal(entry=1.0850, stop=1.0820)          # a 30-pip stop at the plan
    PRICES["EUR/USD"] = 1.0900                        # the market has run 50 pips
    order = asyncio.run(h.place(plan, risk_pct=0.5))
    assert order["entry"] == pytest.approx(1.0900)    # filled where the market is
    assert order["plan_entry"] == pytest.approx(1.0850)
    assert order["slippage_pips"] == pytest.approx(50.0)
    assert order["volume"] < 0.25                     # ...and therefore a smaller size
    # never MORE than the budget was asked for; only the lot step trims it
    assert 0 < order["risk"] <= 75.0001
    assert order["risk"] >= 0.9 * 75.0


def test_a_trade_whose_stop_the_market_has_already_gone_through_is_refused(tmp_path):
    h = hub(tmp_path)
    PRICES["EUR/USD"] = 1.0810                        # below the 1.0820 stop
    with pytest.raises(BrokerError) as err:
        asyncio.run(h.place(signal()))
    assert err.value.reason == "invalidated"
    assert h.stats()["orders_total"] == 0
    # the other way round for a short whose stop is above the market
    PRICES["EUR/USD"] = 1.0870
    with pytest.raises(BrokerError):
        asyncio.run(h.place(signal(side="SHORT", entry=1.0850, stop=1.0820, target=1.0800)))


def test_a_trade_that_has_already_run_to_its_target_is_refused(tmp_path):
    """Filling a long above its own target leaves nothing to take — and then a
    "target" exit books a loss on a trade that looked planned."""
    h = hub(tmp_path)
    PRICES["EUR/USD"] = 1.0950                        # past the 1.0912 target
    with pytest.raises(BrokerError) as err:
        asyncio.run(h.place(signal()))
    assert err.value.reason == "target_reached"
    assert h.stats()["orders_total"] == 0


def test_the_order_records_the_reward_that_is_left_from_the_fill(tmp_path):
    h = hub(tmp_path)
    PRICES["EUR/USD"] = 1.0870                        # halfway through the plan
    order = asyncio.run(h.place(signal()))            # stop 1.0820, target 1.0912
    assert order["rr_at_fill"] == pytest.approx((1.0912 - 1.0870) / (1.0870 - 1.0820), abs=0.01)
    assert order["rr_at_fill"] < order["rr"] if "rr" in order else True
