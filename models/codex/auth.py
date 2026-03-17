from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"

CODEX_DIR = Path.home() / ".codex"
CODEX_AUTH_PATH = CODEX_DIR / "auth.json"


@dataclass
class AccountInfo:
    email: Optional[str]
    account_id: Optional[str]
    plan_type: Optional[str]


class AuthError(RuntimeError):
    pass


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_jwt_claims(token: str) -> Dict[str, Any]:
    """Decode JWT payload without signature verification."""
    if not token or "." not in token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        payload = _b64url_decode(parts[1])
        return json.loads(payload.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return {}


def extract_account_info(id_token: Optional[str], access_token: Optional[str]) -> AccountInfo:
    id_claims = decode_jwt_claims(id_token or "")
    access_claims = decode_jwt_claims(access_token or "")
    auth_claims = access_claims.get("https://api.openai.com/auth", {})

    email = (
        id_claims.get("email")
        or auth_claims.get("chatgpt_email")
        or access_claims.get("email")
        or auth_claims.get("email")
    )
    account_id = (
        auth_claims.get("chatgpt_account_id")
        or access_claims.get("chatgpt_account_id")
        or id_claims.get("chatgpt_account_id")
    )
    plan_type = (
        auth_claims.get("chatgpt_plan_type")
        or access_claims.get("chatgpt_plan_type")
        or id_claims.get("chatgpt_plan_type")
    )

    return AccountInfo(email=email, account_id=account_id, plan_type=plan_type)


def is_token_expired(token: str, leeway_seconds: int = 60) -> bool:
    claims = decode_jwt_claims(token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return True
    return time.time() >= (float(exp) - leeway_seconds)


def refresh_token(refresh_token: str) -> Dict[str, Any]:
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        }
    ).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise AuthError(f"Token refresh failed: HTTP {exc.code} {body}") from exc
    except urllib.error.URLError as exc:
        raise AuthError(f"Token refresh failed: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AuthError("Token refresh returned invalid JSON") from exc


def ensure_fresh_tokens(tokens: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    access_token = tokens.get("access_token")
    refresh_token_value = tokens.get("refresh_token")
    if not access_token or not refresh_token_value:
        raise AuthError("Missing access_token or refresh_token")

    if not force and not is_token_expired(access_token, leeway_seconds=300):
        return tokens

    refreshed = refresh_token(refresh_token_value)
    new_tokens = {
        "access_token": refreshed.get("access_token"),
        "refresh_token": refreshed.get("refresh_token"),
        "id_token": refreshed.get("id_token") or tokens.get("id_token"),
        "account_id": tokens.get("account_id"),
    }

    if not new_tokens["access_token"] or not new_tokens["refresh_token"]:
        raise AuthError("Token refresh did not return new access/refresh tokens")

    return new_tokens


def read_codex_auth() -> Dict[str, Any]:
    with CODEX_AUTH_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_codex_auth(tokens: Dict[str, Any]) -> None:
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    auth_data = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": tokens.get("id_token"),
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "account_id": tokens.get("account_id"),
        },
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    tmp_path = CODEX_AUTH_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, CODEX_AUTH_PATH)
    os.chmod(CODEX_AUTH_PATH, 0o600)
