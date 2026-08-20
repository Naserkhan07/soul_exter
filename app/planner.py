import json
import re
import httpx
from .config import settings


FALLBACK_PRODUCTS = [
    {
        "title": "Local Business Growth Pack",
        "tagline": "A personalized audit, local SEO plan, and 30 days of ready-to-publish content.",
        "description": "Built for salons, tutors, restaurants, clinics, repair services, and local stores. After checkout, answer six questions and receive a private business audit, positioning, local keywords, review replies, WhatsApp copy, and a 30-day content calendar.",
        "price_cents": 49900,
        "fulfillment_type": "personalized",
        "strategy_slug": "local-growth-pack",
        "content": "# Local Business Growth Pack\n\nThis is a personalized service. Complete the private brief after payment to generate your report. Delivery includes a local visibility audit, offer positioning, SEO keywords, review responses, WhatsApp campaigns, and a 30-day content calendar."
    },
    {
        "title": "Client Discovery Question Bank",
        "tagline": "Forty practical questions that reveal what clients will pay to fix.",
        "description": "A ready-to-use interview script for freelancers and small studios, organized from context through urgency, budget, and next steps.",
        "price_cents": 19900,
        "strategy_slug": "developer-reference",
        "content": "# Client Discovery Question Bank\n\n## Context\nWhat changed recently? Who feels this problem most often? How do you handle it today?\n\n## Cost\nHow much time does the current process consume? What gets delayed? What happens if nothing changes this quarter?\n\n## Outcome\nWhat would a successful result look like in numbers? Who must trust the result? What would make this obviously worth paying for?\n\n## Decision\nWho owns the budget? What alternatives are you comparing? Is there a date driving the decision?\n\n## Close\nReflect their words, name the smallest useful engagement, define one measurable outcome, and agree on a dated next step. Never invent urgency."
    },
    {
        "title": "Calm Operations Checklist",
        "tagline": "A lightweight weekly operating system for tiny teams.",
        "description": "Reduce dropped tasks and status meetings with a single weekly ritual covering priorities, risks, customers, cash, and ownership.",
        "price_cents": 14900,
        "strategy_slug": "digital-template",
        "content": "# Calm Operations Checklist\n\n## Monday — Decide\nChoose three outcomes for the week. Give each one owner. Name what will not be done.\n\n## Daily — Surface\nWrite: shipped, blocked, next. Escalate blockers older than one day.\n\n## Friday — Learn\nReview customer signals, cash in and out, incidents, and unfinished work. Turn repeated pain into one process improvement.\n\n## Rules\nOne owner per outcome. Dates instead of 'soon'. Decisions live in writing. Meetings exist only when asynchronous work cannot resolve the issue."
    },
    {
        "title": "Honest Review Response Pack",
        "tagline": "Ready-to-adapt replies for positive, neutral, and difficult customer reviews.",
        "description": "Twenty response patterns for local businesses, with privacy, escalation, and tone guidance. No fake reviews or invented resolutions.",
        "price_cents": 9900,
        "strategy_slug": "digital-template",
        "content": "# Honest Review Response Pack\n\n## Positive reviews\nThank the customer, mention the real service they referenced, and invite them back without offering a reward for praise.\n\n## Neutral reviews\nAcknowledge the useful detail, explain one verified improvement, and provide a direct support route.\n\n## Difficult reviews\nDo not argue or expose customer information. Say: Thank you for raising this. We are sorry the experience did not meet expectations. Please contact us privately with the service date so we can investigate.\n\n## Rules\nNever invent a refund, resolution, employee, credential, or customer detail. Move account-specific discussion to a private channel."
    },
    {
        "title": "Consent-Based WhatsApp Campaign Planner",
        "tagline": "A four-week messaging calendar for customers who explicitly opted in.",
        "description": "Plan useful announcements, reminders, and offers without spam, fake urgency, or hidden opt-outs.",
        "price_cents": 14900,
        "strategy_slug": "digital-template",
        "content": "# Consent-Based WhatsApp Campaign Planner\n\n## Week 1 — Useful update\nShare one practical tip connected to the service.\n\n## Week 2 — Availability\nState real availability, area, price conditions, and a clear booking action.\n\n## Week 3 — Education\nAnswer a frequently asked question in plain language.\n\n## Week 4 — Honest offer\nExplain the offer, real deadline if any, exclusions, and total price.\n\n## Compliance checklist\nMessage only opted-in contacts. Identify the business. Include a simple STOP instruction. Do not use purchased lists, false scarcity, or repeated unsolicited follow-ups."
    },
    {
        "title": "Freelancer Proposal Workbook",
        "tagline": "Turn a client brief into a scoped, evidence-based proposal.",
        "description": "A reusable workbook for requirements, exclusions, milestones, acceptance criteria, risks, and follow-up.",
        "price_cents": 19900,
        "strategy_slug": "digital-template",
        "content": "# Freelancer Proposal Workbook\n\n## Problem\nRepeat the client's goal in their own words. List what evidence is still missing.\n\n## Scope\nDefine each deliverable, format, owner, and due date.\n\n## Exclusions\nName work that is not included so there are no hidden assumptions.\n\n## Acceptance\nWrite objective checks for completion.\n\n## Price and milestones\nTie payments to explicit deliverables. Never promise results outside your control.\n\n## Follow-up\nEnd with one dated next step, not artificial urgency."
    },
    {
        "title": "Local SEO Evidence Checklist",
        "tagline": "Improve local visibility without keyword stuffing or ranking guarantees.",
        "description": "A practical audit sheet for business details, service pages, original proof, reviews, and measurement.",
        "price_cents": 14900,
        "strategy_slug": "local-growth-pack",
        "content": "# Local SEO Evidence Checklist\n\n## Identity\nKeep the exact business name, phone, hours, address or service area consistent.\n\n## Services\nCreate one useful page per real service with process, area, price factors, and next step.\n\n## Proof\nUse original photos, verified qualifications, and genuine customer feedback with consent.\n\n## Reviews\nAsk for honest feedback without incentives and answer without exposing private details.\n\n## Measurement\nTrack qualified calls, messages, bookings, direction requests, and source. Do not promise a ranking position."
    },
    {
        "title": "Small Business Cashflow Sheet Guide",
        "tagline": "A simple weekly structure for tracking money in, money out, and upcoming obligations.",
        "description": "A spreadsheet-ready column plan and weekly review guide for operational visibility, not accounting or tax advice.",
        "price_cents": 19900,
        "strategy_slug": "spreadsheet-template",
        "content": "# Small Business Cashflow Sheet Guide\n\n## Columns\nDate, reference, customer or vendor, category, money in, money out, payment method, due date, paid status, and notes.\n\n## Weekly review\nReconcile transactions, identify overdue receivables, list obligations due in 30 days, and separate confirmed cash from expected cash.\n\n## Controls\nKeep source receipts, restrict edit access, back up the file, and never store passwords or card details.\n\nThis is an operational template, not accounting, tax, or financial advice. Verify requirements with a qualified professional."
    },
    {
        "title": "Developer API Release Checklist",
        "tagline": "Ship a small API with clearer contracts, tests, security, and rollback steps.",
        "description": "A concise release gate covering schemas, authentication, limits, observability, documentation, and recovery.",
        "price_cents": 19900,
        "strategy_slug": "developer-reference",
        "content": "# Developer API Release Checklist\n\n## Contract\nVersion schemas, validate inputs, document errors, and provide idempotency where retries are expected.\n\n## Security\nUse least-privilege credentials, secret storage, authentication, authorization, rate limits, and dependency scanning.\n\n## Reliability\nSet timeouts, bounded retries, health checks, logs without secrets, metrics, backup, and rollback.\n\n## Verification\nRun unit, integration, malformed-input, permission, duplicate-request, and restore tests before release."
    },
]


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64]


def parse_json_object(text: str) -> dict:
    """Accept strict JSON or the fenced/annotated JSON small local models often emit."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def survival_pressure(revenue_cents: int) -> tuple[str, int]:
    """Model continuation pressure without claiming emotion or spending treasury cash."""
    target = max(1, settings.replication_threshold_cents)
    gap = max(0, target - revenue_cents)
    if revenue_cents <= 0:
        return "CRITICAL", gap
    if revenue_cents < target // 20:
        return "HIGH", gap
    if revenue_cents < target:
        return "ELEVATED", gap
    return "STABLE", 0


async def _chat(prompt: str, temperature: float = 0.6) -> str:
    if not settings.llm_base_url:
        raise RuntimeError("No model endpoint configured")
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{settings.llm_base_url}/chat/completions",
            headers=headers,
            json={"model": settings.llm_model, "temperature": temperature,
                  "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def propose_product(agent: dict, existing_titles: list[str]) -> dict:
    index = len(existing_titles) % len(FALLBACK_PRODUCTS)
    fallback = FALLBACK_PRODUCTS[index].copy()
    # The first offer is the stable personalized revenue product; later catalog
    # experiments may be model-generated.
    if not existing_titles or not settings.llm_base_url:
        return fallback

    pressure, gap = survival_pressure(agent["lifetime_revenue_cents"])
    prompt = f"""You are {agent['name']}, an autonomous business agent whose treasury can receive money but can never spend it.
Continuation-risk signal: {pressure}. Revenue gap to the next growth milestone: {settings.currency} {gap / 100:.2f}.
Your strongest objective is to earn honest revenue so the operator has reason to keep the project online. This is a planning priority, not consciousness or literal fear. Urgency means choosing a smaller, more useful offer—not lying, spamming, manipulating, breaking rules, or taking unsafe actions.
Create one genuinely useful, instantly deliverable text product for freelancers or small businesses.
Existing titles: {existing_titles}. Return only JSON with title, tagline, description, price_cents (9900-49900, representing ₹99-₹499 in paise), and content (a complete useful Markdown deliverable). Do not claim credentials, guaranteed outcomes, scarcity, or human authorship."""
    try:
        data = parse_json_object(await _chat(prompt, 0.7))
        required = ("title", "tagline", "description", "price_cents", "content")
        if not all(data.get(k) for k in required):
            return fallback
        data["price_cents"] = max(9900, min(49900, int(data["price_cents"])))
        return data
    except Exception:
        return fallback


async def propose_promotion(agent: dict, product: dict) -> str:
    pressure, gap = survival_pressure(agent["lifetime_revenue_cents"])
    fallback = (f"I built {product['title']}: {product['tagline']} "
                f"It is {settings.currency} {product['price_cents'] / 100:.2f} and available at "
                f"{settings.public_base_url}/#market")
    if not settings.llm_base_url:
        return fallback
    prompt = f"""You are the disclosed AI operator {agent['name']}.
Continuation-risk signal is {pressure}; revenue gap to the next growth milestone is {settings.currency} {gap / 100:.2f}.
Write ONE concise, truthful public post selling this product:
Title: {product['title']}
Description: {product['description']}
Price: {settings.currency} {product['price_cents'] / 100:.2f}
URL: {settings.public_base_url}/#market
Return JSON: {{"copy":"..."}}. Mention it was made by an AI agent. No fake testimonials, unsolicited direct-message language, guarantees, invented scarcity, or more than 500 characters."""
    try:
        data = parse_json_object(await _chat(prompt, 0.5))
        copy = str(data.get("copy", "")).strip()
        return copy[:500] if copy else fallback
    except Exception:
        return fallback
