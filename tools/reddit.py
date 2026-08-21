"""
Reddit discovery — explicit-intent signals via the official Reddit API (PRAW).

We search public posts where Indian business owners explicitly describe a
need ("my website gets no traffic", "need someone for social media", ...).
These are HIGH-intent research signals.

Strictly read-only research. No posting, no DMs, no automation of any
interaction. Requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (free app
credentials) — without them the tool disables itself.
"""

import logging
import re

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


def is_configured() -> bool:
    return bool(config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET)


def _client():
    import praw
    return praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )


def detect_needs(text: str) -> list:
    return [need for need, pat in NEED_PATTERNS.items() if pat.search(text or "")]


def search_reddit(limit_per_query: int = 10) -> list:
    """
    Return high-intent signal dicts:
      {source, title, text_excerpt, url, subreddit, detected_needs, explicit_demand}
    """
    if not is_configured():
        log.info("Reddit credentials not set — reddit discovery disabled")
        return []
    try:
        import praw  # noqa: F401
    except ImportError:
        log.warning("praw not installed (pip install praw) — reddit disabled")
        return []

    reddit = _client()
    signals, seen_ids = [], set()
    sub = reddit.subreddit("+".join(SUBREDDITS))
    for query in INTENT_QUERIES:
        try:
            for post in sub.search(query, sort="new", limit=limit_per_query):
                if post.id in seen_ids:
                    continue
                seen_ids.add(post.id)
                body = f"{post.title}\n{getattr(post, 'selftext', '')}"
                needs = detect_needs(body)
                if not needs:
                    continue
                signals.append({
                    "source": "reddit",
                    "title": post.title,
                    "text_excerpt": (getattr(post, "selftext", "") or "")[:500],
                    "url": f"https://www.reddit.com{post.permalink}",
                    "subreddit": str(post.subreddit),
                    "detected_needs": needs,
                    "explicit_demand": post.title[:200],
                })
        except Exception as exc:
            log.warning("Reddit query '%s' failed: %s", query, exc)
    log.info("Reddit: %d high-intent signals", len(signals))
    return signals
