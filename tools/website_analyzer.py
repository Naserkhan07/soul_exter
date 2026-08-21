"""
Website analyzer — deterministic marketing/technical audit of a business site.

Feeds Qwen structured observations:
  technical : https, load time, mobile viewport, page errors
  marketing : title, meta description, headings, word count, CTAs
  business  : social links, contact page, address hints, local SEO signals
"""

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import config
from tools.browser import fetch

log = logging.getLogger("tools.analyzer")

CTA_PATTERNS = re.compile(
    r"(contact us|get (a )?quote|book now|order now|enquire|enquiry|"
    r"call now|whatsapp|get started|free consultation|request|subscribe|"
    r"buy now|shop now|schedule)", re.I)

CONTACT_LINK_PAT = re.compile(r"(contact|reach|enquir|about)", re.I)

OUTDATED_MARKERS = (
    "table-based layout", "frameset", "marquee", "blink",
)

SOCIAL_DOMAINS = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "linkedin.com": "linkedin",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "twitter.com": "twitter",
    "x.com": "twitter",
}


def analyze_website(url: str) -> dict:
    """Fetch and audit a website. Returns a JSON-safe observations dict."""
    result = fetch(url)
    analysis = {
        "url": url,
        "reachable": result.ok,
        "status": result.status,
        "https": result.final_url.startswith("https://") if result.ok else None,
        "load_time_seconds": round(result.elapsed, 2),
        "error": result.error or None,
    }
    if not result.ok:
        return analysis

    soup = BeautifulSoup(result.html, "lxml")
    text = soup.get_text(" ", strip=True)
    low_html = result.html.lower()

    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if tag:
        meta_desc = (tag.get("content") or "").strip()

    viewport = soup.find("meta", attrs={"name": "viewport"}) is not None

    # crude "outdated design" heuristics
    outdated = (
        "<frameset" in low_html
        or "<marquee" in low_html
        or ("<table" in low_html and "viewport" not in low_html
            and low_html.count("<div") < 5)
    )

    # social links
    socials = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        host = urlparse(urljoin(result.final_url, href)).netloc.lower()
        host = re.sub(r"^www\.", "", host)
        for domain, key in SOCIAL_DOMAINS.items():
            if host.endswith(domain) and key not in socials:
                socials[key] = urljoin(result.final_url, href)

    # contact page discovery
    contact_pages = []
    for a in soup.find_all("a", href=True):
        label = f"{a.get_text(' ', strip=True)} {a['href']}"
        if CONTACT_LINK_PAT.search(label):
            full = urljoin(result.final_url, a["href"])
            if urlparse(full).netloc == urlparse(result.final_url).netloc:
                contact_pages.append(full)
    contact_pages = list(dict.fromkeys(contact_pages))[:3]

    # local SEO signals
    has_schema_org = "schema.org" in low_html
    has_local_business_schema = "localbusiness" in low_html
    mentions_address = bool(re.search(
        r"\b(pin ?code|pincode|address|[1-9][0-9]{5})\b", text, re.I))

    analysis.update({
        "final_url": result.final_url,
        "title": title[:200],
        "title_length": len(title),
        "meta_description": meta_desc[:300],
        "h1_count": len(soup.find_all("h1")),
        "h2_count": len(soup.find_all("h2")),
        "word_count": len(text.split()),
        "mobile_friendly": viewport,
        "outdated_design": outdated,
        "has_cta": bool(CTA_PATTERNS.search(text)),
        "has_schema_org": has_schema_org,
        "has_local_business_schema": has_local_business_schema,
        "mentions_address": mentions_address,
        "social_links": socials,
        "contact_pages": contact_pages,
        "image_count": len(soup.find_all("img")),
        "images_missing_alt": sum(
            1 for img in soup.find_all("img") if not img.get("alt")),
        "broken_favicon": False,
    })
    return analysis


def summarize_issues(analysis: dict) -> list:
    """Turn raw analysis into human-readable issue strings."""
    issues = []
    if not analysis.get("reachable"):
        return [f"website unreachable ({analysis.get('error') or analysis.get('status')})"]
    if analysis.get("https") is False:
        issues.append("no HTTPS")
    if not analysis.get("mobile_friendly"):
        issues.append("no mobile viewport (likely not mobile friendly)")
    if analysis.get("outdated_design"):
        issues.append("outdated design markers")
    if analysis.get("load_time_seconds", 0) > 5:
        issues.append(f"slow load ({analysis['load_time_seconds']}s)")
    if not analysis.get("title"):
        issues.append("missing <title>")
    if not analysis.get("meta_description"):
        issues.append("missing meta description")
    if analysis.get("h1_count", 0) == 0:
        issues.append("no H1 heading")
    if analysis.get("word_count", 0) < 150:
        issues.append("thin content")
    if not analysis.get("has_cta"):
        issues.append("no clear call-to-action")
    if not analysis.get("has_local_business_schema"):
        issues.append("no LocalBusiness structured data")
    if not analysis.get("social_links"):
        issues.append("no social links on site")
    return issues
