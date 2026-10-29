"""
tests/conftest.py
-----------------
Shared pytest fixtures for the Smart Business Data Analytics Platform test suite.
"""

from __future__ import annotations

import io
import pathlib

import pandas as pd
import pytest


# ── Minimal valid DataFrame ───────────────────────────────────────────────────

@pytest.fixture()
def valid_df() -> pd.DataFrame:
    """
    A minimal, fully valid DataFrame with two rows belonging to the same
    order (ORD-001) and one row belonging to a separate order (ORD-002).
    Useful for verifying that multi-product orders are NOT flagged as dupes.
    """
    return pd.DataFrame(
        {
            "transaction_id": ["TXN-001", "TXN-002", "TXN-003"],
            "order_id": ["ORD-001", "ORD-001", "ORD-002"],
            "transaction_date": ["2024-01-15", "2024-01-15", "2024-02-10"],
            "customer_id": ["C01", "C01", "C02"],
            "customer_name": ["Alice", "Alice", "Bob"],
            "product": ["Widget A", "Widget B", "Gadget X"],
            "category": ["Widgets", "Widgets", "Gadgets"],
            "region": ["North", "North", "South"],
            "quantity": ["2", "1", "5"],
            "unit_price": ["50.00", "80.00", "20.00"],
            "unit_cost": ["30.00", "40.00", "10.00"],
        }
    )


@pytest.fixture()
def valid_csv_bytes(valid_df: pd.DataFrame) -> bytes:
    """CSV bytes of the valid_df fixture — for testing load_file."""
    buf = io.BytesIO()
    valid_df.to_csv(buf, index=False)
    return buf.getvalue()


@pytest.fixture()
def project_root() -> pathlib.Path:
    """Absolute path to the project root (parent of tests/)."""
    return pathlib.Path(__file__).resolve().parent.parent
