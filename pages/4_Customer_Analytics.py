"""
Page 4 — Customer Analytics
Unique customers, top customers by revenue, trends, and segmentation.
"""

import streamlit as st
import plotly.express as px
from src.database import init_db, get_transactions
from src.analytics import customer_summary, segment_customers, sales_by_period

st.set_page_config(page_title="Customer Analytics · Smart Analytics", page_icon="👥", layout="wide")
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


st.title("👥 Customer Analytics")
st.caption("Customer revenue, purchase trends, and segmentation.")

start, end, region, category = _get_filters()
df = load_data(start, end, region, category)

if df.empty:
    st.info("No data available. Go to **Data Management** to load data.", icon="ℹ️")
    st.stop()

# ── Summary KPIs ───────────────────────────────────────────────────────────────
cust_df = customer_summary(df)
total_customers = len(cust_df)
top1_revenue = float(cust_df.iloc[0]["revenue"]) if not cust_df.empty else 0.0
total_revenue = float(cust_df["revenue"].sum()) if not cust_df.empty else 0.0
top1_pct = (top1_revenue / total_revenue * 100) if total_revenue > 0 else 0.0

k1, k2, k3 = st.columns(3)
k1.metric("Unique Customers", f"{total_customers:,}")
k2.metric("Top Customer Revenue", f"${top1_revenue:,.0f}")
k3.metric("Top Customer Share", f"{top1_pct:.1f}%")

st.divider()

# ── Top customers table ────────────────────────────────────────────────────────
st.subheader("Top Customers by Revenue")
n_top = st.slider("Show top N customers", min_value=5, max_value=50, value=15, step=5)
top_cust = cust_df.head(n_top).copy()
top_cust["avg_order_value"] = top_cust["avg_order_value"].round(2)
top_cust["revenue"] = top_cust["revenue"].round(2)
top_cust["profit"] = top_cust["profit"].round(2)

st.dataframe(
    top_cust.rename(columns={
        "customer_id": "Customer ID",
        "customer_name": "Name",
        "revenue": "Revenue ($)",
        "profit": "Profit ($)",
        "orders": "Orders",
        "line_items": "Line Items",
        "avg_order_value": "AOV ($)",
    }),
    use_container_width=True,
)

# Revenue bar chart — top N customers
fig_cust = px.bar(
    top_cust,
    x="customer_name",
    y="revenue",
    color_discrete_sequence=["#3b82d4"],
    labels={"customer_name": "Customer", "revenue": "Revenue ($)"},
)
fig_cust.update_layout(
    xaxis_tickangle=-35,
    plot_bgcolor="#ffffff",
    paper_bgcolor="#ffffff",
)
st.plotly_chart(fig_cust, use_container_width=True)

st.divider()

# ── Customer segmentation ──────────────────────────────────────────────────────
st.subheader("Customer Segmentation")
st.caption(
    "Customers are segmented by total revenue: "
    "**High Value** = top 20%, **Mid Value** = 50th-80th percentile, **Low Value** = bottom 50%."
)
seg_df = segment_customers(df)

col_pie, col_tbl = st.columns([1, 2])
with col_pie:
    seg_counts = seg_df["segment"].value_counts().reset_index()
    seg_counts.columns = ["Segment", "Count"]
    fig_seg = px.pie(
        seg_counts,
        names="Segment",
        values="Count",
        hole=0.4,
        color="Segment",
        color_discrete_map={
            "High Value": "#3b82d4",
            "Mid Value": "#7c5cd8",
            "Low Value": "#aab4c4",
        },
    )
    fig_seg.update_layout(paper_bgcolor="#ffffff")
    st.plotly_chart(fig_seg, use_container_width=True)

with col_tbl:
    st.dataframe(
        seg_df[["customer_name", "revenue", "orders", "segment"]].rename(columns={
            "customer_name": "Customer",
            "revenue": "Revenue ($)",
            "orders": "Orders",
            "segment": "Segment",
        }),
        use_container_width=True,
    )

st.divider()

# ── Purchase trend ─────────────────────────────────────────────────────────────
st.subheader("Customer Purchase Trend (Orders per Period)")
trend = sales_by_period(df, period="month")
fig_trend = px.line(
    trend,
    x="period_label",
    y="orders",
    markers=True,
    labels={"period_label": "Month", "orders": "Orders"},
    color_discrete_sequence=["#3b82d4"],
)
fig_trend.update_layout(
    plot_bgcolor="#ffffff",
    paper_bgcolor="#ffffff",
    hovermode="x unified",
)
st.plotly_chart(fig_trend, use_container_width=True)
