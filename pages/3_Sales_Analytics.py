"""
Page 3 — Sales Analytics
Sales by time period, product, category, and region.
"""

import streamlit as st
import plotly.express as px
from src.database import init_db, get_transactions
from src.analytics import (
    sales_by_period,
    sales_by_product,
    sales_by_category,
    sales_by_region,
    top_products,
    bottom_products,
)

st.set_page_config(page_title="Sales Analytics · Smart Analytics", page_icon="💰", layout="wide")
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


st.title("💰 Sales Analytics")
st.caption("Sales performance broken down by time, product, category, and region.")

start, end, region, category = _get_filters()
df = load_data(start, end, region, category)

if df.empty:
    st.info("No data available. Go to **Data Management** to load data.", icon="ℹ️")
    st.stop()

# ── Sales by period ────────────────────────────────────────────────────────────
st.subheader("Sales Over Time")
p_col, _ = st.columns([2, 5])
with p_col:
    period = st.selectbox("Group by", ["Month", "Year"], key="sales_period")

trend = sales_by_period(df, period=period.lower())
fig = px.bar(
    trend,
    x="period_label",
    y="revenue",
    color_discrete_sequence=["#3b82d4"],
    labels={"period_label": period, "revenue": "Revenue ($)"},
)
fig.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

# ── Sales by category and region side by side ──────────────────────────────────
col_cat, col_reg = st.columns(2)

with col_cat:
    st.subheader("Revenue by Category")
    cat_df = sales_by_category(df)
    fig_cat = px.pie(
        cat_df,
        names="category",
        values="revenue",
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    fig_cat.update_traces(textposition="inside", textinfo="percent+label")
    fig_cat.update_layout(showlegend=False, paper_bgcolor="#ffffff")
    st.plotly_chart(fig_cat, use_container_width=True)

with col_reg:
    st.subheader("Revenue by Region")
    reg_df = sales_by_region(df)
    fig_reg = px.bar(
        reg_df,
        x="region",
        y="revenue",
        color="revenue",
        color_continuous_scale="Blues",
        labels={"revenue": "Revenue ($)", "region": "Region"},
    )
    fig_reg.update_layout(
        coloraxis_showscale=False,
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    st.plotly_chart(fig_reg, use_container_width=True)

st.divider()

# ── Top & Bottom products ──────────────────────────────────────────────────────
col_top, col_bot = st.columns(2)

with col_top:
    st.subheader("Top 10 Products by Revenue")
    top_df = top_products(df, n=10)
    fig_top = px.bar(
        top_df,
        x="revenue",
        y="product",
        orientation="h",
        color_discrete_sequence=["#3b82d4"],
        labels={"revenue": "Revenue ($)", "product": "Product"},
    )
    fig_top.update_layout(
        yaxis={"categoryorder": "total ascending"},
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    st.plotly_chart(fig_top, use_container_width=True)

with col_bot:
    st.subheader("Bottom 10 Products by Revenue")
    bot_df = bottom_products(df, n=10)
    fig_bot = px.bar(
        bot_df,
        x="revenue",
        y="product",
        orientation="h",
        color_discrete_sequence=["#7c5cd8"],
        labels={"revenue": "Revenue ($)", "product": "Product"},
    )
    fig_bot.update_layout(
        yaxis={"categoryorder": "total ascending"},
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    st.plotly_chart(fig_bot, use_container_width=True)

st.divider()

# ── Product table ──────────────────────────────────────────────────────────────
st.subheader("Product Sales Table")
prod_df = sales_by_product(df)
prod_df["profit_margin_%"] = (prod_df["profit_margin"] * 100).round(1)
st.dataframe(
    prod_df.drop(columns=["profit_margin"]).rename(
        columns={
            "product": "Product",
            "revenue": "Revenue ($)",
            "profit": "Profit ($)",
            "profit_margin_%": "Margin %",
            "orders": "Orders",
            "line_items": "Line Items",
        }
    ),
    use_container_width=True,
)
