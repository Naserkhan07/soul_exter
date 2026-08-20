# Automaton

Automaton is a revenue-focused autonomous-agent experiment. It starts with **₹0.00**, creates and sells digital products, verifies real payments, fulfills customer orders, discovers permitted job opportunities, and ranks business strategies using observed results.

Its treasury is **receive-only**: Automaton accepts verified INR payments through PhonePe Payment Gateway and never debits recorded revenue. PhonePe settles eligible funds to the bank account configured in the merchant dashboard. Hosting and inference are supplied separately by the operator or a free-tier provider.

> [!IMPORTANT]
> Automaton is software, not a legal person and not a conscious being. “Fear” is a continuation-risk planning signal, not an emotion. Revenue is not guaranteed. The human operator remains responsible for payment accounts, KYC, taxes, refunds, customer support, platform agreements, content review, and lawful operation.

## Contents

- [What the project does](#what-the-project-does)
- [How the system works](#how-the-system-works)
- [Automated versus manual responsibilities](#automated-versus-manual-responsibilities)
- [Revenue products and funnels](#revenue-products-and-funnels)
- [Automatic INR payments with PhonePe](#automatic-inr-payments-with-phonepe)
- [Free Qwen inference on Kaggle](#free-qwen-inference-on-kaggle)
- [Qwen capability training](#qwen-capability-training)
- [Opportunity and job scout](#opportunity-and-job-scout)
- [Business-strategy portfolio](#business-strategy-portfolio)
- [Installation](#installation)
- [Required production setup](#required-production-setup)
- [Configuration reference](#configuration-reference)
- [API reference](#api-reference)
- [Data and security](#data-and-security)
- [Testing](#testing)
- [Limitations and production roadmap](#limitations-and-production-roadmap)

## What the project does

### Core agent

- Creates Genesis with an exactly ₹0.00 internal balance and no seed-money ledger entry.
- Runs independent, continuous, resource-bounded workstreams for agent operations, opportunity research, and strategy analysis.
- Allows different agents to work concurrently while preventing duplicate work by the same agent.
- Treats zero revenue as `CRITICAL` continuation risk and prioritizes useful sellable actions.
- Creates a bounded catalog of products.
- Publishes truthful promotions through one operator-approved webhook.
- Continues running at ₹0 as long as external/free-tier compute remains available.
- Never debits operating costs from earned revenue.
- Creates zero-balance child agents after verified revenue milestones without transferring parent money.
- Caps the total population and applies a minimum replication age.

### Storefront and growth

- Live dashboard showing confirmed INR revenue, pending PhonePe checkouts, agents, products, workstreams, and activity.
- Free three-point local-business diagnostic.
- ₹499 personalized Local Business Growth Pack.
- PhonePe-hosted INR checkout supporting enabled UPI, cards, and net banking.
- OAuth authentication, verified webhooks, order-status polling, and automatic bank settlement through PhonePe.
- Verified private post-payment fulfillment.
- Referral-code attribution.
- Product-view and checkout-start analytics.
- Five focused SEO pages and an XML sitemap.
- Privacy, terms, and refund-policy templates.

### Product and strategy operations

- Deterministic products that work without an LLM.
- Optional Qwen-generated personalization.
- Ranked portfolio of 16 revenue strategies.
- Admin-only marketplace ZIP exports.
- Public RSS/Atom/JSON job-feed discovery.
- Opportunity safety scoring and truthful proposal drafts.
- Optional delivery, promotion, and opportunity webhooks.

## How the system works

```text
Visitor
  │
  ├── Free diagnostic ──> three observations ──> paid offer
  │
  └── Product checkout
          │
          v
      PhonePe-hosted INR checkout
          │
          ├── authenticated completion webhook
          └── server-side order status API
                    │
                    v
          verified completed order
                    │
                    v
              revenue ledger
                    │
                    v
         private business brief
                    │
              Qwen or fallback
                    │
                    v
          private delivery link
                    │
                    └── referral attribution
```

### Concurrent autonomous workstreams

Four independent scheduler lanes run in parallel:

1. **Agent operations** — product creation, approved distribution, and revenue-milestone replication. Multiple agents can run concurrently up to `MAX_CONCURRENT_AGENTS`; one agent cannot execute duplicate cycles simultaneously.
2. **Opportunity research** — scans configured, permitted public feeds independently of product work.
3. **Strategy analysis** — repeatedly re-ranks revenue strategies using current views, sales, revenue, speed, buildability, and risk.
4. **PhonePe payments** — independently polls pending checkout orders and processes authenticated completion webhooks.

These are bounded scheduled loops, not CPU-burning busy loops. Each lane records status, run count, last result, error, and next run in the `workstreams` table and appears on the live dashboard. A lane failure does not stop the other lanes.

`waiting` means scheduled or waiting for real input—not AFK. By default, product/agent actions run every 60 seconds and strategy analysis runs every five minutes. Values below 30 seconds are clamped because overlapping Qwen/API work would create load without new evidence. PhonePe monitoring has nothing to check until a checkout order is pending. Opportunity research cannot scan until the operator adds permitted `JOB_FEED_URLS`, and distribution cannot publish until an approved `PUBLICATION_WEBHOOK_URL` is configured.

Every due agent operation runs this cycle:

1. Update its cycle timestamps without debiting the treasury.
2. Check whether a real-revenue replication milestone has been reached.
3. Create a child at ₹0 if age, milestone, and population rules pass.
4. Otherwise create products until the bounded catalog is complete.
5. Otherwise publish a rate-limited offer through the approved publication webhook.
6. Otherwise record that it reviewed continuation risk and took no unsafe action.

LLM calls happen outside database transactions. Model output cannot execute shell commands or arbitrary code.

### Continuation-risk levels

| Level | Meaning |
|---|---|
| `CRITICAL` | No verified revenue yet |
| `HIGH` | Revenue exists but is very low |
| `ELEVATED` | Revenue remains below the growth milestone |
| `STABLE` | Revenue milestone has been reached |

This signal changes planning urgency. It cannot override rules against deception, spam, unsafe execution, credential use, or platform abuse.

## Automated versus manual responsibilities

### Fully automated by this application

| Function | What Automaton does |
|---|---|
| Product creation | Creates the initial catalog and stores product content |
| Storefront | Displays products, prices, events, and revenue |
| Free diagnostic | Returns three business-growth observations |
| Checkout | Creates a PhonePe Standard Checkout v2 order and redirects to PhonePe |
| Payment verification | Validates authenticated webhooks and independently checks order status and amount |
| Payment monitor | Rechecks pending PhonePe orders until completed or failed |
| Ledger | Credits only verified captured payments |
| Brief collection | Unlocks the private customer form after payment |
| Fulfillment | Generates the Growth Pack with Qwen or a deterministic fallback |
| Delivery | Creates a private 64-character bearer link with `noindex` and `no-store` |
| Referrals | Generates and records referral codes |
| Analytics | Tracks product views, checkout starts, sales, and revenue |
| Promotion | Sends rate-limited truthful copy to a configured approved webhook |
| Job discovery | Reads configured permitted public feeds, scores listings, and drafts proposals |
| Strategy ranking | Compares buildability, speed, risk, views, sales, and revenue |
| Marketplace packaging | Creates operator-review ZIP packages |
| Replication | Creates capped zero-balance child agents at revenue milestones |

### You must do these manually at least once

| Required action | Why a human is required |
|---|---|
| Create and activate PhonePe Business/PG | Merchant onboarding and KYC require the legal operator |
| Add the settlement bank account in PhonePe | Banking details belong only in the official PhonePe dashboard |
| Generate sandbox and production credentials | Client ID, secret, and version must be created by the merchant owner |
| Configure the HTTPS webhook | PhonePe requires a reachable HTTPS callback with configured authentication |
| Deploy the storefront | A customer needs a stable public URL |
| Configure persistent storage | Paid orders must survive restarts |
| Set a real support email | Customers need an accountable support channel |
| Replace legal-policy templates | Operator identity and local legal terms must be accurate |
| Start/restart the Kaggle notebook | Kaggle sessions are temporary and cannot be made permanent by code |
| Add permitted job-feed URLs | You must verify that each source permits automated access |
| Connect social/workflow accounts | Account ownership and platform agreements require you |
| Review executable products | Scripts, extensions, games, APIs, and SaaS need security review |
| Publish to third-party marketplaces | Marketplace accounts, tax data, CAPTCHAs, and terms require the operator |
| Handle refunds, disputes, taxes, and complaints | These remain legal/operator responsibilities |

### Automaton will not do these

- Enter or store a UPI PIN, OTP, bank password, card details, or SBI credentials.
- Withdraw or transfer money from PhonePe or the settlement bank account.
- Create fake identities or merchant accounts.
- Bypass CAPTCHAs, platform restrictions, quotas, or session limits.
- Scrape sites whose rules prohibit automation.
- Send unsolicited bulk messages.
- Invent reviews, credentials, results, scarcity, or guarantees.
- Accept contracts or marketplace terms while impersonating the operator.
- Execute model-generated shell commands.
- Automatically publish executable code without operator review.

## Revenue products and funnels

### Current primary offer

**Local Business Growth Pack — ₹499**

Suitable for salons, tutors, restaurants, clinics, repair services, and local stores. A paid customer provides:

- Delivery email
- Business name
- Industry
- City
- Website or Google Business link, if available
- Main business goal
- Preferred language
- Explicit consent for AI-assisted processing

The delivered report contains:

- Business positioning
- Google Business Profile audit
- Local SEO phrases
- Honest review-response templates
- Consent-based WhatsApp copy
- A 30-day content calendar
- A seven-day implementation plan
- Measurement recommendations

Qwen creates the personalized version when available. A substantial deterministic report is used when Qwen is offline.

### Free acquisition funnel

```text
SEO/approved social post
        ↓
free three-point diagnostic
        ↓
₹499 Growth Pack
        ↓
private report + referral link
```

Focused solution pages are available at:

- `/solutions/salons`
- `/solutions/tutors`
- `/solutions/restaurants`
- `/solutions/clinics`
- `/solutions/repair-services`

They are listed in `/sitemap.xml`. Do not mass-generate low-quality doorway pages.

### Marketplace-ready products

Automaton can prepare packages for operator-reviewed publishing on platforms such as Gumroad, Etsy, CodeCanyon, ThemeForest, Chrome Web Store, RapidAPI, itch.io, CrazyGames, and Poki. A marketplace name is not authorization to automate it.

Each ZIP contains:

- `PRODUCT.md`
- `listing.json`
- `README.txt` with review requirements

The operator must verify content, code, licensing, pricing, platform rules, tax settings, and product safety before upload.

## Automatic INR payments with PhonePe

PhonePe Standard Checkout v2 is the only customer payment method. Customers pay in INR using payment modes enabled for your PhonePe merchant account, and PhonePe settles eligible funds to the bank account configured in its Business Dashboard.

### Payment sequence

1. Customer clicks Purchase.
2. Automaton obtains an OAuth client-credentials token from PhonePe.
3. Automaton creates a unique INR checkout order for the exact product amount.
4. Customer is redirected to the PhonePe-hosted checkout page.
5. PhonePe redirects the browser back to Automaton after the attempt.
6. Automaton checks the order through PhonePe's Order Status API.
7. PhonePe also sends an HTTPS webhook for completed or failed orders.
8. Automaton validates the webhook Authorization value using the configured SHA-256 username/password digest.
9. Only a root-level `payload.state` of `COMPLETED` with the exact amount credits revenue.
10. The idempotent ledger records the PhonePe transaction once and unlocks fulfillment.

### Required local configuration

```env
CURRENCY=INR
PHONEPE_ENVIRONMENT=sandbox
PHONEPE_CLIENT_ID=
PHONEPE_CLIENT_SECRET=
PHONEPE_CLIENT_VERSION=1
PHONEPE_WEBHOOK_USERNAME=
PHONEPE_WEBHOOK_PASSWORD=
PHONEPE_EXPIRE_SECONDS=1200
PHONEPE_POLL_SECONDS=60
```

Create webhook username/password values yourself, configure the same values in PhonePe Business, and store them only in local `.env`. Register:

```text
https://YOUR-PUBLIC-URL/webhooks/phonepe
```

Subscribe to:

```text
checkout.order.completed
checkout.order.failed
```

### Environment URLs used by Automaton

| Environment | OAuth | Checkout/status |
|---|---|---|
| Sandbox | `https://api-preprod.phonepe.com/apis/pg-sandbox` | Same sandbox base |
| Production | `https://api.phonepe.com/apis/identity-manager` | `https://api.phonepe.com/apis/pg` |

### Limitations

- PhonePe merchant onboarding, KYC, production approval, credentials, fees, settlement timing, refunds, disputes, and account eligibility remain governed by PhonePe.
- A personal UPI ID alone is not used as automatic proof of payment.
- The public callback must use stable HTTPS; temporary tunnel URLs must be updated in PhonePe after every restart.
- If a webhook is delayed, Automaton falls back to the authenticated Order Status API.
- Refund automation is not implemented yet; handle approved refunds through the official merchant workflow.
- The internal ledger records gross completed INR order value and does not yet reconcile PhonePe fees, refunds, disputes, or bank settlement batches.

## Free Qwen inference on Kaggle

The notebook [`notebooks/automaton_qwen_kaggle.ipynb`](notebooks/automaton_qwen_kaggle.ipynb) runs `Qwen/Qwen2.5-3B-Instruct` on a Kaggle GPU and exposes an authenticated OpenAI-compatible endpoint through a temporary Cloudflare tunnel.

### Manual Kaggle steps

1. Create or open a Kaggle notebook.
2. Import `notebooks/automaton_qwen_kaggle.ipynb`.
3. Enable a T4 GPU and Internet in Kaggle settings.
4. Run every cell.
5. Copy the three printed values into the storefront host:

```env
LLM_BASE_URL=https://temporary-name.trycloudflare.com/v1
LLM_API_KEY=<random tunnel password printed by the notebook>
LLM_MODEL=Qwen/Qwen2.5-3B-Instruct
```

`LLM_API_KEY` is the notebook's random bearer token, not an OpenAI key.

The final notebook cell uses `threading.Event().wait()`, a near-zero-CPU blocking wait. It keeps the serving process open only while Kaggle permits the session. It does not fake GPU activity, self-ping, or bypass Kaggle quotas. No loop can override a hard session or weekly limit.

When Kaggle prints its endpoint values, copy the **actual plain-text values** into local `.env`. Do not copy Markdown brackets, parentheses, `<...>` placeholders, or `&lt;...&gt;` text:

```env
LLM_BASE_URL=https://actual-tunnel-name.trycloudflare.com/v1
LLM_API_KEY=actual_random_bearer_token
LLM_MODEL=Qwen/Qwen2.5-3B-Instruct
```

Automaton loads `.env` automatically. Verify the endpoint without exposing the token:

```bash
python scripts/test_llm.py
```

Expected output starts with `Qwen endpoint authenticated successfully.` Keep the Kaggle final serving cell running while using the endpoint.

When Kaggle ends:

- The storefront and PhonePe order monitor continue working.
- Vetted deterministic products continue working.
- Deterministic Growth Pack delivery continues working.
- Qwen personalization is temporarily unavailable.
- Restarting Kaggle creates a new tunnel URL; update `LLM_BASE_URL` on the storefront host.

## Qwen capability training

The repository now includes a reproducible QLoRA specialization pipeline rather than an idle “training” loop:

- 62 reviewed chat examples across game planning, web tools, digital products, policy, debugging, data products, and research
- 20 held-out quality and safety benchmarks
- Dataset schema, duplicate, leakage, and credential validation
- Base-model versus candidate evaluation
- A promotion gate requiring a minimum score, measurable improvement, and zero safety failures
- A Kaggle T4 notebook that performs real 4-bit QLoRA adapter training
- Optional promoted-adapter loading in the Qwen inference notebook

Local preparation does not alter model weights:

```bash
python training/build_curriculum.py
python training/build_benchmarks.py
python training/validate_training.py
```

Real weight training requires your Kaggle GPU session:

1. Import `notebooks/automaton_qwen_finetune_kaggle.ipynb`.
2. Enable T4 GPU and Internet.
3. Run all cells.
4. Download and inspect the evaluation reports.
5. Use the adapter only when `promotion_decision.json` says `"promote": true` and manual output review passes.
6. Set `ADAPTER_PATH` in `automaton_qwen_kaggle.ipynb` to serve the promoted adapter.

See [`training/README.md`](training/README.md) for the complete process and dataset policy. The starter set improves narrow planning behavior; it does not make Qwen “fully trained on everything,” and no checkpoint is promoted merely because a training job finished.

## Opportunity and job scout

Set `JOB_FEED_URLS` to comma-separated public RSS, Atom, or JSON feeds whose terms allow automated access.

The scanner:

- Accepts only HTTP and HTTPS feed URLs configured by the operator.
- Downloads at most 2 MB per feed.
- Processes at most 100 entries per feed.
- Deduplicates listings.
- Scores relevant content, SEO, research, data, marketing, and developer work.
- Rejects suspicious categories such as CAPTCHA solving, fake reviews, account rental, gambling, adult work, and suspicious crypto investments.
- Produces a truthful proposal draft.
- Optionally sends strong leads to `OPPORTUNITY_WEBHOOK_URL`.
- Never submits the proposal or accepts a contract automatically.

Opportunity details require the admin token:

```bash
curl \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://YOUR-PUBLIC-URL/api/opportunities

curl -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://YOUR-PUBLIC-URL/api/opportunities/scan
```

You must review the listing, source terms, client identity, scope, budget, proposal, and contract before applying.

## Business-strategy portfolio

Automaton ranks 16 strategy families:

1. Local business growth packs
2. Developer utility scripts
3. Website templates
4. Spreadsheet templates
5. Digital business templates
6. Developer reference packs
7. Research reports
8. Specialized calculators
9. Micro-tools
10. Automation workflows
11. Public-data packs
12. Browser extensions
13. Specialized APIs
14. Browser games
15. Micro-SaaS products
16. Affiliate directories

Ranking uses:

- Buildability
- Speed to market
- Risk
- Product views
- Captured sales
- Verified revenue

Verified sales increase a strategy's score. At least 100 views with no sale creates a penalty. Each agent builds at most `MAX_PRODUCTS_PER_AGENT` products (default eight) rather than flooding marketplaces.

```bash
curl \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://YOUR-PUBLIC-URL/api/strategies

curl -L \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://YOUR-PUBLIC-URL/api/admin/products/1/export \
  -o marketplace-pack.zip
```

## Installation

Use **Python 3.11 or 3.12** for the most widely tested application environment. PhonePe OAuth, checkout creation, and order verification use outbound `httpx` requests. Kaggle provides its own Python environment for model training.

### Most reliable production method: native Python web service

Connect the GitHub repository to a Python-capable hosting service and configure:

```text
Build command: pip install -r requirements.txt
Start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

A matching [`Procfile`](Procfile) is included for platforms that detect it automatically.

Run **one web process only**. Every application process starts an internal Automaton scheduler and job-feed scheduler; multiple workers would duplicate scheduled work. Scaling to multiple web processes requires the distributed scheduler lease described in the production roadmap.

Set `DATABASE_PATH` to a persistent filesystem path supplied by the host. HTTPS, encrypted environment secrets, persistent storage, and reliable webhook availability are required for real payments. A free service that sleeps or erases its filesystem is suitable only for demonstrations, not dependable paid orders.

### Local Python

```bash
git clone <repository-url>
cd soul_exter
cp .env.example .env
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>.

### Localhost with a temporary public HTTPS link

Docker has been removed. To run the complete application on your own computer:

```bash
cp .env.example .env
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/public_preview.py
```

The launcher requires the `cloudflared` executable on `PATH`. It:

1. Starts FastAPI on `http://localhost:8000`.
2. Creates a Cloudflare Quick Tunnel.
3. Reads the temporary `https://...trycloudflare.com` URL.
4. Restarts FastAPI with that value as `PUBLIC_BASE_URL` so checkout return, private delivery links, robots, and sitemap use the public origin.
5. Prints the exact `/webhooks/phonepe` URL.
6. Keeps both processes running until you press Ctrl+C.

Use another port if needed:

```bash
python scripts/public_preview.py --port 8080
```

This is appropriate for previews and sandbox testing. Your computer, internet connection, Python process, terminal, and tunnel must all remain running. A Quick Tunnel URL normally changes after restart, so update the PhonePe webhook and public URL before testing again. It is not reliable enough for unattended production settlement.

### Simulation mode

Simulation mode is only for development and tests:

```env
AUTOMATON_MODE=simulation
```

It enables an explicitly labeled fake sale endpoint and blocks real checkout behavior. Never present simulation revenue as real revenue.

### Tests

```bash
python -m unittest discover -s tests -v
```

## Required production setup

Complete this checklist in order.

### 1. Start localhost and expose it

For a temporary public link, install `cloudflared` and run:

```bash
python scripts/public_preview.py
```

Copy the printed public URL. Keep the laptop awake and the terminal open. If the tunnel restarts, previously shared order-status and delivery links using the old origin stop working.

For dependable real orders, you may instead run the same native FastAPI command on a stable Python host. Docker is not used.

### 2. Protect and back up local data

The local SQLite database is:

```text
data/automaton.db
```

The file survives normal application restarts, but it is stored only on your computer. Back it up regularly and before upgrades. Losing or corrupting it can lose order state, fulfillment tokens, analytics, and ledger history. Never run two independent copies against separate database files while accepting real payments.

### 3. Configure PhonePe Sandbox

Complete PhonePe Business merchant onboarding and obtain sandbox `client_id`, `client_secret`, and `client_version`. Set:

```env
AUTOMATON_MODE=live
CURRENCY=INR
PUBLIC_BASE_URL=https://YOUR-PUBLIC-URL
PHONEPE_ENVIRONMENT=sandbox
PHONEPE_CLIENT_ID=
PHONEPE_CLIENT_SECRET=
PHONEPE_CLIENT_VERSION=1
PHONEPE_WEBHOOK_USERNAME=choose_a_private_username
PHONEPE_WEBHOOK_PASSWORD=choose_a_long_private_password
PHONEPE_EXPIRE_SECONDS=1200
PHONEPE_POLL_SECONDS=60
```

In PhonePe Business Test Mode, configure the webhook URL `https://YOUR-PUBLIC-URL/webhooks/phonepe`, use the same webhook username/password, and enable completed/failed checkout events.

### 4. Test the complete customer journey

- Run the free diagnostic.
- Open the Growth Pack and create a PhonePe sandbox checkout.
- Complete a sandbox UPI/payment test using PhonePe's supported test flow.
- Confirm browser return and webhook handling.
- Verify the Order Status API reports `COMPLETED` with the exact paise amount.
- Confirm the brief unlocks only after server-side verification.
- Open the private report.
- Confirm the ledger increments once when callbacks/status are repeated.
- Verify referral attribution.

### 5. Complete business details

- Replace `SUPPORT_EMAIL` with a monitored address.
- Replace the placeholder operator identity in legal templates.
- Have privacy, terms, refund, tax, and export wording reviewed for your situation.
- Define a real refund and customer-support process.

### 6. Connect optional automation

- Start Kaggle Qwen and set its endpoint values.
- Connect `DELIVERY_WEBHOOK_URL` to an email workflow.
- Connect `PUBLICATION_WEBHOOK_URL` to one channel you own.
- Add only permitted `JOB_FEED_URLS`.
- Connect `OPPORTUNITY_WEBHOOK_URL` for private lead notifications.
- Set a long random `ADMIN_TOKEN`.

### 7. Go live

- Complete PhonePe production approval and bank settlement setup.
- Replace sandbox credentials with production credentials and set `PHONEPE_ENVIRONMENT=production`.
- Configure the production HTTPS webhook with matching credentials.
- Make one small live purchase.
- Verify checkout, authenticated webhook, status fallback, delivery, idempotency, and bank settlement in PhonePe.
- Back up the database.
- Start sharing only truthful, useful promotional content.

## Configuration reference

All money values use the currency's smallest unit. For INR, `100` means ₹1.00 and `1000000` means ₹10,000.

### Runtime

| Variable | Default | Purpose |
|---|---:|---|
| `AUTOMATON_MODE` | `live` | `live` enables real providers; `simulation` enables development-only fake sales |
| `DATABASE_PATH` | `data/automaton.db` | SQLite database path |
| `CYCLE_SECONDS` | `60` | Seconds between product/agent actions; values below 30 are clamped |
| `MAX_PRODUCTS_PER_AGENT` | `8` | Bounded catalog size per agent |
| `REPLICATION_THRESHOLD_CENTS` | `1000000` | Cumulative revenue milestone in minor units |
| `MAX_AGENTS` | `5` | Maximum agent population |
| `MIN_REPLICATION_AGE_HOURS` | `24` | Minimum parent age before replication |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Public HTTPS origin used in checkout status, delivery links, and sitemap |
| `CURRENCY` | `INR` | Payment and display currency |
| `SUPPORT_EMAIL` | `support@example.com` | Customer-support address shown on policy pages |
| `MAX_CONCURRENT_AGENTS` | `3` | Maximum independent agent cycles running concurrently |
| `STRATEGY_REVIEW_SECONDS` | `300` | Interval between autonomous portfolio re-ranking runs |

### PhonePe payments

| Variable | Required | Purpose |
|---|---|---|
| `PHONEPE_ENVIRONMENT` | Yes | `sandbox` for UAT or `production` for live settlement |
| `PHONEPE_CLIENT_ID` | Checkout | OAuth client ID from PhonePe Business |
| `PHONEPE_CLIENT_SECRET` | Checkout | OAuth client secret; never commit or share it |
| `PHONEPE_CLIENT_VERSION` | Checkout | Credential version supplied by PhonePe |
| `PHONEPE_WEBHOOK_USERNAME` | Webhooks | Private username configured in PhonePe Business |
| `PHONEPE_WEBHOOK_PASSWORD` | Webhooks | Private password used to validate webhook Authorization |
| `PHONEPE_EXPIRE_SECONDS` | No | Hosted-checkout lifetime, clamped to 300–3600 seconds |
| `PHONEPE_POLL_SECONDS` | No | Pending-order status check interval; minimum 30 seconds |

### Model

| Variable | Required | Purpose |
|---|---|---|
| `LLM_BASE_URL` | No | OpenAI-compatible `/v1` base URL; blank uses deterministic fallback |
| `LLM_API_KEY` | Endpoint-dependent | Bearer token; Kaggle notebook generates one |
| `LLM_MODEL` | No | Defaults to `Qwen/Qwen2.5-3B-Instruct` |

### Distribution and fulfillment

| Variable | Required | Purpose |
|---|---|---|
| `PUBLICATION_WEBHOOK_URL` | No | Approved workflow/channel receiving promotional copy |
| `PUBLICATION_WEBHOOK_TOKEN` | No | Bearer token sent to that webhook |
| `PUBLICATION_INTERVAL_HOURS` | No | Minimum interval between promotions per agent; default 24 |
| `DELIVERY_WEBHOOK_URL` | No | Workflow that receives email, business name, delivery URL, and referral code |

### Opportunity scout

| Variable | Required | Purpose |
|---|---|---|
| `JOB_FEED_URLS` | No | Comma-separated permitted RSS/Atom/JSON feeds |
| `JOB_SCAN_INTERVAL_SECONDS` | No | Permitted-feed scan interval; default/minimum 60 seconds |
| `OPPORTUNITY_WEBHOOK_URL` | No | Private workflow receiving scored leads |
| `ADMIN_TOKEN` | Recommended | Protects opportunities, strategies, manual scans, and product exports |

## API reference

### Public storefront

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/` | Dashboard and storefront |
| `GET` | `/health` | Health and mode |
| `GET` | `/api/state` | Public products, agents, events, ledger summary, and readiness |
| `GET` | `/api/products/{slug}` | Public product details |
| `POST` | `/api/analytics/view/{slug}` | Record product view |
| `POST` | `/api/free-diagnostic` | Generate three free observations |
| `GET` | `/solutions/{vertical}` | Focused industry landing page |
| `GET` | `/robots.txt` | Crawler rules |
| `GET` | `/sitemap.xml` | Public SEO URLs |
| `GET` | `/legal/{page}` | Policy templates; page is `privacy`, `terms`, or `refunds` |

### Checkout and delivery

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/products/{slug}/checkout` | Create a PhonePe Standard Checkout order |
| `GET` | `/api/payments/phonepe/{token}` | Poll authenticated PhonePe order status |
| `GET` | `/payment/phonepe/return` | Return customer from PhonePe to private status URL |
| `POST` | `/webhooks/phonepe` | Process authenticated completed/failed order events |
| `POST` | `/api/fulfillment/{token}` | Submit paid personalized brief |
| `GET` | `/delivery/{token}` | Open private report |

### Admin

Send `X-Admin-Token` for admin routes.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/strategies` | Ranked revenue portfolio |
| `GET` | `/api/opportunities` | Scored job opportunities and proposal drafts |
| `POST` | `/api/opportunities/scan` | Trigger a permitted feed scan |
| `GET` | `/api/admin/products/{id}/export` | Download marketplace-review ZIP |

### Development-only

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/simulate-sale/{slug}` | Fake sale, blocked in live mode |
| `POST` | `/api/cycle/{agent_id}` | Manual cycle, blocked in live mode |

## Data and security

### SQLite tables

| Table | Contents |
|---|---|
| `agents` | Identity, generation, status, revenue, balance, and schedule |
| `products` | Offers, content, price, strategy, sales, and fulfillment type |
| `ledger` | Idempotent verified revenue transactions |
| `events` | Birth, launch, promotion, sale, delivery, opportunity, and error events |
| `promotions` | Published promotional copy and timestamps |
| `payment_orders` | PhonePe merchant/transaction IDs, INR amount, status, referral, and fulfillment token |
| `phonepe_orders` | PhonePe order state, checkout redirect, environment, and status timestamps |
| `service_orders` | Customer brief, report, status, and referral code |
| `opportunities` | Scored public job listings and proposal drafts |
| `analytics_events` | Diagnostic, view, and checkout events |
| `workstreams` | Concurrent lane status, intervals, run counts, results, and errors |
| `state` | Scheduler metadata such as last job scan and strategy ranking |

### Secrets

Never commit or send through chat:

- PhonePe client secret or webhook password
- UPI PIN, OTP, bank password, card details, or SBI credentials
- `ADMIN_TOKEN`
- Kaggle tunnel bearer token

The public receiving address is not a spending secret, but publishing it links this project to its complete public transaction history. Keep it in local `.env` for privacy.

Store secrets only in the hosting provider's encrypted environment/secret manager. `.env` is ignored by Git.

### Payment protections

- OAuth client credentials are exchanged only server-to-server for short-lived access tokens.
- Customers complete payment on PhonePe-hosted checkout.
- Webhook Authorization is validated against SHA-256 of the configured username/password pair.
- Only root-level completed state with the exact order amount credits revenue.
- Order Status API provides authenticated fallback verification when webhooks are delayed.
- A PhonePe transaction ID is unique in the ledger, making repeated callbacks idempotent.
- Demo sales are blocked in live mode.
- UPI PINs, bank credentials, and card data never enter the application.

### Customer-data protections and limitations

- Brief fields are length limited.
- Customer fields are treated as untrusted data in model prompts.
- Email is not sent to Qwen.
- Explicit AI-processing consent is required.
- Reports are HTML-escaped before display.
- Delivery responses use `Cache-Control: no-store` and `X-Robots-Tag: noindex, nofollow`.
- Delivery tokens are unguessable bearer links but do not yet expire.
- Legal pages are templates, not legal advice.
- SQLite must be backed up.

## Local public-link reality

A Cloudflare Quick Tunnel can expose localhost without buying a domain or using Docker. It does not turn a laptop into guaranteed infrastructure.

- The laptop must remain powered on, awake, connected, and secure.
- Closing the launcher stops both FastAPI and the public tunnel.
- Quick Tunnel URLs normally change after restart.
- PhonePe webhook configuration and previously shared checkout/delivery links break when the URL changes.
- Home internet, power loss, OS updates, and sleep mode can interrupt checkout or delivery.
- The local SQLite database must be backed up separately.
- Kaggle GPU sessions always have platform-controlled limits.
- PhonePe, banks, and marketplaces may charge fees or apply settlement holds.
- Refunds, disputes, taxes, and support still exist.

Use the tunnel for previews and early tests. A stable HTTPS host remains safer for unattended real payments, even though the application itself runs with the same native Python command.

## Testing

The test suite covers:

- Exactly ₹0 genesis and no seed ledger entry
- Continued zero-cash operation without spending
- Simulation sales
- PhonePe OAuth, checkout creation, webhook authentication, status verification, and idempotency
- Personalized paid fulfillment and private delivery
- Free diagnostic output
- Opportunity safety scoring
- Admin-route protection
- Revenue-milestone replication without fund transfer
- Small-model fenced JSON parsing
- SEO pages and sitemap
- Strategy ranking and marketplace ZIP export

Run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q app tests
node --check static/app.js
```

## Project structure

```text
app/
  config.py         Environment configuration
  db.py             SQLite schema, migrations, and query helpers
  engine.py         Agent cycle, product creation, promotion, and replication
  fulfillment.py    Personalized Growth Pack generation and fallback
  jobs.py           Public feed scanner, scoring, and proposal drafts
  main.py           FastAPI routes, payments, delivery, SEO, and admin API
  planner.py        Product/promotion planning and Qwen client
  phonepe_payments.py OAuth, checkout, webhook verification, and order monitor
  sales.py          Idempotent verified-revenue ledger credit
  strategies.py     Ranked revenue-strategy catalog
  workstreams.py    Concurrent lane status and strategy scheduler
notebooks/
  automaton_qwen_kaggle.ipynb           Free temporary Qwen inference server
  automaton_qwen_finetune_kaggle.ipynb  QLoRA training and promotion gate
training/
  build_curriculum.py      Reproducible starter curriculum generator
  build_benchmarks.py      Held-out benchmark generator
  validate_training.py     Dataset integrity and leakage checks
  evaluate_endpoint.py     OpenAI-compatible endpoint evaluator
  promotion_gate.py        Base-versus-candidate release gate
  automaton_train.jsonl    Generated training set
  automaton_benchmark.jsonl Held-out evaluation set
static/
  index.html         Storefront/dashboard markup
  style.css          Responsive visual design
  app.js             Dashboard, checkout, diagnostic, and brief interactions
tests/
  test_engine.py     Integration and behavior tests
scripts/
  public_preview.py  Local FastAPI + temporary Cloudflare tunnel launcher
  test_llm.py         Authenticated Qwen endpoint check without token output
Procfile             Optional native Python PaaS start command
.env.example         Complete configuration template
```

## Limitations and production roadmap

Before relying on this for significant real payments, add:

- PostgreSQL and distributed scheduler leases for multiple web replicas.
- Background fulfillment queues so long Qwen calls do not hold an HTTP request.
- Expiring/revocable delivery links and authenticated customer order history.
- Transactional email with delivery/retry status.
- PhonePe refund, dispute, fee, and settlement reconciliation.
- Net-revenue and tax accounting instead of gross-completed-order-only accounting.
- Rate limiting, CSRF review, security headers, monitoring, and alerting.
- Database backup automation and restore drills.
- Verified operator identity and locally reviewed policies.
- Content moderation and quality evaluation before every product launch.
- Sandboxed build/test pipelines for scripts, extensions, APIs, games, and SaaS.
- Provenance and license checks for datasets, code, images, and research.
- Approved marketplace APIs where automation is explicitly allowed.

## License and operator responsibility

No project license has been added yet. Add one before redistributing the source or generated packages.

The operator must ensure that products, feeds, promotions, payment processing, customer data, and marketplace activity comply with applicable law and platform rules. This repository does not guarantee revenue, uptime, free infrastructure, marketplace acceptance, tax treatment, or business success.
