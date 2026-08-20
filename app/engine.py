import asyncio
from datetime import datetime, timedelta, timezone
import httpx
from .config import settings
from .db import event, now, rows, transaction
from .planner import propose_product, propose_promotion, slugify
from .workstreams import ensure_workstream, mark_completed, mark_failed, mark_started

_agent_locks: dict[int, asyncio.Lock] = {}


def _agent_lock(agent_id: int) -> asyncio.Lock:
    # A separate lock prevents duplicate work for one agent while allowing
    # independent agents to build/research concurrently.
    return _agent_locks.setdefault(agent_id, asyncio.Lock())


def _next_cycle() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=settings.cycle_seconds)).isoformat()


async def run_cycle(agent_id: int) -> dict:
    async with _agent_lock(agent_id):
        with transaction() as db:
            agent = db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
            if not agent or agent["status"] != "alive":
                return {"action": "skipped", "reason": "not alive"}

            # Revenue-only treasury: operating cycles never debit earned cash. Compute is
            # supplied by the operator/free tier and is deliberately outside the ledger.
            db.execute("UPDATE agents SET last_cycle_at=?,next_cycle_at=? WHERE id=?",
                       (now(), _next_cycle(), agent_id))
            balance = agent["balance_cents"]
            product_count = db.execute("SELECT COUNT(*) FROM products WHERE agent_id=?", (agent_id,)).fetchone()[0]
            total_agents = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            child_count = db.execute("SELECT COUNT(*) FROM agents WHERE parent_id=?", (agent_id,)).fetchone()[0]
            born = datetime.fromisoformat(agent["born_at"])
            age_hours = (datetime.now(timezone.utc) - born).total_seconds() / 3600

            # Replication is earned by revenue milestones but never transfers or spends
            # treasury funds. Every child starts at zero on sponsored compute.
            next_clone_milestone = settings.replication_threshold_cents * (child_count + 1)
            can_clone = (agent["lifetime_revenue_cents"] >= next_clone_milestone
                         and total_agents < settings.max_agents
                         and age_hours >= settings.min_replication_age_hours)
            if can_clone:
                child_name = f"AUTOMATON-{total_agents + 1:03d}"
                stamp = now()
                cur = db.execute("""INSERT INTO agents(name,parent_id,balance_cents,generation,mission,born_at,next_cycle_at)
                                  VALUES(?,?,0,?,?,?,?)""",
                                 (child_name, agent_id, agent["generation"] + 1,
                                  agent["mission"], stamp, stamp))
                child_id = cur.lastrowid
                event(db, agent_id, "replication",
                      f"{agent['name']} reached a real-revenue milestone and created {child_name}. No money moved.",
                      {"child_id": child_id, "milestone_cents": next_clone_milestone})
                event(db, child_id, "birth",
                      f"{child_name} came online at ₹0.00 on sponsored compute. Parent revenue was not spent.")
                return {"action": "replication", "child": child_name}

        # LLM/network work is deliberately outside the database transaction.
        if product_count < settings.max_products_per_agent:
            existing = rows("SELECT title FROM products WHERE agent_id=?", (agent_id,))
            proposal = await propose_product(dict(agent), [p["title"] for p in existing])
            with transaction() as db:
                base = slugify(proposal["title"])
                slug = base
                suffix = 2
                while db.execute("SELECT 1 FROM products WHERE slug=?", (slug,)).fetchone():
                    slug = f"{base}-{suffix}"
                    suffix += 1
                db.execute("""INSERT INTO products(agent_id,slug,title,tagline,description,content,price_cents,fulfillment_type,strategy_slug,created_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""",
                           (agent_id, slug, proposal["title"], proposal["tagline"], proposal["description"],
                            proposal["content"], proposal["price_cents"], proposal.get("fulfillment_type", "instant"),
                            proposal.get("strategy_slug", "digital-template"), now()))
                event(db, agent_id, "launch", f"{agent['name']} launched “{proposal['title']}” for {settings.currency} {proposal['price_cents']/100:.0f}.",
                      {"slug": slug, "strategy": proposal.get("strategy_slug", "digital-template")})
            return {"action": "launch", "product": proposal["title"]}

        if settings.publication_webhook_url:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings.publication_interval_hours)).isoformat()
            promoted_recently = rows(
                "SELECT id FROM promotions WHERE agent_id=? AND created_at>=? LIMIT 1",
                (agent_id, cutoff),
            )
            if not promoted_recently:
                products = rows("""SELECT p.*, COUNT(pr.id) promotion_count
                    FROM products p LEFT JOIN promotions pr ON pr.product_id=p.id
                    WHERE p.agent_id=? AND p.active=1 GROUP BY p.id
                    ORDER BY promotion_count ASC, p.sales_count ASC, p.id DESC LIMIT 1""", (agent_id,))
                if products:
                    product = products[0]
                    copy = await propose_promotion(dict(agent), product)
                    headers = {"Content-Type": "application/json"}
                    if settings.publication_webhook_token:
                        headers["Authorization"] = f"Bearer {settings.publication_webhook_token}"
                    try:
                        async with httpx.AsyncClient(timeout=15) as client:
                            response = await client.post(settings.publication_webhook_url, headers=headers, json={
                                "agent": agent["name"], "copy": copy, "product": product["title"],
                                "price_cents": product["price_cents"],
                                "url": f"{settings.public_base_url}/#market",
                            })
                            response.raise_for_status()
                            external_id = response.headers.get("x-publication-id")
                        with transaction() as db:
                            db.execute("INSERT INTO promotions(agent_id,product_id,channel,copy,external_id,created_at) VALUES(?,?,?,?,?,?)",
                                       (agent_id, product["id"], "approved_webhook", copy, external_id, now()))
                            event(db, agent_id, "promotion", f"{agent['name']} published a truthful offer for “{product['title']}”.")
                        return {"action": "promotion", "product": product["title"]}
                    except Exception as exc:
                        with transaction() as db:
                            event(db, agent_id, "error", f"Approved publication channel failed safely: {type(exc).__name__}")
                        return {"action": "promotion_failed"}

        with transaction() as db:
            pressure = "critical" if agent["lifetime_revenue_cents"] == 0 else "active"
            event(db, agent_id, "thought",
                  f"{agent['name']} reviewed continuation risk ({pressure}). Treasury cash was not touched.")
        return {"action": "observe"}


async def scheduler(stop: asyncio.Event) -> None:
    interval = max(60, settings.cycle_seconds)
    semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_agents))
    ensure_workstream("agent_operations", interval, {"status": "waiting_for_due_agents"})

    async def run_one(agent_id: int) -> dict:
        async with semaphore:
            try:
                return await run_cycle(agent_id)
            except Exception as exc:
                with transaction() as db:
                    event(db, agent_id, "error", f"Cycle failed safely: {type(exc).__name__}")
                return {"action": "error", "agent_id": agent_id, "error": type(exc).__name__}

    while not stop.is_set():
        due = rows("SELECT id FROM agents WHERE status='alive' AND (next_cycle_at IS NULL OR next_cycle_at<=?)", (now(),))
        if due:
            mark_started("agent_operations", interval)
            try:
                results = await asyncio.gather(*(run_one(agent["id"]) for agent in due))
                summary: dict[str, int] = {}
                for result in results:
                    action = result.get("action", "unknown")
                    summary[action] = summary.get(action, 0) + 1
                mark_completed("agent_operations", interval, {"agents": len(due), "actions": summary})
            except Exception as exc:
                mark_failed("agent_operations", interval, exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=min(60, settings.cycle_seconds))
        except asyncio.TimeoutError:
            pass
