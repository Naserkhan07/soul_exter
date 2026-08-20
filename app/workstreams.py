import asyncio
import json
from datetime import datetime, timedelta, timezone
from .config import settings
from .db import now, rows, transaction
from .strategies import rank_strategies


def _next_run(interval_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)).isoformat()


def ensure_workstream(name: str, interval_seconds: int, result: dict | None = None) -> None:
    with transaction() as db:
        db.execute("""INSERT INTO workstreams(name,status,interval_seconds,runs,next_run_at,last_result)
                      VALUES(?,'waiting',?,0,?,?)
                      ON CONFLICT(name) DO UPDATE SET interval_seconds=excluded.interval_seconds,
                      next_run_at=CASE WHEN workstreams.next_run_at IS NULL OR workstreams.next_run_at>excluded.next_run_at
                                       THEN excluded.next_run_at ELSE workstreams.next_run_at END""",
                   (name, interval_seconds, _next_run(interval_seconds), json.dumps(result or {})))


def mark_started(name: str, interval_seconds: int) -> None:
    with transaction() as db:
        db.execute("""INSERT INTO workstreams(name,status,interval_seconds,runs,last_started_at,next_run_at,last_result,last_error)
                      VALUES(?,'running',?,0,?,?,'{}',NULL)
                      ON CONFLICT(name) DO UPDATE SET status='running',interval_seconds=excluded.interval_seconds,
                      last_started_at=excluded.last_started_at,last_error=NULL""",
                   (name, interval_seconds, now(), _next_run(interval_seconds)))


def mark_completed(name: str, interval_seconds: int, result: dict) -> None:
    with transaction() as db:
        db.execute("""INSERT INTO workstreams(name,status,interval_seconds,runs,last_completed_at,next_run_at,last_result)
                      VALUES(?,'waiting',?,1,?,?,?)
                      ON CONFLICT(name) DO UPDATE SET status='waiting',runs=runs+1,
                      last_completed_at=excluded.last_completed_at,next_run_at=excluded.next_run_at,
                      last_result=excluded.last_result,last_error=NULL""",
                   (name, interval_seconds, now(), _next_run(interval_seconds), json.dumps(result)))


def mark_failed(name: str, interval_seconds: int, error: Exception) -> None:
    with transaction() as db:
        db.execute("""INSERT INTO workstreams(name,status,interval_seconds,runs,last_completed_at,next_run_at,last_result,last_error)
                      VALUES(?,'error',?,1,?,?,'{}',?)
                      ON CONFLICT(name) DO UPDATE SET status='error',runs=runs+1,
                      last_completed_at=excluded.last_completed_at,next_run_at=excluded.next_run_at,
                      last_error=excluded.last_error""",
                   (name, interval_seconds, now(), _next_run(interval_seconds), type(error).__name__))


def _strategy_metrics() -> dict[str, dict]:
    products = rows("SELECT id,strategy_slug,sales_count,revenue_cents FROM products")
    product_strategy = {p["id"]: p["strategy_slug"] for p in products}
    metrics: dict[str, dict] = {}
    for product in products:
        item = metrics.setdefault(product["strategy_slug"], {"views": 0, "sales": 0, "revenue_cents": 0})
        item["sales"] += product["sales_count"]
        item["revenue_cents"] += product["revenue_cents"]
    for analytic in rows("SELECT metadata FROM analytics_events WHERE type='product_view'"):
        try:
            product_id = int(json.loads(analytic["metadata"])["product_id"])
            slug = product_strategy.get(product_id)
            if slug:
                metrics.setdefault(slug, {"views": 0, "sales": 0, "revenue_cents": 0})["views"] += 1
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return metrics


async def strategy_scheduler(stop: asyncio.Event) -> None:
    interval = max(60, settings.strategy_review_seconds)
    ensure_workstream("strategy_research", interval, {"status": "waiting_for_review"})
    while not stop.is_set():
        state = rows("SELECT next_run_at FROM workstreams WHERE name='strategy_research'")
        due = not state or not state[0]["next_run_at"] or state[0]["next_run_at"] <= now()
        if due:
            mark_started("strategy_research", interval)
            try:
                ranking = rank_strategies(_strategy_metrics())
                top = ranking[:3]
                result = {"top_strategies": [{"slug": x["slug"], "score": x["score"], "next_action": x["next_action"]} for x in top]}
                with transaction() as db:
                    db.execute("INSERT INTO state(key,value) VALUES('latest_strategy_ranking',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (json.dumps(result),))
                mark_completed("strategy_research", interval, result)
            except Exception as exc:
                mark_failed("strategy_research", interval, exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=min(60, interval))
        except asyncio.TimeoutError:
            pass
