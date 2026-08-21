"""
LinkedIn enrichment — strictly ToS-respecting.

We do NOT scrape LinkedIn. LinkedIn data enters the system only through:
  1. The Hugging Face company dataset (already-published records).
  2. LinkedIn URLs a business publishes on its OWN website.
  3. Manually pasted URLs/names (human research handoff).

This module normalizes those URLs and extracts decision-maker hints from
text a business chose to publish itself (e.g. "Founder: Rahul Kumar" on
their About page).
"""

import logging
import re

log = logging.getLogger("tools.linkedin")

COMPANY_URL_RE = re.compile(
    r"(https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[\w\-%.]+)", re.I)
PROFILE_URL_RE = re.compile(
    r"(https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%.]+)", re.I)

DECISION_ROLES = [
    "founder", "co-founder", "cofounder", "owner", "proprietor", "ceo",
    "managing director", "director", "partner", "marketing manager",
    "business development manager", "operations manager", "it manager",
]

# "Founder: Rahul Kumar" / "Rahul Kumar, Founder" / "Founded by Rahul Kumar"
_ROLE_ALT = "|".join(re.escape(r) for r in DECISION_ROLES)
# Role matching is case-insensitive; the captured NAME must stay capitalized.
PERSON_PATTERNS = [
    re.compile(rf"(?i:{_ROLE_ALT})\s*[:\-–]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{0,3}})"),
    re.compile(rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{0,3}})\s*[,\-–]\s*(?i:{_ROLE_ALT})"),
    re.compile(rf"(?i:founded by)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{0,3}})"),
]


def normalize_company_url(url: str) -> str:
    m = COMPANY_URL_RE.search(url or "")
    return m.group(1).rstrip("/").split("?")[0] if m else ""


def extract_linkedin_urls(html: str) -> dict:
    """Find LinkedIn URLs a business published on its own pages."""
    company = COMPANY_URL_RE.findall(html or "")
    profiles = PROFILE_URL_RE.findall(html or "")
    return {
        "company": company[0].split("?")[0] if company else "",
        "profiles": list(dict.fromkeys(p.split("?")[0] for p in profiles))[:5],
    }


def extract_decision_maker(text: str) -> dict:
    """
    Extract a self-published decision maker mention from website text.
    Returns {"person_name": ..., "person_role": ...} or empties.
    """
    if not text:
        return {"person_name": "", "person_role": ""}
    for pat in PERSON_PATTERNS:
        m = pat.search(text)
        if m:
            name = m.group(1).strip()
            window = text[max(0, m.start() - 60): m.end() + 60].lower()
            role = next((r for r in DECISION_ROLES if r in window), "")
            if 2 <= len(name.split()) <= 4 or (len(name.split()) == 1 and len(name) > 2):
                return {"person_name": name, "person_role": role.title()}
    return {"person_name": "", "person_role": ""}
