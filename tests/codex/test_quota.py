import json
import urllib.error
from unittest import mock

import pytest
from models.codex.account import CodexAccount
from models.codex.quota import CodexQuota, QuotaError, fetch_all_quotas, fetch_quota


@pytest.fixture
def mock_usage_response():
    return {
        "email": "test@example.com",
        "plan_type": "free",
        "rate_limit": {
            "limit_reached": False,
            "primary_window": {
                "used_percent": 42,
                "reset_at": 1700000000,
            },
            "secondary_window": None,
        },
        "code_review_rate_limit": {
            "primary_window": {
                "used_percent": 10,
                "reset_at": 1700000001,
            }
        },
    }


@mock.patch("urllib.request.urlopen")
def test_fetch_quota_success(mock_urlopen, mock_usage_response):
    mock_resp = mock.MagicMock()
    mock_resp.read.return_value = json.dumps(mock_usage_response).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    quota = fetch_quota("fake_access", "fake_account_id")

    assert quota.email == "test@example.com"
    assert quota.plan_type == "free"
    assert quota.weekly_used_percent == 42
    assert quota.weekly_reset_at == 1700000000
    assert quota.weekly_limit_reached is False
    assert quota.burst_used_percent == 0
    assert quota.code_review_used_percent == 10
    assert quota.code_review_reset_at == 1700000001
    assert quota.raw == mock_usage_response


@mock.patch("urllib.request.urlopen")
def test_fetch_quota_http_error(mock_urlopen):
    mock_error = urllib.error.HTTPError(
        url="https://chatgpt.com/backend-api/wham/usage",
        code=403,
        msg="Forbidden",
        hdrs={},
        fp=mock.MagicMock(),
    )
    # Give the mock fp a working read() method that returns bytes so decode() works
    mock_error.read = mock.MagicMock(return_value=b"Custom error body")
    mock_urlopen.side_effect = mock_error

    with pytest.raises(QuotaError, match="Quota fetch failed: HTTP 403 Custom error body") as exc:
        fetch_quota("fake_access", "fake_account_id")
    assert exc.value.status_code == 403


@mock.patch("urllib.request.urlopen")
def test_fetch_quota_url_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("Connection reset by peer")

    with pytest.raises(QuotaError, match="Quota fetch failed: Connection reset by peer"):
        fetch_quota("fake_access", "fake_account_id")


@mock.patch("urllib.request.urlopen")
def test_fetch_quota_invalid_json(mock_urlopen):
    mock_resp = mock.MagicMock()
    mock_resp.read.return_value = b"<!DOCTYPE html><html>...</html>"
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    with pytest.raises(QuotaError, match="Quota response was not valid JSON"):
        fetch_quota("fake_access", "fake_account_id")


@mock.patch("models.codex.quota.fetch_quota")
def test_fetch_all_quotas_success(mock_fetch_quota):
    acc1 = CodexAccount("a@test", "tok1", "", "", "id1", "free", {}, False, 0, 0)
    acc2 = CodexAccount("b@test", "tok2", "", "", "id2", "plus", {}, False, 0, 0)

    q1 = CodexQuota("a@test", "free", 10, 0, False, 0, 0, 0, 0)
    q2 = CodexQuota("b@test", "plus", 20, 0, False, 0, 0, 0, 0)

    # Return q1 for a@test, q2 for b@test
    def mock_fetch(access, account_id):
        if access == "tok1":
            return q1
        return q2

    mock_fetch_quota.side_effect = mock_fetch

    results = fetch_all_quotas([acc1, acc2])
    assert len(results) == 2
    assert q1 in results
    assert q2 in results


@mock.patch("models.codex.quota.fetch_quota")
def test_fetch_all_quotas_partial_failure(mock_fetch_quota):
    acc1 = CodexAccount("a@test", "tok1", "", "", "id1", "free", {}, False, 0, 0)
    acc2 = CodexAccount("b@test", "tok2", "", "", "id2", "free", {}, False, 0, 0)

    def mock_fetch(access, account_id):
        if access == "tok1":
            return CodexQuota("a@test", "free", 10, 0, False, 0, 0, 0, 0)
        raise QuotaError("Simulated failure")

    mock_fetch_quota.side_effect = mock_fetch

    with pytest.raises(QuotaError, match="Failed to fetch quota for some accounts: b@test: Simulated failure"):
        fetch_all_quotas([acc1, acc2])
