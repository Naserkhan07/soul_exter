"""
Lead data model. One dataclass = one row in the leads table = one Excel row.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class Lead:
    # Identity
    lead_id: str = ""                 # stable dedup key (set by deduplication)
    business_name: str = ""
    business_category: str = ""

    # Decision maker
    person_name: str = ""
    person_role: str = ""

    # Geography
    state: str = ""
    district: str = ""
    city: str = ""
    locality: str = ""
    full_location: str = ""

    # Contacts (public only — never guessed; empty string means "not found")
    phone: str = ""
    whatsapp: str = ""
    email: str = ""

    # URLs
    website: str = ""
    linkedin: str = ""
    instagram: str = ""
    facebook: str = ""
    youtube: str = ""
    twitter: str = ""
    other_contact_url: str = ""
    source_urls: list = field(default_factory=list)

    # Qualification (from Qwen)
    digital_marketing_need: str = "none"
    seo_need: str = "none"
    local_seo_need: str = "none"
    social_media_need: str = "none"
    website_need: str = "none"
    ecommerce_need: str = "none"
    mobile_app_need: str = "none"
    web_app_need: str = "none"
    ai_automation_need: str = "none"
    technical_support_need: str = "none"

    detected_problems: list = field(default_factory=list)
    recommended_services: list = field(default_factory=list)
    lead_score: int = 0
    evidence_reason: str = ""

    # Meta
    discovery_source: str = ""        # maps | hf_dataset | reddit | web | manual
    date_found: str = ""

    def __post_init__(self):
        if not self.date_found:
            self.date_found = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # -- serialization ------------------------------------------------------
    def to_row(self) -> dict:
        d = asdict(self)
        d["source_urls"] = json.dumps(self.source_urls, ensure_ascii=False)
        d["detected_problems"] = json.dumps(self.detected_problems, ensure_ascii=False)
        d["recommended_services"] = json.dumps(self.recommended_services, ensure_ascii=False)
        return d

    @classmethod
    def from_row(cls, row: dict) -> "Lead":
        d = dict(row)
        for key in ("source_urls", "detected_problems", "recommended_services"):
            v = d.get(key)
            if isinstance(v, str):
                try:
                    d[key] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    d[key] = [v] if v else []
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# Mapping from taxonomy service keys -> Lead need columns
NEED_FIELD_MAP = {
    "digital_marketing": "digital_marketing_need",
    "seo": "seo_need",
    "local_seo": "local_seo_need",
    "social_media": "social_media_need",
    "website": "website_need",
    "website_redesign": "website_need",
    "ecommerce": "ecommerce_need",
    "mobile_application": "mobile_app_need",
    "web_application": "web_app_need",
    "ai_automation": "ai_automation_need",
    "business_automation": "ai_automation_need",
    "chatbot": "ai_automation_need",
    "technical_support": "technical_support_need",
}

_LEVEL_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def apply_needs(lead: Lead, needs: dict) -> None:
    """Copy Qwen's need levels onto the Lead columns (keep the highest)."""
    for service, level in needs.items():
        column = NEED_FIELD_MAP.get(service)
        if not column:
            continue
        current = getattr(lead, column, "none")
        if _LEVEL_ORDER.get(level, 0) > _LEVEL_ORDER.get(current, 0):
            setattr(lead, column, level)
