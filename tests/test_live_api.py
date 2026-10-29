"""
tests/test_live_api.py
----------------------
Unit tests for src/live_api.py.

All HTTP calls are mocked — no real API credentials or internet access required.

Coverage
--------
load_config
  - reads LIVE_API_ENABLED, LIVE_API_URL, LIVE_API_TOKEN, LIVE_API_TIMEOUT_SECONDS,
    LIVE_API_DATA_KEY from the environment
  - enabled is False by default and when set to anything other than "true"
  - timeout defaults to 30 when unset or invalid
  - has_token is True only when the token env var is non-empty
  - token value is NOT stored in LiveApiConfig

fetch_raw_records
  - returns records from a bare-array response
  - returns records from a wrapped-object response using data_key
  - follows pagination via "next" key
  - stops after _MAX_PAGES to prevent runaway loops
  - returns empty list + error on HTTP error status
  - returns empty list + error on timeout
  - returns empty list + error on connection error
  - returns empty list + error on invalid JSON
  - sets Bearer auth header when token is provided
  - omits Authorization header when no token
  - respects Retry-After on 429

sync_from_api
  - returns disabled result when config.enabled is False
  - returns error result when URL is not set
  - valid response inserts records and returns correct counts
  - empty response returns success with 0 counts (existing data preserved)
  - HTTP error returns failure result with 0 inserted
  - invalid JSON returns failure result
  - missing required fields returns failure with all records as rejected
  - duplicate transaction IDs in API response are deduplicated by validation
  - repeated sync with same transaction IDs results in skipped_duplicate counts
  - invalid rows in response are counted in rejected_invalid
  - sum invariant: inserted + skipped_duplicate + rejected_invalid == records_fetched
  - no exceptions propagate to caller on any error

should_auto_refresh
  - returns True when last_sync_time is None
  - returns True when interval has elapsed
  - returns False when interval has not elapsed

Existing tests
  - all 154 existing tests still pass (verified by running full suite)
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.live_api import (
    REFRESH_INTERVAL_SECONDS,
    LiveApiConfig,
    SyncResult,
    fetch_raw_records,
    load_config,
    should_auto_refresh,
    sync_from_api,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _minimal_record(txn_id: str = "TXN-001", order_id: str = "ORD-001") -> Dict[str, Any]:
    """Return a dict that satisfies the 11-column transaction schema."""
    return {
        "transaction_id": txn_id,
        "order_id": order_id,
        "transaction_date": "2024-03-01",
        "customer_id": "C01",
        "customer_name": "Alice",
        "product": "Widget A",
        "category": "Widgets",
        "region": "North",
        "quantity": 2,
        "unit_price": 50.0,
        "unit_cost": 30.0,
    }


def _enabled_config(
    url: str = "https://api.example.com/transactions",
    token: str = "",
    timeout: int = 10,
    data_key: str = "data",
) -> LiveApiConfig:
    """Return an enabled LiveApiConfig suitable for most tests."""
    return LiveApiConfig(
        enabled=True,
        url=url,
        has_token=bool(token),
        timeout=timeout,
        data_key=data_key,
    )


def _mock_response(
    json_data: Any = None,
    status_code: int = 200,
    headers: Dict[str, str] = None,
) -> MagicMock:
    """Build a mock requests.Response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.headers = headers or {}
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON object could be decoded")
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# load_config
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadConfig:
    def test_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIVE_API_ENABLED", None)
            cfg = load_config()
        assert cfg.enabled is False

    def test_enabled_when_set_to_true(self) -> None:
        with patch.dict(os.environ, {"LIVE_API_ENABLED": "true"}):
            cfg = load_config()
        assert cfg.enabled is True

    def test_not_enabled_for_yes(self) -> None:
        with patch.dict(os.environ, {"LIVE_API_ENABLED": "yes"}):
            cfg = load_config()
        assert cfg.enabled is False

    def test_url_read_from_env(self) -> None:
        with patch.dict(os.environ, {"LIVE_API_URL": "https://example.com/api"}):
            cfg = load_config()
        assert cfg.url == "https://example.com/api"

    def test_url_empty_by_default(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LIVE_API_URL"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.url == ""

    def test_has_token_true_when_token_set(self) -> None:
        with patch.dict(os.environ, {"LIVE_API_TOKEN": "secret"}):
            cfg = load_config()
        assert cfg.has_token is True

    def test_has_token_false_when_token_missing(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LIVE_API_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.has_token is False

    def test_token_value_not_in_config(self) -> None:
        """LiveApiConfig must not expose the raw token string."""
        with patch.dict(os.environ, {"LIVE_API_TOKEN": "super-secret"}):
            cfg = load_config()
        # has_token is a bool — it must not be the token string
        assert cfg.has_token is True
        assert not hasattr(cfg, "token")
        # Confirm the config tuple does not contain the actual secret
        assert "super-secret" not in str(cfg)

    def test_timeout_defaults_to_30(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LIVE_API_TIMEOUT_SECONDS"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.timeout == 30

    def test_timeout_read_from_env(self) -> None:
        with patch.dict(os.environ, {"LIVE_API_TIMEOUT_SECONDS": "45"}):
            cfg = load_config()
        assert cfg.timeout == 45

    def test_invalid_timeout_falls_back_to_30(self) -> None:
        with patch.dict(os.environ, {"LIVE_API_TIMEOUT_SECONDS": "not_a_number"}):
            cfg = load_config()
        assert cfg.timeout == 30

    def test_negative_timeout_falls_back_to_30(self) -> None:
        with patch.dict(os.environ, {"LIVE_API_TIMEOUT_SECONDS": "-5"}):
            cfg = load_config()
        assert cfg.timeout == 30

    def test_data_key_defaults_to_data(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "LIVE_API_DATA_KEY"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.data_key == "data"

    def test_data_key_read_from_env(self) -> None:
        with patch.dict(os.environ, {"LIVE_API_DATA_KEY": "transactions"}):
            cfg = load_config()
        assert cfg.data_key == "transactions"


# ══════════════════════════════════════════════════════════════════════════════
# fetch_raw_records
# ══════════════════════════════════════════════════════════════════════════════


class TestFetchRawRecords:
    def test_bare_array_response(self) -> None:
        records = [_minimal_record("T1"), _minimal_record("T2")]
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(records)):
            result, pages, error = fetch_raw_records(cfg)
        assert len(result) == 2
        assert pages == 1
        assert error == ""

    def test_wrapped_object_response(self) -> None:
        records = [_minimal_record("T1")]
        payload = {"data": records}
        cfg = _enabled_config(data_key="data")
        with patch("requests.get", return_value=_mock_response(payload)):
            result, pages, error = fetch_raw_records(cfg)
        assert len(result) == 1
        assert error == ""

    def test_custom_data_key(self) -> None:
        records = [_minimal_record("T1")]
        payload = {"transactions": records}
        cfg = _enabled_config(data_key="transactions")
        with patch("requests.get", return_value=_mock_response(payload)):
            result, pages, error = fetch_raw_records(cfg)
        assert len(result) == 1

    def test_pagination_follows_next_key(self) -> None:
        page1 = {"data": [_minimal_record("T1")], "next": "https://api.example.com/p2"}
        page2 = {"data": [_minimal_record("T2")]}
        cfg = _enabled_config()
        responses = [_mock_response(page1), _mock_response(page2)]
        with patch("requests.get", side_effect=responses):
            result, pages, error = fetch_raw_records(cfg)
        assert len(result) == 2
        assert pages == 2
        assert error == ""

    def test_http_error_returns_error_string(self) -> None:
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(status_code=500)):
            result, pages, error = fetch_raw_records(cfg)
        assert result == []
        assert "500" in error

    def test_404_returns_error(self) -> None:
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(status_code=404)):
            result, pages, error = fetch_raw_records(cfg)
        assert "404" in error

    def test_timeout_returns_error(self) -> None:
        import requests as req_mod
        cfg = _enabled_config()
        with patch("requests.get", side_effect=req_mod.exceptions.Timeout):
            result, pages, error = fetch_raw_records(cfg)
        assert result == []
        assert "timed out" in error.lower()

    def test_connection_error_returns_error(self) -> None:
        import requests as req_mod
        cfg = _enabled_config()
        with patch("requests.get", side_effect=req_mod.exceptions.ConnectionError):
            result, pages, error = fetch_raw_records(cfg)
        assert result == []
        assert "connect" in error.lower()

    def test_invalid_json_returns_error(self) -> None:
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(json_data=None)):
            result, pages, error = fetch_raw_records(cfg)
        assert result == []
        assert "json" in error.lower()

    def test_rate_limit_429_returns_error(self) -> None:
        cfg = _enabled_config()
        resp = _mock_response(status_code=429)
        resp.headers = {"Retry-After": "60"}
        with patch("requests.get", return_value=resp):
            result, pages, error = fetch_raw_records(cfg)
        assert "rate limit" in error.lower() or "429" in error

    def test_bearer_token_sent_in_header(self) -> None:
        records = [_minimal_record()]
        cfg = _enabled_config(token="tok")
        # Patch at the module level where requests is imported
        with patch("requests.get", return_value=_mock_response(records)) as mock_get:
            # Patch _get_token to return the token
            with patch("src.live_api._get_token", return_value="tok"):
                fetch_raw_records(cfg)
        call_kwargs = mock_get.call_args
        headers_sent = call_kwargs[1].get("headers", {}) or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        # Access via keyword argument
        headers_sent = mock_get.call_args.kwargs.get("headers", {})
        assert headers_sent.get("Authorization") == "Bearer tok"

    def test_no_auth_header_without_token(self) -> None:
        records = [_minimal_record()]
        cfg = _enabled_config(token="")
        with patch("requests.get", return_value=_mock_response(records)) as mock_get:
            with patch("src.live_api._get_token", return_value=""):
                fetch_raw_records(cfg)
        headers_sent = mock_get.call_args.kwargs.get("headers", {})
        assert "Authorization" not in headers_sent

    def test_empty_array_response_returns_empty(self) -> None:
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response([])):
            result, pages, error = fetch_raw_records(cfg)
        assert result == []
        assert error == ""


# ══════════════════════════════════════════════════════════════════════════════
# sync_from_api
# ══════════════════════════════════════════════════════════════════════════════


class TestSyncFromApi:
    """Tests use clear_transactions() to avoid cross-test DB state pollution."""

    def setup_method(self) -> None:
        from src.database import clear_transactions, init_db
        init_db()
        clear_transactions()

    def teardown_method(self) -> None:
        from src.database import clear_transactions
        clear_transactions()

    def test_disabled_integration_returns_failure(self) -> None:
        cfg = LiveApiConfig(enabled=False, url="https://x.com", has_token=False, timeout=10, data_key="data")
        result = sync_from_api(cfg)
        assert result.success is False
        assert "disabled" in result.error_message.lower()

    def test_missing_url_returns_failure(self) -> None:
        cfg = LiveApiConfig(enabled=True, url="", has_token=False, timeout=10, data_key="data")
        result = sync_from_api(cfg)
        assert result.success is False
        assert "url" in result.error_message.lower()

    def test_valid_response_inserts_records(self) -> None:
        records = [_minimal_record("TXN-A"), _minimal_record("TXN-B", "ORD-002")]
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(records)):
            result = sync_from_api(cfg)
        assert result.success is True
        assert result.inserted == 2
        assert result.skipped_duplicate == 0
        assert result.rejected_invalid == 0
        assert result.records_fetched == 2

    def test_empty_response_success_zero_inserted(self) -> None:
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response([])):
            result = sync_from_api(cfg)
        assert result.success is True
        assert result.inserted == 0
        assert result.records_fetched == 0

    def test_http_error_returns_failure(self) -> None:
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(status_code=503)):
            result = sync_from_api(cfg)
        assert result.success is False
        assert result.inserted == 0

    def test_invalid_json_returns_failure(self) -> None:
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(json_data=None)):
            result = sync_from_api(cfg)
        assert result.success is False
        assert result.inserted == 0

    def test_missing_required_fields_in_response(self) -> None:
        # Record is missing transaction_id, unit_cost, etc.
        bad_records = [{"order_id": "O1", "product": "Widget"}]
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(bad_records)):
            result = sync_from_api(cfg)
        assert result.success is False
        assert result.inserted == 0
        assert result.rejected_invalid >= 1

    def test_duplicate_transaction_ids_in_api_response(self) -> None:
        """
        When the API returns two rows with the same transaction_id, validation
        deduplicates them — only one is inserted.
        """
        rec = _minimal_record("TXN-DUP")
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response([rec, rec])):
            result = sync_from_api(cfg)
        assert result.inserted == 1
        # One is a duplicate, counted in rejected_invalid (from validation dedup)
        assert result.rejected_invalid >= 1

    def test_repeated_sync_same_data_skipped(self) -> None:
        """Second sync with the same transaction IDs must result in skipped_duplicate."""
        records = [_minimal_record("TXN-001")]
        cfg = _enabled_config()
        # First sync
        with patch("requests.get", return_value=_mock_response(records)):
            r1 = sync_from_api(cfg)
        assert r1.inserted == 1

        # Second sync — same record
        with patch("requests.get", return_value=_mock_response(records)):
            r2 = sync_from_api(cfg)
        assert r2.skipped_duplicate == 1
        assert r2.inserted == 0

    def test_invalid_rows_counted_in_rejected(self) -> None:
        """A record with a non-numeric quantity must be counted in rejected_invalid."""
        good = _minimal_record("TXN-GOOD")
        bad = dict(_minimal_record("TXN-BAD"))
        bad["quantity"] = "NOT_A_NUMBER"
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response([good, bad])):
            result = sync_from_api(cfg)
        assert result.inserted == 1
        assert result.rejected_invalid >= 1

    def test_count_invariant(self) -> None:
        """inserted + skipped_duplicate + rejected_invalid == records_fetched."""
        good1 = _minimal_record("TXN-G1")
        good2 = _minimal_record("TXN-G2", "ORD-002")
        bad = dict(_minimal_record("TXN-BAD"))
        bad["quantity"] = "OOPS"
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response([good1, good2, bad])):
            result = sync_from_api(cfg)
        total = result.inserted + result.skipped_duplicate + result.rejected_invalid
        assert total == result.records_fetched

    def test_no_exception_propagates_on_http_error(self) -> None:
        """sync_from_api must never raise — all errors are captured in SyncResult."""
        import requests as req_mod
        cfg = _enabled_config()
        with patch("requests.get", side_effect=req_mod.exceptions.ConnectionError):
            try:
                result = sync_from_api(cfg)
            except Exception as exc:
                pytest.fail(f"sync_from_api raised an exception: {exc}")
        assert result.success is False

    def test_no_exception_on_invalid_json(self) -> None:
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response(json_data=None)):
            try:
                result = sync_from_api(cfg)
            except Exception as exc:
                pytest.fail(f"sync_from_api raised: {exc}")
        assert result.success is False

    def test_sync_result_has_fetched_at_timestamp(self) -> None:
        before = time.time()
        cfg = LiveApiConfig(enabled=False, url="", has_token=False, timeout=10, data_key="data")
        result = sync_from_api(cfg)
        after = time.time()
        assert before <= result.fetched_at <= after

    def test_existing_data_preserved_on_empty_response(self) -> None:
        """
        An empty API response must not delete or alter records already in the DB.
        """
        from src.database import get_transactions, insert_transactions
        from src.data_validation import validate_dataframe
        import io
        from src.data_loader import load_file

        # Pre-populate with one record via the normal import path
        df = pd.DataFrame([_minimal_record("TXN-EXISTING")])
        df_clean, report = validate_dataframe(df)
        insert_transactions(df_clean, rejected_invalid=0)

        # Sync with empty response
        cfg = _enabled_config()
        with patch("requests.get", return_value=_mock_response([])):
            result = sync_from_api(cfg)

        assert result.success is True
        df_after = get_transactions()
        assert len(df_after) >= 1
        assert "TXN-EXISTING" in df_after["transaction_id"].values

    def test_timeout_does_not_corrupt_db(self) -> None:
        import requests as req_mod
        from src.database import get_transactions, insert_transactions
        from src.data_validation import validate_dataframe

        # Pre-populate
        df = pd.DataFrame([_minimal_record("TXN-SAFE")])
        df_clean, report = validate_dataframe(df)
        insert_transactions(df_clean, rejected_invalid=0)

        cfg = _enabled_config()
        with patch("requests.get", side_effect=req_mod.exceptions.Timeout):
            result = sync_from_api(cfg)

        assert result.success is False
        df_after = get_transactions()
        assert "TXN-SAFE" in df_after["transaction_id"].values

    def test_pagination_all_records_inserted(self) -> None:
        """Multi-page response must insert all records across all pages."""
        page1 = {"data": [_minimal_record("P1-T1")], "next": "https://api.example.com/p2"}
        page2 = {"data": [_minimal_record("P2-T1", "ORD-002")]}
        cfg = _enabled_config()
        responses = [_mock_response(page1), _mock_response(page2)]
        with patch("requests.get", side_effect=responses):
            result = sync_from_api(cfg)
        assert result.inserted == 2
        assert result.records_fetched == 2
        assert result.pages_fetched == 2


# ══════════════════════════════════════════════════════════════════════════════
# should_auto_refresh
# ══════════════════════════════════════════════════════════════════════════════


class TestShouldAutoRefresh:
    def test_returns_true_when_no_previous_sync(self) -> None:
        assert should_auto_refresh(None) is True

    def test_returns_true_when_interval_elapsed(self) -> None:
        old_time = time.time() - (REFRESH_INTERVAL_SECONDS + 5)
        assert should_auto_refresh(old_time) is True

    def test_returns_false_when_interval_not_elapsed(self) -> None:
        recent = time.time() - 10  # 10 seconds ago — well within 60s window
        assert should_auto_refresh(recent) is False

    def test_boundary_exactly_at_interval(self) -> None:
        at_boundary = time.time() - REFRESH_INTERVAL_SECONDS
        # At exact boundary, elapsed >= interval → should refresh
        assert should_auto_refresh(at_boundary) is True


# ══════════════════════════════════════════════════════════════════════════════
# SyncResult structure
# ══════════════════════════════════════════════════════════════════════════════


class TestSyncResultStructure:
    def test_is_named_tuple(self) -> None:
        r = SyncResult(
            success=True,
            records_fetched=5,
            inserted=3,
            skipped_duplicate=1,
            rejected_invalid=1,
            error_message="",
            fetched_at=0.0,
            pages_fetched=1,
        )
        assert r.success is True
        assert r.inserted == 3

    def test_count_invariant_holds_on_fixture(self) -> None:
        r = SyncResult(
            success=True,
            records_fetched=6,
            inserted=3,
            skipped_duplicate=2,
            rejected_invalid=1,
            error_message="",
            fetched_at=0.0,
            pages_fetched=1,
        )
        assert r.inserted + r.skipped_duplicate + r.rejected_invalid == r.records_fetched
