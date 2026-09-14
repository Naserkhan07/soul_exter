"""The desks are trained: curriculum, settled decisions, and adapters.

These tests cover the loop that makes a desk better than it was an hour ago —
the dataset it is trained on, and the fact that a verdict is only labelled once
the position that came out of it has actually closed.
"""
import json

import pytest

from soul.config import load_config
from soul.models import CouncilResult, TradeCandidate, Verdict
from soul.training import DESKS, TrainingBook


def _trade(trade_id: str = "T-TEST01") -> TradeCandidate:
    return TradeCandidate(
        symbol="ARB/USDT", side="SHORT", strategy="MOMENTUM_BREAKOUT",
        entry=0.612, stop=0.635, target=0.560, score=0.71,
        features={"rsi": 38.0, "vol_z": 1.4, "ema_stack": -1.0, "regime": -0.5},
        id=trade_id,
    )


def _result(trade: TradeCandidate, approve: bool = True) -> CouncilResult:
    result = CouncilResult(trade=trade)
    for i, (cabin, verdict) in enumerate(
        [("QUANT", "APPROVE" if approve else "REJECT"),
         ("RISK", "REJECT" if approve else "APPROVE"),
         ("NEWS", "REJECT"),
         ("MACRO", "APPROVE"),
         ("COMPLIANCE", "REJECT")]
    ):
        result.verdicts.append(Verdict(
            cabin=cabin, model="test", verdict=verdict, confidence=62,
            reason=f"{cabin} read the packet", risk_flags=["stop inside the noise band"],
            stage=1 + i // 3,
        ))
    result.ceo_verdict = Verdict(
        cabin="CEO", model="test", verdict="APPROVE" if approve else "REJECT",
        confidence=58, reason="head of desk ruled", risk_flags=["event risk"],
        stage=9,
    )
    result.approvals = sum(1 for v in result.verdicts if v.verdict == "APPROVE")
    result.rejections = len(result.verdicts) - result.approvals
    result.decision = "ENTER" if approve else "SKIP"
    return result


@pytest.fixture()
def book(tmp_path):
    cfg = load_config()
    cfg.training_dataset = str(tmp_path / "desk-sft.jsonl")
    cfg.adapters_dir = str(tmp_path / "adapters")
    return TrainingBook(cfg)


# --------------------------------------------------------------- curriculum --
def test_curriculum_covers_every_desk(book):
    rows = book.curriculum_rows()
    desks = {r["meta"]["desk"] for r in rows}
    assert desks == set(DESKS)
    assert len(rows) == 120                       # 6 desks x (10 seeds + 10 playbook rules)


def test_every_row_is_a_chat_triple(book):
    for row in book.curriculum_rows():
        roles = [m["role"] for m in row["messages"]]
        assert roles == ["system", "user", "assistant"]
        assert all(m["content"].strip() for m in row["messages"])
        # the system prompt is the desk's own, playbook included
        assert "HOUSE PLAYBOOK" in row["messages"][0]["content"]


def test_rows_are_prompted_in_the_desks_own_name(book):
    for row in book.curriculum_rows():
        desk = row["meta"]["desk"]
        spec = book._spec(desk)
        assert (spec.name or desk) in row["messages"][0]["content"]


# ------------------------------------------------------------------ settled --
def test_a_settled_win_rewards_the_approvers_and_reflects_on_the_refusers(book):
    trade = _trade()
    result = _result(trade, approve=True)
    book.note(trade, result, {})
    assert book.settle(trade.id, pnl=+120.5, risk=60.0, pnl_pct=2.4) == 6

    kinds = {(r["meta"]["desk"], r["meta"]["kind"]) for r in book.samples}
    assert ("QUANT", "settled") in kinds          # approved a winner: keep doing that
    assert ("RISK", "reflection") in kinds        # refused a winner: smaller yes, not a veto

    reflection = next(r for r in book.samples
                      if r["meta"]["desk"] == "RISK" and r["meta"]["kind"] == "reflection")
    body = json.loads(reflection["messages"][2]["content"])
    assert body["verdict"] == "APPROVE"
    assert body["adjustment"]["size_multiplier"] == 0.5
    assert reflection["meta"]["outcome"] == "win" and reflection["meta"]["right"] is False


def test_a_settled_loss_trains_the_approver_on_its_own_flags(book):
    trade = _trade("T-TEST02")
    result = _result(trade, approve=True)
    book.note(trade, result, {})
    assert book.settle(trade.id, pnl=-88.0, risk=60.0, pnl_pct=-1.8) == 6

    reflection = next(r for r in book.samples
                      if r["meta"]["desk"] == "QUANT" and r["meta"]["kind"] == "reflection")
    body = json.loads(reflection["messages"][2]["content"])
    assert body["verdict"] == "REJECT"
    assert body["risk_flags"]                       # the desk's own flags became the reason
    assert reflection["meta"]["weight"] > 1.0       # a real loss teaches harder than a drill

    # the desk that refused the loser is rewarded with its own refusal: refusing
    # a bad trade is the job, and it is trained exactly like being right on a winner
    refused = next(r for r in book.samples
                   if r["meta"]["desk"] == "RISK" and r["meta"]["kind"] == "settled")
    assert json.loads(refused["messages"][2]["content"])["verdict"] == "REJECT"
    assert refused["meta"]["right"] is True


def test_the_ceo_is_trained_on_its_own_decision(book):
    trade = _trade("T-TEST03")
    book.note(trade, _result(trade, approve=False), {})
    # never opened: the desk took no risk, so there is no outcome to learn from
    assert book.settle(trade.id, pnl=0.0) == 0
    trade2 = _trade("T-TEST04")
    book.note(trade2, _result(trade2, approve=True), {})
    book.settle(trade2.id, pnl=+40.0, risk=30.0, pnl_pct=1.1)
    assert any(r["meta"]["desk"] == "CEO" for r in book.samples)


def test_the_prompt_in_a_row_is_the_prompt_the_desk_was_given(book):
    trade = _trade("T-TEST05")
    book.note(trade, _result(trade, approve=True), {})
    book.settle(trade.id, pnl=-10.0, risk=20.0, pnl_pct=-0.4)
    row = next(r for r in book.samples if r["meta"]["desk"] == "QUANT")
    user = row["messages"][1]["content"]
    assert "TRADE PACKET" in user and "ARB/USDT" in user and "MOMENTUM_BREAKOUT" in user


# ---------------------------------------------------------------- the room ---
def test_a_rule_agreed_in_the_room_is_trained_into_every_desk(book):
    lessons = [{"text": "Rule written: correlated tickets are one risk",
                "topic": "SOL/USDT LONG", "round": 3, "ts": 1.0}]
    rows = book.lesson_rows(lessons)
    assert len(rows) == len(DESKS)
    assert {r["meta"]["desk"] for r in rows} == set(DESKS)
    assert all("correlated tickets" in r["messages"][2]["content"] for r in rows)


# -------------------------------------------------------------- the dataset --
def test_build_writes_jsonl_and_a_manifest(book):
    trade = _trade("T-TEST06")
    book.note(trade, _result(trade, approve=True), {})
    book.settle(trade.id, pnl=+10.0, risk=20.0, pnl_pct=0.5)
    manifest = book.build(lessons=[{"text": "Rule written: half size", "topic": "x", "ts": 2.0}])

    path = book.dataset_path
    assert path.exists()
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) == manifest["rows"] == 120 + len(DESKS) + 6
    assert manifest["kinds"]["curriculum"] == 120
    assert manifest["kinds"]["lesson"] == len(DESKS)
    assert manifest["settled_trades"] == 6
    for row in rows:
        assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]


# --------------------------------------------------------------- adapters ----
def test_an_adapter_is_only_claimed_when_it_exists(book):
    stats = book.stats([])
    assert stats["trained_now"] is False
    assert all(v["adapter"] is None for v in stats["desks"].values())

    adapter = book.adapters_dir / "QUANT"
    adapter.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}")
    stats = book.stats([])
    assert stats["desks"]["QUANT"]["adapter"].endswith("QUANT")
    assert stats["desks"]["RISK"]["adapter"] is None
    assert stats["trained_now"] is True
