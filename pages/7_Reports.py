"""
Page 7 — Reports
Export filtered data as CSV or PDF with filter summary and KPI snapshot.
"""

import streamlit as st
from src.database import init_db, get_transactions
from src.analytics import compute_kpis
from src.insights import generate_insights
from src.reports import export_csv, build_pdf_report

st.set_page_config(page_title="Reports · Smart Analytics", page_icon="📄", layout="wide")
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


st.title("📄 Reports")
st.caption("Export filtered transaction data and a KPI summary report.")

start, end, region, category = _get_filters()
df = load_data(start, end, region, category)

if df.empty:
    st.info("No data available. Go to **Data Management** to load data.", icon="ℹ️")
    st.stop()

kpis = compute_kpis(df)
insights = generate_insights(df)

# ── Applied filters summary ────────────────────────────────────────────────────
st.subheader("Applied Filters")
filters_dict = {
    "Date from": start or "All",
    "Date to": end or "All",
    "Region": region or "All",
    "Category": category or "All",
}
cols = st.columns(4)
for col, (k, v) in zip(cols, filters_dict.items()):
    col.metric(k, v)

st.divider()

# ── KPI snapshot ───────────────────────────────────────────────────────────────
st.subheader("KPI Snapshot")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Revenue", f"${kpis['total_revenue']:,.0f}")
k2.metric("Total Profit", f"${kpis['total_profit']:,.0f}")
k3.metric("Total Orders", f"{kpis['total_orders']:,}")
k4.metric("Avg Order Value", f"${kpis['avg_order_value']:,.0f}")
k5.metric("Profit Margin", f"{kpis['profit_margin_pct']:.1f}%")

st.divider()

# ── Download buttons ───────────────────────────────────────────────────────────
st.subheader("Export Options")

col_csv, col_pdf = st.columns(2)

# CSV export
with col_csv:
    st.markdown("#### CSV Export")
    st.caption(f"Export {len(df):,} filtered transaction rows as a UTF-8 CSV file.")
    csv_bytes = export_csv(df, filters=filters_dict)
    st.download_button(
        label="Download CSV",
        data=csv_bytes,
        file_name="smart_analytics_export.csv",
        mime="text/csv",
        type="primary",
    )

# PDF export
with col_pdf:
    st.markdown("#### PDF Report")
    st.caption("Download a summary PDF with KPIs and business insights.")
    if st.button("Generate PDF Report", type="primary"):
        with st.spinner("Building PDF..."):
            pdf_bytes, err = build_pdf_report(kpis, insights, filters=filters_dict)
        if err:
            st.error(f"PDF export failed: {err}")
        else:
            st.download_button(
                label="Download PDF",
                data=pdf_bytes,
                file_name="smart_analytics_report.pdf",
                mime="application/pdf",
            )

st.divider()

# ── Data preview ───────────────────────────────────────────────────────────────
st.subheader("Data Preview")
st.caption(f"Showing first 100 of {len(df):,} filtered rows.")
st.dataframe(df.head(100), use_container_width=True)
