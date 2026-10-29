"""
tests/test_database.py
----------------------
Focused unit tests for src/database.py.

Coverage
--------
init_db
  - creates analytics.db on disk
  - transactions table has the correct 11 columns in the correct order
  - idx_order_id index is created

insert_transactions
  - returns ImportResult(inserted=N, skipped_duplicate=0, rejected_invalid=0) for fresh rows
  - INSERT OR IGNORE: re-inserting the same rows returns inserted=0, skipped_duplicate=N
  - multi-product orders (shared order_id) are ALL kept — not deduplicated
  - rejected_invalid is passed through unchanged from the caller
  - empty DataFrame returns inserted=0, skipped_duplicate=0
  - transaction_date stored and retrieved as ISO-8601 string / datetime64

get_transactions
  - no filters returns all rows
  - start_date filter excludes earlier rows
  - end_date filter excludes later rows
  - region filter returns only matching rows
  - category filter returns only matching rows
  - combined filters are ANDed correctly
  - returns empty DataFrame when no rows match
  - returned DataFrame has correct dtypes

clear_transactions
  - deletes all rows; table still exists afterward

get_distinct_regions / get_distinct_categories
  - return sorted lists with no duplicates

ImportResult
  - is a NamedTuple with fields inserted, skipped_duplicate, rejected_invalid
  - rejected_invalid is a passthrough: database layer does not compute it

order_id semantics
  - COUNT(DISTINCT order_id) < total rows for multi-product orders (KPI correctness)
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from src.database import (
    DB_PATH,
    ImportResult,
    clear_transactions,
    get_distinct_categories,
    get_distinct_regions,
    get_transactions,
    init_db,
    insert_transactions,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    """Ensure each test starts and ends with an empty transactions table."""
    init_db()
    clear_transactions()
    yield
    clear_transactions()


def _make_df(rows: list) -> pd.DataFrame:
    """Build a minimal valid transactions DataFrame from a list of dicts."""
    defaults = {
        "transaction_id":   "TXN-DEFAULT",
        "order_id":         "ORD-001",
        "transaction_date": pd.Timestamp("2024-01-15"),
        "customer_id":      "C01",
        "customer_name":    "Alice",
        "product":          "Widget",
        "category":         "Widgets",
        "region":           "North",
        "quantity":         2,
        "unit_price":       50.0,
        "unit_cost":        30.0,
    }
    records = []
    for i, row in enumerate(rows):
        r = {**defaults, "transaction_id": f"TXN-{i:03d}", **row}
        records.append(r)
    df = pd.DataFrame(records)
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["quantity"] = df["quantity"].astype(int)
    df["unit_price"] = df["unit_price"].astype(float)
    df["unit_cost"] = df["unit_cost"].astype(float)
    return df


@pytest.fixture()
def three_row_df() -> pd.DataFrame:
    """
    Two rows belonging to ORD-001 (multi-product order) and one to ORD-002.
    This is the canonical fixture for testing multi-product order semantics.
    """
    return _make_df([
        {"transaction_id": "TXN-001", "order_id": "ORD-001",
         "transaction_date": "2024-01-10", "region": "North", "category": "Widgets"},
        {"transaction_id": "TXN-002", "order_id": "ORD-001",
         "transaction_date": "2024-01-10", "region": "North", "category": "Gadgets"},
        {"transaction_id": "TXN-003", "order_id": "ORD-002",
         "transaction_date": "2024-02-20", "region": "South", "category": "Widgets"},
    ])


# ══════════════════════════════════════════════════════════════════════════════
# init_db
# ══════════════════════════════════════════════════════════════════════════════

class TestInitDb:
    def test_creates_db_file(self):
        init_db()
        assert DB_PATH.exists(), f"Expected {DB_PATH} to exist after init_db()"

    def test_transactions_table_has_11_columns(self):
        import sqlite3
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cols = [row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()]
        conn.close()
        expected = [
            "transaction_id", "order_id", "transaction_date",
            "customer_id", "customer_name", "product", "category",
            "region", "quantity", "unit_price", "unit_cost",
        ]
        assert cols == expected, f"Column mismatch: {cols}"
        assert len(cols) == 11

    def test_transaction_id_is_primary_key(self):
        import sqlite3
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        pk_cols = [
            row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()
            if row[5] == 1   # pk column = 1
        ]
        conn.close()
        assert pk_cols == ["transaction_id"]

    def test_order_id_index_exists(self):
        import sqlite3
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        indexes = [row[1] for row in conn.execute("PRAGMA index_list(transactions)").fetchall()]
        conn.close()
        assert "idx_order_id" in indexes

    def test_safe_to_call_twice(self):
        """CREATE TABLE IF NOT EXISTS — calling init_db twice must not raise."""
        init_db()
        init_db()   # should be a no-op


# ══════════════════════════════════════════════════════════════════════════════
# insert_transactions — counts
# ══════════════════════════════════════════════════════════════════════════════

class TestInsertTransactionsCounts:
    def test_fresh_insert_reports_correct_inserted_count(self, three_row_df):
        result = insert_transactions(three_row_df)
        assert result.inserted == 3
        assert result.skipped_duplicate == 0

    def test_reinsert_same_rows_all_skipped(self, three_row_df):
        insert_transactions(three_row_df)
        result2 = insert_transactions(three_row_df)
        assert result2.inserted == 0
        assert result2.skipped_duplicate == 3

    def test_partial_overlap_counts_correctly(self, three_row_df):
        insert_transactions(three_row_df)
        # Add one new row alongside two existing ones
        new_row = _make_df([{
            "transaction_id": "TXN-NEW",
            "order_id": "ORD-003",
        }])
        overlap = pd.concat([three_row_df.iloc[:2], new_row], ignore_index=True)
        result = insert_transactions(overlap)
        assert result.inserted == 1
        assert result.skipped_duplicate == 2

    def test_empty_df_returns_zero_counts(self):
        result = insert_transactions(pd.DataFrame())
        assert result.inserted == 0
        assert result.skipped_duplicate == 0
        assert result.rejected_invalid == 0

    def test_rejected_invalid_is_passthrough(self, three_row_df):
        """
        The database layer does NOT compute rejected_invalid.
        It is supplied by the validation layer (Sub-Task 3) and passed through.
        This test confirms the passthrough contract is honoured.
        """
        result = insert_transactions(three_row_df, rejected_invalid=7)
        assert result.rejected_invalid == 7
        # inserted + skipped + rejected must not double-count:
        # rejected_invalid represents rows that never reached insert_transactions
        assert result.inserted == 3
        assert result.inserted + result.skipped_duplicate == 3   # only 3 rows were attempted


# ══════════════════════════════════════════════════════════════════════════════
# insert_transactions — multi-product order semantics
# ══════════════════════════════════════════════════════════════════════════════

class TestInsertTransactionsOrderSemantics:
    def test_multi_product_order_all_rows_kept(self, three_row_df):
        """
        ORD-001 has two rows (TXN-001, TXN-002).  Both must be stored.
        Deduplication is on transaction_id, NOT order_id.
        """
        insert_transactions(three_row_df)
        df = get_transactions()
        ord001 = df[df["order_id"] == "ORD-001"]
        assert len(ord001) == 2, (
            f"Expected 2 rows for ORD-001, got {len(ord001)}. "
            "Multi-product orders must not be deduplicated."
        )

    def test_total_orders_less_than_total_rows(self, three_row_df):
        """
        KPI correctness: COUNT(DISTINCT order_id) must be < total rows
        when multi-product orders are present.
        """
        insert_transactions(three_row_df)
        df = get_transactions()
        total_rows = len(df)
        total_orders = df["order_id"].nunique()
        assert total_orders < total_rows, (
            f"Total orders ({total_orders}) should be less than "
            f"total rows ({total_rows}) — ORD-001 has 2 line items."
        )

    def test_duplicate_transaction_id_only_first_is_kept(self):
        """A repeated transaction_id is a true duplicate — only the first is stored."""
        df = _make_df([
            {"transaction_id": "TXN-DUP", "order_id": "ORD-A", "region": "North"},
            {"transaction_id": "TXN-DUP", "order_id": "ORD-B", "region": "South"},  # same txn_id
        ])
        result = insert_transactions(df)
        assert result.inserted == 1
        assert result.skipped_duplicate == 1
        stored = get_transactions()
        assert len(stored) == 1
        assert stored.iloc[0]["order_id"] == "ORD-A"   # first occurrence kept


# ══════════════════════════════════════════════════════════════════════════════
# insert_transactions — date handling
# ══════════════════════════════════════════════════════════════════════════════

class TestInsertTransactionsDateHandling:
    def test_datetime64_stored_as_iso_string(self):
        df = _make_df([{"transaction_date": pd.Timestamp("2024-06-15")}])
        insert_transactions(df)
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        raw = conn.execute("SELECT transaction_date FROM transactions").fetchone()[0]
        conn.close()
        assert raw == "2024-06-15"

    def test_retrieved_date_is_datetime64(self):
        df = _make_df([{"transaction_date": "2024-06-15"}])
        insert_transactions(df)
        result = get_transactions()
        assert pd.api.types.is_datetime64_any_dtype(result["transaction_date"])


# ══════════════════════════════════════════════════════════════════════════════
# get_transactions — filters
# ══════════════════════════════════════════════════════════════════════════════

class TestGetTransactions:
    def test_no_filters_returns_all_rows(self, three_row_df):
        insert_transactions(three_row_df)
        df = get_transactions()
        assert len(df) == 3

    def test_start_date_excludes_earlier_rows(self, three_row_df):
        insert_transactions(three_row_df)
        df = get_transactions(start_date="2024-02-01")
        # Only TXN-003 (2024-02-20) should be returned
        assert len(df) == 1
        assert df.iloc[0]["transaction_id"] == "TXN-003"

    def test_end_date_excludes_later_rows(self, three_row_df):
        insert_transactions(three_row_df)
        df = get_transactions(end_date="2024-01-31")
        assert len(df) == 2
        assert set(df["transaction_id"]) == {"TXN-001", "TXN-002"}

    def test_region_filter(self, three_row_df):
        insert_transactions(three_row_df)
        df = get_transactions(region="South")
        assert len(df) == 1
        assert df.iloc[0]["transaction_id"] == "TXN-003"

    def test_category_filter(self, three_row_df):
        insert_transactions(three_row_df)
        df = get_transactions(category="Gadgets")
        assert len(df) == 1
        assert df.iloc[0]["transaction_id"] == "TXN-002"

    def test_combined_filters_are_anded(self, three_row_df):
        insert_transactions(three_row_df)
        df = get_transactions(region="North", category="Widgets")
        assert len(df) == 1
        assert df.iloc[0]["transaction_id"] == "TXN-001"

    def test_no_match_returns_empty_dataframe(self, three_row_df):
        insert_transactions(three_row_df)
        df = get_transactions(region="East")
        assert df.empty

    def test_returned_dtypes(self, three_row_df):
        insert_transactions(three_row_df)
        df = get_transactions()
        assert pd.api.types.is_datetime64_any_dtype(df["transaction_date"])
        assert df["quantity"].dtype == int
        assert pd.api.types.is_float_dtype(df["unit_price"])
        assert pd.api.types.is_float_dtype(df["unit_cost"])

    def test_all_filters_use_parameterized_queries(self, three_row_df):
        """
        SQL injection guard: passing a value that would break raw SQL
        must return an empty result, not an error or unexpected rows.
        """
        insert_transactions(three_row_df)
        df = get_transactions(region="North' OR '1'='1")
        assert df.empty, "SQL injection via region filter should return no rows"


# ══════════════════════════════════════════════════════════════════════════════
# clear_transactions
# ══════════════════════════════════════════════════════════════════════════════

class TestClearTransactions:
    def test_deletes_all_rows(self, three_row_df):
        insert_transactions(three_row_df)
        clear_transactions()
        assert get_transactions().empty

    def test_table_still_exists_after_clear(self):
        clear_transactions()
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        assert "transactions" in tables


# ══════════════════════════════════════════════════════════════════════════════
# get_distinct_regions / get_distinct_categories
# ══════════════════════════════════════════════════════════════════════════════

class TestDistinctHelpers:
    def test_get_distinct_regions_sorted(self, three_row_df):
        insert_transactions(three_row_df)
        regions = get_distinct_regions()
        assert sorted(regions) == regions
        assert set(regions) == {"North", "South"}

    def test_get_distinct_categories_sorted(self, three_row_df):
        insert_transactions(three_row_df)
        cats = get_distinct_categories()
        assert sorted(cats) == cats
        assert set(cats) == {"Gadgets", "Widgets"}

    def test_empty_db_returns_empty_lists(self):
        assert get_distinct_regions() == []
        assert get_distinct_categories() == []

    def test_no_duplicates_in_region_list(self):
        # Insert two rows with the same region
        df = _make_df([
            {"transaction_id": "T1", "region": "East"},
            {"transaction_id": "T2", "region": "East"},
        ])
        insert_transactions(df)
        regions = get_distinct_regions()
        assert regions.count("East") == 1


# ══════════════════════════════════════════════════════════════════════════════
# ImportResult contract
# ══════════════════════════════════════════════════════════════════════════════

class TestImportResult:
    def test_is_named_tuple(self):
        r = ImportResult(inserted=1, skipped_duplicate=2, rejected_invalid=3)
        assert r.inserted == 1
        assert r.skipped_duplicate == 2
        assert r.rejected_invalid == 3

    def test_unpacks_correctly(self):
        inserted, skipped, rejected = ImportResult(5, 3, 1)
        assert inserted == 5
        assert skipped == 3
        assert rejected == 1

    def test_rejected_invalid_is_not_computed_by_db_layer(self, three_row_df):
        """
        The DB layer never inspects the DataFrame to compute rejected_invalid.
        It receives a pre-computed count from the validation layer (Sub-Task 3).
        Passing rejected_invalid=0 (default) must still work correctly.
        """
        result = insert_transactions(three_row_df, rejected_invalid=0)
        assert result.rejected_invalid == 0
        # Confirm nothing was silently discarded at DB level
        assert result.inserted + result.skipped_duplicate == len(three_row_df)
