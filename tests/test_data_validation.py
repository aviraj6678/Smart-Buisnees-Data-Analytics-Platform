"""
tests/test_data_validation.py
------------------------------
Unit tests for src/data_loader.py and src/data_validation.py.

Coverage
--------
data_loader.load_file
  - loads a valid CSV from BytesIO
  - normalises column names (strips whitespace, lowercases)
  - rejects unsupported extensions
  - rejects files over the size limit

data_validation.check_required_columns
  - returns empty list when all required columns are present
  - returns names of missing columns

data_validation.coerce_types
  - parses dates to datetime64
  - parses numeric strings to float64
  - marks unparseable dates as NaT
  - marks non-numeric values as NaN
  - marks business-rule violations (quantity < 1, unit_price <= 0) as NaN

data_validation.detect_duplicates
  - finds rows with duplicated transaction_id
  - does NOT flag rows sharing the same order_id as duplicates

data_validation.handle_missing_values
  - drops rows missing required fields
  - fills customer_name and region with "Unknown" values
  - converts quantity to int after cleaning

data_validation.validate_dataframe
  - happy path: returns cleaned df and empty error lists
  - aborts early when required columns are missing
  - counts duplicate transaction_id rows removed
  - counts rows dropped for invalid / missing required values
  - counts rows filled with "Unknown"
  - confirms multi-product orders (shared order_id) are preserved
  - confirms Total Orders < total rows for multi-product orders
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from src.data_loader import ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES, load_file
from src.data_validation import (
    REQUIRED_COLUMNS,
    check_required_columns,
    coerce_types,
    detect_duplicates,
    handle_missing_values,
    validate_dataframe,
)


# ══════════════════════════════════════════════════════════════════════════════
# data_loader.load_file
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadFile:
    def test_loads_valid_csv(self, valid_csv_bytes: bytes) -> None:
        buf = io.BytesIO(valid_csv_bytes)
        buf.name = "data.csv"
        df = load_file(buf)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3

    def test_column_names_are_normalised(self, valid_csv_bytes: bytes) -> None:
        """Columns should be lowercased and stripped even if the file uses mixed case."""
        # Build a CSV with mixed-case headers
        raw = b"Transaction_ID,Order_ID,transaction_date,customer_id,customer_name,"
        raw += b"product,category,region,quantity,unit_price,unit_cost\n"
        raw += b"TXN-001,ORD-001,2024-01-01,C01,Alice,Widget,Widgets,North,1,10.0,5.0\n"
        buf = io.BytesIO(raw)
        buf.name = "mixed.csv"
        df = load_file(buf)
        assert "transaction_id" in df.columns
        assert "order_id" in df.columns

    def test_rejects_unsupported_extension(self) -> None:
        buf = io.BytesIO(b"col1,col2\n1,2")
        buf.name = "data.json"
        with pytest.raises(ValueError, match="Unsupported file type"):
            load_file(buf)

    def test_rejects_oversized_file(self) -> None:
        oversized = io.BytesIO(b"x" * (MAX_FILE_SIZE_BYTES + 1))
        oversized.name = "big.csv"
        with pytest.raises(ValueError, match="exceeds the 50 MB limit"):
            load_file(oversized)

    def test_allowed_extensions_constant(self) -> None:
        assert ".csv" in ALLOWED_EXTENSIONS
        assert ".xlsx" in ALLOWED_EXTENSIONS


# ══════════════════════════════════════════════════════════════════════════════
# check_required_columns
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckRequiredColumns:
    def test_all_columns_present(self, valid_df: pd.DataFrame) -> None:
        missing = check_required_columns(valid_df)
        assert missing == []

    def test_detects_missing_transaction_id(self, valid_df: pd.DataFrame) -> None:
        df = valid_df.drop(columns=["transaction_id"])
        missing = check_required_columns(df)
        assert "transaction_id" in missing

    def test_detects_multiple_missing_columns(self, valid_df: pd.DataFrame) -> None:
        df = valid_df.drop(columns=["transaction_id", "unit_cost"])
        missing = check_required_columns(df)
        assert "transaction_id" in missing
        assert "unit_cost" in missing

    def test_required_columns_list_includes_transaction_id(self) -> None:
        assert "transaction_id" in REQUIRED_COLUMNS

    def test_required_columns_list_includes_order_id(self) -> None:
        assert "order_id" in REQUIRED_COLUMNS


# ══════════════════════════════════════════════════════════════════════════════
# coerce_types
# ══════════════════════════════════════════════════════════════════════════════


class TestCoerceTypes:
    def test_parses_date_strings(self, valid_df: pd.DataFrame) -> None:
        df, errors = coerce_types(valid_df)
        assert pd.api.types.is_datetime64_any_dtype(df["transaction_date"])
        assert df["transaction_date"].notna().all()

    def test_parses_numeric_strings(self, valid_df: pd.DataFrame) -> None:
        df, errors = coerce_types(valid_df)
        assert pd.api.types.is_float_dtype(df["unit_price"])
        assert pd.api.types.is_float_dtype(df["unit_cost"])

    def test_unparseable_date_becomes_nat(self) -> None:
        df = pd.DataFrame(
            [{"transaction_id": "T1", "order_id": "O1", "transaction_date": "NOT_A_DATE",
              "customer_id": "C1", "customer_name": "Alice", "product": "P",
              "category": "Cat", "region": "R", "quantity": "1",
              "unit_price": "10.0", "unit_cost": "5.0"}]
        )
        df_out, errors = coerce_types(df)
        assert df_out["transaction_date"].isna().iloc[0]
        assert any("transaction_date" in e for e in errors)

    def test_non_numeric_quantity_becomes_nan(self) -> None:
        df = pd.DataFrame(
            [{"transaction_id": "T1", "order_id": "O1", "transaction_date": "2024-01-01",
              "customer_id": "C1", "customer_name": "Alice", "product": "P",
              "category": "Cat", "region": "R", "quantity": "ABC",
              "unit_price": "10.0", "unit_cost": "5.0"}]
        )
        df_out, errors = coerce_types(df)
        assert pd.isna(df_out["quantity"].iloc[0])
        assert any("quantity" in e for e in errors)

    def test_zero_quantity_violates_business_rule(self) -> None:
        df = pd.DataFrame(
            [{"transaction_id": "T1", "order_id": "O1", "transaction_date": "2024-01-01",
              "customer_id": "C1", "customer_name": "Alice", "product": "P",
              "category": "Cat", "region": "R", "quantity": "0",
              "unit_price": "10.0", "unit_cost": "5.0"}]
        )
        df_out, errors = coerce_types(df)
        assert pd.isna(df_out["quantity"].iloc[0])
        assert any("quantity" in e for e in errors)

    def test_negative_unit_price_violates_business_rule(self) -> None:
        df = pd.DataFrame(
            [{"transaction_id": "T1", "order_id": "O1", "transaction_date": "2024-01-01",
              "customer_id": "C1", "customer_name": "Alice", "product": "P",
              "category": "Cat", "region": "R", "quantity": "1",
              "unit_price": "-5.0", "unit_cost": "5.0"}]
        )
        df_out, errors = coerce_types(df)
        assert pd.isna(df_out["unit_price"].iloc[0])
        assert any("unit_price" in e for e in errors)

    def test_zero_unit_cost_is_valid(self) -> None:
        """unit_cost >= 0 is the rule; zero cost is a legitimate free-sample or internal transfer."""
        df = pd.DataFrame(
            [{"transaction_id": "T1", "order_id": "O1", "transaction_date": "2024-01-01",
              "customer_id": "C1", "customer_name": "Alice", "product": "P",
              "category": "Cat", "region": "R", "quantity": "1",
              "unit_price": "10.0", "unit_cost": "0.0"}]
        )
        df_out, errors = coerce_types(df)
        assert not pd.isna(df_out["unit_cost"].iloc[0])
        assert not any("unit_cost" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# detect_duplicates
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectDuplicates:
    def test_no_duplicates_returns_empty_df(self, valid_df: pd.DataFrame) -> None:
        dupes = detect_duplicates(valid_df)
        assert len(dupes) == 0

    def test_detects_duplicate_transaction_id(self, valid_df: pd.DataFrame) -> None:
        df = pd.concat(
            [valid_df, valid_df.iloc[[0]].assign(order_id="ORD-999")],
            ignore_index=True,
        )
        dupes = detect_duplicates(df)
        assert "TXN-001" in dupes["transaction_id"].values

    def test_shared_order_id_is_not_a_duplicate(self, valid_df: pd.DataFrame) -> None:
        """
        ORD-001 appears on rows TXN-001 and TXN-002 (different products).
        Neither row should be flagged as a duplicate.
        """
        dupes = detect_duplicates(valid_df)
        # Rows with order_id == 'ORD-001' must NOT appear in duplicates
        assert len(dupes[dupes["order_id"] == "ORD-001"]) == 0

    def test_returns_both_occurrences_of_duplicate(self) -> None:
        """detect_duplicates uses keep=False so both copies are returned."""
        df = pd.DataFrame(
            [
                {"transaction_id": "TXN-DUP", "order_id": "O1"},
                {"transaction_id": "TXN-DUP", "order_id": "O2"},
                {"transaction_id": "TXN-UNQ", "order_id": "O3"},
            ]
        )
        dupes = detect_duplicates(df)
        assert len(dupes) == 2
        assert set(dupes["transaction_id"]) == {"TXN-DUP"}


# ══════════════════════════════════════════════════════════════════════════════
# handle_missing_values
# ══════════════════════════════════════════════════════════════════════════════


class TestHandleMissingValues:
    def _coerced(self, valid_df: pd.DataFrame) -> pd.DataFrame:
        df, _ = coerce_types(valid_df)
        return df

    def test_no_missing_returns_all_rows(self, valid_df: pd.DataFrame) -> None:
        df, counts = handle_missing_values(self._coerced(valid_df))
        assert len(df) == 3
        assert counts["rows_dropped_missing_required"] == 0
        assert counts["rows_filled_unknown"] == 0

    def test_drops_row_missing_required_numeric(self, valid_df: pd.DataFrame) -> None:
        df = self._coerced(valid_df).copy()
        df.loc[0, "unit_price"] = float("nan")
        cleaned, counts = handle_missing_values(df)
        assert len(cleaned) == 2
        assert counts["rows_dropped_missing_required"] == 1

    def test_fills_missing_customer_name(self, valid_df: pd.DataFrame) -> None:
        df = self._coerced(valid_df).copy()
        df.loc[0, "customer_name"] = None
        cleaned, counts = handle_missing_values(df)
        assert cleaned.loc[cleaned["transaction_id"] == "TXN-001", "customer_name"].iloc[0] == "Unknown Customer"
        assert counts["rows_filled_unknown"] == 1

    def test_fills_missing_region(self, valid_df: pd.DataFrame) -> None:
        df = self._coerced(valid_df).copy()
        df.loc[2, "region"] = None
        cleaned, counts = handle_missing_values(df)
        assert cleaned.loc[cleaned["transaction_id"] == "TXN-003", "region"].iloc[0] == "Unknown Region"
        assert counts["rows_filled_unknown"] == 1

    def test_quantity_is_int_after_cleaning(self, valid_df: pd.DataFrame) -> None:
        df, _ = handle_missing_values(self._coerced(valid_df))
        assert df["quantity"].dtype == int


# ══════════════════════════════════════════════════════════════════════════════
# validate_dataframe (composed pipeline)
# ══════════════════════════════════════════════════════════════════════════════


class TestValidateDataframe:
    def test_happy_path(self, valid_df: pd.DataFrame) -> None:
        cleaned, report = validate_dataframe(valid_df)
        assert len(cleaned) == 3
        assert report["missing_columns"] == []
        assert report["type_errors"] == []
        assert report["duplicate_transaction_ids_removed"] == 0
        assert report["rows_dropped_missing_required"] == 0
        assert report["rows_filled_unknown"] == 0

    def test_aborts_on_missing_required_column(self, valid_df: pd.DataFrame) -> None:
        df = valid_df.drop(columns=["transaction_id"])
        cleaned, report = validate_dataframe(df)
        assert cleaned.empty
        assert "transaction_id" in report["missing_columns"]

    def test_counts_duplicate_transaction_ids(self, valid_df: pd.DataFrame) -> None:
        df = pd.concat([valid_df, valid_df.iloc[[0]]], ignore_index=True)
        cleaned, report = validate_dataframe(df)
        assert report["duplicate_transaction_ids_removed"] == 1
        assert len(cleaned) == 3  # one duplicate removed

    def test_counts_rows_dropped_for_invalid_value(self, valid_df: pd.DataFrame) -> None:
        df = valid_df.copy()
        df.loc[0, "quantity"] = "INVALID"
        cleaned, report = validate_dataframe(df)
        assert report["rows_dropped_missing_required"] >= 1
        assert len(cleaned) == 2

    def test_counts_rows_filled_unknown(self, valid_df: pd.DataFrame) -> None:
        df = valid_df.copy()
        df.loc[1, "region"] = None
        cleaned, report = validate_dataframe(df)
        assert report["rows_filled_unknown"] >= 1

    def test_multi_product_order_preserved(self, valid_df: pd.DataFrame) -> None:
        """
        ORD-001 has two rows (TXN-001, TXN-002).  Both must survive validation.
        """
        cleaned, report = validate_dataframe(valid_df)
        ord001 = cleaned[cleaned["order_id"] == "ORD-001"]
        assert len(ord001) == 2, (
            f"Expected 2 rows for ORD-001, got {len(ord001)}. "
            "Multi-product orders must not be deduplicated."
        )

    def test_total_orders_less_than_total_rows(self, valid_df: pd.DataFrame) -> None:
        """
        Core KPI correctness: COUNT(DISTINCT order_id) must be < total rows
        when multi-product orders are present.
        """
        cleaned, _ = validate_dataframe(valid_df)
        total_rows = len(cleaned)
        total_orders = cleaned["order_id"].nunique()
        assert total_orders < total_rows, (
            f"Total orders ({total_orders}) should be less than total rows ({total_rows}) "
            "because ORD-001 contains two product lines."
        )

    def test_error_report_keys_present(self, valid_df: pd.DataFrame) -> None:
        _, report = validate_dataframe(valid_df)
        expected_keys = {
            "missing_columns",
            "type_errors",
            "duplicate_transaction_ids_removed",
            "rows_dropped_missing_required",
            "rows_filled_unknown",
        }
        assert set(report.keys()) == expected_keys


# ══════════════════════════════════════════════════════════════════════════════
# data_loader.load_file — Excel (.xlsx) path
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadFileExcel:
    """Verify that load_file() handles .xlsx files identically to .csv."""

    @staticmethod
    def _make_xlsx_buf(df: pd.DataFrame) -> io.BytesIO:
        """Write *df* to an in-memory .xlsx buffer and return it."""
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        buf.seek(0)
        buf.name = "data.xlsx"
        return buf

    def test_loads_valid_xlsx(self, valid_df: pd.DataFrame) -> None:
        buf = self._make_xlsx_buf(valid_df)
        result = load_file(buf)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3

    def test_xlsx_column_names_are_normalised(self, valid_df: pd.DataFrame) -> None:
        """Columns written with mixed-case headers must be lowercased after loading."""
        mixed = valid_df.copy()
        mixed.columns = [c.upper() for c in mixed.columns]  # TRANSACTION_ID, etc.
        buf = self._make_xlsx_buf(mixed)
        result = load_file(buf)
        assert "transaction_id" in result.columns
        assert "order_id" in result.columns
        assert "unit_price" in result.columns

    def test_xlsx_row_count_matches_source(self, valid_df: pd.DataFrame) -> None:
        buf = self._make_xlsx_buf(valid_df)
        result = load_file(buf)
        assert len(result) == len(valid_df)

    def test_xlsx_values_match_source(self, valid_df: pd.DataFrame) -> None:
        buf = self._make_xlsx_buf(valid_df)
        result = load_file(buf)
        # load_file reads everything as str; compare on the raw string values
        assert list(result["transaction_id"]) == list(valid_df["transaction_id"])
        assert list(result["product"]) == list(valid_df["product"])

    def test_rejects_xlsx_over_size_limit(self) -> None:
        oversized = io.BytesIO(b"x" * (MAX_FILE_SIZE_BYTES + 1))
        oversized.name = "big.xlsx"
        with pytest.raises(ValueError, match="exceeds the 50 MB limit"):
            load_file(oversized)


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end: load_file → validate_dataframe → insert_transactions
# ══════════════════════════════════════════════════════════════════════════════


class TestValidationToImportIntegration:
    """
    Integration test: exercise the full import pipeline and assert that the
    three ImportResult counts are accurate with no double-counting.

    Pipeline:
        raw file bytes
          → load_file()           — parse + normalise column names
          → validate_dataframe()  — coerce / deduplicate / drop / fill
          → insert_transactions() — persist; detect DB-level duplicates

    ImportResult invariant
    ----------------------
    Given a raw file with N rows, the following must always hold:

        inserted + skipped_duplicate + rejected_invalid == N_raw

    where N_raw is the number of data rows in the raw file (before any
    validation), and rejected_invalid counts rows removed by validation.
    """

    def _pipeline(
        self,
        buf: io.BytesIO,
        raw_row_count: int,
    ):
        """Run the full pipeline and return (ImportResult, cleaned_df)."""
        from src.database import clear_transactions, init_db, insert_transactions

        init_db()
        clear_transactions()

        df_raw = load_file(buf)
        df_clean, report = validate_dataframe(df_raw)

        rejected = (
            report["duplicate_transaction_ids_removed"]
            + report["rows_dropped_missing_required"]
        )
        result = insert_transactions(df_clean, rejected_invalid=rejected)
        return result, df_clean

    def test_happy_path_all_rows_inserted(self, valid_csv_bytes: bytes) -> None:
        """All 3 valid rows must be inserted; nothing skipped or rejected."""
        buf = io.BytesIO(valid_csv_bytes)
        buf.name = "data.csv"
        result, _ = self._pipeline(buf, raw_row_count=3)

        assert result.inserted == 3
        assert result.skipped_duplicate == 0
        assert result.rejected_invalid == 0

    def test_import_result_counts_sum_to_raw_rows(self, valid_csv_bytes: bytes) -> None:
        """
        Core invariant: inserted + skipped_duplicate + rejected_invalid
        must equal the number of data rows in the raw file.
        """
        buf = io.BytesIO(valid_csv_bytes)
        buf.name = "data.csv"
        result, _ = self._pipeline(buf, raw_row_count=3)

        total = result.inserted + result.skipped_duplicate + result.rejected_invalid
        assert total == 3, (
            f"Count mismatch: inserted={result.inserted}, "
            f"skipped_duplicate={result.skipped_duplicate}, "
            f"rejected_invalid={result.rejected_invalid} — sum={total}, expected 3"
        )

    def test_reimport_same_file_all_skipped(self, valid_csv_bytes: bytes) -> None:
        """
        Importing the same file twice must produce 0 inserted and 3
        skipped_duplicate on the second import (INSERT OR IGNORE semantics).
        """
        from src.database import clear_transactions, init_db, insert_transactions

        init_db()
        clear_transactions()

        buf1 = io.BytesIO(valid_csv_bytes)
        buf1.name = "data.csv"
        df_raw = load_file(buf1)
        df_clean, report = validate_dataframe(df_raw)
        rejected = (
            report["duplicate_transaction_ids_removed"]
            + report["rows_dropped_missing_required"]
        )
        # First import
        insert_transactions(df_clean, rejected_invalid=rejected)

        # Second import — same data
        buf2 = io.BytesIO(valid_csv_bytes)
        buf2.name = "data.csv"
        df_raw2 = load_file(buf2)
        df_clean2, report2 = validate_dataframe(df_raw2)
        rejected2 = (
            report2["duplicate_transaction_ids_removed"]
            + report2["rows_dropped_missing_required"]
        )
        result2 = insert_transactions(df_clean2, rejected_invalid=rejected2)

        assert result2.inserted == 0
        assert result2.skipped_duplicate == 3

    def test_invalid_row_counted_in_rejected(self, valid_df: pd.DataFrame) -> None:
        """
        A file with 3 rows, one of which has an unparseable quantity, must
        produce rejected_invalid >= 1 and inserted == 2.
        """
        from src.database import clear_transactions, init_db, insert_transactions

        init_db()
        clear_transactions()

        df = valid_df.copy()
        df.loc[0, "quantity"] = "INVALID"  # will be coerced to NaN → row dropped

        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        buf.name = "data.csv"

        df_raw = load_file(buf)
        df_clean, report = validate_dataframe(df_raw)
        rejected = (
            report["duplicate_transaction_ids_removed"]
            + report["rows_dropped_missing_required"]
        )
        result = insert_transactions(df_clean, rejected_invalid=rejected)

        assert result.rejected_invalid >= 1
        assert result.inserted == 2
        assert result.inserted + result.skipped_duplicate + result.rejected_invalid == 3

    def test_excel_file_import_happy_path(self, valid_df: pd.DataFrame) -> None:
        """
        The same invariant must hold when the file is an .xlsx rather than .csv.
        """
        from src.database import clear_transactions, init_db, insert_transactions

        init_db()
        clear_transactions()

        buf = io.BytesIO()
        valid_df.to_excel(buf, index=False)
        buf.seek(0)
        buf.name = "data.xlsx"

        df_raw = load_file(buf)
        df_clean, report = validate_dataframe(df_raw)
        rejected = (
            report["duplicate_transaction_ids_removed"]
            + report["rows_dropped_missing_required"]
        )
        result = insert_transactions(df_clean, rejected_invalid=rejected)

        assert result.inserted == 3
        assert result.skipped_duplicate == 0
        assert result.rejected_invalid == 0
        total = result.inserted + result.skipped_duplicate + result.rejected_invalid
        assert total == 3
