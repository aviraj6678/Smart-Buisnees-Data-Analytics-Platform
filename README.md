# Smart Business Data Analytics Platform

A professional, multi-page business intelligence dashboard built with Python and Streamlit. Upload your transaction data or use the built-in synthetic sample dataset to explore sales, customer, and profit analytics — with rule-based insights and CSV/PDF export.

> **Sample data notice:** The built-in dataset (`data/sample_data.csv`) is entirely synthetic. It was generated with a fixed random seed and does not represent any real business.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Running the Application](#running-the-application)
4. [Loading Data](#loading-data)
5. [Live API Integration](#live-api-integration)
6. [Synthetic Demo Data](#synthetic-demo-data)
7. [Pages](#pages)
8. [Dataset Schema](#dataset-schema)
9. [KPI Formulas](#kpi-formulas)
10. [Running Tests](#running-tests)
11. [Project Structure](#project-structure)
12. [Known Limitations](#known-limitations)

---

## Prerequisites

- **Python 3.9 or newer** (tested on Python 3.13)
- **pip** (included with Python)
- No external services, paid APIs, or database servers required

> **Note on type hints:** This project uses `typing.Optional` instead of the `X | None` union syntax to maintain compatibility with Python 3.9 and newer.

---

## Installation

```bash
# 1. Clone or download the project
cd "Smart Buisnees Data Analytics"

# 2. (Recommended) Create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install all dependencies
pip install -r requirements.txt
```

### Dependencies installed

| Package | Purpose |
|---------|---------|
| `streamlit >= 1.32` | Web application framework |
| `pandas >= 2.0` | Data processing and aggregation |
| `numpy >= 1.26` | Numerical operations |
| `plotly >= 5.20` | Interactive charts |
| `openpyxl >= 3.1` | Excel file support |
| `fpdf2 >= 2.7` | PDF report generation |
| `pytest >= 8.0` | Automated testing |

---

## Running the Application

```bash
streamlit run app.py
```

The app opens at **http://localhost:8501** by default.

To use a different port:

```bash
streamlit run app.py --server.port 8502
```

---

## Loading Data

### Option A — Load the built-in sample dataset

1. Open the app and navigate to **Data Management**
2. Click the **Sample Dataset** tab
3. Click **Load Sample Dataset**

The sample dataset covers January–December 2023 with 929 transaction rows across 457 orders, 55 customers, 35 products, 5 categories, and 4 regions. It contains deliberate anomalies (a revenue decline in September and two loss-making products) to demonstrate the Business Insights page.

### Option B — Upload your own data

1. Navigate to **Data Management**
2. Click the **Upload File** tab
3. Upload a `.csv` or `.xlsx` file

Your file must include all 11 required columns (see [Dataset Schema](#dataset-schema)). The platform will validate the file, report any issues, and show you a three-number import summary:

- **Rows inserted** — successfully written to the database
- **Rows skipped** — `transaction_id` already exists in the database
- **Rows rejected** — removed by validation (invalid types, missing required fields, etc.)

### Regenerating the sample dataset

```bash
python data/generate_sample.py
```

This recreates `data/sample_data.csv` with a fixed random seed (42) for reproducibility.

---

## Live API Integration

The platform includes an optional live API integration that fetches transaction data from a configurable REST API, validates it using the same pipeline as CSV/Excel upload, and stores it in the SQLite database. Existing CSV/Excel import is unaffected.

> **Integration status:** The module is fully implemented and tested with mocked responses. It has **not** been verified against a specific real API provider. You must supply the URL, authentication details, and confirm the response schema before relying on it in production.

### 5.1 — Environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LIVE_API_ENABLED` | No | `false` | Set to `true` to enable live sync. Any other value keeps it off. |
| `LIVE_API_URL` | When enabled | — | Full URL of the REST endpoint returning transaction JSON. |
| `LIVE_API_TOKEN` | No | — | Bearer token for API auth. Omit for public APIs. **Never commit this.** |
| `LIVE_API_TIMEOUT_SECONDS` | No | `30` | Per-request timeout in seconds. |
| `LIVE_API_DATA_KEY` | No | `data` | JSON key containing the transaction array when the API returns a wrapper object. |

`python-dotenv` is installed automatically with `pip install -r requirements.txt`. When present, values in `.env` are loaded on app start.

### 5.2 — Expected JSON response format

**Format A — bare array (simplest):**
```json
[
  {
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
  }
]
```

**Format B — wrapper object with pagination:**
```json
{
  "data": [ {...}, {...} ],
  "next": "https://api.example.com/transactions?page=2"
}
```

Set `LIVE_API_DATA_KEY` to the wrapper key name (default: `"data"`). Pagination follows the `next`, `next_page`, or `next_url` key until exhausted (max 100 pages per sync).

**Field mapping:** JSON field names must match the 11 transaction schema columns exactly (case-insensitive, whitespace-stripped). Extra fields are silently ignored. See [Dataset Schema](#dataset-schema) for the full column rules.

### 5.3 — Enabling and disabling sync

```ini
# .env — enable
LIVE_API_ENABLED=true
LIVE_API_URL=https://your-api.example.com/transactions
LIVE_API_TOKEN=your_token_here

# .env — disable (or just omit LIVE_API_ENABLED)
LIVE_API_ENABLED=false
```

Restart the app after changing `.env`.

### 5.4 — Using the Live API tab in the UI

1. Open the app and navigate to **Data Management**
2. Click the **🔴 Live API** tab
3. The **Configuration Status** panel shows whether the integration is enabled and whether the URL and token are set — the token value is never displayed
4. Click **🔄 Sync now** to fetch records immediately
5. Enable the **Auto-refresh every 60s** toggle to trigger a sync on each page reload after 60 seconds have elapsed since the last sync
6. Sync results show: records fetched, inserted, skipped (duplicate), rejected (invalid), and pages fetched

### 5.5 — How the 60-second refresh works

Streamlit re-runs the entire page script on each user interaction or browser reload. The auto-refresh logic checks `time.time()` against the last sync timestamp stored in `st.session_state`. If 60 or more seconds have passed, a new sync is triggered and the page reruns to show updated data.

**Important limitations:**
- A sync only runs when the Data Management page is open and a script rerun occurs.
- There is no background scheduler. Syncing does not continue while the app is closed.
- Each browser tab has its own `session_state` — multiple open tabs may each trigger a sync independently.
- On shared hosting platforms (e.g. Streamlit Community Cloud), background threads are not supported. Use `st_autorefresh` from `streamlit-autorefresh` (an optional third-party package) if continuous background polling is required.

### 5.6 — Authentication

The token is sent as an HTTP `Authorization: Bearer <token>` header. OAuth flows, API-key query parameters, and custom header schemes are not built in — modify [`_build_headers()`](src/live_api.py) in `src/live_api.py` for alternative schemes.

### 5.7 — Pagination

Auto-pagination follows any key named `next`, `next_page`, or `next_url` in a wrapper response. Pagination stops when the key is absent or `null`, or after 100 pages (safety limit configurable via `_MAX_PAGES` in `src/live_api.py`).

### 5.8 — Rate limits

When the API returns HTTP 429, the sync is aborted and the `Retry-After` header value is included in the error message displayed in the UI. The next "Sync now" or auto-refresh will retry from scratch.

### 5.9 — Idempotency and data safety

- Re-fetching the same `transaction_id` is harmless — the existing record is kept (`INSERT OR IGNORE`).
- A failed or empty sync **never deletes or alters existing records**.
- The sync is wrapped in a safe call that catches all exceptions — a broken API cannot corrupt the database.

### 5.10 — Provider-specific configuration still needed

The following details are **unknown until you connect a real API**:

| Item | What you must verify |
|------|---------------------|
| Field names | Confirm JSON keys match the 11 schema columns, or add a field-mapping layer |
| Pagination scheme | Confirm key name (`next`, `next_page`, `cursor`, etc.) |
| Auth scheme | Confirm Bearer token vs API key vs OAuth |
| Rate limits | Check your API plan and set `LIVE_API_TIMEOUT_SECONDS` accordingly |
| Record update policy | `INSERT OR IGNORE` keeps the first-seen version; modify `insert_transactions()` in `src/database.py` if you need upsert (UPDATE on conflict) |

---

## Synthetic Demo Data

> ⚠️ **All records produced by this feature are entirely fictional.** They do not represent real business activity and must not be used for real business analysis or reporting.

The Synthetic Demo Data Generator creates small batches of realistic-but-fictional sales transactions and inserts them into the same SQLite database used by all other analytics pages. No external services or API keys are required.

### 6.1 — What it is (and what it is not)

| Property | Value |
|---|---|
| Data source | Locally generated Python code — no network calls, no external data |
| Relationship to Live API | Completely independent; either feature can be used alone |
| Purpose | Demonstrating dashboard behaviour with continuously changing data |
| Schema | Identical to the real transaction schema — no new columns |
| Transaction ID prefix | `DEMO-` (e.g. `DEMO-3f8a1c92b047`) — visible in all exports |
| Order ID prefix | `DEMO-ORD-` — one shared order ID per batch (multi-product order) |

### 6.2 — Enabling and disabling

1. Open the app and navigate to **Data Management**
2. Click the **🧪 Synthetic Demo** tab
3. Toggle **"Enable auto-generation"** to start the 60-second cycle
4. Adjust **"Lines per batch"** (default 3, range 1–10)

The generator is **disabled by default** so it never modifies existing datasets unexpectedly.

Disabling the toggle never deletes records that have already been inserted. Use the **Manage Database** tab to clear all data if needed.

### 6.3 — Generating a batch manually

Click **⚡ Generate Demo Batch Now** at any time to insert one batch immediately, regardless of the timer.

### 6.4 — How the 60-second refresh works

The auto-generation logic checks two guards on each page rerun:

1. **Session-state guard** (`should_auto_generate`): checks whether 60 seconds have elapsed since the last generation *in this browser tab*.
2. **Database-backed guard** (`was_batch_generated_recently`): checks the `demo_generation_log` table to prevent duplicate batches across multiple tabs or sessions within the same 60-second window.

If both guards pass, a new batch is generated and the page reruns to show updated KPIs.

> **Important:** A generation cycle only fires when the **Data Management** page is open and Streamlit reruns the script (user interaction or page reload). Generation **does not continue when the app is closed**.

### 6.5 — How demo records affect KPIs and charts

Generated records flow through the same validation and insert pipeline as CSV/Excel uploads:

- **Revenue**, **Profit**, **Total Orders** (`COUNT(DISTINCT order_id)`) and **AOV** are all recalculated from the full database content after each batch, including demo rows.
- Because each batch uses `today()` as the transaction date, records always fall within the default date filter.
- If the sidebar date filter excludes today (e.g. you are browsing historical data), the generated rows will not appear in the filtered view. The **Manage Database** tab shows all rows regardless of filters.

### 6.6 — Avoiding demo data in real demonstrations

To ensure a clean slate before a real business demonstration:

```bash
# Option 1 — use the Manage Database tab in the UI (clears ALL data)

# Option 2 — run the sample dataset to restore clean reference data
python data/generate_sample.py           # regenerate sample_data.csv
# Then load it from the Sample Dataset tab
```

Demo records are identifiable by the `DEMO-` prefix in `transaction_id` and `DEMO-ORD-` prefix in `order_id`. If you need to selectively remove them, use a SQLite client:

```sql
DELETE FROM transactions WHERE transaction_id LIKE 'DEMO-%';
DELETE FROM demo_generation_log;
```

### 6.7 — Concurrency and multi-user limitations

The `demo_generation_log` table provides a cross-session duplicate guard within a single SQLite database file. However:

- SQLite does not support concurrent writes — running multiple Streamlit sessions simultaneously may cause locking errors.
- The 60-second interval is approximate; clock drift across sessions may produce a batch slightly outside the window.
- For multi-user deployments, the database layer should be replaced with PostgreSQL and the log guard updated accordingly.

### 6.8 — Running relevant tests

```bash
pytest tests/test_demo_generator.py -v
```

Expected output: **44 tests, 0 failures**. All tests use an isolated temporary database — no production data is read or written.

---

## Pages

| Page | Description |
|------|-------------|
| **Overview** | Five KPI cards (revenue, profit, orders, AOV, margin) and revenue/profit trend charts grouped by month or year |
| **Data Management** | Upload CSV/Excel, view validation results, load sample data, inspect or clear the database |
| **Sales Analytics** | Sales over time, revenue by category and region, top and bottom products by revenue, full product table |
| **Customer Analytics** | Unique customer count, top customers by revenue, revenue-tier segmentation (High/Mid/Low Value), orders trend |
| **Profit Analysis** | Profit margin by category and product, revenue vs cost vs profit grouped chart, low-profit and loss-making product table |
| **Business Insights** | Rule-based findings sorted by severity (Critical / Warning / Info), severity filter, metric citations, recommendations |
| **Reports** | Applied filter summary, KPI snapshot, CSV download of filtered data, PDF report generation and download |

### Sidebar filters

The sidebar on every page exposes:

- **From date / To date** — filter all data to a date range
- **Region** — filter to a single region (or All)
- **Category** — filter to a single product category (or All)

Filters are stored in `st.session_state` and apply to all pages simultaneously.

---

## Dataset Schema

Every imported file must contain these 11 columns. Column names are matched case-insensitively with leading/trailing whitespace stripped.

| Column | Type | Rules |
|--------|------|-------|
| `transaction_id` | string | **Required. Must be unique per row.** This is the primary key — deduplication is based on this column only. |
| `order_id` | string | Required. **Not unique** — multiple rows may share the same `order_id` (multi-product orders). |
| `transaction_date` | date | Required. Parsed as `YYYY-MM-DD`. |
| `customer_id` | string | Required. |
| `customer_name` | string | Required. Filled with "Unknown Customer" if blank. |
| `product` | string | Required. |
| `category` | string | Required. |
| `region` | string | Required. Filled with "Unknown Region" if blank. |
| `quantity` | integer >= 1 | Required. Rows with quantity < 1 are rejected. |
| `unit_price` | float > 0 | Required. Rows with unit_price <= 0 are rejected. |
| `unit_cost` | float >= 0 | Required. Zero cost is valid (e.g. internal transfers). |

**Key distinction:** A single *order* (one `order_id`) represents a customer purchase event and may contain several product line items — one row per product. `transaction_id` uniquely identifies each line item. Do not deduplicate on `order_id`.

### Derived columns (computed at query time, never stored)

| Column | Formula |
|--------|---------|
| `revenue` | `quantity × unit_price` |
| `cost` | `quantity × unit_cost` |
| `profit` | `revenue − cost` |
| `profit_margin` | `profit ÷ revenue` (0.0 when revenue = 0) |

---

## KPI Formulas

| KPI | Formula | Note |
|-----|---------|------|
| Total Revenue | `SUM(quantity × unit_price)` | Filtered by sidebar date/region/category |
| Total Profit | `SUM(profit)` | Can be negative |
| Total Orders | `COUNT(DISTINCT order_id)` | Counts purchase events, not line items |
| Total Line Items | `COUNT(transaction_id)` | Counts individual product rows |
| Average Order Value | `Total Revenue ÷ Total Orders` | 0 when no orders |
| Profit Margin % | `Total Profit ÷ Total Revenue × 100` | 0 when revenue = 0 |

---

## Running Tests

```bash
pytest tests/
```

Expected output: **248 tests, 0 failures**.

To run a specific test file:

```bash
pytest tests/test_analytics.py -v
pytest tests/test_data_validation.py -v
pytest tests/test_insights.py -v
pytest tests/test_live_api.py -v
pytest tests/test_demo_generator.py -v
```

### Test coverage

| File | Tests | What is covered |
|------|-------|----------------|
| `tests/test_data_validation.py` | 44 | File loading (CSV + Excel), column validation, type coercion, duplicate detection, missing value handling, end-to-end import pipeline |
| `tests/test_analytics.py` | 46 | All KPI functions, aggregations, segmentation, profit flags; confirms `Total Orders != len(df)` for multi-product orders |
| `tests/test_insights.py` | 31 | All 5 insight detectors, severity levels, metric accuracy, no-fabrication guarantee |
| `tests/test_database.py` | 33 | DB init, insert/skip/reject counts, multi-product order semantics, date handling, filters, clear, distinct helpers |
| `tests/test_live_api.py` | 50 | `load_config`, `fetch_raw_records` (bare/wrapped/paginated/errors/rate-limits), `sync_from_api` (all error paths, dedup, count invariant, data preservation), `should_auto_refresh` |
| `tests/test_demo_generator.py` | 44 | `generate_batch` (schema, IDs, numeric rules, date policy), `init_demo_log`, `was_batch_generated_recently`, `run_demo_generation` (counts, dedup guard, force flag, existing-data preservation), `should_auto_generate` |

All 50 live API tests use mocked HTTP. All 44 demo generator tests use an isolated temporary database — **no production data is read or written**.

---

## Project Structure

```
Smart Buisnees Data Analytics/
|
+-- app.py                        Entry point — DB init + global sidebar filters
+-- requirements.txt              Python package dependencies
+-- README.md                     This file
+-- .gitignore                    Excludes database/, __pycache__/, .env
+-- .env.example                  Template for environment variables (copy to .env)
|
+-- .streamlit/
|   +-- config.toml               Streamlit theme (colours, font)
|
+-- data/
|   +-- sample_data.csv           Synthetic sample dataset (929 rows, seed=42)
|   +-- generate_sample.py        Script to regenerate sample_data.csv
|
+-- database/
|   +-- analytics.db              SQLite database (created at runtime, git-ignored)
|
+-- src/
|   +-- __init__.py
|   +-- database.py               SQLite layer: init, insert, query, ImportResult
|   +-- data_loader.py            CSV/Excel file reader with extension + size guards
|   +-- data_validation.py        Schema check, type coercion, dedup, missing-value handling
|   +-- analytics.py              KPI calculations, aggregations, segmentation
|   +-- insights.py               Rule-based insight engine (5 detectors)
|   +-- reports.py                CSV export and PDF report builder
|   +-- live_api.py               Optional live API integration (fetch, validate, insert)
|   +-- demo_generator.py         Synthetic demo data generator (batch gen, log table, guards)
|
+-- pages/
|   +-- 1_Overview.py             KPI cards + trend charts
|   +-- 2_Data_Management.py      Upload, validate, import, live API, demo generator, manage DB
|   +-- 3_Sales_Analytics.py      Sales by time, product, category, region
|   +-- 4_Customer_Analytics.py   Customer KPIs, segmentation, trends
|   +-- 5_Profit_Analysis.py      Margin analysis, low-profit detection
|   +-- 6_Business_Insights.py    Severity-coded rule-based findings
|   +-- 7_Reports.py              CSV and PDF export
|
+-- tests/
    +-- __init__.py
    +-- conftest.py               Shared pytest fixtures
    +-- test_data_validation.py   44 tests for loader and validation (CSV + Excel)
    +-- test_analytics.py         46 tests for KPIs and aggregations
    +-- test_insights.py          31 tests for the insight engine
    +-- test_database.py          33 tests for the database layer
    +-- test_live_api.py          50 tests for live API integration (all mocked)
    +-- test_demo_generator.py    44 tests for the synthetic demo generator (isolated tmp DB)
```

---

## Known Limitations

| Limitation | Details |
|------------|---------|
| **Single-user only** | The SQLite database does not support concurrent writes. Running multiple Streamlit sessions against the same `analytics.db` may cause locking errors. For multi-user deployments, replace the database layer with PostgreSQL. |
| **File size limit** | Files larger than 50 MB are rejected at upload time. Split large files into batches before importing. |
| **PDF font** | PDF reports use the built-in Helvetica core font (Latin-1 only). Product names or customer names containing non-Latin characters will cause a PDF generation error. A Unicode font can be configured in `src/reports.py` if needed. |
| **Live API not verified** | The live API integration module is fully implemented and unit-tested with mocked responses. It has not been tested against a real API provider. Field mapping, authentication scheme, and pagination format must be confirmed before production use. |
| **No background scheduler** | The 60-second auto-refresh (live API) and auto-generation (demo) only fire when the Data Management page is open in a browser tab and Streamlit reruns the script. Neither continues when the app is closed. |
| **Demo data mixes with real data** | The demo generator inserts records into the same database as real uploads. Always clear the database or filter by `transaction_id LIKE 'DEMO-%'` before switching to real business data. |
| **No real-time data (without API)** | Without live API configuration, the platform reads only from the local SQLite database populated by CSV/Excel upload or sample data. |
| **No authentication** | There is no login screen or role-based access control. Do not expose the app publicly without adding authentication. |
| **Machine learning** | All analytics and insights are rule-based. No ML models are used or required. |
| **Python version** | Minimum Python 3.9. The `X \| Y` union type syntax (Python 3.10+) is intentionally avoided; `typing.Optional` is used throughout. |
