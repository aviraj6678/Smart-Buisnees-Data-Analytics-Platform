"""
Page 2 — Data Management
Upload, validate, and import transaction data. Load sample dataset.
Optionally connect a live REST API for automatic data refresh every 60 seconds.
Optionally run the synthetic demo data generator every 60 seconds.
"""

import datetime
import pathlib
import time
import streamlit as st
import pandas as pd
from src.database import init_db, get_transactions, clear_transactions
from src.data_loader import load_file
from src.data_validation import validate_dataframe
from src.live_api import (
    load_config,
    sync_from_api,
    should_auto_refresh,
    SYNC_RESULT_KEY,
    LAST_SYNC_TIME_KEY,
    REFRESH_INTERVAL_SECONDS,
)
from src.demo_generator import (
    init_demo_log,
    run_demo_generation,
    should_auto_generate,
    get_last_batch_time,
    get_total_demo_lines,
    DEMO_RESULT_KEY,
    DEMO_LAST_TIME_KEY,
    DEMO_REFRESH_INTERVAL_SECONDS,
)

st.set_page_config(page_title="Data Management · Smart Analytics", page_icon="🗂️", layout="wide")
init_db()
init_demo_log()

_SAMPLE_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "sample_data.csv"

st.title("🗂️ Data Management")
st.caption("Upload your transaction data, load the built-in synthetic sample dataset, connect a live API, or run the synthetic demo generator.")

# ── Current database status ────────────────────────────────────────────────────
df_existing = get_transactions()
if df_existing.empty:
    st.info("The database is empty. Upload a file or load the sample dataset below.", icon="ℹ️")
else:
    st.success(
        f"Database contains **{len(df_existing):,}** line items across "
        f"**{df_existing['order_id'].nunique():,}** orders.",
        icon="✅",
    )

st.divider()

# ── Tab layout ─────────────────────────────────────────────────────────────────
tab_upload, tab_sample, tab_live, tab_demo, tab_manage = st.tabs(
    ["Upload File", "Sample Dataset", "🔴 Live API", "🧪 Synthetic Demo", "Manage Database"]
)

# ── Tab 1: Upload file ─────────────────────────────────────────────────────────
with tab_upload:
    st.subheader("Upload CSV or Excel File")
    st.markdown(
        "Upload a `.csv` or `.xlsx` file containing transaction data. "
        "The file must include these columns: "
        "`transaction_id`, `order_id`, `transaction_date`, `customer_id`, `customer_name`, "
        "`product`, `category`, `region`, `quantity`, `unit_price`, `unit_cost`."
    )

    uploaded = st.file_uploader("Choose a file", type=["csv", "xlsx"])

    if uploaded is not None:
        with st.spinner("Reading file..."):
            try:
                raw_df = load_file(uploaded)
            except ValueError as exc:
                st.error(f"File error: {exc}")
                st.stop()

        st.subheader("Preview (first 10 rows)")
        st.dataframe(raw_df.head(10), use_container_width=True)

        with st.spinner("Validating..."):
            clean_df, report = validate_dataframe(raw_df)

        # Validation report
        st.subheader("Validation Report")
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Rows in file", len(raw_df))
        col_b.metric("Duplicates removed", report["duplicate_transaction_ids_removed"])
        col_c.metric("Rows dropped (invalid)", report["rows_dropped_missing_required"])
        col_d.metric("Rows filled (Unknown)", report["rows_filled_unknown"])

        if report["missing_columns"]:
            st.error(f"Missing required columns: {', '.join(report['missing_columns'])}")
            st.stop()

        if report["type_errors"]:
            with st.expander(f"Type / value warnings ({len(report['type_errors'])})"):
                for err in report["type_errors"]:
                    st.warning(err)

        if clean_df.empty:
            st.error("No valid rows remain after validation. Please check your file.")
            st.stop()

        st.success(f"{len(clean_df):,} rows passed validation and are ready to import.")

        if st.button("Import into Database", type="primary"):
            from src.database import insert_transactions
            result = insert_transactions(
                clean_df,
                rejected_invalid=report["duplicate_transaction_ids_removed"]
                + report["rows_dropped_missing_required"],
            )
            st.success(
                f"Import complete: **{result.inserted}** rows inserted, "
                f"**{result.skipped_duplicate}** skipped (already in DB), "
                f"**{result.rejected_invalid}** rejected by validation."
            )
            st.cache_data.clear()


# ── Tab 2: Sample dataset ──────────────────────────────────────────────────────
with tab_sample:
    st.subheader("Synthetic Sample Dataset")
    st.markdown(
        "> **Note:** This dataset is entirely synthetic. "
        "It does not represent real business data."
    )

    if not _SAMPLE_PATH.exists():
        st.warning(
            "Sample dataset not found at `data/sample_data.csv`. "
            "Run `python data/generate_sample.py` to generate it.",
            icon="⚠️",
        )
    else:
        sample_preview = pd.read_csv(_SAMPLE_PATH, comment="#")
        st.write(f"**{len(sample_preview):,} rows** | Preview:")
        st.dataframe(sample_preview.head(10), use_container_width=True)

        if st.button("Load Sample Dataset", type="primary"):
            from src.data_loader import load_file as lf
            from src.data_validation import validate_dataframe as vdf
            from src.database import insert_transactions as ins_tx
            with st.spinner("Validating sample data..."):
                raw = lf(str(_SAMPLE_PATH))
                clean, rpt = vdf(raw)
            if clean.empty:
                st.error("Sample data failed validation.")
            else:
                result = ins_tx(
                    clean,
                    rejected_invalid=rpt["duplicate_transaction_ids_removed"]
                    + rpt["rows_dropped_missing_required"],
                )
                st.success(
                    f"Sample dataset loaded: **{result.inserted}** rows inserted, "
                    f"**{result.skipped_duplicate}** already in DB."
                )
                st.cache_data.clear()


# ── Tab 3: Live API ────────────────────────────────────────────────────────────
with tab_live:
    st.subheader("Live API Integration")
    st.markdown(
        "Connect a REST API to automatically import transaction data every "
        f"**{REFRESH_INTERVAL_SECONDS} seconds**. "
        "Configure the connection using environment variables (see `.env.example`)."
    )

    # Load config (never displays token value)
    api_cfg = load_config()

    # ── Configuration status ───────────────────────────────────────────────────
    st.markdown("#### Configuration Status")
    cfg_col1, cfg_col2, cfg_col3, cfg_col4 = st.columns(4)

    cfg_col1.metric(
        "Integration",
        "Enabled ✅" if api_cfg.enabled else "Disabled ⛔",
    )
    cfg_col2.metric(
        "API URL",
        "Set ✅" if api_cfg.url else "Not set ⚠️",
    )
    cfg_col3.metric(
        "Auth Token",
        "Set ✅" if api_cfg.has_token else "None (public API)",
    )
    cfg_col4.metric(
        "Timeout",
        f"{api_cfg.timeout}s",
    )

    if not api_cfg.enabled:
        st.info(
            "Live API integration is **disabled**. "
            "Set `LIVE_API_ENABLED=true` in your `.env` file or environment to enable it.",
            icon="ℹ️",
        )
    elif not api_cfg.url:
        st.warning(
            "Live API integration is enabled but `LIVE_API_URL` is not set. "
            "Add the API endpoint URL to your `.env` file.",
            icon="⚠️",
        )
    else:
        st.success(
            f"API configured: `{api_cfg.url}` "
            f"({'authenticated' if api_cfg.has_token else 'no auth token'})",
            icon="🔗",
        )

    st.divider()

    # ── Last sync status ───────────────────────────────────────────────────────
    st.markdown("#### Sync Status")

    last_result = st.session_state.get(SYNC_RESULT_KEY)
    last_sync_time = st.session_state.get(LAST_SYNC_TIME_KEY)

    if last_result is None:
        st.info("No sync has been run yet this session.", icon="🕐")
    else:
        import datetime as _dt
        sync_dt = _dt.datetime.fromtimestamp(last_result.fetched_at).strftime("%Y-%m-%d %H:%M:%S")

        if last_result.success:
            st.success(f"Last sync succeeded at **{sync_dt}**", icon="✅")
        else:
            st.error(f"Last sync failed at **{sync_dt}**: {last_result.error_message}", icon="❌")

        s1, s2, s3, s4, s5 = st.columns(5)
        s1.metric("Records fetched", last_result.records_fetched)
        s2.metric("Inserted", last_result.inserted)
        s3.metric("Skipped (duplicate)", last_result.skipped_duplicate)
        s4.metric("Rejected (invalid)", last_result.rejected_invalid)
        s5.metric("Pages fetched", last_result.pages_fetched)

    st.divider()

    # ── Manual sync / auto-refresh controls ───────────────────────────────────
    st.markdown("#### Controls")

    sync_col1, sync_col2 = st.columns([1, 3])

    with sync_col1:
        manual_sync = st.button(
            "🔄 Sync now",
            type="primary",
            disabled=not (api_cfg.enabled and api_cfg.url),
            help="Fetch new records from the API immediately.",
        )

    with sync_col2:
        auto_refresh_on = st.toggle(
            f"Auto-refresh every {REFRESH_INTERVAL_SECONDS}s",
            value=False,
            key="live_api_auto_refresh",
            help=(
                "When enabled, each page load checks whether 60 seconds have "
                "passed since the last sync and triggers a new one if so. "
                "A sync only runs if this page is open and Streamlit reruns the script."
            ),
        )

    # Perform manual sync
    if manual_sync:
        with st.spinner("Syncing..."):
            result = sync_from_api(api_cfg)
        st.session_state[SYNC_RESULT_KEY] = result
        st.session_state[LAST_SYNC_TIME_KEY] = result.fetched_at
        st.cache_data.clear()
        st.rerun()

    # Perform auto-refresh if interval has elapsed
    if auto_refresh_on and api_cfg.enabled and api_cfg.url:
        if should_auto_refresh(last_sync_time):
            with st.spinner("Auto-refreshing..."):
                result = sync_from_api(api_cfg)
            st.session_state[SYNC_RESULT_KEY] = result
            st.session_state[LAST_SYNC_TIME_KEY] = result.fetched_at
            st.cache_data.clear()
            st.rerun()
        else:
            next_refresh_in = int(
                REFRESH_INTERVAL_SECONDS - (time.time() - (last_sync_time or 0))
            )
            st.caption(f"Next auto-refresh in ~{max(0, next_refresh_in)}s (reload the page to check).")

    st.divider()

    # ── Setup instructions ────────────────────────────────────────────────────
    with st.expander("📋 Setup instructions", expanded=False):
        st.markdown(
            f"""
**Step 1 — Copy the example environment file:**
```bash
cp .env.example .env
```

**Step 2 — Edit `.env` with your API details:**
```ini
LIVE_API_ENABLED=true
LIVE_API_URL=https://your-api.example.com/transactions
LIVE_API_TOKEN=your_secret_token_here   # omit if the API is public
LIVE_API_TIMEOUT_SECONDS=30
LIVE_API_DATA_KEY=data                  # key containing the array in wrapped responses
```

**Step 3 — Restart the app:**
```bash
streamlit run app.py
```

**Expected JSON format (bare array):**
```json
[
  {{
    "transaction_id": "T001",
    "order_id": "O001",
    "transaction_date": "2024-01-15",
    "customer_id": "C01",
    "customer_name": "Alice",
    "product": "Widget A",
    "category": "Widgets",
    "region": "North",
    "quantity": 2,
    "unit_price": 50.00,
    "unit_cost": 30.00
  }}
]
```

**Expected JSON format (wrapped with pagination):**
```json
{{
  "data": [ {{...}}, {{...}} ],
  "next": "https://your-api.example.com/transactions?page=2"
}}
```

> **Security:** The token is never displayed, logged, or stored in the database.
> Existing records are never deleted by a failed or empty sync.
"""
        )


# ── Tab 4: Synthetic demo data ────────────────────────────────────────────────
with tab_demo:
    st.subheader("🧪 Synthetic Demo Data Generator")

    st.warning(
        "⚠️ **DEMO DATA** — Records generated here are entirely fictional synthetic data. "
        "They do not represent real business activity and must not be used for "
        "real business analysis or reporting.",
        icon="🧪",
    )

    st.markdown(
        f"Automatically generate small batches of fictional transaction lines "
        f"every **{DEMO_REFRESH_INTERVAL_SECONDS} seconds** and insert them into "
        "the database. The dashboard KPIs and charts will reflect the new data. "
        "Generated records are labelled with a `DEMO-` prefix on their transaction ID."
    )

    st.divider()

    # ── Controls ──────────────────────────────────────────────────────────────
    st.markdown("#### Generator Controls")

    demo_ctrl1, demo_ctrl2, demo_ctrl3 = st.columns([1, 1, 2])

    with demo_ctrl1:
        demo_enabled = st.toggle(
            "Enable auto-generation",
            value=False,
            key="demo_gen_enabled",
            help=(
                "When enabled, a new batch is generated each time 60 seconds "
                "have elapsed since the last batch. The page must be open for "
                "auto-generation to fire. Disabled by default."
            ),
        )

    with demo_ctrl2:
        batch_size = st.number_input(
            "Lines per batch",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="demo_batch_size",
            help="Number of transaction lines generated per cycle (1–10).",
        )

    with demo_ctrl3:
        generate_now = st.button(
            "⚡ Generate Demo Batch Now",
            type="primary",
            help="Immediately insert a new demo batch regardless of the timer.",
        )

    st.divider()

    # ── Status ────────────────────────────────────────────────────────────────
    st.markdown("#### Status")

    db_last = get_last_batch_time()
    total_demo = get_total_demo_lines()
    last_result: object = st.session_state.get(DEMO_RESULT_KEY)
    last_gen_time = st.session_state.get(DEMO_LAST_TIME_KEY)

    stat1, stat2, stat3 = st.columns(3)
    stat1.metric(
        "Auto-generation",
        "Enabled ✅" if demo_enabled else "Disabled ⛔",
    )
    stat2.metric(
        "DEMO lines in DB",
        f"{total_demo:,}",
        help="Total transaction lines with a DEMO- prefix currently in the database.",
    )
    stat3.metric(
        "Last batch (DB)",
        db_last.strftime("%H:%M:%S") if db_last else "Never",
        help="Timestamp of the last successfully logged demo batch (all sessions).",
    )

    if last_result is not None:
        from src.demo_generator import DemoGenResult
        assert isinstance(last_result, DemoGenResult)
        gen_dt = datetime.datetime.fromtimestamp(last_result.generated_at).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        if last_result.success:
            st.success(
                f"Last batch at **{gen_dt}** — "
                f"**{last_result.inserted}** inserted, "
                f"**{last_result.skipped_duplicate}** skipped, "
                f"**{last_result.rejected_invalid}** rejected.",
                icon="✅",
            )
        else:
            st.error(
                f"Last batch at **{gen_dt}** failed: {last_result.error_message}",
                icon="❌",
            )
    else:
        st.info("No demo batch has been generated yet this session.", icon="🕐")

    st.divider()

    # ── Manual generation ─────────────────────────────────────────────────────
    if generate_now:
        with st.spinner("Generating demo batch..."):
            result = run_demo_generation(batch_size=int(batch_size), force=True)
        st.session_state[DEMO_RESULT_KEY] = result
        st.session_state[DEMO_LAST_TIME_KEY] = result.generated_at
        st.cache_data.clear()
        st.rerun()

    # ── Auto-generation ───────────────────────────────────────────────────────
    if demo_enabled:
        if should_auto_generate(last_gen_time):
            with st.spinner("Auto-generating demo batch..."):
                result = run_demo_generation(batch_size=int(batch_size), force=False)
            st.session_state[DEMO_RESULT_KEY] = result
            st.session_state[DEMO_LAST_TIME_KEY] = result.generated_at
            st.cache_data.clear()
            st.rerun()
        else:
            next_in = int(DEMO_REFRESH_INTERVAL_SECONDS - (time.time() - (last_gen_time or 0)))
            st.caption(
                f"Next auto-generation in ~{max(0, next_in)}s "
                "(reload the page or interact to trigger the check)."
            )

    st.divider()

    # ── How it works ──────────────────────────────────────────────────────────
    with st.expander("ℹ️ How synthetic demo data works", expanded=False):
        st.markdown(
            """
**Transaction ID convention:**
Generated records use the prefix `DEMO-` (e.g. `DEMO-3f8a1c92b047`).
This makes them distinguishable in the database and exports without
requiring any schema changes.

**Order ID convention:**
Lines in the same batch share one order ID (`DEMO-ORD-{hex}`),
preserving the multi-product order semantics used throughout the platform.

**Date policy:**
All generated records use **today's date**, so they always appear within
the default date filter on the Overview and Sales pages.

**Idempotency:**
A `demo_generation_log` table (same database file, separate table)
records each successful batch. The auto-generation check reads this log
so that multiple browser tabs or Streamlit reruns within the same 60-second
window do not produce duplicate batches.

**Prices and costs:**
All demo records have `unit_cost < unit_price` — no deliberate loss makers.
Price varies ±5 % around catalogue values; cost is fixed.

**Warning:**
Disabling auto-generation never deletes records already in the database.
Use the **Manage Database** tab to clear all data if needed.
"""
        )


# ── Tab 5: Manage database ─────────────────────────────────────────────────────
with tab_manage:
    st.subheader("Database Contents")

    df_all = get_transactions()
    if df_all.empty:
        st.info("Database is empty.")
    else:
        kpi_c1, kpi_c2, kpi_c3 = st.columns(3)
        kpi_c1.metric("Total Line Items", f"{len(df_all):,}")
        kpi_c2.metric("Total Orders", f"{df_all['order_id'].nunique():,}")
        kpi_c3.metric("Date Range",
                       f"{df_all['transaction_date'].min().date()} to "
                       f"{df_all['transaction_date'].max().date()}")

        st.dataframe(
            df_all.sort_values("transaction_date", ascending=False).head(50),
            use_container_width=True,
        )

    st.divider()
    st.subheader("Clear Database")
    st.warning(
        "This will permanently delete all transaction records from the database.",
        icon="⚠️",
    )
    if st.button("Clear all data", type="secondary"):
        clear_transactions()
        st.success("Database cleared.")
        st.cache_data.clear()
        st.rerun()
