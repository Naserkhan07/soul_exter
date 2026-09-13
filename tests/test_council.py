"""Vote routing, verdict parsing, the desk, and the end-to-end flow."""
from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soul.brains.base import CABINS, CEO_SPEC, build_cabin_prompt, build_ceo_prompt, parse_verdict
from soul.brains.mock import MockBrain
from soul.config import Config, CouncilRules
from soul.council import Council
from soul.desk import PaperDesk
from soul.models import TradeCandidate, Verdict


class RecordingBus:
    def __init__(self):
        self.events = []

    async def publish(self, kind, **payload):
        self.events.append({"type": kind, "payload": payload})
        return {"type": kind}

    def of(self, kind):
        return [e for e in self.events if e["type"] == kind]


def trade(**kw) -> TradeCandidate:
    base = dict(symbol="SOL/USDT", side="LONG", strategy="MOMENTUM_BREAKOUT",
                entry=100.0, stop=98.0, target=106.0, score=0.6,
                features={"rr": 3.0, "risk_pct": 2.0, "rsi": 58.0, "vol_z": 1.8, "ema_stack": 1.0,
                          "regime": 1.0, "atr_rank": 40.0, "atr_pct": 1.4, "rel_strength": 1.2,
                          "corr_proxy": 1.4, "bb_width_rank": 45.0, "range_pos": 0.6,
                          "btc_ret_12": 0.8, "spread_proxy_bps": 3.0})
    base.update(kw)
    return TradeCandidate(**base)


# ── routing ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("approvals,expected", [
    (5, "FINALIZED"),
    (4, "ESCALATED"),
    (3, "ESCALATED"),
    (2, "ESCALATED"),
    (1, "ESCALATED"),
    (0, "REJECTED"),
])
def test_vote_routing(approvals, expected):
    assert CouncilRules().route(approvals, 5) == expected


def test_routing_survives_partial_answers():
    rules = CouncilRules()
    assert rules.route(0, 0) == "ESCALATED"      # nothing answered yet
    assert rules.route(3, 3) == "ESCALATED"      # 3 of 3 answered, split
    assert rules.route(2, 5) == "ESCALATED"


# ── verdict parsing ──────────────────────────────────────────────────────
def test_parse_clean_json():
    v = parse_verdict('{"verdict":"APPROVE","confidence":72,"reason":"R:R 2.1 clears the bar",'
                      '"risk_flags":["wide stop"],"adjustment":{"size_multiplier":0.7}}')
    assert v["verdict"] == "APPROVE" and v["confidence"] == 72
    assert v["risk_flags"] == ["wide stop"]
    assert v["adjustment"]["size_multiplier"] == 0.7


def test_parse_json_wrapped_in_prose_and_code_fence():
    raw = ('Sure, here is my assessment.\n```json\n{"verdict": "REJECT", "confidence": 64, '
           '"reason": "stop too tight"}\n```\nLet me know if you need more.')
    v = parse_verdict(raw)
    assert v["verdict"] == "REJECT" and v["confidence"] == 64


def test_parse_trailing_commas_and_fractional_confidence():
    v = parse_verdict('{"verdict":"APPROVE","confidence":0.8,"reason":"ok","risk_flags":[],}')
    assert v["verdict"] == "APPROVE"
    assert v["confidence"] == 80.0        # 0..1 answers are rescaled


def test_parse_keyword_fallback_when_not_json():
    v = parse_verdict("I would APPROVE this one, confidence 55, the tape supports it.")
    assert v["verdict"] == "APPROVE"
    assert v["confidence"] == 55
    assert "unstructured_output" in v["risk_flags"]


def test_parse_empty_response_abstains():
    v = parse_verdict("")
    assert v["verdict"] == "ABSTAIN"
    assert v["risk_flags"] == ["no_model_output"]


def test_reject_zeroes_the_size_multiplier():
    v = parse_verdict('{"verdict":"REJECT","confidence":80,"reason":"no","adjustment":{"size_multiplier":1.0}}')
    assert v["adjustment"]["size_multiplier"] == 0.0


# ── prompts ──────────────────────────────────────────────────────────────
def test_cabin_prompt_carries_the_packet_and_prior_votes():
    prior = [Verdict(cabin="QUANT", model="m", verdict="APPROVE", confidence=70, reason="clean setup")]
    p = build_cabin_prompt(CABINS[1], trade(), {"market": {"price": 100, "change_pct": 1.2, "high": 101,
                                                           "low": 99, "regime": "risk-on",
                                                           "btc_change_pct": 0.9, "vol_rank": 40,
                                                           "spread_bps": 3},
                                                 "portfolio": {"equity": 15000, "cash": 15000,
                                                               "positions": [], "max_positions": 8,
                                                               "planned_risk_pct": 0.0,
                                                               "risk_budget_pct": 0.75}}, prior)
    assert "SOL/USDT" in p and "R:R" in p
    assert "QUANT" in p and "clean setup" in p        # the desk sees earlier desks
    assert "JSON" in p


def test_ceo_prompt_summarises_the_split():
    verdicts = [
        Verdict(cabin="QUANT", model="m", verdict="APPROVE", confidence=80, reason="good rr"),
        Verdict(cabin="RISK", model="m", verdict="REJECT", confidence=77, reason="stop too wide",
                risk_flags=["wide stop"]),
        Verdict(cabin="NEWS", model="m", verdict="APPROVE", confidence=61, reason="narrative ok"),
        Verdict(cabin="MACRO", model="m", verdict="REJECT", confidence=55, reason="fighting the tape"),
        Verdict(cabin="COMPLIANCE", model="m", verdict="APPROVE", confidence=66, reason="within limits"),
    ]
    ctx = {"market": {"price": 100, "change_pct": 1.0, "high": 101, "low": 99, "regime": "risk-on",
                      "btc_change_pct": 0.9, "vol_rank": 40, "spread_bps": 3},
           "portfolio": {"equity": 15000, "cash": 15000, "positions": [], "max_positions": 8,
                         "planned_risk_pct": 0.0, "risk_budget_pct": 0.75}}
    p = build_ceo_prompt(CEO_SPEC, trade(), verdicts, ctx)
    assert "3 approve / 2 reject" in p
    assert "stop too wide" in p


# ── the council ──────────────────────────────────────────────────────────
def make_council(cfg, monkey_brain=None):
    bus = RecordingBus()
    brains = {c.key: MockBrain(c, latency=0.0, jitter=0.0) for c in CABINS + [CEO_SPEC]}
    if monkey_brain:
        brains.update(monkey_brain)
    return Council(cfg, brains, bus), bus


def ctx_fn():
    return {"market": {"price": 100, "change_pct": 1.0, "high": 101, "low": 99, "regime": "risk-on",
                       "btc_change_pct": 0.8, "vol_rank": 40, "spread_bps": 3},
            "portfolio": {"equity": 15000, "cash": 15000, "positions": [], "max_positions": 8,
                          "planned_risk_pct": 0.0, "risk_budget_pct": 0.75}}


class FixedBrain:
    """A cabin that always answers the same way — used to pin the routing."""

    kind = "fixed"

    def __init__(self, spec, verdict, confidence=70.0):
        self.spec = spec
        self._verdict, self._conf = verdict, confidence

    async def judge(self, trade, ctx, prior=None, stage=1):
        return Verdict(cabin=self.spec.key, model="fixed", verdict=self._verdict,
                       confidence=self._conf, reason=f"fixed {self._verdict}",
                       stage=stage, trade_id=trade.id)


def test_unanimous_approval_goes_straight_to_the_entry_door():
    cfg = Config(mock_llm=True)
    brains = {c.key: FixedBrain(c, "APPROVE") for c in CABINS}
    council, bus = make_council(cfg, brains)
    result = asyncio.run(council.review(trade(), ctx_fn))
    assert result.route == "FINALIZED" and result.decision == "ENTER"
    assert result.approvals == 5
    assert result.ceo_verdict is None                     # CEO was never woken
    assert bus.of("entry_door") and not bus.of("exit_door")
    assert len(bus.of("cabin_verdict")) == 5


def test_unanimous_rejection_walks_out_the_exit_door():
    cfg = Config(mock_llm=True)
    brains = {c.key: FixedBrain(c, "REJECT") for c in CABINS}
    council, bus = make_council(cfg, brains)
    result = asyncio.run(council.review(trade(), ctx_fn))
    assert result.route == "REJECTED" and result.decision == "SKIP"
    assert bus.of("exit_door") and not bus.of("entry_door")
    assert not bus.of("escalated")


def test_split_council_is_escalated_to_the_ceo():
    cfg = Config(mock_llm=True)
    brains = {c.key: FixedBrain(c, "APPROVE") for c in CABINS[:4]}
    brains["COMPLIANCE"] = FixedBrain(CABINS[4], "REJECT")
    brains["CEO"] = FixedBrain(CEO_SPEC, "APPROVE", confidence=64)
    council, bus = make_council(cfg, brains)
    result = asyncio.run(council.review(trade(), ctx_fn))
    assert result.route == "ESCALATED"
    assert result.approvals == 4 and result.rejections == 1
    assert result.ceo_verdict is not None and result.ceo_verdict.verdict == "APPROVE"
    assert result.decision == "ENTER"
    assert bus.of("escalated") and bus.of("ceo_verdict") and bus.of("entry_door")
    assert council.stats["escalated"] == 1 and council.stats["ceo_approved"] == 1


def test_ceo_can_veto_a_majority():
    cfg = Config(mock_llm=True)
    brains = {c.key: FixedBrain(c, "APPROVE") for c in CABINS[:3]}
    brains["RISK"] = FixedBrain(CABINS[1], "REJECT")
    brains["MACRO"] = FixedBrain(CABINS[3], "REJECT")
    # Every cabin must be named explicitly: any key left out falls back to the
    # mock brain, whose verdict is seeded from the trade's random id, and the
    # test then fails at random. (That is exactly how this one used to flake.)
    brains["COMPLIANCE"] = FixedBrain(CABINS[4], "APPROVE")
    brains["CEO"] = FixedBrain(CEO_SPEC, "REJECT", confidence=81)
    council, bus = make_council(cfg, brains)
    result = asyncio.run(council.review(trade(), ctx_fn))
    assert result.approvals == 3 and result.route == "ESCALATED"
    assert result.decision == "SKIP"
    assert bus.of("exit_door") and not bus.of("entry_door")


def test_every_trade_visits_every_cabin_in_order():
    cfg = Config(mock_llm=True)
    council, bus = make_council(cfg)
    asyncio.run(council.review(trade(), ctx_fn))
    seen = [e["payload"]["cabin"] for e in bus.of("cabin_verdict")]
    assert seen == ["QUANT", "RISK", "NEWS", "MACRO", "COMPLIANCE"]
    walks = [(e["payload"]["from"], e["payload"]["to"]) for e in bus.of("trader_walks")]
    assert walks[0][1] == "QUANT"
    assert all(w[1] in {"QUANT", "RISK", "NEWS", "MACRO", "COMPLIANCE", "CEO"} for w in walks)


def _priors_seen(cfg):
    """How many earlier verdicts each cabin was handed."""
    seen: dict[str, int] = {}

    class Spy(MockBrain):
        async def judge(self, trade, ctx, prior=None, stage=1):
            seen[self.spec.key] = len(prior or [])
            return await super().judge(trade, ctx, prior, stage)

    brains = {c.key: Spy(c, latency=0.0, jitter=0.0) for c in CABINS + [CEO_SPEC]}
    council = Council(cfg, brains, RecordingBus())
    asyncio.run(council.review(trade(), ctx_fn))
    return seen


def test_single_cabin_queue_every_cabin_reads_all_its_predecessors():
    """SOUL_WAVE_MODE=0: the literal reading of the flow the project is about."""
    seen = _priors_seen(Config(mock_llm=True, wave_mode=False))
    assert seen["QUANT"] == 0          # first to speak
    assert seen["RISK"] == 1           # saw QUANT
    assert seen["NEWS"] == 2           # saw QUANT + RISK
    assert seen["MACRO"] == 3
    assert seen["COMPLIANCE"] == 4     # saw all four


def test_wave_mode_keeps_cross_wave_visibility_for_speed():
    """Default: wave 1 runs in parallel, wave 2 sees all of wave 1."""
    seen = _priors_seen(Config(mock_llm=True, wave_mode=True))
    assert seen["QUANT"] == seen["RISK"] == seen["NEWS"] == 0
    assert seen["MACRO"] == 3 and seen["COMPLIANCE"] == 3


# ── paper desk ───────────────────────────────────────────────────────────
def test_desk_sizes_by_risk_and_respects_caps():
    cfg = Config(risk_per_trade_pct=1.0, max_session_risk_pct=3.0, max_open_positions=2)
    bus = RecordingBus()
    desk = PaperDesk(cfg, bus)

    class R:
        approvals, confidence, verdicts, ceo_verdict = 5, 70.0, [], None

    budget_before = desk.risk_budget()                   # 1% of $15,000 = $150

    # a 4% stop means $150 of risk buys a $3,750 position, so the exposure cap
    # is not what stops the third trade — the position count is.
    async def run():
        for i, sym in enumerate(["SOL/USDT", "ADA/USDT", "DOGE/USDT"]):
            await desk.open(trade(id=f"T{i}", symbol=sym, entry=100.0, stop=96.0, target=112.0), R())
    asyncio.run(run())
    assert len(desk.positions) == 2                      # third blocked by the cap
    assert len(bus.of("order_blocked")) == 1
    pos = next(iter(desk.positions.values()))
    # $4 of risk per unit and a $150 budget -> 37.5 units, $150 of risk.
    assert pos.qty == pytest.approx(budget_before / 4.0, rel=1e-6)
    assert pos.risk == pytest.approx(budget_before, rel=1e-6)
    assert pos.size == pytest.approx(pos.qty * pos.entry)
    assert desk.equity() == pytest.approx(desk.starting_cash, rel=1e-9), \
        "opening at market must not change equity"


def test_desk_applies_the_cabins_size_multiplier():
    cfg = Config(risk_per_trade_pct=1.0)
    desk = PaperDesk(cfg, RecordingBus())

    class V:
        verdict, adjustment = "APPROVE", {"size_multiplier": 0.5}

    class R:
        approvals, confidence, verdicts, ceo_verdict = 5, 60.0, [V()], None

    budget = desk.risk_budget()                          # captured before the fill

    async def run():
        await desk.open(trade(symbol="SOL/USDT", entry=100.0, stop=99.0, target=103.0), R())
    asyncio.run(run())
    pos = next(iter(desk.positions.values()))
    # half size -> $75 of risk; $1 of risk buys one unit here, so 75 units
    # and $7,500 of notional exposure.
    assert pos.risk == pytest.approx(budget * 0.5, rel=1e-6)
    assert pos.qty == pytest.approx(budget * 0.5, rel=1e-6)
    assert pos.notional == pytest.approx(pos.qty * 100.0, rel=1e-6)


def test_desk_never_exceeds_the_session_risk_budget():
    cfg = Config(risk_per_trade_pct=1.0, max_open_positions=20)
    desk = PaperDesk(cfg, RecordingBus())

    class R:
        approvals, confidence, verdicts, ceo_verdict = 5, 70.0, [], None

    budget = desk.risk_budget()

    async def run():
        for i in range(6):
            await desk.open(trade(id=f"T{i}", symbol=f"S{i}/USDT", entry=100.0, stop=99.0,
                                  target=103.0), R())
    asyncio.run(run())
    total_risk = sum(abs(p.entry - p.stop) * p.qty for p in desk.positions.values())
    assert total_risk <= budget + 1e-6, f"committed {total_risk} of a {budget} session budget"
    assert total_risk > 0
    assert len(desk.positions) < 6, "sizing should stop adding risk once the budget is used"


def test_stop_and_target_close_the_position():
    cfg = Config(risk_per_trade_pct=1.0)
    bus = RecordingBus()
    desk = PaperDesk(cfg, bus)

    class R:
        approvals, confidence, verdicts, ceo_verdict = 5, 70.0, [], None

    async def run():
        await desk.open(trade(symbol="SOL/USDT", entry=100.0, stop=98.0, target=104.0), R())
        pid = next(iter(desk.positions))
        await desk.mark({"SOL/USDT": 103.0})
        assert pid in desk.positions, "should still be open below the target"
        await desk.mark({"SOL/USDT": 104.5})            # tag the target
    asyncio.run(run())
    assert not desk.positions
    closed = bus.of("position_closed")
    assert closed and closed[0]["payload"]["exit_reason"] == "TARGET"
    assert closed[0]["payload"]["pnl"] > 0
    assert desk.stats()["wins"] == 1


def test_stop_out_loses_money_and_frees_cash():
    cfg = Config(risk_per_trade_pct=1.0)
    bus = RecordingBus()
    desk = PaperDesk(cfg, bus)

    class R:
        approvals, confidence, verdicts, ceo_verdict = 5, 70.0, [], None

    async def run():
        await desk.open(trade(symbol="SOL/USDT", entry=100.0, stop=98.0, target=104.0), R())
        await desk.mark({"SOL/USDT": 97.5})
    asyncio.run(run())
    assert not desk.positions
    pnl = bus.of("position_closed")[0]["payload"]["pnl"]
    assert pnl < 0
    assert desk.stats()["losses"] == 1


def test_desk_refuses_a_duplicate_symbol():
    cfg = Config(risk_per_trade_pct=1.0)
    bus = RecordingBus()
    desk = PaperDesk(cfg, bus)

    class R:
        approvals, confidence, verdicts, ceo_verdict = 5, 70.0, [], None

    async def run():
        await desk.open(trade(symbol="SOL/USDT", entry=100.0, stop=99.0, target=103.0), R())
        again = await desk.open(trade(id="T-DUP", symbol="SOL/USDT", entry=100.0, stop=99.0, target=103.0), R())
        assert again is None
    asyncio.run(run())
    assert "already holding" in bus.of("order_blocked")[0]["payload"]["reason"]


# ── engines of the real thing ────────────────────────────────────────────
def test_mock_council_produces_a_spread_of_outcomes():
    """Not a correctness test — a calibration guard.

    If a future change makes every mock trade unanimous (or every trade
    escalate), the demo stops showing the door/CEO behaviour this project is
    about, so fail loudly.
    """
    cfg = Config(mock_llm=True)
    # Each mock verdict is seeded from the trade's (random) id, so a single deck
    # is a random draw. This guard is therefore statistical: it scores a few
    # dozen trades with the latency turned off, which makes the flake rate
    # negligible while keeping the test fast.
    cfg.mock_latency = 0.0
    cfg.mock_jitter = 0.0
    council, bus = make_council(cfg)
    from soul.market import MarketFeed
    from soul.scanner import Scanner

    async def run():
        cfg2 = Config(mock_llm=True, market_source="sim", min_score=0.05, max_candidates_per_scan=4)
        mkt = MarketFeed(cfg2)
        await mkt.start()
        scanner = Scanner(cfg2, mkt)
        deck = []
        seen = set()
        for _ in range(25):
            scanner.cooldowns.clear()
            for t in await scanner.scan(force=True):
                k = (t.symbol, t.side, t.strategy)
                if k not in seen:
                    seen.add(k)
                    deck.append(t)
            for _ in range(4):
                mkt._step_simulator()
        return deck

    deck = asyncio.run(run())
    assert len(deck) >= 8, "scanner should find setups in the simulator"

    # The spread is a property of the brains, not of whatever tape the simulator
    # happened to print, so drive the histogram from a FIXED deck. Deriving it
    # from the live simulator made this guard flaky: the simulator advances with
    # wall-clock time, so a slow machine scores a different deck.
    # Seeded, so the deck is identical on every run, but sampled across the whole
    # feature range the scanner actually produces — including the weak, late and
    # conflicted setups that the cabins are supposed to push back on.
    rng = random.Random(20240913)
    fixed = []
    for i in range(40):
        t = trade(symbol=f"TST{i}/USDT",
                  side="LONG" if i % 2 == 0 else "SHORT",
                  score=rng.uniform(0.05, 0.95),
                  entry=100.0, stop=100.0 - rng.uniform(0.4, 3.0),
                  target=100.0 + rng.uniform(0.8, 6.0))
        t.features = dict(t.features)
        t.features.update({
            "rsi": rng.uniform(20.0, 85.0),
            "rel_strength": rng.uniform(-4.0, 4.0),
            "vol_z": rng.uniform(-1.0, 3.5),
            "regime": float(rng.choice([-1.0, 0.0, 1.0])),
            "atr_rank": rng.uniform(5.0, 95.0),
            "atr_pct": rng.uniform(0.2, 3.0),
            "range_pos": rng.uniform(0.0, 1.0),
            "bb_width_rank": rng.uniform(0.0, 100.0),
            "btc_ret_12": rng.uniform(-3.0, 3.0),
            "corr_proxy": rng.uniform(0.8, 2.0),
            "ema_stack": float(rng.choice([-1.0, 1.0])),
            "rr": round(rng.uniform(0.8, 3.5), 2),
        })
        fixed.append(t)

    histogram = {}
    entries = 0
    for t in fixed:
        r = asyncio.run(council.review(t, ctx_fn))
        histogram[r.approvals] = histogram.get(r.approvals, 0) + 1
        entries += 1 if r.decision == "ENTER" else 0
    assert len(histogram) >= 3, f"mock council is too uniform: {histogram}"
    assert any(k >= 4 for k in histogram), f"no near-consensus approvals: {histogram}"
    assert any(k <= 1 for k in histogram), f"no near-consensus rejections: {histogram}"
    assert 0 < entries < len(fixed), "every trade took the same door"
