"""
src/live_api.py
---------------
Optional live API integration for the Smart Business Data Analytics Platform.

This module fetches transaction data from a configurable REST API endpoint,
validates it using the existing data_validation pipeline, and inserts new
records into the SQLite database via the existing insert_transactions function.

The integration is entirely OPTIONAL and OFF by default.  The CSV/Excel upload
workflow is unaffected.

Configuration (environment variables)
--------------------------------------
LIVE_API_ENABLED          "true" to enable; anything else (or absent) = disabled
LIVE_API_URL              Full URL returning a JSON array or paginated JSON
LIVE_API_TOKEN            Bearer token (optional; omit if the API is public)
LIVE_API_TIMEOUT_SECONDS  Request timeout in seconds (default: 30)

All four values are loaded from the environment at import time.  When python-dotenv
is installed a .env file in the project root is loaded automatically.

Expected JSON response format
------------------------------
The API must return one of:

  A) A JSON array of transaction objects:
       [{"transaction_id": "T1", "order_id": "O1", ...}, ...]

  B) A JSON object with a key whose value is the array, e.g.:
       {"data": [...], "next_page": "..."}
     In this case set LIVE_API_DATA_KEY to the key name (default: "data").
     Pagination is supported: if the response contains a "next" or "next_page"
     key, subsequent pages are fetched automatically until exhausted or a safety
     limit is reached.

Every object in the array must contain (at minimum) the 11 required transaction
schema fields.  Extra fields are silently ignored.

Security notes
--------------
- Tokens are read from environment variables only; never logged or displayed.
- Requests use parameterized timeouts; unbounded reads are not permitted.
- All inserted SQL uses existing parameterized placeholders from database.py.
- Malformed responses, HTTP errors, and timeouts are caught; exceptions never
  propagate raw API data or credentials to the UI.

Idempotency
-----------
INSERT OR IGNORE is used (via insert_transactions), so re-fetching the same
transaction_id is harmless — the existing record is kept and the row is counted
in skipped_duplicate.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import pandas as pd
import requests

# Load .env if python-dotenv is installed (optional dependency)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

# Pagination safety: never fetch more than this many pages in one sync call
_MAX_PAGES = 100

# Column name in a JSON-object response that holds the array of transactions
_DEFAULT_DATA_KEY = "data"


class LiveApiConfig(NamedTuple):
    """
    Resolved configuration for the live API integration.

    Attributes
    ----------
    enabled : bool
        True when LIVE_API_ENABLED=true in the environment.
    url : str
        The API endpoint URL (empty string when not set).
    has_token : bool
        True when LIVE_API_TOKEN is set (token value is never exposed).
    timeout : int
        Request timeout in seconds.
    data_key : str
        JSON key whose value is the transaction array when the API returns a
        wrapper object instead of a bare array.
    """

    enabled: bool
    url: str
    has_token: bool
    timeout: int
    data_key: str


def load_config() -> LiveApiConfig:
    """
    Read all live-API settings from environment variables.

    Returns a LiveApiConfig.  Token value is NOT stored in the config — only
    whether one was provided (has_token).  Call ``_get_token()`` separately
    when the actual value is needed for a request.
    """
    enabled_raw = os.environ.get("LIVE_API_ENABLED", "false").strip().lower()
    url = os.environ.get("LIVE_API_URL", "").strip()
    token = os.environ.get("LIVE_API_TOKEN", "").strip()
    timeout_raw = os.environ.get("LIVE_API_TIMEOUT_SECONDS", "30").strip()
    data_key = os.environ.get("LIVE_API_DATA_KEY", _DEFAULT_DATA_KEY).strip()

    try:
        timeout = int(timeout_raw)
        if timeout <= 0:
            timeout = 30
    except ValueError:
        timeout = 30

    return LiveApiConfig(
        enabled=enabled_raw == "true",
        url=url,
        has_token=bool(token),
        timeout=timeout,
        data_key=data_key,
    )


def _get_token() -> str:
    """Return the raw token string (empty string if not set)."""
    return os.environ.get("LIVE_API_TOKEN", "").strip()


# ── SyncResult ─────────────────────────────────────────────────────────────────


class SyncResult(NamedTuple):
    """
    Outcome of a single sync attempt.

    Attributes
    ----------
    success : bool
        True when the HTTP request succeeded and data was processed.
    records_fetched : int
        Number of raw records returned by the API (before validation).
    inserted : int
        Rows written to the database this sync.
    skipped_duplicate : int
        Rows already in the database (INSERT OR IGNORE).
    rejected_invalid : int
        Rows removed by the validation layer.
    error_message : str
        Human-readable error description (empty on success).  Never contains
        the token, raw HTTP body, or other sensitive data.
    fetched_at : float
        Unix timestamp of the sync attempt (time.time()).
    pages_fetched : int
        Number of HTTP pages requested.
    """

    success: bool
    records_fetched: int
    inserted: int
    skipped_duplicate: int
    rejected_invalid: int
    error_message: str
    fetched_at: float
    pages_fetched: int


def _empty_result(error: str, fetched_at: Optional[float] = None) -> SyncResult:
    """Return a failed SyncResult with zero counts."""
    return SyncResult(
        success=False,
        records_fetched=0,
        inserted=0,
        skipped_duplicate=0,
        rejected_invalid=0,
        error_message=error,
        fetched_at=fetched_at if fetched_at is not None else time.time(),
        pages_fetched=0,
    )


# ── HTTP fetching ──────────────────────────────────────────────────────────────


def _build_headers(token: str) -> Dict[str, str]:
    """Return request headers.  Token is sent as Bearer auth if provided."""
    headers: Dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _extract_records(
    payload: Any,
    data_key: str,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Parse the API response payload into a list of record dicts and an
    optional URL for the next page.

    Supports two response shapes:
    - Bare list:  [{"transaction_id": ...}, ...]
    - Wrapped:    {"data": [...], "next": "https://..."}
                  The key name is configurable via LIVE_API_DATA_KEY.

    Returns
    -------
    (records, next_url)
        records  – list of raw dicts
        next_url – next page URL, or None when no further pages exist
    """
    if isinstance(payload, list):
        return payload, None

    if isinstance(payload, dict):
        records = payload.get(data_key, [])
        if not isinstance(records, list):
            records = []
        # Try common pagination key names
        next_url: Optional[str] = (
            payload.get("next")
            or payload.get("next_page")
            or payload.get("next_url")
            or None
        )
        return records, next_url

    return [], None


def fetch_raw_records(config: LiveApiConfig) -> Tuple[List[Dict[str, Any]], int, str]:
    """
    Fetch all pages from the API and return (records, pages_fetched, error).

    On any HTTP / network / JSON error this returns ([], pages_fetched, error_message).
    Error messages never include the token, raw response body, or stack traces.
    """
    token = _get_token()
    headers = _build_headers(token)
    all_records: List[Dict[str, Any]] = []
    pages = 0
    url: Optional[str] = config.url

    while url and pages < _MAX_PAGES:
        try:
            response = requests.get(url, headers=headers, timeout=config.timeout)
        except requests.exceptions.Timeout:
            return all_records, pages, f"Request timed out after {config.timeout}s."
        except requests.exceptions.ConnectionError:
            return all_records, pages, "Could not connect to the API endpoint."
        except requests.exceptions.RequestException as exc:
            # Log the type but not the message (may contain URL with embedded token)
            logger.warning("API request failed: %s", type(exc).__name__)
            return all_records, pages, "Network error while contacting the API."

        pages += 1

        # Handle Retry-After
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            return all_records, pages, f"Rate limited by API (Retry-After: {retry_after})."

        if not response.ok:
            return all_records, pages, f"API returned HTTP {response.status_code}."

        try:
            payload = response.json()
        except ValueError:
            return all_records, pages, "API response was not valid JSON."

        page_records, next_url = _extract_records(payload, config.data_key)
        all_records.extend(page_records)
        url = next_url

    return all_records, pages, ""


# ── Sync orchestrator ──────────────────────────────────────────────────────────


def sync_from_api(config: Optional[LiveApiConfig] = None) -> SyncResult:
    """
    Run a full sync cycle: fetch → validate → insert.

    This is the single public entry point for a sync.  It:
    1. Checks that the integration is enabled and the URL is configured.
    2. Fetches all pages from the API.
    3. Converts the raw records to a DataFrame.
    4. Runs the existing validate_dataframe() pipeline.
    5. Calls insert_transactions() (INSERT OR IGNORE — idempotent).
    6. Returns a SyncResult with all counts.

    No exceptions propagate to the caller; all errors are captured in
    SyncResult.error_message.
    """
    fetched_at = time.time()

    if config is None:
        config = load_config()

    if not config.enabled:
        return _empty_result("Live API integration is disabled.", fetched_at)

    if not config.url:
        return _empty_result("LIVE_API_URL is not configured.", fetched_at)

    # Fetch
    raw_records, pages_fetched, fetch_error = fetch_raw_records(config)

    if fetch_error:
        return SyncResult(
            success=False,
            records_fetched=len(raw_records),
            inserted=0,
            skipped_duplicate=0,
            rejected_invalid=0,
            error_message=fetch_error,
            fetched_at=fetched_at,
            pages_fetched=pages_fetched,
        )

    if not raw_records:
        # Empty response is not an error; nothing to insert
        logger.info("Live API sync: 0 records returned.")
        return SyncResult(
            success=True,
            records_fetched=0,
            inserted=0,
            skipped_duplicate=0,
            rejected_invalid=0,
            error_message="",
            fetched_at=fetched_at,
            pages_fetched=pages_fetched,
        )

    # Convert to DataFrame and validate using the existing pipeline
    try:
        df_raw = pd.DataFrame(raw_records)
        # Normalise column names the same way data_loader does
        df_raw.columns = [str(c).strip().lower().replace(" ", "_") for c in df_raw.columns]
    except Exception:
        return _empty_result("Could not convert API response to a table.", fetched_at)

    from src.data_validation import validate_dataframe
    from src.database import insert_transactions

    try:
        df_clean, report = validate_dataframe(df_raw)
    except Exception:
        return _empty_result("Validation pipeline raised an unexpected error.", fetched_at)

    rejected = (
        report["duplicate_transaction_ids_removed"]
        + report["rows_dropped_missing_required"]
    )

    if report["missing_columns"]:
        missing_str = ", ".join(report["missing_columns"])
        return SyncResult(
            success=False,
            records_fetched=len(raw_records),
            inserted=0,
            skipped_duplicate=0,
            rejected_invalid=len(raw_records),
            error_message=f"API response is missing required fields: {missing_str}",
            fetched_at=fetched_at,
            pages_fetched=pages_fetched,
        )

    try:
        db_result = insert_transactions(df_clean, rejected_invalid=rejected)
    except Exception:
        return _empty_result("Database insert failed.", fetched_at)

    logger.info(
        "Live API sync complete: fetched=%d inserted=%d skipped=%d rejected=%d",
        len(raw_records),
        db_result.inserted,
        db_result.skipped_duplicate,
        db_result.rejected_invalid,
    )

    return SyncResult(
        success=True,
        records_fetched=len(raw_records),
        inserted=db_result.inserted,
        skipped_duplicate=db_result.skipped_duplicate,
        rejected_invalid=db_result.rejected_invalid,
        error_message="",
        fetched_at=fetched_at,
        pages_fetched=pages_fetched,
    )


# ── Streamlit session-state helpers ───────────────────────────────────────────

# Key names used in st.session_state for the live API panel
SYNC_RESULT_KEY = "live_api_last_result"
LAST_SYNC_TIME_KEY = "live_api_last_sync_time"
REFRESH_INTERVAL_SECONDS = 60


def should_auto_refresh(last_sync_time: Optional[float]) -> bool:
    """
    Return True when the auto-refresh interval has elapsed since the last sync.

    Parameters
    ----------
    last_sync_time : float or None
        Unix timestamp of the previous sync (time.time()), or None if no sync
        has ever run.
    """
    if last_sync_time is None:
        return True
    return (time.time() - last_sync_time) >= REFRESH_INTERVAL_SECONDS
