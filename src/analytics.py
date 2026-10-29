"""
src/analytics.py
----------------
All KPI calculations, aggregations, and segmentation logic for the
Smart Business Data Analytics Platform.

Design rules
------------
- Every public function accepts a **pre-filtered** DataFrame.
  Filtering by date range, region, or category is done by the caller
  (typically a Streamlit page) before passing the DataFrame here.
- Derived columns (revenue, cost, profit, profit_margin) are computed
  on-the-fly from the base columns — they are never stored in the DB.
- safe_divide() is used for every division to prevent ZeroDivisionError
  and NaN leaking into KPI display widgets.
- Total Orders = df["order_id"].nunique()  — NOT len(df).
- AOV = Total Revenue / Total Orders       — denominator is distinct orders.
"""

from __future__ import annotations

from typing import Union

import numpy as np
import pandas as pd

# ── Constants ─────────────────────────────────────────────────────────────────

LOW_PROFIT_MARGIN_THRESHOLD: float = 0.10   # 10 % — flag as low-profit
HIGH_VALUE_REVENUE_PERCENTILE: float = 0.80  # top 20 % by revenue = High Value
MID_VALUE_REVENUE_PERCENTILE: float = 0.50  # next 30 % = Mid Value  (bottom 50 % = Low Value)

# ── Utility ───────────────────────────────────────────────────────────────────


def safe_divide(
    numerator: Union[float, pd.Series, np.ndarray],
    denominator: Union[float, pd.Series, np.ndarray],
    default: float = 0.0,
) -> Union[float, pd.Series, np.ndarray]:
    """
    Divide numerator by denominator, returning ``default`` wherever the
    denominator is zero or NaN.

    Works for scalars, Pandas Series, and NumPy arrays.
    """
    if isinstance(numerator, (int, float)) and isinstance(denominator, (int, float)):
        return default if denominator == 0 else numerator / denominator

    # Series / array path
    denom = pd.to_numeric(denominator, errors="coerce") if not isinstance(denominator, (pd.Series, np.ndarray)) else denominator
    num = pd.to_numeric(numerator, errors="coerce") if not isinstance(numerator, (pd.Series, np.ndarray)) else numerator
    result = np.where((denom == 0) | pd.isna(denom), default, num / denom)
    if isinstance(numerator, pd.Series):
        return pd.Series(result, index=numerator.index)
    return result


def _add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy of ``df`` with revenue, cost, profit, and profit_margin
    columns added.  These are computed from base columns and never stored.
    """
    df = df.copy()
    df["revenue"] = df["quantity"] * df["unit_price"]
    df["cost"] = df["quantity"] * df["unit_cost"]
    df["profit"] = df["revenue"] - df["cost"]
    df["profit_margin"] = safe_divide(df["profit"], df["revenue"])
    return df


# ── KPIs ──────────────────────────────────────────────────────────────────────


def compute_kpis(df: pd.DataFrame) -> dict:
    """
    Compute top-level KPIs from a (pre-filtered) transactions DataFrame.

    Returns
    -------
    dict with keys:
        total_revenue       : float
        total_profit        : float
        total_orders        : int   (COUNT DISTINCT order_id)
        total_line_items    : int   (row count)
        avg_order_value     : float (total_revenue / total_orders)
        profit_margin_pct   : float (0–100)
    """
    if df.empty:
        return {
            "total_revenue": 0.0,
            "total_profit": 0.0,
            "total_orders": 0,
            "total_line_items": 0,
            "avg_order_value": 0.0,
            "profit_margin_pct": 0.0,
        }

    df = _add_derived(df)

    total_revenue: float = float(df["revenue"].sum())
    total_profit: float = float(df["profit"].sum())
    total_orders: int = int(df["order_id"].nunique())   # distinct orders, NOT rows
    total_line_items: int = len(df)
    avg_order_value: float = safe_divide(total_revenue, total_orders)
    profit_margin_pct: float = safe_divide(total_profit, total_revenue) * 100

    return {
        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "total_orders": total_orders,
        "total_line_items": total_line_items,
        "avg_order_value": float(avg_order_value),
        "profit_margin_pct": float(profit_margin_pct),
    }


# ── Sales aggregations ────────────────────────────────────────────────────────


def sales_by_period(df: pd.DataFrame, period: str = "month") -> pd.DataFrame:
    """
    Aggregate revenue and profit by time period.

    Parameters
    ----------
    df : pd.DataFrame
        Pre-filtered transactions DataFrame.
    period : str
        ``"month"`` (default) or ``"year"``.

    Returns
    -------
    pd.DataFrame with columns: period_label, revenue, profit, orders, line_items
        Sorted chronologically.
    """
    if df.empty:
        return pd.DataFrame(columns=["period_label", "revenue", "profit", "orders", "line_items"])

    df = _add_derived(df.copy())
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])

    if period == "year":
        df["period_label"] = df["transaction_date"].dt.year.astype(str)
    else:
        # Default: month — format as "YYYY-MM" for chronological sort
        df["period_label"] = df["transaction_date"].dt.to_period("M").astype(str)

    agg = (
        df.groupby("period_label", sort=True)
        .agg(
            revenue=("revenue", "sum"),
            profit=("profit", "sum"),
            orders=("order_id", "nunique"),
            line_items=("transaction_id", "count"),
        )
        .reset_index()
    )
    return agg.sort_values("period_label").reset_index(drop=True)


def sales_by_product(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate revenue, profit, and order count by product.

    Returns
    -------
    pd.DataFrame with columns: product, revenue, profit, profit_margin, orders, line_items
        Sorted by revenue descending.
    """
    if df.empty:
        return pd.DataFrame(columns=["product", "revenue", "profit", "profit_margin", "orders", "line_items"])

    df = _add_derived(df.copy())
    agg = (
        df.groupby("product", sort=False)
        .agg(
            revenue=("revenue", "sum"),
            profit=("profit", "sum"),
            orders=("order_id", "nunique"),
            line_items=("transaction_id", "count"),
        )
        .reset_index()
    )
    agg["profit_margin"] = safe_divide(agg["profit"], agg["revenue"])
    return agg.sort_values("revenue", ascending=False).reset_index(drop=True)


def sales_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate revenue, profit, and order count by product category.

    Returns
    -------
    pd.DataFrame with columns: category, revenue, profit, profit_margin, orders, line_items
        Sorted by revenue descending.
    """
    if df.empty:
        return pd.DataFrame(columns=["category", "revenue", "profit", "profit_margin", "orders", "line_items"])

    df = _add_derived(df.copy())
    agg = (
        df.groupby("category", sort=False)
        .agg(
            revenue=("revenue", "sum"),
            profit=("profit", "sum"),
            orders=("order_id", "nunique"),
            line_items=("transaction_id", "count"),
        )
        .reset_index()
    )
    agg["profit_margin"] = safe_divide(agg["profit"], agg["revenue"])
    return agg.sort_values("revenue", ascending=False).reset_index(drop=True)


def sales_by_region(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate revenue, profit, and order count by region.

    Returns
    -------
    pd.DataFrame with columns: region, revenue, profit, profit_margin, orders, line_items
        Sorted by revenue descending.
    """
    if df.empty:
        return pd.DataFrame(columns=["region", "revenue", "profit", "profit_margin", "orders", "line_items"])

    df = _add_derived(df.copy())
    agg = (
        df.groupby("region", sort=False)
        .agg(
            revenue=("revenue", "sum"),
            profit=("profit", "sum"),
            orders=("order_id", "nunique"),
            line_items=("transaction_id", "count"),
        )
        .reset_index()
    )
    agg["profit_margin"] = safe_divide(agg["profit"], agg["revenue"])
    return agg.sort_values("revenue", ascending=False).reset_index(drop=True)


def top_products(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return the top ``n`` products by revenue (descending)."""
    return sales_by_product(df).head(n)


def bottom_products(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return the bottom ``n`` products by revenue (ascending)."""
    if df.empty:
        return pd.DataFrame(columns=["product", "revenue", "profit", "profit_margin", "orders", "line_items"])
    return sales_by_product(df).tail(n).sort_values("revenue").reset_index(drop=True)


# ── Customer analytics ────────────────────────────────────────────────────────


def customer_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-customer revenue, profit, order count, and line-item count.

    Returns
    -------
    pd.DataFrame with columns:
        customer_id, customer_name, revenue, profit, orders, line_items, avg_order_value
        Sorted by revenue descending.
    """
    if df.empty:
        return pd.DataFrame(
            columns=["customer_id", "customer_name", "revenue", "profit",
                     "orders", "line_items", "avg_order_value"]
        )

    df = _add_derived(df.copy())
    agg = (
        df.groupby(["customer_id", "customer_name"], sort=False)
        .agg(
            revenue=("revenue", "sum"),
            profit=("profit", "sum"),
            orders=("order_id", "nunique"),
            line_items=("transaction_id", "count"),
        )
        .reset_index()
    )
    agg["avg_order_value"] = safe_divide(agg["revenue"], agg["orders"])
    return agg.sort_values("revenue", ascending=False).reset_index(drop=True)


def segment_customers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign a revenue-tier segment to each customer using simple rule-based
    percentile thresholds.  No ML is used.

    Segment rules (applied to per-customer total revenue):
        High Value  — customer is in the top 20 % by revenue
        Mid Value   — customer is between the 50th and 80th percentile
        Low Value   — customer is in the bottom 50 %

    Returns
    -------
    pd.DataFrame (customer_summary columns) plus a ``segment`` column.
    """
    summary = customer_summary(df)
    if summary.empty:
        summary["segment"] = pd.Series(dtype=str)
        return summary

    p80 = summary["revenue"].quantile(HIGH_VALUE_REVENUE_PERCENTILE)
    p50 = summary["revenue"].quantile(MID_VALUE_REVENUE_PERCENTILE)

    def _tier(rev: float) -> str:
        if rev >= p80:
            return "High Value"
        if rev >= p50:
            return "Mid Value"
        return "Low Value"

    summary["segment"] = summary["revenue"].apply(_tier)
    return summary


# ── Profit analytics ──────────────────────────────────────────────────────────


def profit_by_product(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return per-product profit analysis including a low-profit flag.

    A product is flagged as low-profit when its profit_margin is below
    ``LOW_PROFIT_MARGIN_THRESHOLD`` (10 %).  Negative margins are also
    flagged (they satisfy the < 10 % condition).

    Returns
    -------
    pd.DataFrame with columns:
        product, category, revenue, cost, profit, profit_margin, low_profit_flag
        Sorted by profit_margin ascending (worst margins first).
    """
    if df.empty:
        return pd.DataFrame(
            columns=["product", "category", "revenue", "cost", "profit",
                     "profit_margin", "low_profit_flag"]
        )

    df = _add_derived(df.copy())
    agg = (
        df.groupby(["product", "category"], sort=False)
        .agg(
            revenue=("revenue", "sum"),
            cost=("cost", "sum"),
            profit=("profit", "sum"),
        )
        .reset_index()
    )
    agg["profit_margin"] = safe_divide(agg["profit"], agg["revenue"])
    agg["low_profit_flag"] = agg["profit_margin"] < LOW_PROFIT_MARGIN_THRESHOLD
    return agg.sort_values("profit_margin").reset_index(drop=True)


def profit_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return per-category profit analysis including a low-profit flag.

    Returns
    -------
    pd.DataFrame with columns:
        category, revenue, cost, profit, profit_margin, low_profit_flag
        Sorted by profit_margin ascending.
    """
    if df.empty:
        return pd.DataFrame(
            columns=["category", "revenue", "cost", "profit",
                     "profit_margin", "low_profit_flag"]
        )

    df = _add_derived(df.copy())
    agg = (
        df.groupby("category", sort=False)
        .agg(
            revenue=("revenue", "sum"),
            cost=("cost", "sum"),
            profit=("profit", "sum"),
        )
        .reset_index()
    )
    agg["profit_margin"] = safe_divide(agg["profit"], agg["revenue"])
    agg["low_profit_flag"] = agg["profit_margin"] < LOW_PROFIT_MARGIN_THRESHOLD
    return agg.sort_values("profit_margin").reset_index(drop=True)
