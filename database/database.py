"""
SQLite lead database. SQLite is the source of truth; Excel is an export.
"""

import sqlite3
import logging
from contextlib import contextmanager

import config
from database.models import Lead

log = logging.getLogger("database")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    business_name TEXT,
    business_category TEXT,
    person_name TEXT,
    person_role TEXT,
    state TEXT,
    district TEXT,
    city TEXT,
    locality TEXT,
    full_location TEXT,
    phone TEXT,
    whatsapp TEXT,
    email TEXT,
    website TEXT,
    linkedin TEXT,
    instagram TEXT,
    facebook TEXT,
    youtube TEXT,
    twitter TEXT,
    other_contact_url TEXT,
    source_urls TEXT,
    digital_marketing_need TEXT,
    seo_need TEXT,
    local_seo_need TEXT,
    social_media_need TEXT,
    website_need TEXT,
    ecommerce_need TEXT,
    mobile_app_need TEXT,
    web_app_need TEXT,
    ai_automation_need TEXT,
    technical_support_need TEXT,
    detected_problems TEXT,
    recommended_services TEXT,
    lead_score INTEGER,
    evidence_reason TEXT,
    discovery_source TEXT,
    date_found TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(lead_score);
CREATE INDEX IF NOT EXISTS idx_leads_city ON leads(city);

CREATE TABLE IF NOT EXISTS seen_candidates (
    identity_key TEXT PRIMARY KEY,
    first_seen TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class LeadDatabase:
    def __init__(self, db_path=None):
        self.db_path = str(db_path or config.DB_PATH)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- leads --------------------------------------------------------------
    def upsert_lead(self, lead: Lead) -> None:
        row = lead.to_row()
        cols = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        updates = ", ".join(f"{c}=excluded.{c}" for c in row if c != "lead_id")
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO leads ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT(lead_id) DO UPDATE SET {updates}",
                list(row.values()),
            )
        log.info("Saved lead %s (%s, score %s)",
                 lead.lead_id, lead.business_name, lead.lead_score)

    def get_lead(self, lead_id: str):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM leads WHERE lead_id=?", (lead_id,)
            ).fetchone()
        return Lead.from_row(dict(row)) if row else None

    def all_leads(self, min_score: int = 0):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM leads WHERE lead_score >= ? "
                "ORDER BY lead_score DESC",
                (min_score,),
            ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]

    # -- dedup bookkeeping ----------------------------------------------------
    def has_seen(self, identity_key: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_candidates WHERE identity_key=?",
                (identity_key,),
            ).fetchone()
        return row is not None

    def mark_seen(self, identity_key: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_candidates (identity_key) VALUES (?)",
                (identity_key,),
            )

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            seen = conn.execute(
                "SELECT COUNT(*) FROM seen_candidates"
            ).fetchone()[0]
            avg = conn.execute(
                "SELECT AVG(lead_score) FROM leads"
            ).fetchone()[0]
            by_city = conn.execute(
                "SELECT city, COUNT(*) c FROM leads GROUP BY city "
                "ORDER BY c DESC LIMIT 10"
            ).fetchall()
        return {
            "total_leads": total,
            "candidates_seen": seen,
            "avg_score": round(avg or 0, 1),
            "top_cities": {r["city"]: r["c"] for r in by_city},
        }
