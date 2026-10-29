"""
Page 1 — Overview
Business dashboard: KPI cards and revenue/profit trend chart.
"""

import streamlit as st
import plotly.express as px
import pandas as pd
from src.database import init_db, get_transactions
from src.analytics import compute_kpis, sales_by_period

st.set_page_config(page_title="Overview · Smart Analytics", page_icon="📈", layout="wide")
init_db()


def _get_filters():
    start = st.session_state.get("filter_start_date")
    end = st.session_state.get("filter_end_date")
    region = st.session_state.get("filter_region", "All")
    category = st.session_state.get("filter_category", "All")
    return (
        str(start) if start else None,
        str(end) if end else None,
        None if region == "All" else region,
        None if category == "All" else category,
    )


@st.cache_data(ttl=60)
def load_data(start, end, region, category):
    return get_transactions(start_date=start, end_date=end, region=region, category=category)


st.title("📈 Business Overview")
st.caption("Key performance indicators for the selected date range and filters.")

start, end, region, category = _get_filters()
df = load_data(start, end, region, category)

if df.empty:
    st.info(
        "No data loaded yet. Go to **Data Management** to upload a file or load the sample dataset.",
        icon="ℹ️",
    )
    st.stop()

kpis = compute_kpis(df)

# ── KPI cards ──────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Revenue", f"${kpis['total_revenue']:,.0f}")
c2.metric("Total Profit", f"${kpis['total_profit']:,.0f}")
c3.metric("Total Orders", f"{kpis['total_orders']:,}")
c4.metric("Avg Order Value", f"${kpis['avg_order_value']:,.0f}")
c5.metric("Profit Margin", f"{kpis['profit_margin_pct']:.1f}%")

st.divider()

# ── Revenue & Profit trend ─────────────────────────────────────────────────────
st.subheader("Revenue & Profit Trend")
period_col, _ = st.columns([2, 4])
with period_col:
    period = st.selectbox("Group by", ["Month", "Year"], key="overview_period")

trend = sales_by_period(df, period=period.lower())
if trend.empty:
    st.info("Not enough data for trend chart.")
else:
    fig = px.line(
        trend,
        x="period_label",
        y=["revenue", "profit"],
        markers=True,
        labels={"period_label": period, "value": "Amount ($)", "variable": "Metric"},
        color_discrete_map={"revenue": "#3b82d4", "profit": "#7c5cd8"},
    )
    fig.update_layout(
        legend_title_text="",
        xaxis_title=period,
        yaxis_title="Amount ($)",
        hovermode="x unified",
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Orders per period ──────────────────────────────────────────────────────────
st.subheader("Orders per Period")
fig2 = px.bar(
    trend,
    x="period_label",
    y="orders",
    labels={"period_label": period, "orders": "Number of Orders"},
    color_discrete_sequence=["#3b82d4"],
)
fig2.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="#ffffff")
st.plotly_chart(fig2, use_container_width=True)

st.caption(f"Showing {kpis['total_line_items']:,} line items across {kpis['total_orders']:,} orders.")
