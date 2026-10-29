"""
Page 5 — Profit Analysis
Margin by product and category, low-profit detection, revenue vs cost breakdown.
"""

import streamlit as st
import plotly.express as px
from src.database import init_db, get_transactions
from src.analytics import profit_by_product, profit_by_category, compute_kpis

st.set_page_config(page_title="Profit Analysis · Smart Analytics", page_icon="📉", layout="wide")
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


st.title("📉 Profit Analysis")
st.caption("Profit margin breakdown, low-profit detection, and revenue vs cost comparison.")

start, end, region, category = _get_filters()
df = load_data(start, end, region, category)

if df.empty:
    st.info("No data available. Go to **Data Management** to load data.", icon="ℹ️")
    st.stop()

kpis = compute_kpis(df)

# ── KPI summary ────────────────────────────────────────────────────────────────
k1, k2, k3 = st.columns(3)
k1.metric("Total Revenue", f"${kpis['total_revenue']:,.0f}")
k2.metric("Total Profit", f"${kpis['total_profit']:,.0f}")
k3.metric("Overall Margin", f"{kpis['profit_margin_pct']:.1f}%")

st.divider()

# ── Margin by category ─────────────────────────────────────────────────────────
st.subheader("Profit Margin by Category")
cat_df = profit_by_category(df)
cat_df["margin_%"] = (cat_df["profit_margin"] * 100).round(1)
cat_df["flag"] = cat_df["low_profit_flag"].map({True: "Low Profit", False: "Healthy"})

fig_cat = px.bar(
    cat_df,
    x="category",
    y="margin_%",
    color="flag",
    color_discrete_map={"Low Profit": "#e74c3c", "Healthy": "#3b82d4"},
    labels={"category": "Category", "margin_%": "Profit Margin (%)"},
)
fig_cat.add_hline(y=10, line_dash="dash", line_color="#aab4c4",
                  annotation_text="10% threshold", annotation_position="top right")
fig_cat.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", legend_title_text="")
st.plotly_chart(fig_cat, use_container_width=True)

# ── Revenue vs Cost vs Profit by category ─────────────────────────────────────
st.subheader("Revenue vs Cost vs Profit by Category")
fig_grouped = px.bar(
    cat_df,
    x="category",
    y=["revenue", "cost", "profit"],
    barmode="group",
    labels={"value": "Amount ($)", "variable": "Metric", "category": "Category"},
    color_discrete_map={"revenue": "#3b82d4", "cost": "#e74c3c", "profit": "#7c5cd8"},
)
fig_grouped.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", legend_title_text="")
st.plotly_chart(fig_grouped, use_container_width=True)

st.divider()

# ── Margin by product ──────────────────────────────────────────────────────────
st.subheader("Profit Margin by Product")
prod_df = profit_by_product(df)
prod_df["margin_%"] = (prod_df["profit_margin"] * 100).round(1)
prod_df["flag"] = prod_df["low_profit_flag"].map({True: "Low / Negative", False: "Healthy"})

fig_prod = px.bar(
    prod_df.head(30),    # cap to 30 for readability
    x="margin_%",
    y="product",
    orientation="h",
    color="flag",
    color_discrete_map={"Low / Negative": "#e74c3c", "Healthy": "#3b82d4"},
    labels={"margin_%": "Profit Margin (%)", "product": "Product"},
)
fig_prod.add_vline(x=10, line_dash="dash", line_color="#aab4c4",
                   annotation_text="10%", annotation_position="top right")
fig_prod.update_layout(
    yaxis={"categoryorder": "total ascending"},
    plot_bgcolor="#ffffff",
    paper_bgcolor="#ffffff",
    legend_title_text="",
)
st.plotly_chart(fig_prod, use_container_width=True)

st.divider()

# ── Low-profit product table ───────────────────────────────────────────────────
st.subheader("Low-Profit and Loss-Making Products")
low_df = prod_df[prod_df["low_profit_flag"] == True].copy()
if low_df.empty:
    st.success("No low-profit or loss-making products detected.", icon="✅")
else:
    st.warning(f"{len(low_df)} product(s) are below the 10% margin threshold.", icon="⚠️")
    st.dataframe(
        low_df[["product", "category", "revenue", "cost", "profit", "margin_%"]].rename(columns={
            "product": "Product",
            "category": "Category",
            "revenue": "Revenue ($)",
            "cost": "Cost ($)",
            "profit": "Profit ($)",
            "margin_%": "Margin %",
        }),
        use_container_width=True,
    )
