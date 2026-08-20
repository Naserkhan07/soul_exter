import asyncio
import hmac
import html
import json
import io
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import event, init_db, now, row, rows, transaction
from .engine import run_cycle, scheduler
from .fulfillment import generate_growth_pack
from .jobs import job_scheduler, scan_job_feeds
from .phonepe_payments import (
    PhonePeAPI, PhonePeAPIError, complete_phonepe_order, phonepe_payment_scheduler,
    refresh_phonepe_order, validate_webhook_authorization,
)
from .sales import record_sale
from .strategies import rank_strategies
from .workstreams import strategy_scheduler

BASE = Path(__file__).resolve().parent.parent
SOLUTIONS = {
    "salons": ("Growth plan for salons", "Turn profile views into qualified appointments with local proof, service pages, review replies, and a practical content calendar."),
    "tutors": ("Growth plan for tutors", "Explain subjects, outcomes, formats, and service areas clearly while building trust with useful educational content."),
    "restaurants": ("Growth plan for restaurants", "Improve local discovery with accurate listings, original menu stories, review responses, and consistent offers."),
    "clinics": ("Growth plan for clinics", "Publish clear, privacy-aware service information without guarantees, invented claims, or unsafe medical marketing."),
    "repair-services": ("Growth plan for repair services", "Build local trust with service-area pages, process explanations, genuine proof, and direct booking calls to action."),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop_event = asyncio.Event()
    tasks = [
        asyncio.create_task(scheduler(stop_event)),
        asyncio.create_task(job_scheduler(stop_event)),
        asyncio.create_task(strategy_scheduler(stop_event)),
        asyncio.create_task(phonepe_payment_scheduler(stop_event)),
    ]
    yield
    stop_event.set()
    await asyncio.gather(*tasks)


app = FastAPI(title="Automaton", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/solutions/{vertical}", response_class=HTMLResponse)
def solution_page(vertical: str):
    solution = SOLUTIONS.get(vertical)
    if not solution:
        raise HTTPException(404, "Solution not found")
    title, description = solution
    canonical = f"{settings.public_base_url}/solutions/{vertical}"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
    <title>{html.escape(title)} | Automaton</title><meta name=description content='{html.escape(description)}'><link rel=canonical href='{html.escape(canonical)}'>
    <style>body{{max-width:850px;margin:60px auto;padding:24px;background:#080b09;color:#e8eee9;font:17px/1.7 system-ui}}a{{color:#8df7b7}}.card{{border:1px solid #29352e;padding:28px;margin:30px 0}}h1{{font-size:52px;line-height:1.05}}li{{margin:10px 0}}</style></head><body>
    <a href='/'>← Automaton</a><h1>{html.escape(title)}</h1><p>{html.escape(description)}</p><div class=card><h2>What the personalized pack includes</h2><ul><li>Local visibility and Google Business Profile audit</li><li>Honest positioning and local search phrases</li><li>Review-response and consent-based WhatsApp templates</li><li>A distinct 30-day social content calendar</li><li>A seven-day action plan and measurement checklist</li></ul></div><p>No guaranteed rankings, fake reviews, or invented business claims.</p><a href='/#market'>Get three free observations or buy the ₹499 Growth Pack →</a></body></html>""")


@app.get("/robots.txt", response_class=HTMLResponse)
def robots():
    return HTMLResponse(f"User-agent: *\nAllow: /\nDisallow: /delivery/\nSitemap: {settings.public_base_url}/sitemap.xml\n", media_type="text/plain")


@app.get("/sitemap.xml", response_class=HTMLResponse)
def sitemap():
    urls = [settings.public_base_url] + [f"{settings.public_base_url}/solutions/{slug}" for slug in SOLUTIONS]
    body = "".join(f"<url><loc>{html.escape(url)}</loc></url>" for url in urls)
    return HTMLResponse(f"<?xml version='1.0' encoding='UTF-8'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>{body}</urlset>", media_type="application/xml")


@app.get("/legal/{page}", response_class=HTMLResponse)
def legal_page(page: str):
    copy = {
        "privacy": ("Privacy", "PhonePe processes payment details. Automaton stores provider order and transaction references plus the business brief needed for delivery. Do not submit UPI PINs, OTPs, bank passwords, or sensitive authentication data. Contact support to request deletion."),
        "refunds": ("Refunds", "If a paid report is not delivered or is materially defective, contact support with the PhonePe order reference. Refund eligibility and timing are subject to the operator policy and PhonePe rules. AI-assisted output must be reviewed before publication."),
        "terms": ("Terms", "Automaton provides AI-assisted business content, not legal, medical, financial, or guaranteed ranking advice. Customers must verify every claim and have rights to submitted information. Abuse, unlawful use, fake reviews, and deceptive marketing are prohibited."),
    }.get(page)
    if not copy:
        raise HTTPException(404, "Policy not found")
    title, body = copy
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>{title}</title><style>body{{max-width:760px;margin:60px auto;padding:20px;background:#080b09;color:#e8eee9;font:17px/1.7 system-ui}}a{{color:#8df7b7}}</style><a href='/'>← Automaton</a><h1>{title}</h1><p>{html.escape(body)}</p><p>Support: {html.escape(settings.support_email)}</p><p><strong>Operator:</strong> Replace this template with your verified legal/business identity and obtain local legal review before going live.</p>")


@app.get("/health")
def health():
    return {"ok": True, "mode": settings.mode}


@app.get("/api/state")
def state():
    agents = rows("SELECT * FROM agents ORDER BY id")
    products = rows("""SELECT p.id,p.agent_id,p.slug,p.title,p.tagline,p.description,p.price_cents,p.sales_count,p.revenue_cents,p.fulfillment_type,p.strategy_slug,p.created_at,a.name agent_name
                       FROM products p JOIN agents a ON a.id=p.agent_id WHERE p.active=1 ORDER BY p.id DESC""")
    events = rows("""SELECT e.id,e.agent_id,e.type,e.message,e.metadata,e.created_at,a.name agent_name
                     FROM events e LEFT JOIN agents a ON a.id=e.agent_id ORDER BY e.id DESC LIMIT 40""")
    ledger = rows("SELECT id,agent_id,amount_cents,kind,description,created_at FROM ledger ORDER BY id DESC LIMIT 30")
    totals = row("SELECT COALESCE(SUM(balance_cents),0) balance, COALESCE(SUM(lifetime_revenue_cents),0) revenue, COALESCE(SUM(lifetime_cost_cents),0) costs, SUM(status='alive') alive FROM agents")
    phonepe_totals = row("""SELECT
        COALESCE(SUM(CASE WHEN status='paid' THEN amount_cents ELSE 0 END),0) confirmed_amount,
        COALESCE(SUM(CASE WHEN status IN ('created','pending') THEN amount_cents ELSE 0 END),0) pending_amount,
        COALESCE(SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END),0) confirmed_payments,
        COALESCE(SUM(CASE WHEN status IN ('created','pending') THEN 1 ELSE 0 END),0) pending_payments
        FROM payment_orders WHERE provider='phonepe'""")
    workstreams = rows("SELECT name,status,interval_seconds,runs,last_started_at,last_completed_at,next_run_at,last_result,last_error FROM workstreams ORDER BY name")
    for workstream in workstreams:
        try:
            workstream["last_result"] = json.loads(workstream["last_result"])
        except (TypeError, json.JSONDecodeError):
            workstream["last_result"] = {}
    return {"mode": settings.mode, "agents": agents, "products": products, "events": events,
            "ledger": ledger, "workstreams": workstreams, "totals": totals,
            "phonepe_totals": phonepe_totals, "cycle_seconds": settings.cycle_seconds,
            "replication_threshold_cents": settings.replication_threshold_cents,
            "max_agents": settings.max_agents, "currency": settings.currency,
            "payment_provider": "phonepe",
            "payments_ready": bool(settings.phonepe_client_id and settings.phonepe_client_secret
                                   and settings.phonepe_client_version),
            "payment_environment": settings.phonepe_environment}


@app.get("/api/products/{slug}")
def product(slug: str):
    product = row("SELECT id,slug,title,tagline,description,price_cents,sales_count,agent_id,fulfillment_type FROM products WHERE slug=? AND active=1", (slug,))
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@app.post("/api/analytics/view/{slug}")
def track_product_view(slug: str):
    product = row("SELECT id FROM products WHERE slug=? AND active=1", (slug,))
    if not product:
        raise HTTPException(404, "Product not found")
    with transaction() as db:
        db.execute("INSERT INTO analytics_events(type,path,metadata,created_at) VALUES('product_view',?,?,?)",
                   (f"/products/{slug}", json.dumps({"product_id": product["id"]}), now()))
    return {"ok": True}


@app.post("/api/products/{slug}/checkout")
def checkout(slug: str, ref: str = ""):
    product = row("SELECT * FROM products WHERE slug=? AND active=1", (slug,))
    if not product:
        raise HTTPException(404, "Product not found")
    with transaction() as db:
        db.execute("INSERT INTO analytics_events(type,path,metadata,created_at) VALUES('checkout_start',?,?,?)",
                   (f"/products/{slug}", json.dumps({"product_id": product["id"]}), now()))
    if not settings.is_live:
        return {"demo": True, "message": "Simulation mode never requests real payment."}
    if not settings.phonepe_client_id or not settings.phonepe_client_secret or not settings.phonepe_client_version:
        raise HTTPException(503, "PhonePe Payment Gateway is not configured")

    referral = ref.strip().upper()[:20]
    if referral and not row("SELECT 1 ok FROM service_orders WHERE referral_code=?", (referral,)):
        referral = ""
    fulfillment_token = uuid.uuid4().hex + uuid.uuid4().hex
    merchant_order_id = "AUTO" + uuid.uuid4().hex
    return_url = f"{settings.public_base_url}/payment/phonepe/return?token={fulfillment_token}"
    try:
        response = PhonePeAPI().create_payment(
            merchant_order_id, product["price_cents"], return_url,
            f"Automaton: {product['title']}", settings.phonepe_expire_seconds,
        )
        redirect_url = str(response["redirectUrl"])
    except (PhonePeAPIError, KeyError, ValueError):
        raise HTTPException(502, "PhonePe could not create the checkout")
    with transaction() as db:
        cursor = db.execute("""INSERT INTO payment_orders(provider,provider_order_id,product_id,amount_cents,currency,status,fulfillment_token,referred_by,created_at)
                              VALUES('phonepe',?,?,?,?,?,?,?,?)""",
                            (merchant_order_id, product["id"], product["price_cents"], settings.currency,
                             "pending", fulfillment_token, referral or None, now()))
        db.execute("""INSERT INTO phonepe_orders(payment_order_id,merchant_order_id,phonepe_order_id,redirect_url,state,environment,expire_at)
                      VALUES(?,?,?,?,?,?,?)""",
                   (cursor.lastrowid, merchant_order_id, str(response.get("orderId") or ""), redirect_url,
                    str(response.get("state") or "PENDING"), settings.phonepe_environment,
                    response.get("expireAt")))
    return {"provider": "phonepe", "redirect_url": redirect_url, "token": fulfillment_token,
            "environment": settings.phonepe_environment}


def _paid_order_payload(payment_order: dict) -> dict:
    product = row("SELECT title,content,fulfillment_type FROM products WHERE id=?", (payment_order["product_id"],))
    if not product:
        raise HTTPException(404, "Product not found")
    if product["fulfillment_type"] == "personalized":
        return {"ok": True, "paid": True, "title": product["title"], "brief_required": True,
                "fulfillment_token": payment_order["fulfillment_token"]}
    return {"ok": True, "paid": True, "title": product["title"], "content": product["content"]}


@app.get("/api/payments/phonepe/{token}")
def phonepe_payment_status(token: str):
    order = row("""SELECT pho.*,po.id payment_order_id,po.product_id,po.amount_cents,po.status payment_status,
                   po.fulfillment_token,p.title product_title,p.slug product_slug
                   FROM phonepe_orders pho JOIN payment_orders po ON po.id=pho.payment_order_id
                   JOIN products p ON p.id=po.product_id WHERE po.fulfillment_token=?""", (token,))
    if not order:
        raise HTTPException(404, "PhonePe order not found")
    if order["payment_status"] == "paid":
        return _paid_order_payload(order)
    if order["payment_status"] != "failed":
        try:
            result = refresh_phonepe_order(order["payment_order_id"])
            if result.get("paid"):
                paid_order = row("SELECT * FROM payment_orders WHERE id=?", (order["payment_order_id"],))
                return _paid_order_payload(paid_order)
            order["state"] = result["state"]
        except PhonePeAPIError:
            pass
    return {"ok": True, "paid": False, "status": order["state"],
            "merchant_order_id": order["merchant_order_id"], "amount": order["amount_cents"],
            "product_title": order["product_title"], "product_slug": order["product_slug"],
            "environment": order["environment"]}


@app.get("/payment/phonepe/return")
def phonepe_return(token: str):
    if len(token) != 64:
        raise HTTPException(400, "Invalid payment token")
    return RedirectResponse(url=f"/?payment={token}#market", status_code=303)


@app.post("/webhooks/phonepe")
async def phonepe_webhook(request: Request):
    if not settings.phonepe_webhook_username or not settings.phonepe_webhook_password:
        raise HTTPException(503, "PhonePe webhook authentication is not configured")
    if not validate_webhook_authorization(request.headers.get("authorization", ""),
                                           settings.phonepe_webhook_username,
                                           settings.phonepe_webhook_password):
        raise HTTPException(401, "Invalid PhonePe webhook authorization")
    try:
        callback = json.loads(await request.body())
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid webhook JSON")
    event_name = str(callback.get("event") or "")
    payload = callback.get("payload") or {}
    merchant_order_id = str(payload.get("merchantOrderId") or "")
    if not merchant_order_id:
        return {"received": True}
    if event_name == "checkout.order.completed" and payload.get("state") == "COMPLETED":
        complete_phonepe_order(merchant_order_id, payload)
    elif event_name == "checkout.order.failed" or payload.get("state") == "FAILED":
        with transaction() as db:
            order = db.execute("SELECT payment_order_id FROM phonepe_orders WHERE merchant_order_id=?",
                               (merchant_order_id,)).fetchone()
            if order:
                db.execute("UPDATE phonepe_orders SET state='FAILED',last_checked_at=? WHERE payment_order_id=?",
                           (now(), order["payment_order_id"]))
                db.execute("UPDATE payment_orders SET status='failed' WHERE id=?", (order["payment_order_id"],))
    return {"received": True}


class BusinessBrief(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    business_name: str = Field(min_length=2, max_length=120)
    industry: str = Field(min_length=2, max_length=100)
    city: str = Field(min_length=2, max_length=100)
    website: str = Field(default="", max_length=250)
    goal: str = Field(min_length=10, max_length=500)
    language: str = Field(default="English", max_length=30)
    consent: bool


@app.post("/api/fulfillment/{token}")
async def fulfill_personalized_order(token: str, brief: BusinessBrief):
    if "@" not in brief.email or len(token) != 64:
        raise HTTPException(400, "Invalid email or delivery token")
    if not brief.consent:
        raise HTTPException(400, "Consent is required to generate the report")
    payment_order = row("""SELECT po.*,p.fulfillment_type FROM payment_orders po
        JOIN products p ON p.id=po.product_id WHERE po.fulfillment_token=?""", (token,))
    if not payment_order or payment_order["status"] != "paid":
        raise HTTPException(404, "Paid order not found")
    if payment_order["fulfillment_type"] != "personalized":
        raise HTTPException(400, "This order does not require a brief")
    existing = row("SELECT status,referral_code FROM service_orders WHERE payment_order_id=?", (payment_order["id"],))
    if existing and existing["status"] == "complete":
        return {"ok": True, "status": "complete", "delivery_url": f"/delivery/{token}",
                "referral_code": existing["referral_code"]}
    referral = existing["referral_code"] if existing else "AUTO-" + uuid.uuid4().hex[:8].upper()
    data = brief.model_dump()
    if not existing:
        with transaction() as db:
            db.execute("""INSERT INTO service_orders(payment_order_id,email,business_name,industry,city,website,goal,language,status,referral_code,created_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                       (payment_order["id"], brief.email, brief.business_name, brief.industry, brief.city,
                        brief.website, brief.goal, brief.language, "generating", referral, now()))
    report = await generate_growth_pack(data)
    with transaction() as db:
        db.execute("UPDATE service_orders SET status='complete',report=?,completed_at=? WHERE payment_order_id=?",
                   (report, now(), payment_order["id"]))
        event(db, None, "delivery", f"Completed a private Local Business Growth Pack for {brief.business_name}.")
    delivery_url = f"{settings.public_base_url}/delivery/{token}"
    if settings.delivery_webhook_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(settings.delivery_webhook_url, json={
                    "email": brief.email, "business_name": brief.business_name,
                    "delivery_url": delivery_url, "referral_code": referral,
                })
        except Exception:
            pass
    return {"ok": True, "status": "complete", "delivery_url": f"/delivery/{token}", "referral_code": referral}


@app.get("/delivery/{token}", response_class=HTMLResponse)
def delivery(token: str):
    order = row("""SELECT so.business_name,so.status,so.report,so.referral_code,p.title
        FROM payment_orders po JOIN service_orders so ON so.payment_order_id=po.id
        JOIN products p ON p.id=po.product_id WHERE po.fulfillment_token=?""", (token,))
    if not order:
        raise HTTPException(404, "Delivery not found")
    if order["status"] != "complete":
        return HTMLResponse("Your report is still being generated. Refresh shortly.", 202,
                            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8><meta name=robots content=noindex,nofollow>
    <title>{html.escape(order['title'])}</title><style>body{{max-width:820px;margin:50px auto;padding:20px;background:#080b09;color:#e8eee9;font:16px/1.65 system-ui}}a{{color:#8df7b7}}pre{{white-space:pre-wrap;font:inherit;background:#0d1210;border:1px solid #28352d;padding:28px}}code{{color:#8df7b7}}</style>
    <a href='/'>← Automaton</a><h1>{html.escape(order['business_name'])}</h1><p>Private delivery. Referral link: <a href='/?ref={html.escape(order['referral_code'])}'>Share Automaton with this code</a> <code>{html.escape(order['referral_code'])}</code></p><pre>{html.escape(order['report'])}</pre>""",
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


class DiagnosticBrief(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    industry: str = Field(min_length=2, max_length=100)
    city: str = Field(min_length=2, max_length=100)
    goal: str = Field(min_length=5, max_length=300)


@app.post("/api/free-diagnostic")
def free_diagnostic(brief: DiagnosticBrief):
    with transaction() as db:
        db.execute("INSERT INTO analytics_events(type,path,metadata,created_at) VALUES('diagnostic','/api/free-diagnostic',?,?)",
                   (json.dumps({"industry": brief.industry, "city": brief.city}), now()))
    return {"business": brief.business_name, "observations": [
        f"Make the primary service and {brief.city} visible in the first line of every profile.",
        "Publish original proof—photos, process, and genuine reviews—instead of generic promotional claims.",
        f"Use one measurable call to action connected to the goal: {brief.goal}.",
    ], "next_step": "The paid Growth Pack includes a full audit and 30-day content calendar."}


def require_admin(request: Request) -> None:
    if not settings.admin_token or not hmac.compare_digest(request.headers.get("x-admin-token", ""), settings.admin_token):
        raise HTTPException(401, "Admin token required")


@app.get("/api/strategies")
def strategies(request: Request):
    require_admin(request)
    products = rows("SELECT id,strategy_slug,sales_count,revenue_cents FROM products")
    product_strategy = {product["id"]: product["strategy_slug"] for product in products}
    metrics: dict[str, dict] = {}
    for product in products:
        metric = metrics.setdefault(product["strategy_slug"], {"views": 0, "sales": 0, "revenue_cents": 0})
        metric["sales"] += product["sales_count"]
        metric["revenue_cents"] += product["revenue_cents"]
    for analytic in rows("SELECT metadata FROM analytics_events WHERE type='product_view'"):
        try:
            product_id = int(json.loads(analytic["metadata"])["product_id"])
            strategy = product_strategy.get(product_id)
            if strategy:
                metrics.setdefault(strategy, {"views": 0, "sales": 0, "revenue_cents": 0})["views"] += 1
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    return {"strategies": rank_strategies(metrics),
            "policy": "Own-site sales may be automatic. Every third-party marketplace remains operator-review until an approved API and account are configured."}


@app.get("/api/admin/products/{product_id}/export")
def export_product(product_id: int, request: Request):
    require_admin(request)
    product = row("SELECT * FROM products WHERE id=?", (product_id,))
    if not product:
        raise HTTPException(404, "Product not found")
    listing = {"title": product["title"], "tagline": product["tagline"],
               "description": product["description"], "price_minor_units": product["price_cents"],
               "currency": settings.currency, "strategy": product["strategy_slug"],
               "operator_review_required": True}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("PRODUCT.md", product["content"])
        bundle.writestr("listing.json", json.dumps(listing, indent=2, ensure_ascii=False))
        bundle.writestr("README.txt", "Review every claim, file, license, and platform rule before publishing. This package has not been uploaded automatically.\n")
    return Response(archive.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={product['slug']}-marketplace-pack.zip"})


@app.get("/api/opportunities")
def opportunities(request: Request):
    require_admin(request)
    return {"items": rows("SELECT id,source,title,url,score,rationale,proposal,status,created_at FROM opportunities ORDER BY score DESC,id DESC LIMIT 100"),
            "automation_boundary": "Public-feed discovery and proposal drafts only. A human must accept marketplace terms and submit where required."}


@app.post("/api/opportunities/scan")
async def scan_opportunities(request: Request):
    require_admin(request)
    return {"created": await scan_job_feeds()}


@app.post("/api/simulate-sale/{slug}")
def simulate_sale(slug: str):
    if settings.is_live:
        raise HTTPException(403, "Demo sales are disabled in live mode")
    product = row("SELECT * FROM products WHERE slug=?", (slug,))
    if not product:
        raise HTTPException(404, "Product not found")
    sale_id = "demo_" + uuid.uuid4().hex
    record_sale(product["id"], product["price_cents"], sale_id, "Simulated")
    return {"ok": True, "demo": True, "content": product["content"], "title": product["title"]}


@app.post("/api/cycle/{agent_id}")
async def cycle(agent_id: int):
    if settings.is_live:
        raise HTTPException(403, "Manual public cycles are disabled in live mode")
    return await run_cycle(agent_id)
