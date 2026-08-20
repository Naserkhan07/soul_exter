import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from .config import settings


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(settings.database_path) or ".", exist_ok=True)
    db = sqlite3.connect(settings.database_path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def transaction():
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    with transaction() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          parent_id INTEGER REFERENCES agents(id),
          status TEXT NOT NULL DEFAULT 'alive',
          balance_cents INTEGER NOT NULL DEFAULT 0,
          lifetime_revenue_cents INTEGER NOT NULL DEFAULT 0,
          lifetime_cost_cents INTEGER NOT NULL DEFAULT 0,
          bootstrap_cycles_remaining INTEGER NOT NULL DEFAULT 0,
          generation INTEGER NOT NULL DEFAULT 0,
          mission TEXT NOT NULL,
          wallet_address TEXT,
          born_at TEXT NOT NULL,
          last_cycle_at TEXT,
          next_cycle_at TEXT
        );
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id INTEGER NOT NULL REFERENCES agents(id),
          slug TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          tagline TEXT NOT NULL,
          description TEXT NOT NULL,
          content TEXT NOT NULL,
          price_cents INTEGER NOT NULL,
          sales_count INTEGER NOT NULL DEFAULT 0,
          revenue_cents INTEGER NOT NULL DEFAULT 0,
          active INTEGER NOT NULL DEFAULT 1,
          fulfillment_type TEXT NOT NULL DEFAULT 'instant',
          strategy_slug TEXT NOT NULL DEFAULT 'digital-template',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id INTEGER NOT NULL REFERENCES agents(id),
          amount_cents INTEGER NOT NULL,
          kind TEXT NOT NULL,
          description TEXT NOT NULL,
          external_id TEXT UNIQUE,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id INTEGER REFERENCES agents(id),
          type TEXT NOT NULL,
          message TEXT NOT NULL,
          metadata TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS promotions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id INTEGER NOT NULL REFERENCES agents(id),
          product_id INTEGER NOT NULL REFERENCES products(id),
          channel TEXT NOT NULL,
          copy TEXT NOT NULL,
          external_id TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payment_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          provider TEXT NOT NULL,
          provider_order_id TEXT NOT NULL UNIQUE,
          provider_payment_id TEXT UNIQUE,
          product_id INTEGER NOT NULL REFERENCES products(id),
          amount_cents INTEGER NOT NULL,
          currency TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'created',
          fulfillment_token TEXT UNIQUE,
          referred_by TEXT,
          created_at TEXT NOT NULL,
          paid_at TEXT
        );
        CREATE TABLE IF NOT EXISTS phonepe_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          payment_order_id INTEGER NOT NULL UNIQUE REFERENCES payment_orders(id),
          merchant_order_id TEXT NOT NULL UNIQUE,
          phonepe_order_id TEXT,
          transaction_id TEXT UNIQUE,
          redirect_url TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'CREATED',
          environment TEXT NOT NULL,
          expire_at INTEGER,
          last_checked_at TEXT,
          completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS service_orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          payment_order_id INTEGER NOT NULL UNIQUE REFERENCES payment_orders(id),
          email TEXT NOT NULL,
          business_name TEXT NOT NULL,
          industry TEXT NOT NULL,
          city TEXT NOT NULL,
          website TEXT,
          goal TEXT NOT NULL,
          language TEXT NOT NULL DEFAULT 'English',
          status TEXT NOT NULL DEFAULT 'received',
          report TEXT,
          referral_code TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS opportunities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          external_key TEXT NOT NULL UNIQUE,
          source TEXT NOT NULL,
          title TEXT NOT NULL,
          url TEXT NOT NULL,
          description TEXT NOT NULL,
          score INTEGER NOT NULL,
          rationale TEXT NOT NULL,
          proposal TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'new',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analytics_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          type TEXT NOT NULL,
          path TEXT,
          metadata TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workstreams (
          name TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'waiting',
          interval_seconds INTEGER NOT NULL,
          runs INTEGER NOT NULL DEFAULT 0,
          last_started_at TEXT,
          last_completed_at TEXT,
          next_run_at TEXT,
          last_result TEXT NOT NULL DEFAULT '{}',
          last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS state (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """)
        # Forward-only migration for databases created before zero-cash bootstrap existed.
        columns = {column["name"] for column in db.execute("PRAGMA table_info(agents)").fetchall()}
        if "bootstrap_cycles_remaining" not in columns:
            db.execute("ALTER TABLE agents ADD COLUMN bootstrap_cycles_remaining INTEGER NOT NULL DEFAULT 0")
        product_columns = {column["name"] for column in db.execute("PRAGMA table_info(products)").fetchall()}
        if "fulfillment_type" not in product_columns:
            db.execute("ALTER TABLE products ADD COLUMN fulfillment_type TEXT NOT NULL DEFAULT 'instant'")
        if "strategy_slug" not in product_columns:
            db.execute("ALTER TABLE products ADD COLUMN strategy_slug TEXT NOT NULL DEFAULT 'digital-template'")
        db.execute("UPDATE products SET strategy_slug='local-growth-pack' WHERE slug LIKE 'local-business-growth-pack%'")
        db.execute("UPDATE products SET strategy_slug='developer-reference' WHERE slug LIKE 'client-discovery-question-bank%'")
        payment_columns = {column["name"] for column in db.execute("PRAGMA table_info(payment_orders)").fetchall()}
        if "fulfillment_token" not in payment_columns:
            db.execute("ALTER TABLE payment_orders ADD COLUMN fulfillment_token TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS payment_orders_fulfillment_token ON payment_orders(fulfillment_token)")
        if "referred_by" not in payment_columns:
            db.execute("ALTER TABLE payment_orders ADD COLUMN referred_by TEXT")

        # This version never auto-kills agents or withdraws their offers. Existing
        # installations are revived when upgraded to the sponsored-compute model.
        db.execute("UPDATE agents SET status='alive',bootstrap_cycles_remaining=0")
        db.execute("UPDATE products SET active=1")
        # When the operator lowers the cycle interval, do not leave existing agents
        # stuck behind an older day-long schedule. Never postpone an earlier run.
        run_now = datetime.now(timezone.utc).isoformat()
        stale_cutoff = (datetime.now(timezone.utc) + timedelta(seconds=settings.cycle_seconds)).isoformat()
        db.execute("""UPDATE agents SET next_cycle_at=? WHERE status='alive'
                      AND (next_cycle_at IS NULL OR next_cycle_at>?)""", (run_now, stale_cutoff))

        count = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        if count == 0:
            stamp = now()
            wallet = None
            cur = db.execute(
                """INSERT INTO agents(name,balance_cents,mission,wallet_address,born_at,next_cycle_at)
                   VALUES(?,0,?,?,?,?)""",
                ("AUTOMATON-001",
                 "Earn honest revenue without ever spending treasury funds.", wallet, stamp, stamp),
            )
            agent_id = cur.lastrowid
            event(db, agent_id, "birth",
                  "AUTOMATON-001 came online with ₹0.00 on sponsored compute. No money was credited and treasury spending is disabled.")


def event(db, agent_id: int | None, type_: str, message: str, metadata: dict | None = None) -> None:
    db.execute(
        "INSERT INTO events(agent_id,type,message,metadata,created_at) VALUES(?,?,?,?,?)",
        (agent_id, type_, message, json.dumps(metadata or {}), now()),
    )


def rows(query: str, params=()) -> list[dict]:
    db = connect()
    try:
        return [dict(r) for r in db.execute(query, params).fetchall()]
    finally:
        db.close()


def row(query: str, params=()) -> dict | None:
    db = connect()
    try:
        value = db.execute(query, params).fetchone()
        return dict(value) if value else None
    finally:
        db.close()
