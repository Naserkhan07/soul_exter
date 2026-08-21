"""
Web search — keyless by default, provider-pluggable.

Provider order:
  1. Brave Search API      (only if BRAVE_SEARCH_KEY set — optional)
  2. SerpAPI               (only if SERPAPI_KEY set — optional)
  3. DuckDuckGo via `ddgs` (FREE, no API key, default)
  4. DuckDuckGo HTML fallback (requests + bs4, no extra package)

So discovery works with ZERO signups. Keys only add redundancy.
"""

import logging
import time

import requests

import config

log = logging.getLogger("tools.web_search")

_last_ddg_call = 0.0
_DDG_DELAY = 3.0  # polite spacing between keyless queries


def is_configured() -> bool:
    """Keyless DuckDuckGo always available -> search is always configured."""
    return True


def search_web(query: str, max_results: int = 10) -> list:
    """Return [{title, url, snippet}] from the first working provider."""
    if config.BRAVE_SEARCH_KEY:
        results = _brave(query, max_results)
        if results:
            return results
    if config.SERPAPI_KEY:
        results = _serpapi(query, max_results)
        if results:
            return results
    results = _ddgs_package(query, max_results)
    if results:
        return results
    return _ddg_html(query, max_results)


# ---------------------------------------------------------------------------
# Keyless providers
# ---------------------------------------------------------------------------
def _ddg_wait():
    global _last_ddg_call
    wait = _DDG_DELAY - (time.monotonic() - _last_ddg_call)
    if wait > 0:
        time.sleep(wait)
    _last_ddg_call = time.monotonic()


def _ddgs_package(query: str, max_results: int) -> list:
    """DuckDuckGo through the `ddgs` package (pip install ddgs)."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:  # older package name
            from duckduckgo_search import DDGS
        except ImportError:
            log.debug("ddgs not installed — trying HTML fallback")
            return []
    _ddg_wait()
    try:
        raw = DDGS().text(query, max_results=min(max_results, 20),
                          region="in-en")
        return [{"title": r.get("title", ""),
                 "url": r.get("href", r.get("url", "")),
                 "snippet": r.get("body", "")} for r in raw]
    except Exception as exc:
        log.warning("ddgs search failed: %s", exc)
        return []


def _ddg_html(query: str, max_results: int) -> list:
    """Last-resort keyless fallback: DuckDuckGo's HTML endpoint."""
    from bs4 import BeautifulSoup
    from urllib.parse import parse_qs, urlparse, unquote

    _ddg_wait()
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "in-en"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("DDG HTML search failed: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    out = []
    for a in soup.select("a.result__a")[:max_results]:
        href = a.get("href", "")
        # ddg wraps urls: //duckduckgo.com/l/?uddg=<real>
        if "uddg=" in href:
            q = parse_qs(urlparse(href).query)
            href = unquote(q.get("uddg", [""])[0])
        if not href.startswith("http"):
            continue
        snippet_el = a.find_parent("div", class_="result__body")
        snippet = ""
        if snippet_el:
            s = snippet_el.select_one(".result__snippet")
            snippet = s.get_text(" ", strip=True) if s else ""
        out.append({"title": a.get_text(" ", strip=True),
                    "url": href, "snippet": snippet})
    return out


# ---------------------------------------------------------------------------
# Optional keyed providers (redundancy only)
# ---------------------------------------------------------------------------
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
