"""
Public contact extractor.

Scans a business's own website (home + contact pages) for PUBLICLY listed
contact details: email, Indian phone numbers, WhatsApp links, social URLs.

Critical rule: if something isn't found, the field stays empty.
Nothing is ever guessed, inferred, or generated.
"""

import logging
import re
from urllib.parse import urljoin, urlparse, unquote

from bs4 import BeautifulSoup

import config
from tools.browser import fetch

log = logging.getLogger("tools.contacts")

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.I)

# Indian phone formats: +91 XXXXX XXXXX, 0XXXXXXXXXX, landlines with STD codes
PHONE_RE = re.compile(
    r"(?:\+?91[\s\-.]?)?(?:0)?([6-9]\d{4}[\s\-.]?\d{5})\b"
    r"|(?:\+?91[\s\-.]?)?(?:0)?(\d{2,4}[\s\-.]?\d{6,8})\b")

WHATSAPP_RE = re.compile(
    r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=|whatsapp://send\?phone=)"
    r"(\+?\d{10,14})", re.I)

BAD_EMAIL_HINTS = ("example.", "sentry", "wixpress", "@sentry", ".png",
                   ".jpg", ".gif", ".webp", "yourdomain", "domain.com",
                   "email.com", "@2x")

SOCIAL_PATTERNS = {
    "instagram": re.compile(r"instagram\.com/([\w.]+)", re.I),
    "facebook": re.compile(r"facebook\.com/([\w.\-]+)", re.I),
    "linkedin": re.compile(r"linkedin\.com/(company|in)/([\w\-%]+)", re.I),
    "youtube": re.compile(r"(youtube\.com/(@?[\w\-]+|channel/[\w\-]+))", re.I),
    "twitter": re.compile(r"(?:twitter|x)\.com/([\w]+)", re.I),
}

_SOCIAL_JUNK = {"sharer", "share", "intent", "plugins", "tr", "p", "l",
                "search", "hashtag", "home"}


def _clean_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    # mobiles: 10 digits starting 6-9; landline w/ STD: 10-11 digits
    if len(digits) == 10 and digits[0] in "6789":
        return "+91 " + digits
    if 10 <= len(digits) <= 11:
        return "+91 " + digits
    return ""


def extract_from_html(html: str, base_url: str = "") -> dict:
    """Extract public contacts from one HTML document."""
    out = {"emails": [], "phones": [], "whatsapp": [], "socials": {}}
    if not html:
        return out

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    # mailto: and tel: links are the most reliable
    for a in soup.find_all("a", href=True):
        href = unquote(a["href"]).strip()
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if EMAIL_RE.fullmatch(addr):
                out["emails"].append(addr.lower())
        elif href.lower().startswith("tel:"):
            cleaned = _clean_phone(href[4:])
            if cleaned:
                out["phones"].append(cleaned)

    # WhatsApp deep links
    for m in WHATSAPP_RE.finditer(html):
        cleaned = _clean_phone(m.group(1))
        if cleaned:
            out["whatsapp"].append(cleaned)

    # plain-text emails
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0).lower()
        if not any(bad in addr for bad in BAD_EMAIL_HINTS):
            out["emails"].append(addr)

    # plain-text phones (text only, to avoid IDs in markup)
    for m in PHONE_RE.finditer(text):
        cleaned = _clean_phone(m.group(0))
        if cleaned:
            out["phones"].append(cleaned)

    # social URLs
    for a in soup.find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        for key, pat in SOCIAL_PATTERNS.items():
            m = pat.search(full)
            if m and key not in out["socials"]:
                handle = m.group(1).lower()
                if handle in _SOCIAL_JUNK:
                    continue
                out["socials"][key] = full.split("?")[0]

    for k in ("emails", "phones", "whatsapp"):
        out[k] = list(dict.fromkeys(out[k]))[:5]
    return out


def find_public_contacts(website: str, contact_pages: list | None = None) -> dict:
    """
    Crawl the site's home page + up to MAX_PAGES_PER_SITE contact-ish pages
    and merge everything found. Returns:
        {phone, whatsapp, email, socials{...}, pages_checked[...]}
    Empty string = not publicly listed. Never guessed.
    """
    merged = {"emails": [], "phones": [], "whatsapp": [], "socials": {}}
    pages_checked = []

    urls = [website] + list(contact_pages or [])
    seen = set()
    for url in urls[: config.MAX_PAGES_PER_SITE]:
        norm = url.rstrip("/")
        if not norm or norm in seen:
            continue
        seen.add(norm)
        res = fetch(url)
        if not res.ok:
            continue
        pages_checked.append(res.final_url)
        found = extract_from_html(res.html, res.final_url)
        merged["emails"] += found["emails"]
        merged["phones"] += found["phones"]
        merged["whatsapp"] += found["whatsapp"]
        for k, v in found["socials"].items():
            merged["socials"].setdefault(k, v)

    merged["emails"] = list(dict.fromkeys(merged["emails"]))
    merged["phones"] = list(dict.fromkeys(merged["phones"]))
    merged["whatsapp"] = list(dict.fromkeys(merged["whatsapp"]))

    return {
        "phone": merged["phones"][0] if merged["phones"] else "",
        "whatsapp": merged["whatsapp"][0] if merged["whatsapp"] else "",
        "email": merged["emails"][0] if merged["emails"] else "",
        "all_emails": merged["emails"],
        "all_phones": merged["phones"],
        "socials": merged["socials"],
        "pages_checked": pages_checked,
    }
