"""
Reddit discovery — explicit-intent signals, NO API KEYS NEEDED.

Uses Reddit's public read-only JSON endpoints (append .json to any listing
URL) with a descriptive User-Agent and polite rate limiting. If you later
add REDDIT_CLIENT_ID/SECRET, the official API via PRAW is used instead
(higher rate limits) — but it's entirely optional now.

Strictly read-only research. No posting, no DMs, no interaction automation.
"""

import logging
import re
import time

import requests

import config

log = logging.getLogger("tools.reddit")

SUBREDDITS = [
    "IndianEntrepreneurs", "smallbusiness", "IndiaBusiness", "StartUpIndia",
    "indianstartups", "Entrepreneur", "DigitalMarketing",
]

INTENT_QUERIES = [
    "need help website india",
    "looking for digital marketing agency india",
    "my website no traffic",
    "need someone social media business",
    "seo help small business india",
    "want to build app for my business",
]

NEED_PATTERNS = {
    "seo": re.compile(r"\b(seo|search ranking|google ranking|no traffic)\b", re.I),
    "website": re.compile(r"\b(website|web ?site|landing page|web design)\b", re.I),
    "social_media": re.compile(r"\b(social media|instagram|facebook page)\b", re.I),
    "digital_marketing": re.compile(r"\b(marketing|ads|advertis|promote|leads?)\b", re.I),
    "ecommerce": re.compile(r"\b(e-?commerce|online store|shopify|sell online)\b", re.I),
    "mobile_application": re.compile(r"\b(mobile app|android app|ios app)\b", re.I),
    "ai_automation": re.compile(r"\b(automat|chatbot|ai tool)\b", re.I),
}

_PUBLIC_DELAY = 3.0  # seconds between keyless JSON requests
_last_call = 0.0


def is_configured() -> bool:
    """Public JSON endpoints need no credentials — always available."""
    return True


def has_api_credentials() -> bool:
    return bool(config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET)


def detect_needs(text: str) -> list:
    return [need for need, pat in NEED_PATTERNS.items() if pat.search(text or "")]


# ---------------------------------------------------------------------------
# Keyless path: public JSON
# ---------------------------------------------------------------------------
def _polite_wait():
    global _last_call
    wait = _PUBLIC_DELAY - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _public_search(query: str, limit: int) -> list:
    """One search query against the public JSON endpoint."""
    _polite_wait()
    try:
        resp = requests.get(
            f"https://www.reddit.com/r/{'+'.join(SUBREDDITS)}/search.json",
            params={"q": query, "restrict_sr": "on", "sort": "new",
                    "limit": min(limit, 25), "t": "year"},
            headers={"User-Agent": config.REDDIT_USER_AGENT},
            timeout=config.HTTP_TIMEOUT,
        )
        if resp.status_code == 429:
            log.warning("Reddit rate limit hit — backing off 30s")
            time.sleep(30)
            return []
        resp.raise_for_status()
        children = resp.json().get("data", {}).get("children", [])
    except (requests.RequestException, ValueError) as exc:
        log.warning("Reddit public search '%s' failed: %s", query, exc)
        return []

    posts = []
    for child in children:
        d = child.get("data", {})
        posts.append({
            "id": d.get("id", ""),
            "title": d.get("title", ""),
            "selftext": d.get("selftext", "") or "",
            "permalink": d.get("permalink", ""),
            "subreddit": d.get("subreddit", ""),
        })
    return posts


# ---------------------------------------------------------------------------
# Optional keyed path: PRAW (used automatically when creds exist)
# ---------------------------------------------------------------------------
def _praw_search(query: str, limit: int) -> list:
    import praw
    reddit = praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )
    sub = reddit.subreddit("+".join(SUBREDDITS))
    posts = []
    for post in sub.search(query, sort="new", limit=limit):
        posts.append({
            "id": post.id,
            "title": post.title,
            "selftext": getattr(post, "selftext", "") or "",
            "permalink": post.permalink,
            "subreddit": str(post.subreddit),
        })
    return posts


# ---------------------------------------------------------------------------
# Public API of this module
# ---------------------------------------------------------------------------
def search_reddit(limit_per_query: int = 10) -> list:
    """
    Return high-intent signal dicts:
      {source, title, text_excerpt, url, subreddit, detected_needs, explicit_demand}
    """
    use_praw = False
    if has_api_credentials():
        try:
            import praw  # noqa: F401
            use_praw = True
        except ImportError:
            log.info("praw not installed — using keyless public JSON")

    signals, seen_ids = [], set()
    for query in INTENT_QUERIES:
        try:
            posts = (_praw_search(query, limit_per_query) if use_praw
                     else _public_search(query, limit_per_query))
        except Exception as exc:
            log.warning("Reddit query '%s' failed: %s", query, exc)
            continue
        for post in posts:
            if not post["id"] or post["id"] in seen_ids:
                continue
            seen_ids.add(post["id"])
            body = f"{post['title']}\n{post['selftext']}"
            needs = detect_needs(body)
            if not needs:
                continue
            signals.append({
                "source": "reddit",
                "title": post["title"],
                "text_excerpt": post["selftext"][:500],
                "url": f"https://www.reddit.com{post['permalink']}",
                "subreddit": post["subreddit"],
                "detected_needs": needs,
                "explicit_demand": post["title"][:200],
            })
    log.info("Reddit: %d high-intent signals (%s mode)",
             len(signals), "praw" if use_praw else "keyless")
    return signals
