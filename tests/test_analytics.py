"""
tests/test_analytics.py
-----------------------
Unit tests for src/analytics.py.

Coverage
--------
safe_divide
  - scalar division
  - returns default when denominator is zero
  - works with Pandas Series

compute_kpis
  - correct revenue, profit, margin calculations
  - Total Orders uses COUNT(DISTINCT order_id) — NOT row count
  - Total Line Items uses row count
  - AOV uses distinct orders as denominator
  - all zeros when DataFrame is empty

sales_by_period
  - groups by month correctly
  - groups by year correctly
  - orders column uses distinct order_id

sales_by_product / sales_by_category / sales_by_region
  - aggregates revenue and profit correctly
  - profit_margin is computed via safe_divide
  - orders column is distinct order count

top_products / bottom_products
  - returns correct n rows
  - top is sorted descending, bottom ascending by revenue

customer_summary
  - computes per-customer revenue and orders
  - avg_order_value uses distinct orders

segment_customers
  - high/mid/low value tiers are assigned
  - segment column is present

profit_by_product / profit_by_category
  - low_profit_flag is True when margin < 10 %
  - negative margin also flagged
  - sorted by profit_margin ascending
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.analytics import (
    LOW_PROFIT_MARGIN_THRESHOLD,
    bottom_products,
    compute_kpis,
    customer_summary,
    profit_by_category,
    profit_by_product,
    safe_divide,
    sales_by_category,
    sales_by_period,
    sales_by_product,
    sales_by_region,
    segment_customers,
    top_products,
)


# ── Shared fixture ─────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_df() -> pd.DataFrame:
    """
    Six transaction rows across three orders.

    ORD-001  — two products (TXN-001, TXN-002)  — customer Alice, North, Widgets
    ORD-002  — two products (TXN-003, TXN-004)  — customer Alice, North, Gadgets
    ORD-003  — two products (TXN-005, TXN-006)  — customer Bob,   South, Widgets

    Deliberate low-margin product: 'Cheap Widget' has cost == price (0 % margin).
    Deliberate negative-margin product: 'Loss Leader' has cost > price.
    """
    return pd.DataFrame(
        {
            "transaction_id": ["TXN-001", "TXN-002", "TXN-003", "TXN-004", "TXN-005", "TXN-006"],
            "order_id":       ["ORD-001", "ORD-001", "ORD-002", "ORD-002", "ORD-003", "ORD-003"],
            "transaction_date": pd.to_datetime(
                ["2024-01-10", "2024-01-10", "2024-02-15", "2024-02-15", "2024-02-20", "2024-03-05"]
            ),
            "customer_id":    ["C01", "C01", "C01", "C01", "C02", "C02"],
            "customer_name":  ["Alice", "Alice", "Alice", "Alice", "Bob", "Bob"],
            "product":        ["Widget A", "Widget B", "Gadget X", "Cheap Widget", "Widget A", "Loss Leader"],
            "category":       ["Widgets", "Widgets", "Gadgets", "Gadgets", "Widgets", "Widgets"],
            "region":         ["North", "North", "North", "North", "South", "South"],
            "quantity":       [2,        1,        5,        3,        4,       2],
            "unit_price":     [50.0,     80.0,     20.0,     15.0,     50.0,    10.0],
            "unit_cost":      [30.0,     40.0,     10.0,     15.0,     30.0,    15.0],
        }
    )
    # Revenue per row: 100, 80, 100, 45, 200, 20   → total 545
    # Cost    per row:  60, 40,  50, 45, 120, 30   → total 345
    # Profit  per row:  40, 40,  50,  0,  80, -10  → total 200


# ══════════════════════════════════════════════════════════════════════════════
# safe_divide
# ══════════════════════════════════════════════════════════════════════════════


class TestSafeDivide:
    def test_normal_scalar_division(self) -> None:
        assert safe_divide(10.0, 4.0) == 2.5

    def test_zero_denominator_returns_default(self) -> None:
        assert safe_divide(10.0, 0.0) == 0.0

    def test_custom_default(self) -> None:
        assert safe_divide(5.0, 0.0, default=-1.0) == -1.0

    def test_series_division(self) -> None:
        num = pd.Series([10.0, 20.0, 0.0])
        den = pd.Series([2.0, 0.0, 5.0])
        result = safe_divide(num, den)
        assert result.iloc[0] == pytest.approx(5.0)
        assert result.iloc[1] == pytest.approx(0.0)   # zero denominator → default
        assert result.iloc[2] == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════════════
# compute_kpis
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeKpis:
    def test_total_revenue(self, sample_df: pd.DataFrame) -> None:
        kpis = compute_kpis(sample_df)
        assert kpis["total_revenue"] == pytest.approx(545.0)

    def test_total_profit(self, sample_df: pd.DataFrame) -> None:
        kpis = compute_kpis(sample_df)
        assert kpis["total_profit"] == pytest.approx(200.0)

    def test_total_orders_uses_distinct_order_id(self, sample_df: pd.DataFrame) -> None:
        """
        KEY TEST: Total Orders must be 3 (distinct order_ids),
        NOT 6 (total rows).  This confirms COUNT(DISTINCT order_id) semantics.
        """
        kpis = compute_kpis(sample_df)
        assert kpis["total_orders"] == 3
        assert kpis["total_orders"] != len(sample_df), (
            "Total Orders must not equal total rows — multi-product orders exist."
        )

    def test_total_line_items_equals_row_count(self, sample_df: pd.DataFrame) -> None:
        kpis = compute_kpis(sample_df)
        assert kpis["total_line_items"] == len(sample_df)  # 6

    def test_avg_order_value_uses_distinct_orders(self, sample_df: pd.DataFrame) -> None:
        """AOV = 545 / 3 orders ≈ 181.67, NOT 545 / 6 rows."""
        kpis = compute_kpis(sample_df)
        expected_aov = 545.0 / 3
        assert kpis["avg_order_value"] == pytest.approx(expected_aov)

    def test_profit_margin_pct(self, sample_df: pd.DataFrame) -> None:
        kpis = compute_kpis(sample_df)
        expected = (200.0 / 545.0) * 100
        assert kpis["profit_margin_pct"] == pytest.approx(expected, rel=1e-4)

    def test_empty_df_returns_zeros(self) -> None:
        kpis = compute_kpis(pd.DataFrame())
        assert kpis["total_revenue"] == 0.0
        assert kpis["total_orders"] == 0
        assert kpis["avg_order_value"] == 0.0
        assert kpis["profit_margin_pct"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# sales_by_period
# ══════════════════════════════════════════════════════════════════════════════


class TestSalesByPeriod:
    def test_groups_by_month(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_period(sample_df, period="month")
        assert "period_label" in result.columns
        assert len(result) == 3  # Jan, Feb, Mar
        assert result["period_label"].tolist() == ["2024-01", "2024-02", "2024-03"]

    def test_groups_by_year(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_period(sample_df, period="year")
        assert len(result) == 1
        assert result["period_label"].iloc[0] == "2024"

    def test_revenue_sums_correctly_by_month(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_period(sample_df, period="month")
        jan = result.loc[result["period_label"] == "2024-01", "revenue"].iloc[0]
        assert jan == pytest.approx(180.0)  # TXN-001 (100) + TXN-002 (80)

    def test_orders_are_distinct_per_period(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_period(sample_df, period="month")
        jan = result.loc[result["period_label"] == "2024-01", "orders"].iloc[0]
        assert jan == 1   # ORD-001 only — both line items are the same order

    def test_empty_df_returns_empty(self) -> None:
        result = sales_by_period(pd.DataFrame())
        assert result.empty


# ══════════════════════════════════════════════════════════════════════════════
# sales_by_product
# ══════════════════════════════════════════════════════════════════════════════


class TestSalesByProduct:
    def test_widget_a_revenue(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_product(sample_df)
        wa = result.loc[result["product"] == "Widget A", "revenue"].iloc[0]
        assert wa == pytest.approx(300.0)  # 2*50 + 4*50

    def test_profit_margin_computed(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_product(sample_df)
        assert "profit_margin" in result.columns
        assert result["profit_margin"].notna().all()

    def test_cheap_widget_zero_margin(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_product(sample_df)
        cw = result.loc[result["product"] == "Cheap Widget", "profit_margin"].iloc[0]
        assert cw == pytest.approx(0.0)

    def test_sorted_by_revenue_descending(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_product(sample_df)
        revenues = result["revenue"].tolist()
        assert revenues == sorted(revenues, reverse=True)

    def test_orders_are_distinct(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_product(sample_df)
        # Widget A appears in ORD-001 (Alice) and ORD-003 (Bob) → 2 distinct orders
        wa = result.loc[result["product"] == "Widget A", "orders"].iloc[0]
        assert wa == 2


# ══════════════════════════════════════════════════════════════════════════════
# sales_by_category
# ══════════════════════════════════════════════════════════════════════════════


class TestSalesByCategory:
    def test_widgets_revenue(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_category(sample_df)
        widgets = result.loc[result["category"] == "Widgets", "revenue"].iloc[0]
        # Widget A: 100+200=300, Widget B: 80, Loss Leader: 20 → 400
        assert widgets == pytest.approx(400.0)

    def test_category_count(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_category(sample_df)
        assert len(result) == 2  # Widgets, Gadgets


# ══════════════════════════════════════════════════════════════════════════════
# sales_by_region
# ══════════════════════════════════════════════════════════════════════════════


class TestSalesByRegion:
    def test_north_revenue(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_region(sample_df)
        north = result.loc[result["region"] == "North", "revenue"].iloc[0]
        # TXN-001(100)+TXN-002(80)+TXN-003(100)+TXN-004(45) = 325
        assert north == pytest.approx(325.0)

    def test_region_count(self, sample_df: pd.DataFrame) -> None:
        result = sales_by_region(sample_df)
        assert len(result) == 2  # North, South


# ══════════════════════════════════════════════════════════════════════════════
# top_products / bottom_products
# ══════════════════════════════════════════════════════════════════════════════


class TestTopBottomProducts:
    def test_top_products_default_n(self, sample_df: pd.DataFrame) -> None:
        result = top_products(sample_df)
        # Only 5 distinct products exist, so all are returned
        assert len(result) <= 10

    def test_top_products_n_2(self, sample_df: pd.DataFrame) -> None:
        result = top_products(sample_df, n=2)
        assert len(result) == 2
        # Widget A (300) should be top
        assert result.iloc[0]["product"] == "Widget A"

    def test_bottom_products_sorted_ascending(self, sample_df: pd.DataFrame) -> None:
        result = bottom_products(sample_df, n=2)
        assert len(result) == 2
        revenues = result["revenue"].tolist()
        assert revenues == sorted(revenues)

    def test_bottom_product_is_lowest_revenue(self, sample_df: pd.DataFrame) -> None:
        result = bottom_products(sample_df, n=1)
        # Loss Leader revenue = 2*10 = 20
        assert result.iloc[0]["revenue"] == pytest.approx(20.0)


# ══════════════════════════════════════════════════════════════════════════════
# customer_summary
# ══════════════════════════════════════════════════════════════════════════════


class TestCustomerSummary:
    def test_two_customers(self, sample_df: pd.DataFrame) -> None:
        result = customer_summary(sample_df)
        assert len(result) == 2

    def test_alice_revenue(self, sample_df: pd.DataFrame) -> None:
        result = customer_summary(sample_df)
        alice = result.loc[result["customer_name"] == "Alice", "revenue"].iloc[0]
        # Alice: TXN-001(100)+TXN-002(80)+TXN-003(100)+TXN-004(45) = 325
        assert alice == pytest.approx(325.0)

    def test_alice_orders_are_distinct(self, sample_df: pd.DataFrame) -> None:
        result = customer_summary(sample_df)
        alice = result.loc[result["customer_name"] == "Alice", "orders"].iloc[0]
        assert alice == 2  # ORD-001 and ORD-002

    def test_aov_uses_distinct_orders(self, sample_df: pd.DataFrame) -> None:
        result = customer_summary(sample_df)
        alice = result.loc[result["customer_name"] == "Alice"]
        expected_aov = 325.0 / 2
        assert alice["avg_order_value"].iloc[0] == pytest.approx(expected_aov)

    def test_sorted_by_revenue_descending(self, sample_df: pd.DataFrame) -> None:
        result = customer_summary(sample_df)
        revenues = result["revenue"].tolist()
        assert revenues == sorted(revenues, reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# segment_customers
# ══════════════════════════════════════════════════════════════════════════════


class TestSegmentCustomers:
    def test_segment_column_present(self, sample_df: pd.DataFrame) -> None:
        result = segment_customers(sample_df)
        assert "segment" in result.columns

    def test_valid_segment_values(self, sample_df: pd.DataFrame) -> None:
        result = segment_customers(sample_df)
        valid = {"High Value", "Mid Value", "Low Value"}
        assert set(result["segment"].unique()).issubset(valid)

    def test_highest_revenue_customer_is_high_value(self, sample_df: pd.DataFrame) -> None:
        result = segment_customers(sample_df)
        top_customer = result.iloc[0]
        assert top_customer["segment"] == "High Value"

    def test_empty_df(self) -> None:
        result = segment_customers(pd.DataFrame())
        assert result.empty


# ══════════════════════════════════════════════════════════════════════════════
# profit_by_product
# ══════════════════════════════════════════════════════════════════════════════


class TestProfitByProduct:
    def test_low_profit_flag_set_for_zero_margin(self, sample_df: pd.DataFrame) -> None:
        result = profit_by_product(sample_df)
        cw = result.loc[result["product"] == "Cheap Widget"]
        assert bool(cw["low_profit_flag"].iloc[0]) is True

    def test_low_profit_flag_set_for_negative_margin(self, sample_df: pd.DataFrame) -> None:
        result = profit_by_product(sample_df)
        ll = result.loc[result["product"] == "Loss Leader"]
        assert bool(ll["low_profit_flag"].iloc[0]) is True

    def test_high_margin_product_not_flagged(self, sample_df: pd.DataFrame) -> None:
        result = profit_by_product(sample_df)
        wa = result.loc[result["product"] == "Widget A"]
        # Widget A profit_margin = (300-240)/300 = 20 % → above 10 % threshold
        assert bool(wa["low_profit_flag"].iloc[0]) is False

    def test_sorted_by_profit_margin_ascending(self, sample_df: pd.DataFrame) -> None:
        result = profit_by_product(sample_df)
        margins = result["profit_margin"].tolist()
        assert margins == sorted(margins)

    def test_low_profit_threshold_constant(self) -> None:
        assert LOW_PROFIT_MARGIN_THRESHOLD == pytest.approx(0.10)


# ══════════════════════════════════════════════════════════════════════════════
# profit_by_category
# ══════════════════════════════════════════════════════════════════════════════


class TestProfitByCategory:
    def test_returns_two_categories(self, sample_df: pd.DataFrame) -> None:
        result = profit_by_category(sample_df)
        assert len(result) == 2

    def test_gadgets_low_profit_flag(self, sample_df: pd.DataFrame) -> None:
        """
        Gadgets: revenue = 100+45 = 145, cost = 50+45 = 95, profit = 50
        margin = 50/145 ≈ 34.5 % → NOT flagged
        """
        result = profit_by_category(sample_df)
        gadgets = result.loc[result["category"] == "Gadgets"]
        # margin > 10 %, so low_profit_flag should be False
        assert bool(gadgets["low_profit_flag"].iloc[0]) is False

    def test_sorted_by_profit_margin_ascending(self, sample_df: pd.DataFrame) -> None:
        result = profit_by_category(sample_df)
        margins = result["profit_margin"].tolist()
        assert margins == sorted(margins)
