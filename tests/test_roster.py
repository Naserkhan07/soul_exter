"""The roster is six desks, six different sets of open weights.

The brief is explicit: five voting cabins plus a head of desk, and the sixth
LLM is a *distinct* model — not the same weights with a different prompt
prefix. These tests pin that, pin the "no keys" rule (ungated weights only, so
nothing needs a Hugging Face token), and pin the CEO's separation from the
desks whose votes it weighs.
"""
from soul.brains import APPROX_VRAM_4BIT_GB, PROFILES, PROFILE_LOW, PROFILE_STANDARD
from soul.brains.base import CABINS, CEO_SPEC

DESKS = [c.key for c in CABINS + [CEO_SPEC]]

#: Repos that need a token or a licence click-through. The project allows none.
GATED = ("meta-llama", "llama-3", "gemma", "google/gemma")


def test_standard_roster_is_six_distinct_models():
    assert sorted(PROFILE_STANDARD) == sorted(DESKS)
    assert len(set(PROFILE_STANDARD.values())) == 6


def test_every_reasoning_profile_keeps_six_distinct_models():
    for name in ("standard", "variety"):
        ids = [PROFILES[name][key] for key in DESKS]
        assert len(set(ids)) == 6, f"{name} profile reuses a model"
        cabins = [PROFILES[name][c.key] for c in CABINS]
        # the head of desk has to decide on weights none of the desks argued on
        assert PROFILES[name]["CEO"] not in cabins


def test_low_profile_shares_small_models_on_purpose():
    ids = set(PROFILE_LOW.values())
    assert ids <= set(APPROX_VRAM_4BIT_GB)
    assert max(APPROX_VRAM_4BIT_GB[i] for i in ids) <= 5.0


def test_no_gated_weights_anywhere():
    for name, roster in PROFILES.items():
        for key, model in roster.items():
            assert not any(g in model.lower() for g in GATED), f"{name}/{key} is gated"
            # and every model is one whose 4-bit footprint this project knows
            assert model in APPROX_VRAM_4BIT_GB, f"{model} is not on the verified list"
