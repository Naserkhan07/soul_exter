"""
Central configuration for the India Client-Finding Agent.

Everything that could ever change lives here:
paths, API keys (read from environment — never hard-coded),
model settings, scoring weights, and the service taxonomy.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
OUTPUT_DIR = ROOT_DIR / "output"
LOG_DIR = ROOT_DIR / "logs"
GEOGRAPHY_DIR = ROOT_DIR / "geography"

DB_PATH = DATA_DIR / "leads.db"
EXCEL_PATH = OUTPUT_DIR / "india_leads.xlsx"
CHECKPOINT_PATH = CHECKPOINT_DIR / "agent_checkpoint.json"
LOG_PATH = LOG_DIR / "agent.log"

for _d in (RAW_DIR, PROCESSED_DIR, CHECKPOINT_DIR, OUTPUT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# LLM brain (Qwen)
# ---------------------------------------------------------------------------
# Backend options:
#   "transformers"  -> load Qwen locally (Kaggle GPU / any CUDA machine)
#   "openai"        -> any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio,
#                      llama.cpp server ...) via BRAIN_API_BASE / BRAIN_API_KEY
#   "heuristic"     -> deterministic rule-based fallback, zero GPU needed.
#                      Lets you develop & test the whole pipeline on any laptop.
BRAIN_BACKEND = os.environ.get("BRAIN_BACKEND", "heuristic")

QWEN_MODEL_ID = os.environ.get("QWEN_MODEL_ID", "Qwen/Qwen2.5-3B-Instruct")
QWEN_LOAD_IN_4BIT = os.environ.get("QWEN_LOAD_IN_4BIT", "1") == "1"
QWEN_MAX_NEW_TOKENS = int(os.environ.get("QWEN_MAX_NEW_TOKENS", "512"))
QWEN_TEMPERATURE = float(os.environ.get("QWEN_TEMPERATURE", "0.2"))

BRAIN_API_BASE = os.environ.get("BRAIN_API_BASE", "http://localhost:11434/v1")
BRAIN_API_KEY = os.environ.get("BRAIN_API_KEY", "not-needed")
BRAIN_API_MODEL = os.environ.get("BRAIN_API_MODEL", "qwen2.5:3b-instruct")

# ---------------------------------------------------------------------------
# Third-party API keys (all optional — tools disable themselves gracefully)
# ---------------------------------------------------------------------------
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get(
    "REDDIT_USER_AGENT", "india-client-finder/0.1 (research; no messaging)"
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
BRAVE_SEARCH_KEY = os.environ.get("BRAVE_SEARCH_KEY", "")

HF_COMPANY_DATASET = os.environ.get(
    "HF_COMPANY_DATASET", "SalaleadsOrg/linkedin-company-profile"
)

# ---------------------------------------------------------------------------
# Crawling etiquette
# ---------------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (compatible; IndiaClientFinder/0.1; business research; "
    "contact site owner for removal)"
)
HTTP_TIMEOUT = 20                 # seconds
REQUEST_DELAY_SECONDS = 2.0       # polite delay between fetches to same host
MAX_PAGES_PER_SITE = 6            # home + contact + about + a few more
RESPECT_ROBOTS_TXT = True

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
BATCH_SIZE = 25                   # candidates investigated per checkpointed batch
MIN_LEAD_SCORE_TO_SAVE = 40       # below this the business is skipped
MAX_CANDIDATES_PER_QUERY = 20

# Business categories the agent cycles through per location.
BUSINESS_CATEGORIES = [
    "restaurant", "dental clinic", "gym", "salon", "furniture store",
    "real estate agency", "coaching institute", "hospital", "hotel",
    "boutique", "car dealership", "interior designer", "law firm",
    "chartered accountant", "travel agency", "jewellery store",
    "manufacturer", "wholesaler", "packers and movers", "event management",
]

# ---------------------------------------------------------------------------
# Service taxonomy (controlled vocabulary — Qwen must pick from these)
# ---------------------------------------------------------------------------
SERVICE_TAXONOMY = {
    "marketing": [
        "digital_marketing", "seo", "local_seo", "social_media",
        "content_marketing", "google_business_optimization",
        "paid_advertising", "email_marketing", "branding",
    ],
    "development": [
        "website", "website_redesign", "ecommerce", "web_application",
        "mobile_application", "booking_system", "customer_portal",
    ],
    "technology": [
        "ai_automation", "chatbot", "business_automation", "crm",
        "technical_support", "integration", "data_systems",
    ],
}

ALL_SERVICES = [s for group in SERVICE_TAXONOMY.values() for s in group]
NEED_LEVELS = ["none", "low", "medium", "high"]

# ---------------------------------------------------------------------------
# Lead scoring weights (rule-based part — max 100)
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "marketing_problem": 20,
    "website_problem": 15,
    "weak_seo": 15,
    "inactive_social": 10,
    "explicit_demand": 20,
    "business_quality": 10,
    "contact_availability": 10,
}
