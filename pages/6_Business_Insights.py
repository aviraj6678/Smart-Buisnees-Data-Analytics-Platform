"""
Page 6 — Business Insights
Rule-based findings with severity colour coding and recommendations.
"""

import streamlit as st
from src.database import init_db, get_transactions
from src.insights import generate_insights

st.set_page_config(page_title="Business Insights · Smart Analytics", page_icon="💡", layout="wide")
init_db()

# Severity colour map (background, text)
_SEVERITY_STYLE = {
    "critical": ("#fdecea", "#c0392b", "🔴"),
    "warning":  ("#fff8e1", "#b7770d", "🟡"),
    "info":     ("#e8f4fd", "#1a6ea8", "🔵"),
}


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


st.title("💡 Business Insights")
st.caption(
    "Rule-based insights derived from your data. "
    "Every finding cites actual computed metrics — no fabricated numbers."
)

start, end, region, category = _get_filters()
df = load_data(start, end, region, category)

if df.empty:
    st.info("No data available. Go to **Data Management** to load data.", icon="ℹ️")
    st.stop()

insights = generate_insights(df)

# ── Summary counts ─────────────────────────────────────────────────────────────
n_critical = sum(1 for i in insights if i["severity"] == "critical")
n_warning  = sum(1 for i in insights if i["severity"] == "warning")
n_info     = sum(1 for i in insights if i["severity"] == "info")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Insights", len(insights))
k2.metric("Critical", n_critical)
k3.metric("Warnings", n_warning)
k4.metric("Info", n_info)

st.divider()

if not insights:
    st.success(
        "No issues detected for the selected filters. "
        "All tracked metrics are within acceptable thresholds.",
        icon="✅",
    )
else:
    # Optional severity filter
    sev_filter = st.multiselect(
        "Filter by severity",
        options=["critical", "warning", "info"],
        default=["critical", "warning", "info"],
        key="insights_sev_filter",
    )
    filtered = [i for i in insights if i["severity"] in sev_filter]

    if not filtered:
        st.info("No insights match the selected severity filters.")
    else:
        for ins in filtered:
            sev = str(ins["severity"])
            bg, fg, icon = _SEVERITY_STYLE.get(sev, ("#f7f8fa", "#1f2328", ""))
            metric_val = ins.get("metric", 0.0)

            # Format metric based on type
            if abs(float(metric_val)) < 10:
                metric_display = f"{float(metric_val) * 100:.1f}%"
            else:
                metric_display = f"${float(metric_val):,.0f}"

            st.markdown(
                f"""
                <div style="
                    background:{bg};
                    border-left: 4px solid {fg};
                    border-radius: 6px;
                    padding: 14px 18px;
                    margin-bottom: 12px;
                ">
                    <div style="font-weight:600; color:{fg}; font-size:0.85rem; margin-bottom:4px;">
                        {icon} {sev.upper()} &nbsp;|&nbsp; {ins['type'].replace('_',' ').title()}
                        &nbsp;&nbsp;<span style="font-size:0.8rem; opacity:0.75;">
                            metric: {metric_display}
                        </span>
                    </div>
                    <div style="color:#1f2328; font-size:0.95rem; margin-bottom:6px;">
                        {ins['message']}
                    </div>
                    <div style="color:#57606a; font-size:0.85rem; font-style:italic;">
                        Recommendation: {ins['recommendation']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

st.divider()
st.caption(
    "Insight thresholds: revenue decline >20% = warning, >40% = critical; "
    "product profit < 0 = critical; category margin < 5% = warning; "
    "top-3 customers >60% of revenue = warning; region growth >10% = info."
)
