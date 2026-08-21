"""
Structured output schemas for the Qwen brain.

Qwen is only allowed to answer in these shapes. Everything it returns is
validated and clamped here so a hallucinated value can never leak into
the database. Contact information is NOT part of the LLM schema on purpose:
contacts come exclusively from the deterministic extractor
(tools/contacts.py). Qwen must never invent a phone number or email.
"""

from dataclasses import dataclass, field, asdict

from config import ALL_SERVICES, NEED_LEVELS


@dataclass
class Qualification:
    """Validated result of a Qwen lead-qualification call."""

    qualified: bool = False
    lead_score: int = 0                      # 0-100
    needs: dict = field(default_factory=dict)  # service -> none/low/medium/high
    detected_problems: list = field(default_factory=list)
    recommended_services: list = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp_level(value) -> str:
    v = str(value).strip().lower()
    return v if v in NEED_LEVELS else "none"


def validate_qualification(raw: dict) -> Qualification:
    """Take whatever JSON the model produced and coerce it into a safe shape."""
    if not isinstance(raw, dict):
        raw = {}

    needs_raw = raw.get("needs", {}) or {}
    needs = {}
    if isinstance(needs_raw, dict):
        for service, level in needs_raw.items():
            key = str(service).strip().lower().replace(" ", "_").replace("-", "_")
            if key in ALL_SERVICES:
                needs[key] = _clamp_level(level)

    try:
        score = int(float(raw.get("lead_score", 0)))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))

    problems = raw.get("detected_problems", raw.get("problems", [])) or []
    if isinstance(problems, str):
        problems = [problems]
    problems = [str(p).strip() for p in problems if str(p).strip()][:15]

    services = raw.get("recommended_services", raw.get("services", [])) or []
    if isinstance(services, str):
        services = [services]
    services = [
        s for s in (
            str(x).strip().lower().replace(" ", "_").replace("-", "_")
            for x in services
        )
        if s in ALL_SERVICES
    ][:10]

    qualified = bool(raw.get("qualified", score >= 40))

    return Qualification(
        qualified=qualified,
        lead_score=score,
        needs=needs,
        detected_problems=problems,
        recommended_services=services,
        reason=str(raw.get("reason", "")).strip()[:1000],
    )


# JSON schema description embedded into the prompt so the model knows
# exactly which keys/values are legal.
QUALIFICATION_JSON_SPEC = {
    "qualified": "boolean",
    "lead_score": "integer 0-100",
    "needs": {service: "one of none|low|medium|high" for service in ALL_SERVICES},
    "detected_problems": ["short strings describing observed problems"],
    "recommended_services": [f"subset of: {', '.join(ALL_SERVICES)}"],
    "reason": "1-3 sentence justification grounded ONLY in the evidence",
}
