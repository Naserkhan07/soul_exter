"""
Web search — optional, provider-pluggable.

Supports SerpAPI or Brave Search API (both have free tiers). Without a key
the tool disables itself; search is an enhancer, never a hard dependency.
"""

import logging

import requests

import config

log = logging.getLogger("tools.web_search")


def is_configured() -> bool:
    return bool(config.SERPAPI_KEY or config.BRAVE_SEARCH_KEY)


def search_web(query: str, max_results: int = 10) -> list:
    """Return [{title, url, snippet}] from the first configured provider."""
    if config.BRAVE_SEARCH_KEY:
        return _brave(query, max_results)
    if config.SERPAPI_KEY:
        return _serpapi(query, max_results)
    log.info("No search API key set — web search disabled")
    return []


def _brave(query: str, max_results: int) -> list:
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": config.BRAVE_SEARCH_KEY},
            params={"q": query, "count": min(max_results, 20),
                    "country": "IN"},
            timeout=config.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("web", {}).get("results", [])
        return [{"title": i.get("title", ""), "url": i.get("url", ""),
                 "snippet": i.get("description", "")} for i in items]
    except requests.RequestException as exc:
        log.warning("Brave search failed: %s", exc)
        return []


def _serpapi(query: str, max_results: int) -> list:
    try:
        resp = requests.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": config.SERPAPI_KEY,
                    "num": max_results, "gl": "in", "hl": "en"},
            timeout=config.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("organic_results", [])
        return [{"title": i.get("title", ""), "url": i.get("link", ""),
                 "snippet": i.get("snippet", "")} for i in items]
    except requests.RequestException as exc:
        log.warning("SerpAPI search failed: %s", exc)
        return []
