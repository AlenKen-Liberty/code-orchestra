import json
import time
import urllib.error
from unittest import mock

import pytest
from models.codex.auth import (
    AuthError,
    decode_jwt_claims,
    ensure_fresh_tokens,
    extract_account_info,
    is_token_expired,
    refresh_token,
)


def test_decode_jwt_claims_valid():
    # Header: {"alg": "HS256", "typ": "JWT"} -> eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9
    # Payload: {"email": "test@example.com"} -> eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20ifQ
    # Signature: dummy
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20ifQ.dummy_signature"
    claims = decode_jwt_claims(token)
    assert claims == {"email": "test@example.com"}


def test_decode_jwt_claims_invalid():
    assert decode_jwt_claims("") == {}
    assert decode_jwt_claims("invalid_token") == {}
    assert decode_jwt_claims("header.invalid_base64.sig") == {}
    assert decode_jwt_claims("header.eyJpbnZhbGlkX2pzb24iOiB0cnV.sig") == {}


def test_extract_account_info():
    # ID Token Payload: {"email": "id@example.com", "chatgpt_plan_type": "free"}
    id_token = "hdr.eyJlbWFpbCI6ICJpZEBleGFtcGxlLmNvbSIsICJjaGF0Z3B0X3BsYW5fdHlwZSI6ICJmcmVlIn0.sig"

    # Access Token Payload: {"https://api.openai.com/auth": {"chatgpt_account_id": "acc-123"}} -> eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOiB7ImNoYXRncHRfYWNjb3VudF9pZCI6ICJhY2MtMTIzIn19
    access_token = "hdr.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOiB7ImNoYXRncHRfYWNjb3VudF9pZCI6ICJhY2MtMTIzIn19.sig"

    info = extract_account_info(id_token, access_token)
    assert info.email == "id@example.com"
    assert info.account_id == "acc-123"
    assert info.plan_type == "free"


def test_extract_account_info_fallback():
    # Test fallback to standard claims if custom OpenAI claims are missing
    access_token = "hdr.eyJlbWFpbCI6ICJmYWxsYmFja0BleGFtcGxlLmNvbSJ9.sig"
    info = extract_account_info(None, access_token)
    assert info.email == "fallback@example.com"


def test_is_token_expired():
    # Expired token (exp = 100)
    expired_token = "hdr.eyJleHAiOiAxMDB9.sig"
    assert is_token_expired(expired_token) is True

    # Valid token (exp = current time + 3600)
    future_time = int(time.time()) + 3600
    valid_payload = json.dumps({"exp": future_time}).encode("utf-8")
    import base64
    valid_token = "hdr." + base64.urlsafe_b64encode(valid_payload).decode("utf-8").rstrip("=") + ".sig"
    assert is_token_expired(valid_token) is False

    # Invalid exp claim (not a number)
    invalid_exp_token = "hdr.eyJleHAiOiAiaW52YWxpZCJ9.sig"
    assert is_token_expired(invalid_exp_token) is True


@mock.patch("urllib.request.urlopen")
def test_refresh_token_success(mock_urlopen):
    mock_response = mock.MagicMock()
    mock_response.read.return_value = b'{"access_token": "new_access", "refresh_token": "new_refresh", "id_token": "new_id"}'
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = refresh_token("old_refresh")
    assert result == {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "id_token": "new_id",
    }


@mock.patch("urllib.request.urlopen")
def test_refresh_token_http_error(mock_urlopen):
    mock_error = urllib.error.HTTPError(
        url="https://auth.openai.com/oauth/token",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=mock.MagicMock(),
    )
    mock_error.read.return_value = b'{"error": "invalid_grant"}'
    mock_urlopen.side_effect = mock_error

    with pytest.raises(AuthError, match="Token refresh failed: HTTP 400"):
        refresh_token("invalid_refresh")


@mock.patch("urllib.request.urlopen")
def test_refresh_token_url_error(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

    with pytest.raises(AuthError, match="Token refresh failed: Connection refused"):
        refresh_token("refresh_token")


@mock.patch("urllib.request.urlopen")
def test_refresh_token_invalid_json(mock_urlopen):
    mock_response = mock.MagicMock()
    mock_response.read.return_value = b"invalid json data"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    with pytest.raises(AuthError, match="Token refresh returned invalid JSON"):
        refresh_token("refresh_token")


@mock.patch("models.codex.auth.refresh_token")
@mock.patch("models.codex.auth.is_token_expired")
def test_ensure_fresh_tokens_not_expired(mock_is_expired, mock_refresh):
    mock_is_expired.return_value = False
    tokens = {"access_token": "valid_access", "refresh_token": "valid_refresh"}

    result = ensure_fresh_tokens(tokens)
    assert result == tokens
    mock_refresh.assert_not_called()


@mock.patch("models.codex.auth.refresh_token")
@mock.patch("models.codex.auth.is_token_expired")
def test_ensure_fresh_tokens_force_refresh(mock_is_expired, mock_refresh):
    mock_is_expired.return_value = False
    tokens = {
        "access_token": "valid_access",
        "refresh_token": "valid_refresh",
        "id_token": "old_id",
        "account_id": "acc-123",
    }
    mock_refresh.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "id_token": "new_id",
    }

    result = ensure_fresh_tokens(tokens, force=True)
    assert result == {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "id_token": "new_id",
        "account_id": "acc-123",
    }
    mock_refresh.assert_called_once_with("valid_refresh")


@mock.patch("models.codex.auth.refresh_token")
@mock.patch("models.codex.auth.is_token_expired")
def test_ensure_fresh_tokens_expired(mock_is_expired, mock_refresh):
    mock_is_expired.return_value = True
    tokens = {"access_token": "expired_access", "refresh_token": "valid_refresh"}
    mock_refresh.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
    }

    result = ensure_fresh_tokens(tokens)
    assert result["access_token"] == "new_access"
    assert result["refresh_token"] == "new_refresh"
    mock_refresh.assert_called_once_with("valid_refresh")


def test_ensure_fresh_tokens_missing_tokens():
    with pytest.raises(AuthError, match="Missing access_token or refresh_token"):
        ensure_fresh_tokens({"access_token": "only_access"})

    with pytest.raises(AuthError, match="Missing access_token or refresh_token"):
        ensure_fresh_tokens({"refresh_token": "only_refresh"})


@mock.patch("models.codex.auth.refresh_token")
@mock.patch("models.codex.auth.is_token_expired")
def test_ensure_fresh_tokens_refresh_missing_new_tokens(mock_is_expired, mock_refresh):
    mock_is_expired.return_value = True
    tokens = {"access_token": "expired_access", "refresh_token": "valid_refresh"}
    # Refresh returns data without new tokens
    mock_refresh.return_value = {"other_data": "value"}

    with pytest.raises(AuthError, match="Token refresh did not return new access/refresh tokens"):
        ensure_fresh_tokens(tokens)
