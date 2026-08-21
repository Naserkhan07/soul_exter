"""
Polite HTTP fetcher + optional Playwright browser.

Default path is plain `requests` (fast, cheap, works everywhere including
Kaggle). Playwright is used only when a page genuinely needs JavaScript,
and it is optional — the project runs fine without it installed.

Includes:
  * robots.txt respect
  * per-host politeness delay
  * login/CAPTCHA handoff: we never bypass security. If a page demands
    login or shows a CAPTCHA we pause and ask the human to act.
"""

import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

import config

log = logging.getLogger("tools.browser")

_last_hit: dict = {}      # host -> monotonic timestamp
_robots_cache: dict = {}  # host -> RobotFileParser | None


def _polite_wait(host: str) -> None:
    last = _last_hit.get(host, 0)
    wait = config.REQUEST_DELAY_SECONDS - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def _robots_allowed(url: str) -> bool:
    if not config.RESPECT_ROBOTS_TXT:
        return True
    host = urlparse(url).netloc
    rp = _robots_cache.get(host, "missing")
    if rp == "missing":
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.set_url(f"{urlparse(url).scheme}://{host}/robots.txt")
            rp.read()
        except Exception:
            rp = None  # unreadable robots -> default allow
        _robots_cache[host] = rp
    if rp is None:
        return True
    try:
        return rp.can_fetch(config.USER_AGENT, url)
    except Exception:
        return True


class FetchResult:
    def __init__(self, url, status=0, html="", elapsed=0.0, error="",
                 final_url=""):
        self.url = url
        self.final_url = final_url or url
        self.status = status
        self.html = html
        self.elapsed = elapsed
        self.error = error

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.html)


def fetch(url: str, session: requests.Session | None = None) -> FetchResult:
    """Fetch a single page politely. Never raises."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if not _robots_allowed(url):
        log.info("robots.txt disallows %s — skipping", url)
        return FetchResult(url, error="disallowed_by_robots")

    host = urlparse(url).netloc
    _polite_wait(host)

    sess = session or requests
    start = time.monotonic()
    try:
        resp = sess.get(
            url,
            headers={"User-Agent": config.USER_AGENT,
                     "Accept-Language": "en-IN,en;q=0.9"},
            timeout=config.HTTP_TIMEOUT,
            allow_redirects=True,
        )
        elapsed = time.monotonic() - start
        ctype = resp.headers.get("Content-Type", "")
        html = resp.text if "text" in ctype or "html" in ctype else ""
        return FetchResult(url, resp.status_code, html, elapsed,
                           final_url=resp.url)
    except requests.RequestException as exc:
        return FetchResult(url, error=type(exc).__name__,
                           elapsed=time.monotonic() - start)


# ---------------------------------------------------------------------------
# Optional Playwright path (JS-heavy sites)
# ---------------------------------------------------------------------------
def fetch_js(url: str, wait_seconds: float = 3.0) -> FetchResult:
    """Render a page with Playwright if it's installed; else fall back."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.debug("Playwright not installed; falling back to requests")
        return fetch(url)

    if not _robots_allowed(url):
        return FetchResult(url, error="disallowed_by_robots")

    start = time.monotonic()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=config.USER_AGENT)
            page.goto(url, timeout=int(config.HTTP_TIMEOUT * 1000))
            page.wait_for_timeout(int(wait_seconds * 1000))
            html = page.content()
            final = page.url
            browser.close()
        return FetchResult(url, 200, html, time.monotonic() - start,
                           final_url=final)
    except Exception as exc:
        return FetchResult(url, error=type(exc).__name__,
                           elapsed=time.monotonic() - start)


# ---------------------------------------------------------------------------
# Login / CAPTCHA handoff
# ---------------------------------------------------------------------------
LOGIN_MARKERS = ("captcha", "recaptcha", "hcaptcha", "please log in",
                 "sign in to continue", "verify you are human")


def needs_human(html: str) -> bool:
    low = (html or "").lower()
    return any(marker in low for marker in LOGIN_MARKERS)


def login_handoff(url: str) -> None:
    """
    Pause and hand control to the human. We never automate credentials or
    attempt to solve CAPTCHAs. In headless/batch mode we simply skip.
    """
    import sys
    if not sys.stdin.isatty():
        log.info("Human interaction needed for %s but running headless — skip", url)
        return
    print(f"\n⚠️  This page needs a human: {url}")
    print("   Open it in your own browser, complete the login/CAPTCHA,")
    input("   then press Enter here to continue (or Ctrl+C to abort)... ")
