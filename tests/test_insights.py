"""
tests/test_insights.py
-----------------------
Unit tests for src/insights.py.

Coverage
--------
detect_revenue_decline
  - returns empty list when fewer than 2 months of data
  - returns empty list when there is no decline
  - warning when decline is between 20% and 40%
  - critical when decline exceeds 40%
  - message cites actual month labels and dollar values

detect_negative_profit_products
  - returns empty list when all products are profitable
  - returns critical insight for each loss-making product
  - message contains product name and loss amount

detect_low_margin_categories
  - returns empty list when all categories are above threshold
  - returns warning for category below 5% margin
  - message contains category name and actual margin %

detect_customer_concentration
  - returns empty list when top-3 < 60% of revenue
  - returns warning when top-3 >= 60% of revenue
  - metric is the concentration ratio (0.0–1.0)

detect_top_region_growth
  - returns empty list when fewer than 2 periods
  - returns info insight for region growing > 10%
  - returns empty list when no region grew > 10%

generate_insights
  - returns empty list for empty DataFrame
  - sorts by severity: critical before warning before info
  - every insight has the required schema keys
  - no fabricated metrics — all values come from the DataFrame
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.insights import (
    CUSTOMER_CONCENTRATION_THRESHOLD,
    LOW_MARGIN_CATEGORY_THRESHOLD,
    REVENUE_DECLINE_THRESHOLD,
    detect_customer_concentration,
    detect_low_margin_categories,
    detect_negative_profit_products,
    detect_revenue_decline,
    detect_top_region_growth,
    generate_insights,
)

# ── Required insight schema keys ──────────────────────────────────────────────
REQUIRED_KEYS = {"severity", "type", "message", "recommendation", "metric"}


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _make_df(rows: list) -> pd.DataFrame:
    """Build a minimal transactions DataFrame from a list of dicts."""
    defaults = {
        "transaction_id": "TXN-X",
        "order_id": "ORD-X",
        "transaction_date": "2024-01-01",
        "customer_id": "C01",
        "customer_name": "Alice",
        "product": "Widget",
        "category": "Widgets",
        "region": "North",
        "quantity": 1,
        "unit_price": 100.0,
        "unit_cost": 50.0,
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
def decline_df() -> pd.DataFrame:
    """January revenue = 1000, February revenue = 500 → decline = 50 % → critical (> 40 %)."""
    return _make_df([
        {"transaction_date": "2024-01-10", "quantity": 10, "unit_price": 100.0, "unit_cost": 40.0,
         "order_id": "O1", "customer_id": "C01"},
        {"transaction_date": "2024-02-10", "quantity": 5, "unit_price": 100.0, "unit_cost": 40.0,
         "order_id": "O2", "customer_id": "C01"},
    ])


@pytest.fixture()
def no_decline_df() -> pd.DataFrame:
    """January revenue = 600, February revenue = 1000 → growth."""
    return _make_df([
        {"transaction_date": "2024-01-10", "quantity": 6, "unit_price": 100.0, "unit_cost": 40.0,
         "order_id": "O1", "customer_id": "C01"},
        {"transaction_date": "2024-02-10", "quantity": 10, "unit_price": 100.0, "unit_cost": 40.0,
         "order_id": "O2", "customer_id": "C01"},
    ])


@pytest.fixture()
def concentration_df() -> pd.DataFrame:
    """
    3 customers. Top customer has 70% of revenue → concentration warning.
    """
    return _make_df([
        {"customer_id": "C01", "order_id": "O1", "quantity": 7, "unit_price": 100.0, "unit_cost": 50.0},
        {"customer_id": "C02", "order_id": "O2", "quantity": 2, "unit_price": 100.0, "unit_cost": 50.0},
        {"customer_id": "C03", "order_id": "O3", "quantity": 1, "unit_price": 100.0, "unit_cost": 50.0},
    ])


# ══════════════════════════════════════════════════════════════════════════════
# detect_revenue_decline
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectRevenueDecline:
    def test_empty_list_when_only_one_month(self) -> None:
        df = _make_df([{"transaction_date": "2024-01-10"}])
        assert detect_revenue_decline(df) == []

    def test_empty_list_when_no_decline(self, no_decline_df: pd.DataFrame) -> None:
        assert detect_revenue_decline(no_decline_df) == []

    def test_warning_when_decline_between_20_and_40_pct(self) -> None:
        """January = 1000, February = 750 → decline = 25 % → warning."""
        df = _make_df([
            {"transaction_date": "2024-01-10", "quantity": 10, "unit_price": 100.0, "unit_cost": 40.0,
             "order_id": "O1", "customer_id": "C01"},
            {"transaction_date": "2024-02-10", "quantity": 7, "unit_price": 100.0 + 7.14, "unit_cost": 40.0,
             "order_id": "O2", "customer_id": "C01"},
        ])
        # Manually build a 25 % decline
        df2 = _make_df([
            {"transaction_date": "2024-01-10", "quantity": 100, "unit_price": 10.0, "unit_cost": 4.0,
             "order_id": "O1", "customer_id": "C01"},
            {"transaction_date": "2024-02-10", "quantity": 75, "unit_price": 10.0, "unit_cost": 4.0,
             "order_id": "O2", "customer_id": "C01"},
        ])
        result = detect_revenue_decline(df2)
        assert len(result) == 1
        assert result[0]["severity"] == "warning"
        assert result[0]["type"] == "revenue_decline"

    def test_critical_when_decline_exceeds_40_pct(self, decline_df: pd.DataFrame) -> None:
        """January = 1000, February = 500 → decline = 50 % → critical (threshold is > 40 %)."""
        result = detect_revenue_decline(decline_df)
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_metric_is_decline_fraction(self, decline_df: pd.DataFrame) -> None:
        result = detect_revenue_decline(decline_df)
        assert result[0]["metric"] == pytest.approx(0.50, abs=1e-4)

    def test_message_cites_period_labels(self, decline_df: pd.DataFrame) -> None:
        result = detect_revenue_decline(decline_df)
        msg = result[0]["message"]
        assert "2024-01" in msg
        assert "2024-02" in msg

    def test_insight_has_all_required_keys(self, decline_df: pd.DataFrame) -> None:
        result = detect_revenue_decline(decline_df)
        assert set(result[0].keys()) == REQUIRED_KEYS


# ══════════════════════════════════════════════════════════════════════════════
# detect_negative_profit_products
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectNegativeProfitProducts:
    def test_empty_list_when_all_profitable(self) -> None:
        df = _make_df([{"product": "Widget", "unit_price": 100.0, "unit_cost": 50.0}])
        assert detect_negative_profit_products(df) == []

    def test_detects_loss_making_product(self) -> None:
        df = _make_df([
            {"product": "Loss Leader", "unit_price": 10.0, "unit_cost": 20.0, "quantity": 5,
             "order_id": "O1"},
        ])
        result = detect_negative_profit_products(df)
        assert len(result) == 1
        assert result[0]["severity"] == "critical"
        assert "Loss Leader" in result[0]["message"]

    def test_metric_is_negative_profit(self) -> None:
        df = _make_df([
            {"product": "Bad Product", "unit_price": 5.0, "unit_cost": 10.0, "quantity": 2,
             "order_id": "O1"},
        ])
        result = detect_negative_profit_products(df)
        # profit = 2*(5-10) = -10
        assert result[0]["metric"] == pytest.approx(-10.0)

    def test_one_insight_per_loss_product(self) -> None:
        df = _make_df([
            {"product": "Bad A", "unit_price": 5.0, "unit_cost": 10.0, "order_id": "O1"},
            {"product": "Bad B", "unit_price": 3.0, "unit_cost": 8.0, "order_id": "O2"},
            {"product": "Good",  "unit_price": 50.0, "unit_cost": 20.0, "order_id": "O3"},
        ])
        result = detect_negative_profit_products(df)
        assert len(result) == 2
        products_mentioned = [r["message"] for r in result]
        assert any("Bad A" in m for m in products_mentioned)
        assert any("Bad B" in m for m in products_mentioned)

    def test_empty_df_returns_empty(self) -> None:
        assert detect_negative_profit_products(pd.DataFrame()) == []


# ══════════════════════════════════════════════════════════════════════════════
# detect_low_margin_categories
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectLowMarginCategories:
    def test_empty_list_when_all_above_threshold(self) -> None:
        df = _make_df([{"category": "Widgets", "unit_price": 100.0, "unit_cost": 50.0}])
        assert detect_low_margin_categories(df) == []

    def test_detects_low_margin_category(self) -> None:
        """Category with 3 % margin should trigger a warning."""
        df = _make_df([
            {"category": "Thin Margin", "unit_price": 100.0, "unit_cost": 97.0, "order_id": "O1"},
        ])
        result = detect_low_margin_categories(df)
        assert len(result) == 1
        assert result[0]["severity"] == "warning"
        assert "Thin Margin" in result[0]["message"]

    def test_metric_is_margin_ratio(self) -> None:
        df = _make_df([
            {"category": "Low", "unit_price": 100.0, "unit_cost": 97.0, "order_id": "O1"},
        ])
        result = detect_low_margin_categories(df)
        # margin = (100-97)/100 = 0.03
        assert result[0]["metric"] == pytest.approx(0.03)

    def test_threshold_constant(self) -> None:
        assert LOW_MARGIN_CATEGORY_THRESHOLD == pytest.approx(0.05)

    def test_empty_df_returns_empty(self) -> None:
        assert detect_low_margin_categories(pd.DataFrame()) == []


# ══════════════════════════════════════════════════════════════════════════════
# detect_customer_concentration
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectCustomerConcentration:
    def test_warning_when_top3_exceed_threshold(
        self, concentration_df: pd.DataFrame
    ) -> None:
        result = detect_customer_concentration(concentration_df)
        assert len(result) == 1
        assert result[0]["severity"] == "warning"
        assert result[0]["type"] == "customer_concentration"

    def test_metric_is_concentration_ratio(
        self, concentration_df: pd.DataFrame
    ) -> None:
        result = detect_customer_concentration(concentration_df)
        # Top 3 = all 3 customers = 100 % concentration
        assert result[0]["metric"] == pytest.approx(1.0)

    def test_empty_list_when_below_threshold(self) -> None:
        """10 customers with equal revenue → each has 10 %, top-3 = 30 %."""
        rows = [
            {"customer_id": f"C{i:02d}", "order_id": f"O{i:02d}",
             "unit_price": 100.0, "unit_cost": 50.0}
            for i in range(10)
        ]
        df = _make_df(rows)
        result = detect_customer_concentration(df)
        assert result == []

    def test_threshold_constant(self) -> None:
        assert CUSTOMER_CONCENTRATION_THRESHOLD == pytest.approx(0.60)

    def test_empty_df_returns_empty(self) -> None:
        assert detect_customer_concentration(pd.DataFrame()) == []


# ══════════════════════════════════════════════════════════════════════════════
# detect_top_region_growth
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectTopRegionGrowth:
    def test_empty_list_when_only_one_month(self) -> None:
        df = _make_df([{"transaction_date": "2024-01-10", "region": "North"}])
        assert detect_top_region_growth(df) == []

    def test_detects_growing_region(self) -> None:
        """North doubles in revenue Jan→Feb → growth = 100 % → info insight."""
        df = _make_df([
            {"transaction_date": "2024-01-10", "region": "North", "quantity": 5,
             "unit_price": 100.0, "unit_cost": 40.0, "order_id": "O1"},
            {"transaction_date": "2024-02-10", "region": "North", "quantity": 10,
             "unit_price": 100.0, "unit_cost": 40.0, "order_id": "O2"},
        ])
        result = detect_top_region_growth(df)
        assert len(result) == 1
        assert result[0]["severity"] == "info"
        assert result[0]["type"] == "region_growth"
        assert "North" in result[0]["message"]

    def test_empty_list_when_no_region_grew(self) -> None:
        """Revenue stays flat → no growth insight."""
        df = _make_df([
            {"transaction_date": "2024-01-10", "region": "North", "quantity": 10,
             "unit_price": 100.0, "unit_cost": 40.0, "order_id": "O1"},
            {"transaction_date": "2024-02-10", "region": "North", "quantity": 10,
             "unit_price": 100.0, "unit_cost": 40.0, "order_id": "O2"},
        ])
        result = detect_top_region_growth(df)
        assert result == []

    def test_metric_is_growth_fraction(self) -> None:
        df = _make_df([
            {"transaction_date": "2024-01-10", "region": "South", "quantity": 10,
             "unit_price": 100.0, "unit_cost": 40.0, "order_id": "O1"},
            {"transaction_date": "2024-02-10", "region": "South", "quantity": 15,
             "unit_price": 100.0, "unit_cost": 40.0, "order_id": "O2"},
        ])
        result = detect_top_region_growth(df)
        # growth = (1500-1000)/1000 = 0.50
        assert len(result) == 1
        assert result[0]["metric"] == pytest.approx(0.50)

    def test_empty_df_returns_empty(self) -> None:
        assert detect_top_region_growth(pd.DataFrame()) == []


# ══════════════════════════════════════════════════════════════════════════════
# generate_insights (composed pipeline)
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerateInsights:
    def test_empty_list_for_empty_df(self) -> None:
        assert generate_insights(pd.DataFrame()) == []

    def test_all_insights_have_required_keys(self) -> None:
        """Run the pipeline on a DataFrame that triggers multiple detectors."""
        df = _make_df([
            # Loss-making product → critical
            {"product": "Bad", "unit_price": 5.0, "unit_cost": 10.0,
             "category": "Low Cat", "order_id": "O1", "customer_id": "C01",
             "transaction_date": "2024-01-10"},
            # Same category in Feb but smaller → revenue decline possible
            {"product": "Bad", "unit_price": 5.0, "unit_cost": 10.0,
             "category": "Low Cat", "order_id": "O2", "customer_id": "C01",
             "transaction_date": "2024-02-10"},
        ])
        results = generate_insights(df)
        for insight in results:
            assert set(insight.keys()) == REQUIRED_KEYS, (
                f"Insight missing keys: {REQUIRED_KEYS - set(insight.keys())}"
            )

    def test_sorted_critical_before_warning_before_info(self) -> None:
        """
        Build a DataFrame that triggers all three severity levels and confirm
        the output ordering is critical → warning → info.
        """
        # Critical: loss-making product
        # Warning: customer concentration (one dominant customer)
        # Info: region growth
        df = _make_df([
            # Jan – loss product, dominant customer, North region
            {"product": "Loss", "unit_price": 5.0, "unit_cost": 10.0,
             "category": "Cat A", "customer_id": "C01", "order_id": "O1",
             "region": "North", "quantity": 10, "transaction_date": "2024-01-10"},
            # Feb – same product, North grows
            {"product": "Loss", "unit_price": 5.0, "unit_cost": 10.0,
             "category": "Cat A", "customer_id": "C01", "order_id": "O2",
             "region": "North", "quantity": 20, "transaction_date": "2024-02-10"},
        ])
        results = generate_insights(df)
        severities = [r["severity"] for r in results]
        order_map = {"critical": 0, "warning": 1, "info": 2}
        ordered = [order_map[s] for s in severities]
        assert ordered == sorted(ordered), (
            f"Insights not sorted by severity: {severities}"
        )

    def test_no_fabricated_metrics(self, decline_df: pd.DataFrame) -> None:
        """
        The metric in a revenue-decline insight must equal the actual computed
        decline fraction — not a hardcoded or guessed value.
        """
        results = generate_insights(decline_df)
        decline_insights = [r for r in results if r["type"] == "revenue_decline"]
        assert len(decline_insights) >= 1
        # Jan=1000, Feb=500 → decline = 50 % (fixture updated to produce > 40 % for critical test)
        assert decline_insights[0]["metric"] == pytest.approx(0.50, abs=1e-4)
