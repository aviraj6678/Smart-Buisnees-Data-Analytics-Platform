"""
src/demo_generator.py
---------------------
Synthetic demo-data generator for the Smart Business Data Analytics Platform.

This module generates small batches of realistic but entirely fictional sales
transaction lines and inserts them into the existing SQLite database using the
same validation and insert pipeline used by CSV/Excel uploads.

Key design decisions
--------------------
Transaction ID prefix
    Every generated transaction ID uses the prefix ``DEMO-`` followed by a
    12-character hex fragment from uuid4():
        DEMO-3f8a1c92b047
    The ``DEMO-`` prefix is a well-documented convention that:
    - keeps IDs unique and traceable,
    - requires no new database columns,
    - does not interfere with ``TXN-`` prefixed CSV imports or ``ORD-`` orders,
    - is clearly visible in the database, dashboards, and exports.

Order ID convention
    A single generated batch may contain 1–5 transaction lines.  Lines in the
    same batch share one ``order_id`` of the form ``DEMO-ORD-{hex}``, mirroring
    the multi-product order semantics used throughout the project.

Date policy
    Generated transaction dates always equal ``datetime.date.today()`` so that
    records fall within the default date filter on the Overview and Sales pages.

Idempotency — generation log
    A lightweight ``demo_generation_log`` table is maintained in the same
    SQLite database file (NOT the transactions table).  Every successful batch
    records a ``batch_id`` (UUID) and ``generated_at`` timestamp.  Before each
    automatic generation cycle the module checks whether an eligible batch was
    already created within the current 60-second window.  This prevents
    duplicate batches across multiple browser sessions or Streamlit reruns.

    Schema (separate table, transactions schema is unchanged):
        batch_id     TEXT PRIMARY KEY   — uuid4 hex
        generated_at TEXT               — ISO-8601 datetime string
        lines_inserted INTEGER          — rows written in this batch

Catalogue
    Products, categories, customers, and regions are drawn from a small
    realistic catalogue matching the one used in ``data/generate_sample.py``.
    Prices and costs use fixed catalogue values with a ±5 % variation.
    ``unit_cost`` is always ≤ ``unit_price`` for demo records (no deliberate
    loss makers — the demo is meant to show healthy transactions).

Disabled by default
    The generator is disabled by default.  It must be explicitly enabled via
    the Streamlit UI.  Disabling it never deletes existing records.

Never overwrites existing data
    ``insert_transactions`` uses ``INSERT OR IGNORE``, so a generated record
    whose ``transaction_id`` already exists is silently skipped.
"""

from __future__ import annotations

import datetime
import sqlite3
import uuid
from typing import Dict, List, NamedTuple, Optional, Tuple

import pandas as pd

from src.database import DB_PATH, ImportResult, insert_transactions
from src.data_validation import validate_dataframe

# ── Catalogue ──────────────────────────────────────────────────────────────────
# (name, category, unit_price, unit_cost) — cost < price for all demo records

_PRODUCTS: List[Tuple[str, str, float, float]] = [
    ("Laptop Pro",           "Electronics",      1200.00,  780.00),
    ("Wireless Keyboard",    "Electronics",        89.00,   45.00),
    ("USB-C Hub",            "Electronics",        49.00,   22.00),
    ("Monitor 24in",         "Electronics",       350.00,  210.00),
    ("Webcam HD",            "Electronics",        75.00,   38.00),
    ("Noise Headphones",     "Electronics",       199.00,  110.00),
    ("Smart Speaker",        "Electronics",       129.00,   72.00),
    ("Ergonomic Chair",      "Office Supplies",   320.00,  175.00),
    ("Standing Desk",        "Office Supplies",   580.00,  340.00),
    ("Desk Lamp LED",        "Office Supplies",    45.00,   22.00),
    ("Whiteboard 4ft",       "Office Supplies",    95.00,   52.00),
    ("Printer Ink Set",      "Office Supplies",    38.00,   18.00),
    ("CRM License",          "Software",          250.00,  120.00),
    ("Analytics Suite",      "Software",          450.00,  210.00),
    ("Project Mgmt Tool",    "Software",          180.00,   85.00),
    ("Security Suite",       "Software",          120.00,   55.00),
    ("Cloud Storage 1TB",    "Software",           60.00,   28.00),
    ("Mechanical Keyboard",  "Peripherals",       110.00,   62.00),
    ("Gaming Mouse",         "Peripherals",        65.00,   32.00),
    ("Docking Station",      "Peripherals",       180.00,  105.00),
    ("Laptop Bag",           "Accessories",        65.00,   30.00),
    ("Monitor Arm",          "Accessories",        85.00,   45.00),
    ("Cable Organiser",      "Accessories",        18.00,    8.00),
]

_REGIONS: List[str] = ["North", "South", "East", "West"]

# 20 fictional demo customers (id, name)
_CUSTOMERS: List[Tuple[str, str]] = [
    ("DEMO-C01", "Acme Corp"),
    ("DEMO-C02", "Pinnacle Ltd"),
    ("DEMO-C03", "Vertex Solutions"),
    ("DEMO-C04", "Horizon Retail"),
    ("DEMO-C05", "Apex Trading"),
    ("DEMO-C06", "Summit Supplies"),
    ("DEMO-C07", "Cascade Systems"),
    ("DEMO-C08", "Aurora Ventures"),
    ("DEMO-C09", "Meridian Group"),
    ("DEMO-C10", "Nexus Partners"),
    ("DEMO-C11", "Solaris Tech"),
    ("DEMO-C12", "Cobalt Markets"),
    ("DEMO-C13", "Ember Analytics"),
    ("DEMO-C14", "Granite Industries"),
    ("DEMO-C15", "Prism Consulting"),
    ("DEMO-C16", "Orbit Enterprise"),
    ("DEMO-C17", "Frost Logistics"),
    ("DEMO-C18", "Nova Distribution"),
    ("DEMO-C19", "Titan Retail"),
    ("DEMO-C20", "Atlas Services"),
]

# ── Generation log DDL ─────────────────────────────────────────────────────────

_CREATE_LOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS demo_generation_log (
    batch_id       TEXT     PRIMARY KEY,
    generated_at   TEXT     NOT NULL,
    lines_inserted INTEGER  NOT NULL DEFAULT 0
);
"""

DEMO_REFRESH_INTERVAL_SECONDS: int = 60

# Session-state keys used by the Streamlit page
DEMO_RESULT_KEY = "demo_gen_last_result"
DEMO_LAST_TIME_KEY = "demo_gen_last_time"


# ── DemoGenResult ─────────────────────────────────────────────────────────────


class DemoGenResult(NamedTuple):
    """
    Outcome of a single demo-data generation attempt.

    Attributes
    ----------
    success : bool
    lines_generated : int
        Rows produced before validation.
    inserted : int
        Rows written to the database.
    skipped_duplicate : int
        Rows whose transaction_id already existed (should normally be 0).
    rejected_invalid : int
        Rows removed by the validation layer.
    batch_id : str
        UUID hex identifying this batch.
    generated_at : float
        Unix timestamp of the generation attempt.
    error_message : str
        Empty on success; human-readable description on failure.
    """

    success: bool
    lines_generated: int
    inserted: int
    skipped_duplicate: int
    rejected_invalid: int
    batch_id: str
    generated_at: float
    error_message: str


# ── DB helpers ─────────────────────────────────────────────────────────────────


def init_demo_log() -> None:
    """
    Create the ``demo_generation_log`` table if it does not exist.
    Safe to call on every app start alongside ``init_db()``.
    The transactions schema is untouched.
    """
    import pathlib
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(_CREATE_LOG_TABLE_SQL)
        conn.commit()


def _log_batch(batch_id: str, generated_at: str, lines_inserted: int) -> None:
    """Insert a row into demo_generation_log (runs inside the same connection)."""
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO demo_generation_log "
            "(batch_id, generated_at, lines_inserted) VALUES (?, ?, ?)",
            (batch_id, generated_at, lines_inserted),
        )
        conn.commit()


def get_last_batch_time() -> Optional[datetime.datetime]:
    """
    Return the datetime of the most recent successfully logged batch,
    or None if no batch has ever been generated.
    """
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute(
                "SELECT generated_at FROM demo_generation_log "
                "ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return datetime.datetime.fromisoformat(row[0])
    except Exception:
        return None


def was_batch_generated_recently(within_seconds: int = DEMO_REFRESH_INTERVAL_SECONDS) -> bool:
    """
    Return True if a batch was already logged within ``within_seconds`` seconds.

    This is a DB-backed check that works across multiple Streamlit sessions and
    browser tabs — unlike session_state, which is per-browser-tab only.
    """
    last = get_last_batch_time()
    if last is None:
        return False
    elapsed = (datetime.datetime.now() - last).total_seconds()
    return elapsed < within_seconds


def get_total_demo_lines() -> int:
    """Return the total number of DEMO- prefixed transaction lines in the DB."""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE transaction_id LIKE 'DEMO-%'"
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


# ── Batch generation ───────────────────────────────────────────────────────────

import random  # stdlib, no extra dependency


def _make_transaction_id() -> str:
    """Return a unique DEMO-prefixed transaction ID."""
    return f"DEMO-{uuid.uuid4().hex[:12]}"


def _make_order_id() -> str:
    """Return a unique DEMO-prefixed order ID for a batch."""
    return f"DEMO-ORD-{uuid.uuid4().hex[:8]}"


def generate_batch(
    batch_size: int = 3,
    rng: Optional[random.Random] = None,
) -> pd.DataFrame:
    """
    Generate a single batch of ``batch_size`` transaction lines.

    All lines in the batch share one ``order_id`` (multi-product order semantics).
    ``unit_cost`` is always < ``unit_price`` for every generated record.

    Parameters
    ----------
    batch_size : int
        Number of transaction lines to generate (clamped to 1–10).
    rng : random.Random, optional
        Provide a seeded instance for deterministic tests.  Defaults to the
        module-level unseeded ``random`` functions.

    Returns
    -------
    pd.DataFrame
        Raw DataFrame ready to be passed into ``validate_dataframe()``.
        All values are already the correct Python types (str, int, float).
    """
    if rng is None:
        rng = random.Random()

    batch_size = max(1, min(batch_size, 10))

    order_id = _make_order_id()
    # Pick a customer for the whole order
    cust_id, cust_name = rng.choice(_CUSTOMERS)
    region = rng.choice(_REGIONS)
    date_str = datetime.date.today().isoformat()

    # Pick distinct products for the batch
    chosen_products = rng.sample(_PRODUCTS, k=min(batch_size, len(_PRODUCTS)))

    rows = []
    for name, category, base_price, base_cost in chosen_products:
        # ±5% price variation; cost stays fixed to guarantee cost ≤ price
        price_var = rng.uniform(0.95, 1.05)
        unit_price = round(base_price * price_var, 2)
        unit_cost = round(base_cost, 2)
        # Safety: ensure unit_cost never exceeds unit_price
        if unit_cost > unit_price:
            unit_cost = round(unit_price * 0.80, 2)

        quantity = rng.randint(1, 5)

        rows.append({
            "transaction_id":   _make_transaction_id(),
            "order_id":         order_id,
            "transaction_date": date_str,
            "customer_id":      cust_id,
            "customer_name":    cust_name,
            "product":          name,
            "category":         category,
            "region":           region,
            "quantity":         quantity,
            "unit_price":       unit_price,
            "unit_cost":        unit_cost,
        })

    return pd.DataFrame(rows)


# ── Orchestrator ───────────────────────────────────────────────────────────────

import time as _time  # alias to avoid conflict with datetime


def run_demo_generation(
    batch_size: int = 3,
    force: bool = False,
    rng: Optional[random.Random] = None,
) -> DemoGenResult:
    """
    Generate and insert one demo batch.

    Parameters
    ----------
    batch_size : int
        Lines per batch (1–10).
    force : bool
        When True, skip the DB-backed duplicate-generation check.  Use for
        manual "Generate Now" actions where the user explicitly requests a batch.
    rng : random.Random, optional
        For deterministic testing only.

    Returns
    -------
    DemoGenResult
        All counts plus success/error status.  Never raises.
    """
    generated_at_ts = _time.time()
    generated_at_iso = datetime.datetime.now().isoformat(timespec="seconds")
    batch_id = uuid.uuid4().hex

    # DB-backed idempotency: skip if a batch was already generated this cycle
    if not force and was_batch_generated_recently(DEMO_REFRESH_INTERVAL_SECONDS):
        return DemoGenResult(
            success=False,
            lines_generated=0,
            inserted=0,
            skipped_duplicate=0,
            rejected_invalid=0,
            batch_id=batch_id,
            generated_at=generated_at_ts,
            error_message="A batch was already generated within the refresh interval.",
        )

    try:
        df_raw = generate_batch(batch_size=batch_size, rng=rng)
    except Exception:
        return DemoGenResult(
            success=False,
            lines_generated=0,
            inserted=0,
            skipped_duplicate=0,
            rejected_invalid=0,
            batch_id=batch_id,
            generated_at=generated_at_ts,
            error_message="Failed to generate batch data.",
        )

    lines_generated = len(df_raw)

    try:
        df_clean, report = validate_dataframe(df_raw)
    except Exception:
        return DemoGenResult(
            success=False,
            lines_generated=lines_generated,
            inserted=0,
            skipped_duplicate=0,
            rejected_invalid=lines_generated,
            batch_id=batch_id,
            generated_at=generated_at_ts,
            error_message="Validation raised an unexpected error.",
        )

    rejected = (
        report["duplicate_transaction_ids_removed"]
        + report["rows_dropped_missing_required"]
    )

    if df_clean.empty:
        return DemoGenResult(
            success=False,
            lines_generated=lines_generated,
            inserted=0,
            skipped_duplicate=0,
            rejected_invalid=lines_generated,
            batch_id=batch_id,
            generated_at=generated_at_ts,
            error_message="All generated rows were rejected by validation.",
        )

    try:
        db_result: ImportResult = insert_transactions(df_clean, rejected_invalid=rejected)
    except Exception:
        return DemoGenResult(
            success=False,
            lines_generated=lines_generated,
            inserted=0,
            skipped_duplicate=0,
            rejected_invalid=rejected,
            batch_id=batch_id,
            generated_at=generated_at_ts,
            error_message="Database insert failed; no records were written.",
        )

    # Log the batch so cross-session duplicate checks work
    try:
        _log_batch(batch_id, generated_at_iso, db_result.inserted)
    except Exception:
        pass  # Logging failure does not fail the generation

    return DemoGenResult(
        success=True,
        lines_generated=lines_generated,
        inserted=db_result.inserted,
        skipped_duplicate=db_result.skipped_duplicate,
        rejected_invalid=db_result.rejected_invalid,
        batch_id=batch_id,
        generated_at=generated_at_ts,
        error_message="",
    )


def should_auto_generate(last_gen_time: Optional[float]) -> bool:
    """
    Return True when the auto-generation interval has elapsed since
    the last session-state generation time.

    This is a session-state check (per-tab).  The DB-backed check inside
    ``run_demo_generation`` provides the cross-session guard.

    Parameters
    ----------
    last_gen_time : float or None
        Unix timestamp of the last generation in this session, or None.
    """
    if last_gen_time is None:
        return True
    return (_time.time() - last_gen_time) >= DEMO_REFRESH_INTERVAL_SECONDS
