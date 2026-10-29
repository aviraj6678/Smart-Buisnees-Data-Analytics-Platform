"""
src/database.py
---------------
SQLite persistence layer for the Smart Business Data Analytics Platform.

Responsibilities
----------------
- Create and migrate the `transactions` table (init_db).
- Bulk-insert validated DataFrames and report inserted / skipped / rejected
  counts via ImportResult (insert_transactions).
- Return filtered DataFrames with parameterized queries (get_transactions).
- Provide a test-teardown helper (clear_transactions).

Schema (11 columns)
-------------------
transaction_id   TEXT PRIMARY KEY   — unique line-item identifier
order_id         TEXT               — one order may have many rows (indexed)
transaction_date TEXT               — stored as ISO-8601 string (YYYY-MM-DD)
customer_id      TEXT
customer_name    TEXT
product          TEXT
category         TEXT
region           TEXT
quantity         INTEGER
unit_price       REAL
unit_cost        REAL

All SQL uses parameterized placeholders (?).  No string interpolation in queries.
"""

from __future__ import annotations

import pathlib
import sqlite3
from typing import List, NamedTuple, Optional

import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────

# Resolve the project root as the parent of this file's parent (src/ → project root)
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DB_DIR = _PROJECT_ROOT / "database"
_DB_PATH = _DB_DIR / "analytics.db"

# ── Public constant — lets callers discover the DB path if needed ──────────────
DB_PATH: pathlib.Path = _DB_PATH

# ── ImportResult ──────────────────────────────────────────────────────────────


class ImportResult(NamedTuple):
    """
    Counts returned by insert_transactions().

    Attributes
    ----------
    inserted : int
        Rows successfully written to the database.
    skipped_duplicate : int
        Rows whose transaction_id already existed in the database (INSERT OR IGNORE
        left the existing row untouched).
    rejected_invalid : int
        Rows removed by the validation layer before reaching the database.
        Callers pass this value in; insert_transactions does not compute it.
    """

    inserted: int
    skipped_duplicate: int
    rejected_invalid: int


# ── DDL ───────────────────────────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id   TEXT    PRIMARY KEY,
    order_id         TEXT    NOT NULL,
    transaction_date TEXT    NOT NULL,
    customer_id      TEXT    NOT NULL,
    customer_name    TEXT    NOT NULL,
    product          TEXT    NOT NULL,
    category         TEXT    NOT NULL,
    region           TEXT    NOT NULL,
    quantity         INTEGER NOT NULL,
    unit_price       REAL    NOT NULL,
    unit_cost        REAL    NOT NULL
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_order_id ON transactions (order_id);
"""

# ── Connection helper ──────────────────────────────────────────────────────────


def _connect() -> sqlite3.Connection:
    """Return a connection to the analytics database."""
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ── Public API ────────────────────────────────────────────────────────────────


def init_db() -> None:
    """
    Create the database file, the transactions table, and supporting indexes
    if they do not already exist.  Safe to call on every application start.
    """
    with _connect() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        conn.commit()


def insert_transactions(
    df: pd.DataFrame,
    rejected_invalid: int = 0,
) -> ImportResult:
    """
    Bulk-insert a validated DataFrame into the transactions table.

    Uses INSERT OR IGNORE so that rows whose transaction_id already exists are
    silently skipped rather than raising an error.  The number of actually
    inserted rows is determined by comparing the total row-count before and
    after the batch.

    Parameters
    ----------
    df : pd.DataFrame
        Validated DataFrame conforming to the transactions schema.
        Must contain the column ``transaction_id``.
    rejected_invalid : int
        Count of rows that were removed by the validation layer before this
        function was called.  Passed through into the returned ImportResult
        so the caller can surface a complete picture to the user.

    Returns
    -------
    ImportResult
        inserted          – rows written to the DB this call
        skipped_duplicate – rows whose transaction_id already existed
        rejected_invalid  – passed-through from the argument
    """
    if df.empty:
        return ImportResult(inserted=0, skipped_duplicate=0, rejected_invalid=rejected_invalid)

    columns: List[str] = [
        "transaction_id",
        "order_id",
        "transaction_date",
        "customer_id",
        "customer_name",
        "product",
        "category",
        "region",
        "quantity",
        "unit_price",
        "unit_cost",
    ]

    # Ensure transaction_date is stored as an ISO-8601 string
    df = df.copy()
    if pd.api.types.is_datetime64_any_dtype(df["transaction_date"]):
        df["transaction_date"] = df["transaction_date"].dt.strftime("%Y-%m-%d")
    else:
        df["transaction_date"] = pd.to_datetime(df["transaction_date"]).dt.strftime("%Y-%m-%d")

    rows = [tuple(row) for row in df[columns].itertuples(index=False, name=None)]

    placeholders = ", ".join(["?"] * len(columns))
    insert_sql = f"INSERT OR IGNORE INTO transactions ({', '.join(columns)}) VALUES ({placeholders})"  # noqa: S608

    with _connect() as conn:
        # Row count before insert
        before: int = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.executemany(insert_sql, rows)
        conn.commit()
        after: int = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

    inserted = after - before
    skipped_duplicate = len(rows) - inserted
    return ImportResult(
        inserted=inserted,
        skipped_duplicate=skipped_duplicate,
        rejected_invalid=rejected_invalid,
    )


def get_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: Optional[str] = None,
    category: Optional[str] = None,
) -> pd.DataFrame:
    """
    Return a filtered DataFrame from the transactions table.

    All filter parameters are optional.  When omitted, that dimension is not
    filtered.  Dates must be ISO-8601 strings (YYYY-MM-DD).

    Returns an empty DataFrame with the correct columns when no rows match.
    """
    query = "SELECT * FROM transactions WHERE 1=1"
    params: List[str] = []

    if start_date:
        query += " AND transaction_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND transaction_date <= ?"
        params.append(end_date)
    if region:
        query += " AND region = ?"
        params.append(region)
    if category:
        query += " AND category = ?"
        params.append(category)

    with _connect() as conn:
        df = pd.read_sql_query(query, conn, params=params)

    if not df.empty:
        df["transaction_date"] = pd.to_datetime(df["transaction_date"])
        df["quantity"] = df["quantity"].astype(int)
        df["unit_price"] = df["unit_price"].astype(float)
        df["unit_cost"] = df["unit_cost"].astype(float)

    return df


def clear_transactions() -> None:
    """
    Delete all rows from the transactions table.
    Intended for use in test teardown only — destructive operation.
    """
    with _connect() as conn:
        conn.execute("DELETE FROM transactions")
        conn.commit()


def get_distinct_regions() -> List[str]:
    """Return a sorted list of all distinct region values in the database."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT region FROM transactions ORDER BY region"
        ).fetchall()
    return [row[0] for row in rows]


def get_distinct_categories() -> List[str]:
    """Return a sorted list of all distinct category values in the database."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM transactions ORDER BY category"
        ).fetchall()
    return [row[0] for row in rows]
