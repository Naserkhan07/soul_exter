"""Calibrated expectancy model — the number the council actually argues about.

Weights are fitted by `scripts/train_scorecards.py` on the tickets the entry gate
emits, each walked to first touch. Every desk reads the same coefficients, tilted
towards the evidence that desk is accountable for, so a judge's approval is tied
to a measured distribution of outcomes rather than to how persuasive the story
sounds. `soul_exter_scorecard_weights.json` is optional: without it the desks fall
back to their hand-written scorecards.
"""
from __future__ import annotations

import json
import math
import os
from typing import Dict, List, Optional

TERMS = ["align", "eff_adj", "extended", "chase", "rank", "cost_adj", "rr_adj",
         "vol_ratio", "session_adj", "room_hi", "room_lo", "bb_chase"]

WEIGHTS_PATH = os.environ.get(
    "SOUL_EXTER_WEIGHTS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                 "soul_exter_scorecard_weights.json"))

# how much each desk leans on each family of evidence
DESK_EMPHASIS: Dict[str, Dict[str, float]] = {
    "judge_trend": dict(align=1.45, eff_adj=1.15, extended=1.30, chase=1.30, room_hi=1.20,
                        room_lo=1.20, bb_chase=1.15),
    "judge_quant": dict(eff_adj=1.45, rr_adj=1.40, cost_adj=1.35, vol_ratio=1.40, rank=1.25),
    "judge_macro": dict(session_adj=1.50, vol_ratio=1.20, room_hi=1.15, room_lo=1.15),
    "judge_vol": dict(rank=1.55, vol_ratio=1.45, extended=1.35, chase=1.35, bb_chase=1.25),
    "judge_exec": dict(cost_adj=1.50, session_adj=1.25, rr_adj=1.20, room_hi=1.10, room_lo=1.10),
    "ceo": {},
}

_MODEL: Dict[str, object] = {}
try:
    if os.path.exists(WEIGHTS_PATH):
        with open(WEIGHTS_PATH) as _fh:
            _MODEL = json.load(_fh)
except Exception:                                   # pragma: no cover - keep the floor up
    _MODEL = {}


# Each desk rules on its own mandate, so the council is not six copies of one
# model: separate decision bands plus a small, deterministic idiosyncratic tilt
# (a desk's house view on a given name) produce genuine agreement and dissent.
DESK_BANDS: Dict[str, tuple] = {
    "judge_trend": (0.58, 0.42),      # bold: gives structure the benefit of the doubt
    "judge_quant": (0.64, 0.48),      # strict: wants expectancy to clear the bar
    "judge_macro": (0.60, 0.45),      # balanced
    "judge_vol": (0.62, 0.47),        # wary of stretched entries
    "judge_exec": (0.56, 0.44),       # willing when the fill is clean
    "ceo": (0.60, 0.44),
}
DESK_TILT = 0.17


def desk_tilt(desk_id: str, symbol: str, direction: str) -> float:
    """Deterministic house view: ±1 unit, stable for a given desk+name+direction."""
    h = hash((desk_id, symbol, direction)) & 0xFFFF
    return (h / 0xFFFF) * 2.0 - 1.0


def desk_bands(desk_id: str) -> tuple:
    return DESK_BANDS.get(desk_id, (0.60, 0.44))


def model_ready() -> bool:
    return bool(_MODEL.get("weights"))


def model_meta() -> Dict[str, object]:
    return dict(ready=model_ready(), samples=_MODEL.get("samples"),
                mean_r=_MODEL.get("mean_r"), baseline_win=_MODEL.get("baseline_win"),
                weights_path=WEIGHTS_PATH if model_ready() else None)


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def model_features(f: Dict[str, float], direction: str, rr: float) -> Dict[str, float]:
    """The model's inputs, built from tape evidence only."""
    sgn = 1.0 if direction == "long" else -1.0
    slope21 = float(f.get("slope21", 0.0))
    slope50 = float(f.get("slope50", 0.0))
    tc = 0.62 * math.tanh(slope21 * 120.0) + 0.38 * math.tanh(slope50 * 60.0)
    atr_pct = max(float(f.get("atr_pct", 1e-9)), 1e-9)
    stretch = float(f.get("stretch", 0.0)) * sgn
    cost = float(f.get("spread_ratio", 0.0)) / atr_pct
    return dict(
        align=_clip(tc * sgn, -1.0, 1.0),
        eff_adj=_clip((float(f.get("efficiency", 0.0)) - 0.30) * 3.2, -1.0, 1.0),
        extended=_clip((abs(stretch) - 0.9) / 1.4, 0.0, 1.0),
        chase=_clip((stretch - 0.9) / 1.4, 0.0, 1.0),
        rank=float(f.get("atr_rank", 0.5)),
        cost_adj=_clip((cost - 0.04) / 0.08, 0.0, 1.0),
        rr_adj=_clip((rr - 1.6) / 1.6, -1.0, 1.0),
        vol_ratio=_clip((float(f.get("vol_ratio", 1.0)) - 1.0) / 1.5, -1.0, 1.0),
        session_adj=_clip((float(f.get("session", 1.0)) - 0.9) / 0.9, -1.0, 1.0),
        room_hi=_clip((float(f.get("dist_hi", 3.0)) - 0.5) / 3.0, -1.0, 1.0) * sgn,
        room_lo=_clip((float(f.get("dist_lo", 3.0)) - 0.5) / 3.0, -1.0, 1.0) * sgn,
        bb_chase=_clip((float(f.get("bb_pos", 0.5)) - 0.5) * 2.0, -1.0, 1.0) * sgn,
    )


def predict(f: Dict[str, float], direction: str, rr: float, desk_id: Optional[str] = None,
            prior: float = 0.0) -> float:
    """Predicted R for a ticket, from the fitted coefficients."""
    if not model_ready():
        return 0.0
    weights: Dict[str, float] = dict(_MODEL["weights"])          # type: ignore[arg-type]
    terms: List[str] = list(_MODEL.get("terms") or TERMS)        # type: ignore[arg-type]
    mu = list(_MODEL.get("mu") or [0.0] * len(terms))
    sd = list(_MODEL.get("sd") or [1.0] * len(terms))
    x = model_features(f, direction, rr)
    emphasis = DESK_EMPHASIS.get(desk_id or "", {})
    z_clip = float(_MODEL.get("z_clip", 2.0) or 2.0)             # type: ignore[arg-type]
    pred = float(_MODEL.get("intercept", 0.0))                   # type: ignore[arg-type]
    for i, term in enumerate(terms):
        if i >= len(mu) or i >= len(sd):
            break
        z = (x.get(term, 0.0) - float(mu[i])) / max(float(sd[i]), 1e-9)
        z = max(-z_clip, min(z_clip, z))
        pred += weights.get(term, 0.0) * z * emphasis.get(term, 1.0)
    return float(pred + prior * 0.4)


def percentile(pred: float) -> int:
    """Rough quintile of the calibrated distribution, for the narrative."""
    mean = float(_MODEL.get("mean_r", 0.34) or 0.34)
    if pred > mean + 0.75:
        return 5
    if pred > mean + 0.25:
        return 4
    if pred > mean - 0.15:
        return 3
    if pred > mean - 0.6:
        return 2
    return 1
