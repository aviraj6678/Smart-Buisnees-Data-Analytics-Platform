"""
Smart Business Data Analytics Platform
Entry point — initialises the database and renders the global sidebar.

Run with:
    streamlit run app.py
"""

import datetime
import streamlit as st
from src.database import init_db, get_distinct_regions, get_distinct_categories
from src.demo_generator import init_demo_log

# ── Page configuration (must be first Streamlit call) ─────────────────────────
st.set_page_config(
    page_title="Smart Business Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── One-time DB initialisation ─────────────────────────────────────────────────
init_db()
init_demo_log()

# ── Global sidebar filters (written to session_state for all pages) ────────────
with st.sidebar:
    st.title("📊 Smart Business Analytics")
    st.caption("Business Intelligence Dashboard")
    st.divider()

    st.subheader("Filters")

    # Date range
    today = datetime.date.today()
    default_start = datetime.date(today.year - 1, 1, 1)
    default_end = today

    start_date = st.date_input(
        "From date",
        value=st.session_state.get("filter_start_date", default_start),
        key="filter_start_date",
    )
    end_date = st.date_input(
        "To date",
        value=st.session_state.get("filter_end_date", default_end),
        key="filter_end_date",
    )
    if start_date > end_date:
        st.warning("Start date is after end date.")

    # Region filter
    regions = ["All"] + get_distinct_regions()
    region = st.selectbox(
        "Region",
        options=regions,
        index=0,
        key="filter_region",
    )

    # Category filter
    categories = ["All"] + get_distinct_categories()
    category = st.selectbox(
        "Category",
        options=categories,
        index=0,
        key="filter_category",
    )

    st.divider()
    st.caption("Navigate using the pages above.")
    st.caption("Load data on the **Data Management** page first.")
    st.divider()
    st.caption("Sample data is synthetic. No real business data is included.")

# ── Landing page ───────────────────────────────────────────────────────────────
st.title("📊 Smart Business Data Analytics Platform")
st.markdown(
    """
    Welcome to the **Smart Business Data Analytics Platform** — a professional
    business-intelligence dashboard built with Python and Streamlit.

    ---

    ### Getting started

    | Step | Action |
    |------|--------|
    | 1 | Go to **Data Management** to upload a CSV/Excel file or load the built-in sample dataset |
    | 2 | Visit **Overview** to see key performance indicators |
    | 3 | Explore **Sales Analytics**, **Customer Analytics**, and **Profit Analysis** |
    | 4 | Read auto-generated findings on the **Business Insights** page |
    | 5 | Download reports from the **Reports** page |

    ---

    ### Pages in this application

    - **1 · Overview** — Revenue, profit, order KPIs and trend charts
    - **2 · Data Management** — Upload, validate, and import transaction data
    - **3 · Sales Analytics** — Sales by time, product, category, and region
    - **4 · Customer Analytics** — Top customers, segments, and purchase trends
    - **5 · Profit Analysis** — Margin analysis and low-profit detection
    - **6 · Business Insights** — Rule-based findings and recommendations
    - **7 · Reports** — Export filtered data as CSV or PDF

    ---

    > **Note:** All sample data is synthetic and labelled accordingly.
    > No real business information is included.
    """
)
