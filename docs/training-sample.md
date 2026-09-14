# What “training the desks” means here

Every row of the training set is a real task a desk performs: the desk's own system prompt,
the packet it was shown, and the answer it should have given. `python -m soul.train
--dataset-only` builds the curriculum; a live session adds its own rows and exports them with
`curl /api/training/dataset` — this file is from a session a couple of minutes old.

- rows **168** — curriculum 120, lesson 30, reflection 8, settled 10
- by desk: CEO 28, COMPLIANCE 28, MACRO 28, NEWS 28, QUANT 28, RISK 28
- LoRA per desk: `python -m soul.train --desks all --epochs 2` (GPU box, no API keys)

## 1. Curriculum — the playbook, drilled

**desk=QUANT · kind=curriculum · weight=0.5**

```
SYSTEM     You are Dr. Amara Osei, Head of Quantitative Research. QUANT DESK on an autonomous multi-asset trading floor, and a working professional: you have spent your ca…
USER       Desk check — sizing. State the rule you trade by on this, and the condition that would make you break it.
ASSISTANT  Risk a fixed fraction per idea; the stop sets the size, never conviction. On my desk that shows up as: Decay: if the pattern is on every screen and every newsletter, assume the edge has been arbitraged to a fraction of what the study measured.
```

## 2. The room — a rule the desks agreed, trained into every desk

**desk=QUANT · kind=lesson · weight=0.8**

```
SYSTEM     You are Dr. Amara Osei, Head of Quantitative Research. QUANT DESK on an autonomous multi-asset trading floor, and a working professional: you have spent your ca…
USER       Desk meeting — the room argued: DOGE/USDT SHORT (VOLATILITY_SQUEEZE) — the council passed it 4-1. Is that the right call? What did we agree, and how does this desk implement it?
ASSISTANT  Rule written: when the council splits, the smaller size is the decision and the opinion is not. On the QUANT DESK: Decay: if the pattern is on every screen and every newsletter, assume the edge has been arbitraged to a fraction of what the study measured.
```

## 3. Settled — a desk that was right keeps its own verdict

**desk=NEWS · kind=settled · weight=1.0 · trade=DOGE/USDT SHORT · voted=REJECT · outcome=loss · pnl=-10.06**

```
SYSTEM     You are Lina Marchetti, Head of News Flow and Catalysts. NEWS DESK on an autonomous multi-asset trading floor, and a working professional: you have spent your c…
USER       A trader on the floor has proposed the trade below. NEWS DESK, this is your call. === TRADE PACKET === PAIR: DOGE/USDT DIRECTION: SHORT STRATEGY: VOLATILITY_SQUEEZE (scanner score 0.62/1.00, timeframe 5m) ENTRY: 0.130653 STOP: 0.131809 TARGET: 0.127377 RISK: 0.88% of entry REWARD: 2.51% R:R = 2.83 SIGNAL FEATURES: rsi=39.81, atr_pct=0.7375, atr_rank=3.333, vol_z=-1.32, bb_width_rank=2.778, ema20_slope=-0.069, ema50_slope=-0.03
ASSISTANT  {"verdict": "REJECT", "confidence": 72, "reason": "Tape read for DOGE/USDT: regime +1, RSI 40; tape +1, rel strength -2.06%, RSI 40. Flag: price is moving against the prevailing narrative. rejected by this desk.", "risk_flags": ["price is moving against the prevailing narrative", "no narrative energy — range is compressed"], "adjustment": {"size_multiplier": 1.0, "stop_pct": 0.88}}
```

## 4. Reflection — a desk that was wrong is trained on its own flags

**desk=QUANT · kind=reflection · weight=1.5 · trade=DOGE/USDT SHORT · voted=APPROVE · outcome=loss · pnl=-10.06**

```
SYSTEM     You are Dr. Amara Osei, Head of Quantitative Research. QUANT DESK on an autonomous multi-asset trading floor, and a working professional: you have spent your ca…
USER       A trader on the floor has proposed the trade below. QUANT DESK, this is your call. === TRADE PACKET === PAIR: DOGE/USDT DIRECTION: SHORT STRATEGY: VOLATILITY_SQUEEZE (scanner score 0.62/1.00, timeframe 5m) ENTRY: 0.130653 STOP: 0.131809 TARGET: 0.127377 RISK: 0.88% of entry REWARD: 2.51% R:R = 2.83 SIGNAL FEATURES: rsi=39.81, atr_pct=0.7375, atr_rank=3.333, vol_z=-1.32, bb_width_rank=2.778, ema20_slope=-0.069, ema50_slope=-0.0
ASSISTANT  {"verdict": "REJECT", "confidence": 74, "reason": "This one closed -10.06 (-0.88%) and nothing on my list caught it — that is the finding. On the next VOLATILITY_SQUEEZE setup I check what this one taught me: name the level that invalidates it before sizing it.", "risk_flags": ["no invalidation written before the entry"], "adjustment": {"size_multiplier": 0.25, "stop_pct": null}}
```

## Where the rows come from

| source | what it teaches | grows with |
|---|---|---|
| curriculum (120) | the house playbook and this desk's schooling, in its own voice | never — fixed |
| room rules (6 × rules agreed) | the rule the head of desk wrote at the end of each round | every debate round |
| settled (per closed trade) | keep the verdicts that were right | every closed position |
| reflection (per closed trade) | the desk's own flags as the reason to refuse, or the same objection at half size | every closed position |

Labels are **noisy and admitted as such**: one trade is one sample, so `meta.weight` says how
much a row counts (a reflection on a real loss 1.5, a curriculum drill 0.5).
