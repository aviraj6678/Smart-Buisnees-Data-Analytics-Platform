"""
src/data_validation.py
----------------------
Schema enforcement, type coercion, and business-rule validation for the
Smart Business Data Analytics Platform.

The central function is ``validate_dataframe``, which composes four steps
in order:

1. check_required_columns  — abort early if any required column is missing
2. coerce_types            — parse dates and numerics; collect failures
3. detect_duplicates       — flag duplicate transaction_id rows (NOT order_id)
4. handle_missing_values   — drop or fill missing values per column rules

``validate_dataframe`` returns:
    (cleaned_df, error_report)

where ``error_report`` is a dict with these keys:

    missing_columns                  : list[str]   — columns absent from the file
    type_errors                      : list[str]   — human-readable coercion failures
    duplicate_transaction_ids_removed: int         — rows dropped for duplicate transaction_id
    rows_dropped_missing_required    : int         — rows dropped for null required fields
    rows_filled_unknown              : int         — rows where customer_name/region was filled

The total rows removed (duplicate + dropped) is the ``rejected_invalid``
count to pass into database.insert_transactions().
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

# ── Schema definition ─────────────────────────────────────────────────────────

# Columns that must be present (case-insensitive matching is applied at load time)
REQUIRED_COLUMNS: List[str] = [
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

# Numeric columns that must have a valid, non-null value — rows are dropped if invalid
REQUIRED_NUMERIC_COLUMNS: List[str] = ["quantity", "unit_price", "unit_cost"]

# Columns where a missing value is filled with "Unknown" instead of dropping the row
FILLABLE_COLUMNS: List[str] = ["customer_name", "region"]

# Business rules for numeric columns
_NUMERIC_RULES: Dict[str, Tuple[float, str]] = {
    # column: (minimum_valid_value, rule_description)
    "quantity":   (1.0,  "quantity must be >= 1"),
    "unit_price": (0.01, "unit_price must be > 0"),
    "unit_cost":  (0.0,  "unit_cost must be >= 0"),
}

# ── Step 1 — Required column check ───────────────────────────────────────────


def check_required_columns(df: pd.DataFrame) -> List[str]:
    """
    Return a list of required column names that are absent from ``df``.

    Column matching is case-insensitive and whitespace-stripped (column names
    should already be normalised by data_loader.load_file).

    Returns an empty list when all required columns are present.
    """
    present = set(df.columns.str.strip().str.lower())
    return [col for col in REQUIRED_COLUMNS if col not in present]


# ── Step 2 — Type coercion ────────────────────────────────────────────────────


def coerce_types(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Parse each column to its target dtype and collect human-readable error
    messages for values that could not be converted.

    Rows with un-parseable values in required numeric columns are NOT dropped
    here — they are marked as NaN so that ``handle_missing_values`` can drop
    them and count them in one place.

    Returns
    -------
    (df_coerced, type_errors)
        df_coerced : DataFrame with corrected dtypes where conversion succeeded
        type_errors: list of descriptive strings, one per conversion problem
    """
    df = df.copy()
    errors: List[str] = []

    # transaction_date → datetime64
    original_date_col = df["transaction_date"].copy()
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    bad_dates = original_date_col[df["transaction_date"].isna() & original_date_col.notna()]
    if not bad_dates.empty:
        sample = bad_dates.iloc[0]
        errors.append(
            f"transaction_date: {len(bad_dates)} value(s) could not be parsed as a date "
            f"(e.g. '{sample}'). These rows will be dropped."
        )

    # Numeric columns → float64
    for col in REQUIRED_NUMERIC_COLUMNS:
        original = df[col].copy()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        bad = original[df[col].isna() & original.notna()]
        if not bad.empty:
            sample = bad.iloc[0]
            errors.append(
                f"{col}: {len(bad)} non-numeric value(s) found "
                f"(e.g. '{sample}'). These rows will be dropped."
            )

    # Enforce business-rule minimums — set violating values to NaN so they are dropped
    for col, (minimum, rule) in _NUMERIC_RULES.items():
        violating = df[col].notna() & (df[col] < minimum)
        count = violating.sum()
        if count > 0:
            sample_val = df.loc[violating, col].iloc[0]
            errors.append(
                f"{col}: {count} row(s) violate rule '{rule}' "
                f"(e.g. value {sample_val!r}). These rows will be dropped."
            )
            df.loc[violating, col] = float("nan")

    # quantity → int64 (after NaN marking so astype doesn't raise)
    # Use Int64 (nullable integer) to preserve NaN, convert to int after drop
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

    return df, errors


# ── Step 3 — Duplicate detection ─────────────────────────────────────────────


def detect_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a DataFrame containing only the duplicate rows — those whose
    ``transaction_id`` appears more than once.

    Detection is based **exclusively on transaction_id**.
    Multiple rows sharing the same ``order_id`` are a valid multi-product
    order and must NOT be returned here.
    """
    return df[df.duplicated(subset=["transaction_id"], keep=False)].copy()


# ── Step 4 — Missing value handling ──────────────────────────────────────────


def handle_missing_values(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """
    Drop rows missing required values; fill optional columns with "Unknown".

    Drop triggers (row removed entirely):
    - transaction_date is NaT (un-parseable or absent)
    - transaction_id is null or empty string
    - order_id is null or empty string
    - customer_id is null or empty string
    - product is null or empty string
    - category is null or empty string
    - quantity, unit_price, or unit_cost is NaN (includes business-rule violations)

    Fill triggers (row kept, value substituted):
    - customer_name is null → "Unknown Customer"
    - region is null → "Unknown Region"

    Returns
    -------
    (cleaned_df, counts)
        counts = {
            "rows_dropped_missing_required": int,
            "rows_filled_unknown": int,
        }
    """
    df = df.copy()
    before = len(df)

    # Columns where null / empty-string = drop
    drop_null_cols = [
        "transaction_id",
        "order_id",
        "transaction_date",
        "customer_id",
        "product",
        "category",
    ] + REQUIRED_NUMERIC_COLUMNS

    # Replace empty strings with NaN for consistent null detection
    str_cols = ["transaction_id", "order_id", "customer_id", "product", "category",
                "customer_name", "region"]
    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].replace("", pd.NA)

    drop_mask = df[drop_null_cols].isnull().any(axis=1)
    df = df[~drop_mask].copy()
    rows_dropped = before - len(df)

    # Fill optional columns
    filled_count = 0
    fill_map = {"customer_name": "Unknown Customer", "region": "Unknown Region"}
    for col, fill_val in fill_map.items():
        if col in df.columns:
            null_mask = df[col].isnull()
            if null_mask.any():
                df.loc[null_mask, col] = fill_val
                filled_count += null_mask.sum()

    # Finalise types: quantity → int (now NaN-free)
    df["quantity"] = df["quantity"].astype(int)
    df["unit_price"] = df["unit_price"].astype(float)
    df["unit_cost"] = df["unit_cost"].astype(float)

    return df, {
        "rows_dropped_missing_required": rows_dropped,
        "rows_filled_unknown": filled_count,
    }


# ── Composed pipeline ─────────────────────────────────────────────────────────


def validate_dataframe(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict]:
    """
    Run the full validation pipeline on a raw DataFrame loaded by data_loader.

    Steps (in order):
    1. Check required columns — return immediately if any are absent.
    2. Coerce types and apply business-rule minimums.
    3. Remove duplicate transaction_id rows (keep first occurrence).
    4. Drop rows with missing required values; fill optional columns.

    Parameters
    ----------
    df : pd.DataFrame
        Raw DataFrame as returned by data_loader.load_file().

    Returns
    -------
    (cleaned_df, error_report)

    error_report keys
    -----------------
    missing_columns                   : list[str]
    type_errors                       : list[str]
    duplicate_transaction_ids_removed : int
    rows_dropped_missing_required     : int
    rows_filled_unknown               : int

    When ``missing_columns`` is non-empty, ``cleaned_df`` is an empty
    DataFrame and no further steps are run.
    """
    error_report: Dict = {
        "missing_columns": [],
        "type_errors": [],
        "duplicate_transaction_ids_removed": 0,
        "rows_dropped_missing_required": 0,
        "rows_filled_unknown": 0,
    }

    # Step 1 — required columns
    missing = check_required_columns(df)
    if missing:
        error_report["missing_columns"] = missing
        return pd.DataFrame(), error_report

    # Step 2 — type coercion
    df, type_errors = coerce_types(df)
    error_report["type_errors"] = type_errors

    # Step 3 — deduplicate on transaction_id (keep first, drop subsequent)
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["transaction_id"], keep="first").copy()
    error_report["duplicate_transaction_ids_removed"] = before_dedup - len(df)

    # Step 4 — missing value handling
    df, mv_counts = handle_missing_values(df)
    error_report["rows_dropped_missing_required"] = mv_counts["rows_dropped_missing_required"]
    error_report["rows_filled_unknown"] = mv_counts["rows_filled_unknown"]

    return df, error_report
