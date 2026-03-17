from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, List

from .account import CodexAccount

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


class QuotaError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class CodexQuota:
    email: str
    plan_type: str
    weekly_used_percent: int
    weekly_reset_at: int
    weekly_limit_reached: bool
    burst_used_percent: int
    burst_reset_at: int
    code_review_used_percent: int
    code_review_reset_at: int
    raw: dict | None = None


def _get_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_quota(access_token: str, account_id: str) -> CodexQuota:
    req = urllib.request.Request(USAGE_URL, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    if account_id:
        req.add_header("ChatGPT-Account-Id", account_id)
    req.add_header("User-Agent", "CodexBar")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise QuotaError(f"Quota fetch failed: HTTP {exc.code} {body}", status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise QuotaError(f"Quota fetch failed: {exc.reason}") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise QuotaError("Quota response was not valid JSON") from exc

    rate_limit = data.get("rate_limit") or {}
    primary = rate_limit.get("primary_window") or {}
    secondary = rate_limit.get("secondary_window") or {}

    code_review = data.get("code_review_rate_limit") or {}
    code_primary = code_review.get("primary_window") or {}

    return CodexQuota(
        email=data.get("email") or "",
        plan_type=data.get("plan_type") or "unknown",
        weekly_used_percent=_get_int(primary.get("used_percent")),
        weekly_reset_at=_get_int(primary.get("reset_at")),
        weekly_limit_reached=bool(rate_limit.get("limit_reached", False)),
        burst_used_percent=_get_int(secondary.get("used_percent")),
        burst_reset_at=_get_int(secondary.get("reset_at")),
        code_review_used_percent=_get_int(code_primary.get("used_percent")),
        code_review_reset_at=_get_int(code_primary.get("reset_at")),
        raw=data,
    )


def fetch_all_quotas(accounts: List[CodexAccount]) -> List[CodexQuota]:
    if not accounts:
        return []

    results: List[CodexQuota] = []
    errors = []

    with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as executor:
        futures = {
            executor.submit(fetch_quota, account.access_token, account.account_id): account
            for account in accounts
        }
        for future in as_completed(futures):
            account = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # pragma: no cover - pass-through
                errors.append((account.email, exc))

    if errors:
        details = "; ".join(f"{email}: {exc}" for email, exc in errors)
        raise QuotaError(f"Failed to fetch quota for some accounts: {details}")

    return results
