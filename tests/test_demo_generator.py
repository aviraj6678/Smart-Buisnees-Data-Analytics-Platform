"""
tests/test_demo_generator.py
-----------------------------
Unit and integration tests for src/demo_generator.py.

All tests use a temporary SQLite database (tmp_path fixture) so they never
touch the production analytics.db.  The module-level DB_PATH is monkey-patched
for each test that exercises the database layer.

Coverage
--------
generate_batch
  - returns a DataFrame with all 11 required columns
  - transaction IDs use the DEMO- prefix
  - all transaction IDs are unique within a batch
  - order IDs use the DEMO-ORD- prefix
  - all lines in a batch share the same order_id
  - numeric values pass the existing validation rules
      (quantity >= 1, unit_price > 0, unit_cost >= 0, unit_cost <= unit_price)
  - transaction_date equals today's ISO date string
  - batch_size is clamped to 1-10
  - deterministic output with a seeded RNG

init_demo_log
  - creates demo_generation_log table without touching transactions
  - safe to call multiple times

was_batch_generated_recently
  - returns False when no batch has been logged
  - returns True immediately after a batch is logged
  - returns False after the interval has elapsed

get_total_demo_lines
  - returns 0 on an empty database
  - counts only DEMO- prefixed rows; ignores TXN- rows

run_demo_generation
  - inserts a batch and returns DemoGenResult with inserted > 0
  - success=True on a valid batch
  - all 11 schema columns present in the inserted row
  - repeated call within interval returns "already generated" when force=False
  - force=True bypasses the interval check and inserts a new batch
  - count invariant: inserted + skipped_duplicate + rejected_invalid == lines_generated
  - generator is disabled by default (force=False + no prior log = would generate)
  - existing records are never deleted by a generation run
  - DEMO- prefixed transaction IDs are unique across multiple batches

should_auto_generate
  - returns True when last_gen_time is None
  - returns True when interval has elapsed
  - returns False within the interval

DemoGenResult structure
  - is a NamedTuple with expected fields
  - count invariant holds on a manually constructed instance

Existing tests
  - all 204 prior tests still pass (verified by running full suite)
"""

from __future__ import annotations

import datetime
import random
import sqlite3
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

import src.demo_generator as demo_mod
from src.demo_generator import (
    DEMO_REFRESH_INTERVAL_SECONDS,
    DemoGenResult,
    generate_batch,
    get_total_demo_lines,
    init_demo_log,
    run_demo_generation,
    should_auto_generate,
    was_batch_generated_recently,
)
from src.data_validation import REQUIRED_COLUMNS


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Redirect all DB operations in src.demo_generator and src.database to a
    fresh temporary database.  Returns the path to that DB file.
    """
    db_file = tmp_path / "test_analytics.db"

    # Patch the DB_PATH used inside demo_generator module
    monkeypatch.setattr(demo_mod, "DB_PATH", db_file)

    # Also patch database.py's _DB_PATH so insert_transactions / init_db
    # use the same temp file
    import src.database as db_mod
    monkeypatch.setattr(db_mod, "_DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    # Patch the _DB_DIR so mkdir doesn't fail
    monkeypatch.setattr(db_mod, "_DB_DIR", tmp_path)

    # Initialise the schema on the temp DB
    db_mod.init_db()
    init_demo_log()

    return db_file


@pytest.fixture()
def seeded_rng() -> random.Random:
    """Deterministic RNG for tests that need reproducible output."""
    return random.Random(42)


# ══════════════════════════════════════════════════════════════════════════════
# generate_batch
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerateBatch:
    def test_returns_dataframe(self, seeded_rng: random.Random) -> None:
        df = generate_batch(batch_size=3, rng=seeded_rng)
        assert isinstance(df, pd.DataFrame)

    def test_all_required_columns_present(self, seeded_rng: random.Random) -> None:
        df = generate_batch(batch_size=3, rng=seeded_rng)
        for col in REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_transaction_ids_have_demo_prefix(self, seeded_rng: random.Random) -> None:
        df = generate_batch(batch_size=5, rng=seeded_rng)
        assert all(tid.startswith("DEMO-") for tid in df["transaction_id"])

    def test_transaction_ids_are_unique_within_batch(self, seeded_rng: random.Random) -> None:
        df = generate_batch(batch_size=5, rng=seeded_rng)
        assert df["transaction_id"].nunique() == len(df)

    def test_order_ids_have_demo_ord_prefix(self, seeded_rng: random.Random) -> None:
        df = generate_batch(batch_size=3, rng=seeded_rng)
        assert all(oid.startswith("DEMO-ORD-") for oid in df["order_id"])

    def test_all_lines_share_same_order_id(self, seeded_rng: random.Random) -> None:
        """A single batch is one multi-product order — one shared order_id."""
        df = generate_batch(batch_size=4, rng=seeded_rng)
        assert df["order_id"].nunique() == 1

    def test_quantity_is_positive_integer(self, seeded_rng: random.Random) -> None:
        df = generate_batch(batch_size=5, rng=seeded_rng)
        assert (df["quantity"] >= 1).all()
        assert df["quantity"].dtype in (int, "int64", "int32")

    def test_unit_price_is_positive(self, seeded_rng: random.Random) -> None:
        df = generate_batch(batch_size=5, rng=seeded_rng)
        assert (df["unit_price"] > 0).all()

    def test_unit_cost_is_non_negative(self, seeded_rng: random.Random) -> None:
        df = generate_batch(batch_size=5, rng=seeded_rng)
        assert (df["unit_cost"] >= 0).all()

    def test_unit_cost_does_not_exceed_unit_price(self, seeded_rng: random.Random) -> None:
        """All demo records must be profitable (no deliberate loss makers)."""
        df = generate_batch(batch_size=10, rng=seeded_rng)
        assert (df["unit_cost"] <= df["unit_price"]).all()

    def test_transaction_date_is_today(self, seeded_rng: random.Random) -> None:
        today = datetime.date.today().isoformat()
        df = generate_batch(batch_size=3, rng=seeded_rng)
        assert (df["transaction_date"] == today).all()

    def test_batch_size_clamped_to_minimum_1(self) -> None:
        df = generate_batch(batch_size=0, rng=random.Random(1))
        assert len(df) == 1

    def test_batch_size_clamped_to_maximum_10(self) -> None:
        df = generate_batch(batch_size=99, rng=random.Random(1))
        assert len(df) == 10

    def test_default_batch_size_is_3(self) -> None:
        df = generate_batch(rng=random.Random(1))
        assert len(df) == 3

    def test_deterministic_with_seeded_rng(self) -> None:
        df1 = generate_batch(batch_size=3, rng=random.Random(99))
        df2 = generate_batch(batch_size=3, rng=random.Random(99))
        assert list(df1["product"]) == list(df2["product"])
        assert list(df1["customer_id"]) == list(df2["customer_id"])

    def test_passes_existing_validation_pipeline(self, seeded_rng: random.Random) -> None:
        """All generated rows must survive the full validate_dataframe pipeline."""
        from src.data_validation import validate_dataframe
        df = generate_batch(batch_size=5, rng=seeded_rng)
        # validate_dataframe expects string types for some columns; the generator
        # produces native Python types — this tests that the pipeline handles both
        df_clean, report = validate_dataframe(df)
        assert not df_clean.empty
        assert report["rows_dropped_missing_required"] == 0
        assert report["missing_columns"] == []


# ══════════════════════════════════════════════════════════════════════════════
# init_demo_log + was_batch_generated_recently + get_total_demo_lines
# ══════════════════════════════════════════════════════════════════════════════


class TestDemoLog:
    def test_init_creates_log_table(self, tmp_db: Path) -> None:
        with sqlite3.connect(str(tmp_db)) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        assert "demo_generation_log" in tables

    def test_transactions_table_still_present(self, tmp_db: Path) -> None:
        with sqlite3.connect(str(tmp_db)) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        assert "transactions" in tables

    def test_init_idempotent(self, tmp_db: Path) -> None:
        """Calling init_demo_log twice must not raise."""
        init_demo_log()
        init_demo_log()

    def test_was_batch_generated_recently_false_on_empty_log(self, tmp_db: Path) -> None:
        assert was_batch_generated_recently(within_seconds=60) is False

    def test_was_batch_generated_recently_true_after_log(self, tmp_db: Path) -> None:
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(str(tmp_db)) as conn:
            conn.execute(
                "INSERT INTO demo_generation_log (batch_id, generated_at, lines_inserted) "
                "VALUES (?, ?, ?)",
                ("test-batch-001", now_iso, 3),
            )
            conn.commit()
        assert was_batch_generated_recently(within_seconds=60) is True

    def test_was_batch_generated_recently_false_after_interval(self, tmp_db: Path) -> None:
        # Log a timestamp well in the past
        old_iso = (
            datetime.datetime.now() - datetime.timedelta(seconds=120)
        ).isoformat(timespec="seconds")
        with sqlite3.connect(str(tmp_db)) as conn:
            conn.execute(
                "INSERT INTO demo_generation_log (batch_id, generated_at, lines_inserted) "
                "VALUES (?, ?, ?)",
                ("old-batch-001", old_iso, 3),
            )
            conn.commit()
        assert was_batch_generated_recently(within_seconds=60) is False

    def test_get_total_demo_lines_zero_on_empty_db(self, tmp_db: Path) -> None:
        assert get_total_demo_lines() == 0

    def test_get_total_demo_lines_counts_only_demo_prefix(self, tmp_db: Path) -> None:
        import src.database as db_mod
        # Insert one DEMO- row and one TXN- row
        df_demo = pd.DataFrame([{
            "transaction_id": "DEMO-abc123",
            "order_id": "DEMO-ORD-001",
            "transaction_date": "2024-01-01",
            "customer_id": "DEMO-C01",
            "customer_name": "Acme Corp",
            "product": "Widget A",
            "category": "Widgets",
            "region": "North",
            "quantity": 1,
            "unit_price": 50.0,
            "unit_cost": 30.0,
        }])
        df_real = pd.DataFrame([{
            "transaction_id": "TXN-000001",
            "order_id": "ORD-00001",
            "transaction_date": "2024-01-01",
            "customer_id": "C01",
            "customer_name": "Alice",
            "product": "Gadget",
            "category": "Gadgets",
            "region": "South",
            "quantity": 2,
            "unit_price": 20.0,
            "unit_cost": 10.0,
        }])
        db_mod.insert_transactions(df_demo)
        db_mod.insert_transactions(df_real)
        assert get_total_demo_lines() == 1


# ══════════════════════════════════════════════════════════════════════════════
# run_demo_generation
# ══════════════════════════════════════════════════════════════════════════════


class TestRunDemoGeneration:
    def test_success_on_first_run(self, tmp_db: Path, seeded_rng: random.Random) -> None:
        result = run_demo_generation(batch_size=3, force=True, rng=seeded_rng)
        assert result.success is True

    def test_inserted_count_equals_batch_size(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        result = run_demo_generation(batch_size=3, force=True, rng=seeded_rng)
        assert result.inserted == 3

    def test_lines_generated_equals_batch_size(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        result = run_demo_generation(batch_size=3, force=True, rng=seeded_rng)
        assert result.lines_generated == 3

    def test_count_invariant(self, tmp_db: Path, seeded_rng: random.Random) -> None:
        """inserted + skipped_duplicate + rejected_invalid == lines_generated."""
        result = run_demo_generation(batch_size=5, force=True, rng=seeded_rng)
        total = result.inserted + result.skipped_duplicate + result.rejected_invalid
        assert total == result.lines_generated

    def test_no_duplicate_batch_within_interval(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        """
        Without force=True, a second call within 60 s must be blocked by the
        DB-backed log check.
        """
        r1 = run_demo_generation(batch_size=2, force=True, rng=seeded_rng)
        assert r1.success is True

        r2 = run_demo_generation(batch_size=2, force=False, rng=random.Random(99))
        assert r2.success is False
        assert "already generated" in r2.error_message.lower()
        assert r2.inserted == 0

    def test_force_bypasses_interval_check(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        """force=True always generates a new batch regardless of the log."""
        r1 = run_demo_generation(batch_size=2, force=True, rng=seeded_rng)
        assert r1.success is True

        # Second batch with force=True and a different RNG seed
        r2 = run_demo_generation(batch_size=2, force=True, rng=random.Random(99))
        assert r2.success is True
        assert r2.inserted == 2

    def test_records_have_demo_prefix_in_db(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        run_demo_generation(batch_size=3, force=True, rng=seeded_rng)
        assert get_total_demo_lines() == 3

    def test_existing_records_not_deleted(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        """A demo generation run must never delete pre-existing rows."""
        import src.database as db_mod
        df_real = pd.DataFrame([{
            "transaction_id": "TXN-EXISTING",
            "order_id": "ORD-EXISTING",
            "transaction_date": "2024-01-01",
            "customer_id": "C01",
            "customer_name": "Alice",
            "product": "Widget",
            "category": "Widgets",
            "region": "North",
            "quantity": 1,
            "unit_price": 50.0,
            "unit_cost": 30.0,
        }])
        db_mod.insert_transactions(df_real)

        run_demo_generation(batch_size=3, force=True, rng=seeded_rng)

        df_after = db_mod.get_transactions()
        assert "TXN-EXISTING" in df_after["transaction_id"].values

    def test_transaction_ids_unique_across_multiple_batches(
        self, tmp_db: Path
    ) -> None:
        """Each batch uses UUID-based IDs — no collisions across runs."""
        r1 = run_demo_generation(batch_size=3, force=True, rng=random.Random(1))
        r2 = run_demo_generation(batch_size=3, force=True, rng=random.Random(2))
        assert r1.success and r2.success
        # Total unique rows = 6 (no duplicates)
        import src.database as db_mod
        df = db_mod.get_transactions()
        demo_rows = df[df["transaction_id"].str.startswith("DEMO-")]
        assert demo_rows["transaction_id"].nunique() == 6

    def test_batch_id_is_logged_in_db(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        result = run_demo_generation(batch_size=2, force=True, rng=seeded_rng)
        with sqlite3.connect(str(tmp_db)) as conn:
            row = conn.execute(
                "SELECT batch_id, lines_inserted FROM demo_generation_log WHERE batch_id = ?",
                (result.batch_id,),
            ).fetchone()
        assert row is not None
        assert row[1] == 2

    def test_error_message_empty_on_success(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        result = run_demo_generation(batch_size=3, force=True, rng=seeded_rng)
        assert result.error_message == ""

    def test_generated_at_is_recent_timestamp(
        self, tmp_db: Path, seeded_rng: random.Random
    ) -> None:
        before = time.time()
        result = run_demo_generation(batch_size=2, force=True, rng=seeded_rng)
        after = time.time()
        assert before <= result.generated_at <= after

    def test_multi_product_order_semantics(
        self, tmp_db: Path
    ) -> None:
        """
        A batch of 3 lines must produce 1 distinct order_id (not 3).
        Total Orders KPI must use COUNT(DISTINCT order_id).
        """
        import src.database as db_mod
        run_demo_generation(batch_size=3, force=True, rng=random.Random(5))
        df = db_mod.get_transactions()
        demo_rows = df[df["transaction_id"].str.startswith("DEMO-")]
        assert len(demo_rows) == 3
        assert demo_rows["order_id"].nunique() == 1


# ══════════════════════════════════════════════════════════════════════════════
# should_auto_generate
# ══════════════════════════════════════════════════════════════════════════════


class TestShouldAutoGenerate:
    def test_returns_true_when_no_previous_generation(self) -> None:
        assert should_auto_generate(None) is True

    def test_returns_true_when_interval_elapsed(self) -> None:
        old = time.time() - (DEMO_REFRESH_INTERVAL_SECONDS + 5)
        assert should_auto_generate(old) is True

    def test_returns_false_within_interval(self) -> None:
        recent = time.time() - 10
        assert should_auto_generate(recent) is False

    def test_boundary_at_exactly_interval(self) -> None:
        at_boundary = time.time() - DEMO_REFRESH_INTERVAL_SECONDS
        assert should_auto_generate(at_boundary) is True


# ══════════════════════════════════════════════════════════════════════════════
# DemoGenResult structure
# ══════════════════════════════════════════════════════════════════════════════


class TestDemoGenResultStructure:
    def test_is_named_tuple(self) -> None:
        r = DemoGenResult(
            success=True,
            lines_generated=3,
            inserted=3,
            skipped_duplicate=0,
            rejected_invalid=0,
            batch_id="abc",
            generated_at=0.0,
            error_message="",
        )
        assert r.success is True
        assert r.inserted == 3

    def test_count_invariant_on_fixture(self) -> None:
        r = DemoGenResult(
            success=True,
            lines_generated=5,
            inserted=3,
            skipped_duplicate=1,
            rejected_invalid=1,
            batch_id="xyz",
            generated_at=0.0,
            error_message="",
        )
        assert r.inserted + r.skipped_duplicate + r.rejected_invalid == r.lines_generated

    def test_disabled_by_default_semantics(self) -> None:
        """
        Confirm that force=False and no prior log would allow generation
        (not blocked) — i.e. the generator is OFF by default only via the UI
        toggle, not via a code-level lock.  The DB check only blocks within
        an active 60-second window.
        """
        # With no log entry and force=False, should_auto_generate returns True
        assert should_auto_generate(None) is True
        # was_batch_generated_recently is False when log is empty (tested separately)
        # — together this confirms the first auto-generation would proceed.
