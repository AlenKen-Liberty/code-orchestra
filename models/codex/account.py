from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import auth

CODEX_DIR = Path.home() / ".codex"
ACCOUNTS_DIR = CODEX_DIR / "accounts"
ACCOUNTS_INDEX_PATH = ACCOUNTS_DIR / "accounts.json"
CODEX_AUTH_PATH = CODEX_DIR / "auth.json"


@dataclass
class CodexAccount:
    email: str
    access_token: str
    refresh_token: str
    id_token: str
    account_id: str
    plan_type: str
    quota_snapshot: Dict[str, Any]
    disabled: bool
    created_at: int
    last_used: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "account_id": self.account_id,
            "plan_type": self.plan_type,
            "quota_snapshot": self.quota_snapshot,
            "disabled": self.disabled,
            "created_at": self.created_at,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodexAccount":
        return cls(
            email=data.get("email", ""),
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            id_token=data.get("id_token", ""),
            account_id=data.get("account_id", ""),
            plan_type=data.get("plan_type", "unknown"),
            quota_snapshot=data.get("quota_snapshot") or {},
            disabled=bool(data.get("disabled", False)),
            created_at=int(data.get("created_at") or int(time.time())),
            last_used=int(data.get("last_used") or int(time.time())),
        )


@dataclass
class AccountIndex:
    accounts: List[str]
    active_account: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accounts": list(self.accounts),
            "active_account": self.active_account,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountIndex":
        accounts = data.get("accounts") or []
        active = data.get("active_account") or ""
        return cls(accounts=list(accounts), active_account=active)


def _ensure_accounts_dir() -> None:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)


def _account_path(email: str) -> Path:
    return ACCOUNTS_DIR / f"{email}.json"


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    _ensure_accounts_dir()
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)


def _load_index() -> AccountIndex:
    if not ACCOUNTS_INDEX_PATH.exists():
        return AccountIndex(accounts=[], active_account="")
    return AccountIndex.from_dict(_read_json(ACCOUNTS_INDEX_PATH))


def _save_index(index: AccountIndex) -> None:
    _atomic_write_json(ACCOUNTS_INDEX_PATH, index.to_dict())


def get_account_index() -> AccountIndex:
    return _load_index()


def get_active_email() -> str:
    return _load_index().active_account


def list_accounts() -> List[str]:
    return _load_index().accounts


def load_account(email: str) -> CodexAccount:
    path = _account_path(email)
    if not path.exists():
        raise FileNotFoundError(f"Account not found: {email}")
    return CodexAccount.from_dict(_read_json(path))


def load_all_accounts() -> List[CodexAccount]:
    index = _load_index()
    accounts: List[CodexAccount] = []
    for email in index.accounts:
        try:
            accounts.append(load_account(email))
        except FileNotFoundError:
            continue
    return accounts


def save_account(account: CodexAccount) -> None:
    _atomic_write_json(_account_path(account.email), account.to_dict())


def add_account(
    email: str,
    tokens: Dict[str, Any],
    account_id: Optional[str] = None,
    plan_type: Optional[str] = None,
    quota_snapshot: Optional[Dict[str, Any]] = None,
    disabled: Optional[bool] = None,
    set_active: bool = False,
    update_last_used: bool = True,
) -> CodexAccount:
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise RuntimeError("Missing access_token or refresh_token for account")

    now = int(time.time())
    existing = None
    try:
        existing = load_account(email)
    except FileNotFoundError:
        pass

    account = CodexAccount(
        email=email,
        access_token=tokens.get("access_token") or "",
        refresh_token=tokens.get("refresh_token") or "",
        id_token=tokens.get("id_token") or "",
        account_id=account_id or (existing.account_id if existing else ""),
        plan_type=plan_type or (existing.plan_type if existing else "unknown"),
        quota_snapshot=quota_snapshot if quota_snapshot is not None else (existing.quota_snapshot if existing else {}),
        disabled=existing.disabled if (existing and disabled is None) else bool(disabled),
        created_at=existing.created_at if existing else now,
        last_used=now if update_last_used else (existing.last_used if existing else now),
    )

    save_account(account)

    index = _load_index()
    if email not in index.accounts:
        index.accounts.append(email)
    if set_active:
        index.active_account = email
    _save_index(index)

    return account


def get_active_account() -> CodexAccount:
    index = _load_index()
    if not index.active_account:
        raise RuntimeError("No active account set")
    return load_account(index.active_account)


def remove_account(email: str) -> None:
    index = _load_index()
    if email in index.accounts:
        index.accounts.remove(email)
    if index.active_account == email:
        index.active_account = ""
    _save_index(index)

    path = _account_path(email)
    if path.exists():
        path.unlink()


def import_current_account() -> CodexAccount:
    auth_data = auth.read_codex_auth()
    tokens = auth_data.get("tokens", {})
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise RuntimeError("Current auth.json is missing access_token or refresh_token")
    info = auth.extract_account_info(tokens.get("id_token"), tokens.get("access_token"))

    email = info.email
    if not email:
        raise RuntimeError("Unable to extract email from current auth.json")

    account_id = tokens.get("account_id") or info.account_id
    plan_type = info.plan_type or "unknown"

    account = add_account(
        email=email,
        tokens={
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "id_token": tokens.get("id_token"),
        },
        account_id=account_id,
        plan_type=plan_type,
        set_active=True,
        update_last_used=True,
    )

    return account


def _is_codex_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "codex"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def refresh_account_tokens(account: CodexAccount, force: bool = False) -> CodexAccount:
    tokens = {
        "access_token": account.access_token,
        "refresh_token": account.refresh_token,
        "id_token": account.id_token,
        "account_id": account.account_id,
    }

    try:
        new_tokens = auth.ensure_fresh_tokens(tokens, force=force)
    except auth.AuthError as exc:
        account.disabled = True
        save_account(account)
        raise RuntimeError(f"Failed to refresh tokens for {account.email}") from exc

    if new_tokens != tokens:
        info = auth.extract_account_info(new_tokens.get("id_token"), new_tokens.get("access_token"))
        if info.account_id:
            account.account_id = info.account_id
        if info.plan_type:
            account.plan_type = info.plan_type

        account.access_token = new_tokens.get("access_token") or account.access_token
        account.refresh_token = new_tokens.get("refresh_token") or account.refresh_token
        account.id_token = new_tokens.get("id_token") or account.id_token
        account.last_used = int(time.time())
        save_account(account)

    return account


def set_active_account(email: str) -> CodexAccount:
    index = _load_index()
    if email not in index.accounts:
        raise RuntimeError(f"Account not found: {email}")

    if _is_codex_running():
        print("Warning: codex appears to be running; restart it after switching.")

    try:
        current_auth = auth.read_codex_auth()
    except FileNotFoundError:
        current_auth = None

    if current_auth:
        tokens = current_auth.get("tokens", {})
        info = auth.extract_account_info(tokens.get("id_token"), tokens.get("access_token"))
        current_email = info.email
        if current_email and current_email != email:
            add_account(
                email=current_email,
                tokens={
                    "access_token": tokens.get("access_token"),
                    "refresh_token": tokens.get("refresh_token"),
                    "id_token": tokens.get("id_token"),
                },
                account_id=tokens.get("account_id") or info.account_id,
                plan_type=info.plan_type or "unknown",
                set_active=False,
                update_last_used=True,
            )

    target = load_account(email)
    if target.disabled:
        raise RuntimeError(f"Account is disabled: {email}")

    target = refresh_account_tokens(target)

    auth.write_codex_auth(
        {
            "access_token": target.access_token,
            "refresh_token": target.refresh_token,
            "id_token": target.id_token,
            "account_id": target.account_id,
        }
    )

    index.active_account = email
    _save_index(index)

    target.last_used = int(time.time())
    save_account(target)

    return target
