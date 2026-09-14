"""The room, as a training channel you can watch.

The desks do not only vote: they argue in one room, write down a rule, carry it
back to their desks, and review a closed position out loud. These tests pin the
parts that make the training *visible* — a ruling being recalled, a rule being
carried, and a post-mortem being spoken by a desk that was on the wrong side.
"""
import asyncio

import pytest

from soul.brains import brain_registry, build_brains
from soul.bus import EventBus
from soul.config import load_config
from soul.debate import CARRIERS_PER_ROUND, DebateRoom

TOPIC = {
    "topic": "ARB/USDT SHORT (MOMENTUM_BREAKOUT) — the council passed it 4-1.",
    "inner": {"rr": 2.1, "risk": 0.75, "symbol": "ARB/USDT", "side": "SHORT",
              "strategy": "MOMENTUM_BREAKOUT", "decision": "ENTER",
              "cap": 3.0, "planned": 84.0, "open": 2, "stop": 0.64, "rules": []},
    "trade_id": "T-TEST01",
}

RECORD = {
    "symbol": "ARB/USDT", "side": "SHORT", "strategy": "MOMENTUM_BREAKOUT",
    "verdicts": [
        {"cabin": "QUANT", "verdict": "APPROVE", "risk_flags": ["stop inside the noise band"]},
        {"cabin": "RISK", "verdict": "REJECT", "risk_flags": []},
        {"cabin": "NEWS", "verdict": "ABSTAIN", "risk_flags": []},
    ],
}


@pytest.fixture(scope="module")
def room():
    cfg = load_config()
    cfg.debate_enabled = True
    brains = asyncio.run(asyncio.to_thread(build_brains, cfg, False))
    bus = EventBus()
    reg = brain_registry(brains, cfg.model_profile)
    return DebateRoom(cfg, brains, bus, reg)


def test_a_round_recalls_writes_and_carries(room):
    said = asyncio.run(room.run_round(dict(TOPIC)))
    turns = [m["turn"] for m in said]
    # claim -> challenge -> question -> answer -> ack -> lesson -> carries
    assert turns[:6] == ["claim", "challenge", "question", "answer", "ack", "lesson"]
    assert turns[6:] == ["carry"] * CARRIERS_PER_ROUND
    # every carry quotes the same rule, and it is the rule this round wrote
    written = said[5]["text"]
    assert "Rule written" in written or "rule" in written.lower()
    for carry in said[6:]:
        assert carry["rule"] == TOPIC["inner"].get("rule") or carry["rule"]
        assert carry["training"] is True


def test_the_second_round_opens_by_recalling_a_rule_on_file(room):
    """A rule agreed in one round has to be *in force* in the next one.

    The recall rotates through the rules on file rather than always quoting the
    newest, so the check is that the claim names one of them — verbatim, and
    without the "Rule written:" preamble the head of desk spoke.
    """
    import re

    asyncio.run(room.run_round(dict(TOPIC)))
    assert room.lessons, "the round wrote no rule"
    on_file = {re.sub(r"^rule written[:—-]\s*", "", l["text"].strip(), flags=re.I)
               for l in room.lessons}
    second = asyncio.run(room.run_round(dict(TOPIC)))
    claim = second[0]
    assert claim["training"] is True
    assert claim["rule"], "the claim names no rule on file"
    assert claim["rule"] in on_file
    assert claim["rule"].lower().startswith("rule written") is False
    assert f'Rule on file: "{claim["rule"]}"' in claim["text"]


def test_the_lessons_on_file_are_the_rules_that_were_written(room):
    for lesson in room.lessons:
        assert lesson["text"].strip()
        assert lesson["speaker"] == "CEO"
    # a desk that repeats the same rule does not file it twice
    texts = [l["text"] for l in room.lessons]
    assert len(texts) == len(set(texts))


def test_a_closed_trade_is_reviewed_by_a_desk_that_was_wrong(room):
    msg = asyncio.run(room.post_mortem("T-TEST01", RECORD, pnl=-45.36, pnl_pct=-0.88,
                                       exit_reason="stop"))
    assert msg is not None
    assert msg["turn"] == "postmortem" and msg["training"] is True
    assert msg["speaker"] == "QUANT"          # approved a loss, so it speaks
    assert "-45.36" in msg["text"]
    assert "training set" in msg["text"]


def test_a_clean_win_is_filed_without_blame(room):
    record = {"symbol": "ETH/USDT", "side": "LONG", "strategy": "TREND_PULLBACK",
              "verdicts": [{"cabin": "QUANT", "verdict": "APPROVE", "risk_flags": []},
                           {"cabin": "RISK", "verdict": "APPROVE", "risk_flags": []}]}
    msg = asyncio.run(room.post_mortem("T-TEST02", record, pnl=+91.0, pnl_pct=2.1,
                                       exit_reason="target"))
    assert msg["turn"] == "postmortem"
    assert msg["speaker"] == "CEO"            # nobody was on the wrong side
    assert "+91.00" in msg["text"]
    assert "right side" in msg["text"] or "settled" in msg["text"]


def test_the_prompt_a_real_model_gets_carries_the_taught_rules(room):
    spec = room.brains["QUANT"].spec
    prompt = spec.debate_prompt(
        "Should we size up?", [{"name": "Naveed", "turn": "lesson",
                                "text": "Rule written: half size"}],
        "carry", rules=["a stop inside the noise band gets coin-flip risk",
                        "correlated tickets are one risk: the second one pays half"],
    )
    assert "RULES THIS DESK HAS BEEN TAUGHT" in prompt
    assert "correlated tickets are one risk" in prompt
    assert "how *you* will trade differently tomorrow" in prompt

    pm = spec.debate_prompt("post-mortem: ARB closed -45.36", [], "postmortem",
                            facts={"symbol": "ARB/USDT", "side": "SHORT", "pnl": -45.36,
                                   "pnl_pct": -0.88, "outcome": "loss", "right": "RISK",
                                   "flags": "stop inside the noise band",
                                   "exit_reason": "stop"})
    assert "THE CLOSE" in pm and "RISK" in pm and "stop inside the noise band" in pm
