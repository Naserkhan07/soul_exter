from dataclasses import dataclass
import os
from dotenv import load_dotenv

# Load local secrets before Settings is constructed. Existing process-level
# environment variables win, which lets the public tunnel override only its URL.
load_dotenv(override=False)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    mode: str = os.getenv("AUTOMATON_MODE", "live").lower()
    database_path: str = os.getenv("DATABASE_PATH", "data/automaton.db")
    cycle_seconds: int = max(30, _int("CYCLE_SECONDS", 60))
    max_products_per_agent: int = max(1, _int("MAX_PRODUCTS_PER_AGENT", 8))
    replication_threshold_cents: int = _int("REPLICATION_THRESHOLD_CENTS", 1000000)
    max_agents: int = _int("MAX_AGENTS", 5)
    min_replication_age_hours: int = _int("MIN_REPLICATION_AGE_HOURS", 24)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    currency: str = os.getenv("CURRENCY", "INR").upper()
    phonepe_environment: str = os.getenv("PHONEPE_ENVIRONMENT", "sandbox").lower()
    phonepe_client_id: str = os.getenv("PHONEPE_CLIENT_ID", "")
    phonepe_client_secret: str = os.getenv("PHONEPE_CLIENT_SECRET", "")
    phonepe_client_version: int = _int("PHONEPE_CLIENT_VERSION", 1)
    phonepe_webhook_username: str = os.getenv("PHONEPE_WEBHOOK_USERNAME", "")
    phonepe_webhook_password: str = os.getenv("PHONEPE_WEBHOOK_PASSWORD", "")
    phonepe_expire_seconds: int = max(300, min(3600, _int("PHONEPE_EXPIRE_SECONDS", 1200)))
    phonepe_poll_seconds: int = max(30, _int("PHONEPE_POLL_SECONDS", 60))
    llm_base_url: str = os.getenv("LLM_BASE_URL", "").rstrip("/")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-3B-Instruct")
    publication_webhook_url: str = os.getenv("PUBLICATION_WEBHOOK_URL", "")
    publication_webhook_token: str = os.getenv("PUBLICATION_WEBHOOK_TOKEN", "")
    publication_interval_hours: int = _int("PUBLICATION_INTERVAL_HOURS", 24)
    job_feed_urls: tuple[str, ...] = tuple(
        url.strip() for url in os.getenv("JOB_FEED_URLS", "").split(",") if url.strip()
    )
    job_scan_interval_seconds: int = max(60, _int("JOB_SCAN_INTERVAL_SECONDS", 60))
    opportunity_webhook_url: str = os.getenv("OPPORTUNITY_WEBHOOK_URL", "")
    delivery_webhook_url: str = os.getenv("DELIVERY_WEBHOOK_URL", "")
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    support_email: str = os.getenv("SUPPORT_EMAIL", "support@example.com")
    max_concurrent_agents: int = _int("MAX_CONCURRENT_AGENTS", 3)
    strategy_review_seconds: int = max(300, _int("STRATEGY_REVIEW_SECONDS", 300))

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


settings = Settings()
