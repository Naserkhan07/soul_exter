# India Client-Finding Agent 🇮🇳

An autonomous **research** agent that finds Indian businesses which may need
digital/technology services (marketing, SEO, social media, websites,
e-commerce, apps, AI/automation, support), qualifies them with **Qwen 2.5 3B**,
and produces an **Excel lead database** — then **STOPS**.

> **No automatic contacting. Ever.** The output is `output/india_leads.xlsx`,
> not messages. Contact details are only recorded when a business has
> **publicly** listed them; nothing is guessed or generated.

---

## Architecture

```
                        QWEN 2.5 3B (brain/)
                              │  structured JSON only
                       Python Agent Core (agent/)
              ┌───────────────┼────────────────┐
           Discovery      Investigation      Storage
          tools/maps      tools/browser     database/ (SQLite)
          tools/huggingface tools/website_analyzer
          tools/reddit    tools/contacts    export/ (Excel)
          tools/web_search tools/linkedin
                              │
                     geography/ (India → state → city → locality)
```

- **Brain** (`brain/`) — pluggable LLM backends behind one interface:
  - `transformers` → Qwen 2.5 3B Instruct, 4-bit, on Kaggle's free GPU
  - `openai` → any OpenAI-compatible server (Ollama/vLLM/llama.cpp)
  - `heuristic` → deterministic rule engine, **zero GPU** — develop and test
    the entire pipeline on any laptop, then flip the backend on Kaggle.
  - The model **never sees raw contact data** and its output is schema-validated,
    so it can never invent a phone number or email.
- **Agent** (`agent/`) — planner (location×category grid), executor
  (investigate one business), loop, memory, JSON **checkpoints** (survives
  Kaggle session death).
- **Tools** (`tools/`) — every third-party source is optional and replaceable;
  a missing API key disables a tool, never the agent:
  | Tool | Access method | Needs |
  |---|---|---|
  | Google Maps | official **Places API (New)** | `GOOGLE_MAPS_API_KEY` |
  | HF company dataset | `datasets` streaming (`SalaleadsOrg/linkedin-company-profile`) | `pip install datasets` |
  | Reddit | official API via PRAW, read-only | `REDDIT_CLIENT_ID/SECRET` |
  | Web search | Brave / SerpAPI | `BRAVE_SEARCH_KEY` or `SERPAPI_KEY` |
  | LinkedIn | **no scraping** — dataset records + URLs businesses publish on their own sites | — |
  | Browser | `requests` (+optional Playwright), robots.txt respected, polite delays, login/CAPTCHA **handoff to human** | — |
- **Database** (`database/`) — SQLite is the source of truth; dedup via a
  business identity key (domain → phone → LinkedIn slug → name+city).
- **Export** (`export/`) — styled `india_leads.xlsx` with every required column.
- **Geography** (`geography/`) — all 36 states/UTs with major cities, walked
  systematically by the planner (extend with `localities.json`).

## Quick start (₹0, no GPU, no API keys)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python main.py demo               # end-to-end smoke test with a seed site
python main.py stats              # database + checkpoint status
python main.py export             # -> output/india_leads.xlsx
```

Investigate your own list of businesses:

```bash
python main.py seed my_seeds.json     # see seeds.example.json for the format
```

Run the autonomous loop (uses whichever discovery sources are configured):

```bash
export GOOGLE_MAPS_API_KEY=...        # optional
export REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=...   # optional
pip install datasets                  # optional (HF company dataset)

python main.py run --max 200 --states "Maharashtra,Telangana"
```

Stop any time with `Ctrl+C` — the checkpoint saves and the next run resumes.

## Running the real Qwen brain on Kaggle

1. New Kaggle notebook → GPU T4.
2. Upload/clone this repo, then:
   ```
   !pip -q install transformers accelerate bitsandbytes datasets \
                   requests beautifulsoup4 lxml openpyxl
   !python kaggle/run_qwen_batch.py --max 200
   ```
3. Persist `data/` + `output/` as a Kaggle Dataset between sessions —
   checkpoints make every session resume where the last stopped.

Locally with Ollama instead:

```bash
ollama pull qwen2.5:3b-instruct
BRAIN_BACKEND=openai python main.py run --max 50
```

## Lead scoring

Rule-grounded, model-explained (max 100):

| Signal | Weight |
|---|---|
| Marketing problem | 20 |
| Website problem | 15 |
| Weak SEO | 15 |
| Inactive social | 10 |
| Explicit demand (e.g. Reddit) | 20 |
| Business quality | 10 |
| Public contact available | 10 |

Leads below `MIN_LEAD_SCORE_TO_SAVE` (default 40) are skipped.

## Ground rules baked into the code

- ✅ research only — the pipeline **stops** after saving the lead
- ✅ contacts must be public; missing = empty, never guessed
- ✅ robots.txt respected, polite per-host delays
- ✅ no login/CAPTCHA bypassing — human handoff instead
- ✅ no LinkedIn/Maps scraping — permitted APIs & published data only
- ✅ third-party sources are replaceable tools, not dependencies

## Project layout

```
main.py  config.py  requirements.txt
brain/      qwen.py prompts.py schemas.py decision_engine.py
agent/      planner.py executor.py loop.py memory.py checkpoint.py
tools/      maps.py linkedin.py reddit.py huggingface.py web_search.py
            browser.py website_analyzer.py contacts.py
geography/  india_states.json loader.py
database/   models.py database.py deduplication.py
export/     excel.py
kaggle/     run_qwen_batch.py
data/       raw/ processed/ checkpoints/ leads.db
output/     india_leads.xlsx
logs/       agent.log
```
