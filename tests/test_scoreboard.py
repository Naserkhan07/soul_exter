"""The desk record: who was right, what it was worth, and what it changes."""
from __future__ import annotations

from soul.scoreboard import MIN_EVIDENCE, Scoreboard


def settle_many(sb: Scoreboard, key: str, verdict: str, pnls, risk: float = 100.0) -> None:
    for pnl in pnls:
        sb.settle(key, verdict, pnl, risk)


def test_a_desk_is_unproven_until_it_has_a_record() -> None:
    sb = Scoreboard()
    settle_many(sb, "QUANT", "APPROVE", [10, 10, 10], risk=100)
    assert sb.hit_rate("QUANT") is None          # three calls is not a record
    assert sb.weight("QUANT") == 1.0
    assert sb.summary() == []


def test_the_record_counts_both_sides_of_the_desk() -> None:
    sb = Scoreboard()
    settle_many(sb, "RISK", "APPROVE", [50, -100, 80, 20], risk=100)   # 3 of 4 right
    settle_many(sb, "COMPLIANCE", "REJECT", [-40, -60, 90, -10], risk=100)  # 3 of 4 right
    assert sb.hit_rate("RISK") == 0.75
    assert sb.hit_rate("COMPLIANCE") == 0.75
    # a REJECT earns no R of its own: it is scored on being right, not on P&L
    assert sb.snapshot()["desks"]["COMPLIANCE"]["r_sum"] == 0.0
    assert sb.snapshot()["desks"]["RISK"]["r_sum"] == 0.5


def test_weight_bends_with_the_record_but_never_past_the_bounds() -> None:
    sb = Scoreboard()
    settle_many(sb, "NEWS", "APPROVE", [1, 1, 1, 1], risk=100)
    assert sb.weight("NEWS") == 1.25
    settle_many(sb, "MACRO", "APPROVE", [-1, -1, -1, -1], risk=100)
    assert sb.weight("MACRO") == 0.75
    assert 0.75 <= sb.book_weight(["NEWS", "MACRO"]) <= 1.25


def test_the_prompt_summary_says_what_a_desk_is_worth() -> None:
    sb = Scoreboard()
    settle_many(sb, "QUANT", "APPROVE", [100, 100, -50, 100, 100], risk=100)
    line = sb.summary(["QUANT"])[0]
    assert "QUANT" in line and "4/5" in line and "R" in line


def test_snapshot_is_json_shaped_for_the_floor() -> None:
    sb = Scoreboard()
    settle_many(sb, "CEO", "APPROVE", [30, -20, 40, 10], risk=100)
    snap = sb.snapshot()
    assert snap["min_evidence"] == MIN_EVIDENCE
    row = snap["desks"]["CEO"]
    assert row["proven"] is True and row["calls"] == 4
    assert 0 <= row["hit_rate"] <= 1 and row["pnl"] == 60.0
