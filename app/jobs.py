import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree
import httpx
from .config import settings
from .db import event, now, rows, transaction
from .workstreams import ensure_workstream, mark_completed, mark_failed, mark_started

SKILLS = {
    "content": 18, "copywriting": 18, "seo": 20, "social media": 18,
    "research": 14, "data entry": 8, "marketing": 16, "local business": 20,
    "website audit": 20, "product description": 18, "lead generation": 10,
    "remote": 5, "freelance": 6, "contract": 6,
}
BLOCKED = ("captcha", "adult", "gambling", "crypto investment", "account rental", "fake review", "commission only")


def score_opportunity(title: str, description: str) -> tuple[int, str]:
    text = f"{title} {description}".lower()
    if any(term in text for term in BLOCKED):
        return 0, "Rejected by safety or quality rules."
    hits = [(term, points) for term, points in SKILLS.items() if term in text]
    score = min(100, sum(points for _, points in hits))
    rationale = "Matched: " + ", ".join(term for term, _ in hits) if hits else "No strong skill match."
    return score, rationale


def draft_proposal(title: str, description: str) -> str:
    return (f"Hello, I can help with {title}. I would begin by confirming the required output, examples, "
            "deadline, and acceptance criteria. Then I would deliver a small first sample, incorporate feedback, "
            "and complete the agreed scope. I use AI-assisted workflows with operator oversight and will not "
            "claim experience or results I cannot verify. Please share the expected format and budget.")[:900]


def _items_from_feed(text: str, content_type: str) -> list[dict]:
    if "json" in content_type or text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("jobs") or data.get("items") or data.get("results") or []
        if not isinstance(data, list):
            return []
        return [{"title": str(x.get("title") or x.get("name") or "Untitled"),
                 "url": str(x.get("url") or x.get("link") or ""),
                 "description": str(x.get("description") or x.get("summary") or x.get("content") or "")}
                for x in data[:100] if isinstance(x, dict)]
    root = ElementTree.fromstring(text)
    found = []
    for item in list(root.findall(".//item")) + list(root.findall(".//{*}entry")):
        def value(names):
            for name in names:
                node = item.find(name)
                if node is None:
                    node = item.find(f"{{*}}{name}")
                if node is not None:
                    return node.get("href") or "".join(node.itertext())
            return ""
        found.append({"title": value(["title"]), "url": value(["link"]),
                      "description": value(["description", "summary", "content"])})
    return found[:100]


async def scan_job_feeds() -> int:
    created = 0
    for feed_url in settings.job_feed_urls:
        parsed = urlparse(feed_url)
        if parsed.scheme not in ("http", "https"):
            continue
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                response = await client.get(feed_url, headers={"User-Agent": "AutomatonOpportunityScout/1.0"})
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    continue
                items = _items_from_feed(response.text, response.headers.get("content-type", ""))
        except Exception:
            continue
        for item in items:
            title, url, description = item["title"][:300], item["url"][:1000], item["description"][:4000]
            if not title or not url:
                continue
            score, rationale = score_opportunity(title, description)
            if score < 25:
                continue
            key = hashlib.sha256(f"{feed_url}|{url}".encode()).hexdigest()
            with transaction() as db:
                if db.execute("SELECT 1 FROM opportunities WHERE external_key=?", (key,)).fetchone():
                    continue
                db.execute("""INSERT INTO opportunities(external_key,source,title,url,description,score,rationale,proposal,created_at)
                              VALUES(?,?,?,?,?,?,?,?,?)""",
                           (key, parsed.netloc, title, url, description, score, rationale,
                            draft_proposal(title, description), now()))
                event(db, None, "opportunity", f"Found a permitted public opportunity: “{title}” (score {score}).")
            created += 1
            if settings.opportunity_webhook_url:
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(settings.opportunity_webhook_url, json={
                            "title": title, "url": url, "score": score,
                            "rationale": rationale, "proposal_draft": draft_proposal(title, description),
                            "requires_human_application": True,
                        })
                except Exception:
                    pass
    return created


async def job_scheduler(stop: asyncio.Event) -> None:
    interval = settings.job_scan_interval_seconds
    ensure_workstream("opportunity_research", interval,
                      {"configured_feeds": len(settings.job_feed_urls), "status": "waiting_for_scan" if settings.job_feed_urls else "waiting_for_permitted_feeds"})
    while not stop.is_set():
        if settings.job_feed_urls:
            state = rows("SELECT value FROM state WHERE key='last_job_scan'")
            due = not state
            if state:
                due = datetime.fromisoformat(state[0]["value"]) <= datetime.now(timezone.utc) - timedelta(seconds=settings.job_scan_interval_seconds)
            if due:
                mark_started("opportunity_research", interval)
                try:
                    created = await scan_job_feeds()
                    with transaction() as db:
                        db.execute("INSERT INTO state(key,value) VALUES('last_job_scan',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now(),))
                    mark_completed("opportunity_research", interval,
                                   {"configured_feeds": len(settings.job_feed_urls), "created": created})
                except Exception as exc:
                    mark_failed("opportunity_research", interval, exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
