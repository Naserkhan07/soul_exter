"""
Deduplication — business identity system.

The same business can surface from Google Maps, the HF dataset, Reddit and
its own website. We build a stable identity key from the strongest available
signal, in priority order:

    1. website domain
    2. normalized phone
    3. LinkedIn company slug
    4. normalized name + city

One business → one key → one lead row.
"""

import hashlib
import re
from urllib.parse import urlparse

_LEGAL_SUFFIXES = (
    "pvt ltd", "private limited", "ltd", "limited", "llp", "inc",
    "co", "company", "corporation", "enterprises", "industries",
    "& sons", "and sons", "&", "the",
)


def normalize_name(name: str) -> str:
    n = (name or "").lower().strip()
    n = re.sub(r"[^\w\s]", " ", n)
    for suffix in _LEGAL_SUFFIXES:
        n = re.sub(rf"\b{re.escape(suffix)}\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def normalize_domain(url: str) -> str:
    if not url:
        return ""
    u = url.strip().lower()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    host = urlparse(u).netloc.split(":")[0]
    host = re.sub(r"^www\.", "", host)
    # generic platforms are not identities (many businesses share them)
    if host in {"facebook.com", "instagram.com", "wa.me", "goo.gl",
                "business.site", "linktr.ee", "justdial.com",
                "indiamart.com", "g.page", ""}:
        return ""
    return host


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return digits if 8 <= len(digits) <= 12 else ""


def linkedin_slug(url: str) -> str:
    if not url or "linkedin.com" not in url.lower():
        return ""
    m = re.search(r"linkedin\.com/(company|in)/([^/?#]+)", url.lower())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def identity_key(name: str = "", website: str = "", phone: str = "",
                 city: str = "", linkedin: str = "") -> str:
    """Return a stable dedup key for a business candidate."""
    domain = normalize_domain(website)
    if domain:
        basis = f"domain:{domain}"
    else:
        ph = normalize_phone(phone)
        if ph:
            basis = f"phone:{ph}"
        else:
            slug = linkedin_slug(linkedin)
            if slug:
                basis = f"li:{slug}"
            else:
                basis = f"name:{normalize_name(name)}|{(city or '').lower().strip()}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def merge_leads(existing, incoming):
    """Merge a fresh Lead into an existing one — fill blanks, keep best score."""
    for field_name in existing.__dataclass_fields__:
        old = getattr(existing, field_name)
        new = getattr(incoming, field_name)
        if field_name == "source_urls":
            merged = list(dict.fromkeys((old or []) + (new or [])))
            existing.source_urls = merged
        elif field_name in ("detected_problems", "recommended_services"):
            if incoming.lead_score >= existing.lead_score and new:
                setattr(existing, field_name, new)
        elif field_name == "lead_score":
            existing.lead_score = max(old or 0, new or 0)
        elif not old and new:
            setattr(existing, field_name, new)
    return existing
