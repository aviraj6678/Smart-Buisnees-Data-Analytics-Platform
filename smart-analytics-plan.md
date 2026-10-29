# Smart Business Data Analytics Platform — Implementation Plan

## Top-Level Overview

**Goal:** Build a complete, professional, multi-page Smart Business Data Analytics Platform using Python 3, Streamlit, Pandas, NumPy, Plotly, SQLite, OpenPyXL, and Pytest.

**Scope:** Eight development phases from architecture design through testing and documentation, delivered across 10 implementation sub-tasks. Each phase produces runnable, verifiable output before the next begins. The phase-to-sub-task mapping is:

| Phase | Sub-Tasks | Focus |
|-------|-----------|-------|
| 1 | — | Architecture, planning, plan file (complete) |
| 2 | 1, 2, 3 | Scaffolding, database layer, data loader + validation |
| 3 | 4, 5 | Analytics module, insights module |
| 4 | 7 | Streamlit dashboard and all pages |
| 5 | 5 (complete), 6 | Smart insights finalised, report exports |
| 6 | 8 | Synthetic sample dataset |
| 7 | 9 | Tests, security review, UI polish |
| 8 | 10 | README and setup instructions |

**Approach:** Streamlit multi-page app with a strict separation between data ingestion (`src/data_loader.py`, `src/data_validation.py`), persistence (`src/database.py`), business logic (`src/analytics.py`, `src/insights.py`), export (`src/reports.py`), and presentation (`pages/`). SQLite is the only required external dependency beyond Python packages.

**Non-Goals:**
- No real-time data connectors or live APIs
- No multi-user authentication
- No paid API dependencies for core features
- Machine-learning features are optional and isolated; core analytics are purely rule-based

---

## Dataset Schema

Every imported transaction record must conform to this schema:

| Column           | Type         | Rules                                                        |
|------------------|--------------|--------------------------------------------------------------|
| transaction_id   | string       | Required, unique per row — primary key for deduplication     |
| order_id         | string       | Required, NOT unique — multiple rows may share an order_id   |
| transaction_date | date         | Required, YYYY-MM-DD                                         |
| customer_id      | string       | Required                                                     |
| customer_name    | string       | Required                                                     |
| product          | string       | Required                                                     |
| category         | string       | Required                                                     |
| region           | string       | Required                                                     |
| quantity         | int >= 1     | Required, positive integer                                   |
| unit_price       | float > 0    | Required, positive float                                     |
| unit_cost        | float >= 0   | Required, non-negative float                                 |

**Key distinction:** A single order (identified by `order_id`) represents a customer purchase event. It may contain multiple line items — one row per product. `transaction_id` uniquely identifies each line item row. Deduplication is performed on `transaction_id`, not `order_id`.

**Derived columns (computed at query time, never stored as duplicates):**

| Metric        | Formula                                       |
|---------------|-----------------------------------------------|
| revenue       | quantity * unit_price                         |
| cost          | quantity * unit_cost                          |
| profit        | revenue - cost                                |
| profit_margin | profit / revenue (returns 0.0 when revenue=0) |

---

## KPI Definitions

| KPI                | Formula                                    | Note                                              |
|--------------------|--------------------------------------------|---------------------------------------------------|
| Total Revenue      | SUM(quantity * unit_price)                 | Filtered by date range                            |
| Total Profit       | SUM(profit)                                | Can be negative                                   |
| Total Orders       | COUNT(DISTINCT order_id)                   | Orders, not line items — one order = many rows    |
| Total Line Items   | COUNT(transaction_id)                      | Individual product rows                           |
| Average Order Value| Total Revenue / Total Orders               | 0 when no orders                                  |
| Profit Margin %    | Total Profit / Total Revenue * 100         | 0 when revenue = 0                                |

---

## Folder Structure

```
smart-business-data-analytics/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── data/
│   └── sample_data.csv
├── database/
│   └── analytics.db              (created at runtime)
├── src/
│   ├── __init__.py
│   ├── database.py
│   ├── data_loader.py
│   ├── data_validation.py
│   ├── analytics.py
│   ├── insights.py
│   └── reports.py
├── pages/
│   ├── 1_Overview.py
│   ├── 2_Data_Management.py
│   ├── 3_Sales_Analytics.py
│   ├── 4_Customer_Analytics.py
│   ├── 5_Profit_Analysis.py
│   ├── 6_Business_Insights.py
│   └── 7_Reports.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_data_validation.py
    ├── test_analytics.py
    └── test_insights.py
```

---

## Sub-Tasks

---

### Sub-Task 1 — Project Scaffolding & Configuration
**Status:** [x] done

**Intent:** Create the folder skeleton, `requirements.txt`, `.gitignore`, and an empty `app.py` entry point so the project is immediately runnable (even if blank).

**Expected Outcomes:**
- All directories exist
- `requirements.txt` lists all dependencies with pinned or minimum versions
- `app.py` launches with `streamlit run app.py` without errors
- `.gitignore` excludes `database/`, `__pycache__/`, `.env`, `*.pyc`

**Todo List:**
1. Create directory tree: `data/`, `database/`, `src/`, `pages/`, `tests/`
2. Write `requirements.txt` with: streamlit, pandas, numpy, plotly, openpyxl, fpdf2, pytest
3. Write `app.py` with sidebar navigation stub
4. Write `.gitignore`
5. Write `src/__init__.py` and `tests/__init__.py`

**Relevant Context:**
- Streamlit multi-page apps use the `pages/` convention — files named `N_Page_Name.py` appear automatically in the sidebar
- `database/` should be git-ignored because it holds runtime SQLite data

---

### Sub-Task 2 — Database Layer
**Status:** [x] done

**Intent:** Implement `src/database.py` to manage the SQLite connection, create the `transactions` table, and expose parameterized read/write helpers that all other modules use.

**Expected Outcomes:**
- `init_db()` creates `database/analytics.db` and the `transactions` table if they do not exist
- `transaction_id` is the PRIMARY KEY — `INSERT OR IGNORE` on `transaction_id` prevents true duplicate rows
- `order_id` is a plain indexed column — multiple rows with the same `order_id` are valid and expected
- `insert_transactions(df)` bulk-inserts a validated DataFrame and returns an `ImportResult` with three explicit counts: `inserted`, `skipped_duplicate`, and `rejected_invalid` — nothing is discarded silently
- The caller (Data Management page) must display all three counts to the user after every import
- `get_transactions(filters)` returns a filtered DataFrame using parameterized queries
- No raw string interpolation in SQL queries

**Todo List:**
1. Implement `init_db()` — connect and CREATE TABLE IF NOT EXISTS
2. Define the transactions table schema: 11 columns total — `transaction_id` (PRIMARY KEY) plus the other 10 columns (`order_id`, `transaction_date`, `customer_id`, `customer_name`, `product`, `category`, `region`, `quantity`, `unit_price`, `unit_cost`)
3. Add an index on `order_id` for fast `COUNT(DISTINCT order_id)` queries
4. Define `ImportResult` as a named tuple or dataclass with fields: `inserted: int`, `skipped_duplicate: int`, `rejected_invalid: int`
5. Implement `insert_transactions(df: pd.DataFrame) -> ImportResult` — attempt `INSERT OR IGNORE` for each row; compare `rowcount` before and after to distinguish inserted vs skipped rows
6. Implement `get_transactions(start_date, end_date, region, category) -> pd.DataFrame`
7. Implement `clear_transactions()` for test teardown
8. Add docstrings and type hints

**Relevant Context:**
- Use `sqlite3` from the standard library — no ORM needed
- `INSERT OR IGNORE` targets `transaction_id` (PRIMARY KEY), not `order_id`
- `database/` path must be constructed relative to the project root, not a hardcoded absolute path
- Total Orders KPI must use `COUNT(DISTINCT order_id)`, never `COUNT(transaction_id)`

---

### Sub-Task 3 — Data Loader & Validation
**Status:** [x] done

**Intent:** Implement `src/data_loader.py` to read CSV and Excel files into DataFrames, and `src/data_validation.py` to enforce the dataset schema, coerce types, flag invalid rows, and detect true duplicates.

**Expected Outcomes:**
- `load_file(uploaded_file)` returns a raw DataFrame from CSV or Excel input
- `validate_dataframe(df)` returns `(cleaned_df, error_report)` where `error_report` is a dict with explicit counts and lists: `missing_columns`, `type_errors`, `duplicate_transaction_ids_removed` (count), `rows_dropped_missing_required` (count), `rows_filled_unknown` (count)
- Missing required columns (including `transaction_id`) produce a clear, user-facing error message
- Invalid numeric values (negative price, zero quantity) are flagged
- `detect_duplicates(df)` detects rows with a duplicated `transaction_id` only — NOT `order_id`
- Multiple rows sharing the same `order_id` (different products) are valid and must NOT be flagged as duplicates
- Clean data has correct dtypes: dates as `datetime64`, numerics as `float64`/`int64`
- The count of rows removed at validation time feeds into the `rejected_invalid` field of `ImportResult` returned by `insert_transactions`

**Todo List:**
1. Implement `load_file(uploaded_file) -> pd.DataFrame` supporting `.csv` and `.xlsx`
2. Implement `check_required_columns(df) -> list[str]` returning missing column names (must include `transaction_id`)
3. Implement `coerce_types(df) -> tuple[pd.DataFrame, list[str]]` — convert and report failures
4. Implement `detect_duplicates(df) -> pd.DataFrame` — duplicate detection based on `transaction_id` only
5. Implement `handle_missing_values(df) -> tuple[pd.DataFrame, dict]` reporting what was filled/dropped
6. Compose all steps in `validate_dataframe(df) -> tuple[pd.DataFrame, dict]`
7. Add unit tests in `tests/test_data_validation.py`

**Relevant Context:**
- Column name matching should be case-insensitive and strip whitespace
- Missing values in `quantity`, `unit_price`, `unit_cost` should drop the row (cannot impute business figures)
- Missing `customer_name` or `region` may be filled with "Unknown" with a warning
- A `transaction_id` that appears twice = true duplicate (remove second occurrence, warn user)
- An `order_id` that appears multiple times = multi-product order (valid, keep all rows)

---

### Sub-Task 4 — Analytics Module
**Status:** [x] done

**Intent:** Implement `src/analytics.py` with all KPI calculations, aggregations, and segmentation logic that power every dashboard page.

**Expected Outcomes:**
- `compute_kpis(df) -> dict` returns Total Revenue, Total Profit, Total Orders, Total Line Items, AOV, Profit Margin %
- `Total Orders` uses `df["order_id"].nunique()` — counts distinct orders, not rows
- `Total Line Items` uses `len(df)` — counts individual transaction rows
- `sales_by_period(df, period) -> pd.DataFrame` aggregates by month or year
- `sales_by_product(df) -> pd.DataFrame` and `sales_by_category(df) -> pd.DataFrame`
- `sales_by_region(df) -> pd.DataFrame`
- `top_products(df, n) -> pd.DataFrame` and `bottom_products(df, n) -> pd.DataFrame`
- `customer_summary(df) -> pd.DataFrame` with unique count, top customers, purchase frequency
- `profit_by_product(df) -> pd.DataFrame` including margin and low-profit flag
- Safe division used everywhere (no ZeroDivisionError, no NaN leaking into KPI display)

**Todo List:**
1. Add `safe_divide(numerator, denominator, default=0.0)` utility
2. Implement `compute_kpis(df) -> dict` — use `df["order_id"].nunique()` for Total Orders
3. Implement `sales_by_period(df, period="month") -> pd.DataFrame`
4. Implement `sales_by_product(df) -> pd.DataFrame` and `sales_by_category`
5. Implement `sales_by_region(df) -> pd.DataFrame`
6. Implement `top_products(df, n=10)` and `bottom_products(df, n=10)`
7. Implement `customer_summary(df) -> pd.DataFrame`
8. Implement `segment_customers(df) -> pd.DataFrame` using revenue-based RFM-lite rules
9. Implement `profit_by_product(df) -> pd.DataFrame`
10. Add unit tests in `tests/test_analytics.py` — include a test that confirms Total Orders != len(df) when multi-product orders are present

**Relevant Context:**
- All functions accept a pre-filtered DataFrame — filtering by date/region/category happens before calling analytics functions
- Customer segmentation uses simple rule-based tiers (e.g. top 20% by revenue = "High Value"), not ML
- Profit margin threshold for "low profit" flag: margin < 10%
- AOV = Total Revenue / COUNT(DISTINCT order_id), not Total Revenue / COUNT(transaction_id)

---

### Sub-Task 5 — Insights Module
**Status:** [x] done

**Intent:** Implement `src/insights.py` to generate rule-based, data-grounded business insights and recommendations. No ML in the core path.

**Expected Outcomes:**
- `generate_insights(df) -> list[dict]` returns a list of insight objects with `type`, `message`, `metric`, and `recommendation`
- Detects: month-over-month revenue decline > 20%, products with negative profit, categories with margin < 5%, top customer concentration risk
- Each insight cites the actual computed metric (e.g. "Revenue fell 23.4% from March to April")
- No fabricated numbers — every insight is derived from the passed DataFrame
- Insights are labelled by severity: `info`, `warning`, `critical`

**Todo List:**
1. Define the insight schema: `{"severity": str, "type": str, "message": str, "recommendation": str, "metric": float}`
2. Implement `detect_revenue_decline(df) -> list[dict]`
3. Implement `detect_negative_profit_products(df) -> list[dict]`
4. Implement `detect_low_margin_categories(df) -> list[dict]`
5. Implement `detect_customer_concentration(df) -> list[dict]`
6. Implement `detect_top_region_growth(df) -> list[dict]`
7. Compose all detectors in `generate_insights(df) -> list[dict]`
8. Add unit tests in `tests/test_insights.py`

**Relevant Context:**
- Revenue decline is measured by comparing the two most recent complete months
- Customer concentration: top 3 customers accounting for > 60% of revenue = warning
- All thresholds should be defined as named constants at the top of the module

---

### Sub-Task 6 — Reports Module
**Status:** [x] done

**Intent:** Implement `src/reports.py` to export filtered data as CSV and generate a summary PDF report.

**Expected Outcomes:**
- `export_csv(df, filters) -> bytes` returns a UTF-8 CSV as bytes for Streamlit download
- `generate_pdf_report(kpis, insights, filters) -> bytes` returns a PDF as bytes
- PDF includes: report date, applied filters, KPI summary table, key insights
- PDF generation fails gracefully if `fpdf2` is unavailable (returns None with a warning)

**Todo List:**
1. Implement `export_csv(df) -> bytes`
2. Implement `build_pdf_report(kpis: dict, insights: list, filters: dict) -> Optional[bytes]` (use `typing.Optional[bytes]` for Python 3.9 compatibility)
3. Add a graceful fallback if fpdf2 is not installed
4. Ensure no file is written to disk during export — use BytesIO

**Relevant Context:**
- Streamlit download buttons accept `bytes` or `str` — use `BytesIO` throughout
- PDF layout: header, filter summary, KPI table, insights list, footer with timestamp

---

### Sub-Task 7 — Streamlit Pages
**Status:** [x] done

**Intent:** Build all seven Streamlit pages and the main `app.py` with shared state, sidebar navigation, and date-range filters.

**Expected Outcomes:**
- `app.py` initialises the DB, loads shared session state, renders sidebar
- Each page imports from `src/` and renders charts using Plotly
- Date-range filter in sidebar applies to all pages
- Region and category filters available on relevant pages
- KPI cards on Overview use `st.metric`
- All charts are interactive Plotly figures
- Tables use `st.dataframe` with appropriate column formatting

**Todo List:**
1. Complete `app.py`: DB init, sidebar, global filter state
2. Build `pages/1_Overview.py`: 5 KPI cards + revenue/profit trend chart
3. Build `pages/2_Data_Management.py`: file upload, preview, validation feedback, load button
4. Build `pages/3_Sales_Analytics.py`: sales by time, product, category, region charts
5. Build `pages/4_Customer_Analytics.py`: customer count, top customers table, segmentation chart
6. Build `pages/5_Profit_Analysis.py`: margin by product/category, low-profit table
7. Build `pages/6_Business_Insights.py`: insight cards with severity colour coding
8. Build `pages/7_Reports.py`: filter summary, CSV download, PDF download

**Relevant Context:**
- Use `st.session_state` for shared filter values across pages
- Plotly charts use `st.plotly_chart(fig, use_container_width=True)`
- Streamlit re-runs the whole script on every interaction — keep expensive queries cached with `@st.cache_data`

---

### Sub-Task 8 — Sample Dataset
**Status:** [x] done

**Intent:** Generate a realistic synthetic dataset (`data/sample_data.csv`) with 500–1000 rows covering at least 12 months, multiple regions, categories, and customers. Clearly labelled as synthetic.

**Expected Outcomes:**
- File saved at `data/sample_data.csv`
- Contains all 11 required columns (including `transaction_id`)
- `transaction_id` values are globally unique (e.g. `TXN-00001`)
- `order_id` values are shared across multiple rows to represent multi-product orders (e.g. `ORD-00042` appears 2–4 times with different products)
- Covers Jan 2023 – Dec 2023 (12 months)
- Includes 5+ product categories, 4 regions, 50+ customers, 30+ products
- Contains some intentionally low-profit products and one declining sales trend for insights demo
- A header comment or README note labels data as synthetic

**Todo List:**
1. Write a Python generation script (`data/generate_sample.py`) using `numpy.random` with a fixed seed
2. Generate orders first (each order gets 1–4 product line items), then assign `transaction_id` to each row
3. Include deliberate anomalies: 2 products with negative margin, 1 month with revenue drop > 20%
4. Save output to `data/sample_data.csv`
5. Verify the file loads cleanly through `data_loader.py` and `data_validation.py`
6. Verify that COUNT(DISTINCT order_id) < total row count (confirming multi-line orders exist)

---

### Sub-Task 9 — Tests, Security Review & UI Polish
**Status:** [x] done

**Intent:** Run the full test suite, address security concerns, and apply final UI improvements.

**Expected Outcomes:**
- All pytest tests pass with no warnings
- No raw SQL string interpolation anywhere
- Uploaded files are validated for extension and size before processing
- No secrets or credentials in code
- UI has consistent colour scheme, readable fonts, and no layout breakage on common screen sizes

**Todo List:**
1. Run `pytest tests/` and fix all failures
2. Audit all SQL queries for parameterization
3. Add file extension whitelist check in `data_loader.py`
4. Add max file size check (e.g. 50 MB) with user-facing message
5. Review all hardcoded paths and replace with `pathlib.Path` relative paths
6. Apply consistent Streamlit theme via `.streamlit/config.toml`
7. Final manual walkthrough of all 7 pages with sample data loaded

---

### Sub-Task 10 — README & Setup Instructions
**Status:** [x] done

**Intent:** Write a complete `README.md` with installation, configuration, and usage instructions.

**Expected Outcomes:**
- README covers: prerequisites, installation, running the app, loading sample data, running tests
- Includes a brief description of each page
- Documents the dataset schema and KPI formulas
- Notes the SQLite single-user limitation
- Labels sample data as synthetic

**Todo List:**
1. Write prerequisites section (Python 3.9 or newer, pip) — note that `typing.Optional` is used instead of `X | None` union syntax throughout to maintain 3.9 compatibility
2. Write installation steps (`pip install -r requirements.txt`)
3. Write run instructions (`streamlit run app.py`)
4. Document dataset schema
5. Document how to load sample data
6. Document how to run tests (`pytest tests/`)
7. Add known limitations section

---

## Design Decisions & Risk Register

| Risk | Decision |
|------|----------|
| Large CSV uploads | Warn and reject files > 50 MB; stream smaller files |
| True duplicate rows | Deduplicate on transaction_id at load time using INSERT OR IGNORE on PRIMARY KEY |
| Multi-product orders misidentified as duplicates | Deduplication is ONLY on transaction_id — shared order_id is valid and expected |
| Incorrect Total Orders count | Always use COUNT(DISTINCT order_id) / df["order_id"].nunique() — never COUNT(*) |
| Zero revenue division | All ratio metrics use safe_divide returning 0.0 not NaN |
| PDF generation availability | fpdf2 used; graceful fallback if not installed |
| ML scope creep | All ML stays in an optional, clearly labelled section |
| SQLite concurrency | Single-user assumption documented in README |
| Fabricated insights | Every insight message cites its computed metric value |
