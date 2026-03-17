"""
account.py — Account management with JSON persistence.

Storage layout (in ~/.gemini/accounts/):
  accounts.json       — index: list of emails, active account
  <email>.json        — per-account: token data, project_id, last quota snapshot

Also provides backward-compatible AccountManager and QuotaTracker classes
for integration with models/manager.py.
"""

import json
import time
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

from models.google.oauth import TokenData, ensure_fresh_token
from models.google.quota import QuotaData, ModelQuota


# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------

ACCOUNTS_DIR = Path.home() / ".gemini" / "accounts"


def _ensure_dir():
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Account data model
# ---------------------------------------------------------------------------

@dataclass
class Account:
    """Full account data stored per-account."""
    email: str
    token: TokenData
    project_id: Optional[str] = None
    subscription_tier: Optional[str] = None
    quota: Optional[Dict[str, Any]] = None   # last quota snapshot
    disabled: bool = False
    disabled_reason: Optional[str] = None
    created_at: int = 0
    last_used: int = 0

    def __post_init__(self):
        now = int(time.time())
        if not self.created_at:
            self.created_at = now
        if not self.last_used:
            self.last_used = now

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "email": self.email,
            "token": self.token.to_dict(),
            "project_id": self.project_id,
            "subscription_tier": self.subscription_tier,
            "quota": self.quota,
            "disabled": self.disabled,
            "disabled_reason": self.disabled_reason,
            "created_at": self.created_at,
            "last_used": self.last_used,
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Account":
        token_data = d.get("token", {})
        return cls(
            email=d["email"],
            token=TokenData.from_dict(token_data) if token_data else TokenData("", "", 0, 0),
            project_id=d.get("project_id"),
            subscription_tier=d.get("subscription_tier"),
            quota=d.get("quota"),
            disabled=d.get("disabled", False),
            disabled_reason=d.get("disabled_reason"),
            created_at=d.get("created_at", 0),
            last_used=d.get("last_used", 0),
        )


# ---------------------------------------------------------------------------
# Index file (accounts.json)
# ---------------------------------------------------------------------------

@dataclass
class AccountIndex:
    """Index of all accounts."""
    accounts: List[str] = field(default_factory=list)       # list of emails
    active_account: Optional[str] = None


def _index_path() -> Path:
    return ACCOUNTS_DIR / "accounts.json"


def _load_index() -> AccountIndex:
    _ensure_dir()
    path = _index_path()
    if not path.exists():
        return AccountIndex()
    try:
        data = json.loads(path.read_text())
        return AccountIndex(
            accounts=data.get("accounts", []),
            active_account=data.get("active_account"),
        )
    except Exception:
        return AccountIndex()


def _save_index(index: AccountIndex):
    _ensure_dir()
    path = _index_path()
    data = {
        "accounts": index.accounts,
        "active_account": index.active_account,
    }
    # Atomic write via temp file
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(path)


# ---------------------------------------------------------------------------
# Per-account file operations
# ---------------------------------------------------------------------------

def _account_path(email: str) -> Path:
    return ACCOUNTS_DIR / f"{email}.json"


def save_account(account: Account):
    """Save account data to disk."""
    _ensure_dir()
    path = _account_path(account.email)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(account.to_dict(), indent=2))
    tmp.rename(path)


def load_account(email: str) -> Optional[Account]:
    """Load account from disk, or None if not found."""
    path = _account_path(email)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Account.from_dict(data)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def add_account(email: str, token: TokenData) -> Account:
    """Add or update an account. Returns the Account."""
    index = _load_index()
    existing = load_account(email)

    if existing:
        # Update token, preserve metadata
        existing.token = token
        existing.token.email = email
        existing.last_used = int(time.time())
        if existing.disabled:
            existing.disabled = False
            existing.disabled_reason = None
        save_account(existing)
        return existing

    # New account
    account = Account(email=email, token=token)
    account.token.email = email
    save_account(account)

    if email not in index.accounts:
        index.accounts.append(email)
    if index.active_account is None:
        index.active_account = email
    _save_index(index)

    return account


def list_accounts() -> List[Account]:
    """List all registered accounts."""
    index = _load_index()
    accounts = []
    for email in index.accounts:
        acc = load_account(email)
        if acc:
            accounts.append(acc)
    return accounts


def get_active_account() -> Optional[Account]:
    """Return the currently active account."""
    index = _load_index()
    if not index.active_account:
        return None
    return load_account(index.active_account)


def get_active_email() -> Optional[str]:
    """Return active account email."""
    return _load_index().active_account


def _sync_openclaw_active(email: str):
    """Sync active_email to ~/.openclaw/google_accounts.json."""
    oc_path = Path.home() / ".openclaw" / "google_accounts.json"
    if not oc_path.exists():
        return
    try:
        data = json.loads(oc_path.read_text())
        if data.get("active_email") != email:
            data["active_email"] = email
            tmp = oc_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.rename(oc_path)
    except Exception:
        pass  # Best-effort sync


def _sync_gemini_active(email: str):
    """Sync active email to ~/.gemini/google_accounts.json for Gemini CLI."""
    gemini_path = Path.home() / ".gemini" / "google_accounts.json"
    try:
        if gemini_path.exists():
            data = json.loads(gemini_path.read_text())
        else:
            data = {"active": "", "old": []}
            
        current = data.get("active", "")
        if current and current != email:
            old_list = data.get("old", [])
            if current not in old_list:
                old_list.append(current)
            data["old"] = old_list
            
        data["active"] = email
        
        tmp = gemini_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(gemini_path)
    except Exception:
        pass  # Best-effort sync

def _sync_gemini_oauth_creds(account: Account):
    """Sync the tokens to ~/.gemini/oauth_creds.json for Gemini CLI core."""
    path = Path.home() / ".gemini" / "oauth_creds.json"
    try:
        # Preserve existing id_token if any (to avoid blowing up Gemini CLI if it strictly expects one),
        # but actually we probably want to strip it if it belongs to another user.
        # But wait, we can just write it without id_token, or preserve it just in case.
        # Best is to just build the dict.
        data = {
            "access_token": account.token.access_token,
            "refresh_token": account.token.refresh_token,
            "scope": "https://www.googleapis.com/auth/userinfo.profile openid https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email",
            "token_type": "Bearer",
            "expiry_date": account.token.expiry_timestamp * 1000,
        }
        # If we had id_token in token data, we'd add it here.
        if hasattr(account.token, 'id_token') and account.token.id_token:
            data["id_token"] = account.token.id_token
        
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(path)
    except Exception:
        pass


def sync_openclaw_rotate(email: str) -> bool:
    """
    Rotate OpenClaw's google-antigravity to use the given account.
    Updates lastGood, ensures expires=0, clears cooldowns.
    Returns True on success.
    """
    ap_path = Path.home() / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
    if not ap_path.exists():
        return False

    try:
        ap = json.loads(ap_path.read_text())
        profile_key = f"google-antigravity:{email}"

        # Profile must exist
        if profile_key not in ap.get("profiles", {}):
            return False

        # Ensure expires=0 to force provider refresh path
        ap["profiles"][profile_key]["expires"] = 0

        # Update lastGood
        last_good = ap.get("lastGood", {})
        last_good["google-antigravity"] = profile_key
        ap["lastGood"] = last_good

        # Clear cooldown on this profile
        usage = ap.get("usageStats", {})
        usage[profile_key] = {
            "lastUsed": int(time.time() * 1000),
            "errorCount": 0,
        }
        ap["usageStats"] = usage

        tmp = ap_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ap, indent=2))
        tmp.rename(ap_path)
        return True
    except Exception:
        return False


def set_active_account(email: str) -> bool:
    """Switch active account. Returns True on success."""
    index = _load_index()
    if email not in index.accounts:
        return False
    index.active_account = email
    _save_index(index)
    _sync_openclaw_active(email)
    _sync_gemini_active(email)
    
    acc = load_account(email)
    if acc:
        _sync_gemini_oauth_creds(acc)
        
    return True


def remove_account(email: str) -> bool:
    """Remove an account. Returns True on success."""
    index = _load_index()
    if email not in index.accounts:
        return False
    index.accounts.remove(email)
    if index.active_account == email:
        index.active_account = index.accounts[0] if index.accounts else None
    _save_index(index)

    path = _account_path(email)
    if path.exists():
        path.unlink()
    return True


# ---------------------------------------------------------------------------
# Backward-compatible classes for manager.py
# ---------------------------------------------------------------------------

def sync_from_gemini_cli() -> Optional[Account]:
    """
    Import the current Gemini CLI token into our account manager.

    Reads ~/.gemini/oauth_creds.json (Gemini CLI's token store),
    determines the email, and updates/creates the corresponding account.

    Returns the synced Account, or None on failure.
    """
    creds_path = Path.home() / ".gemini" / "oauth_creds.json"
    if not creds_path.exists():
        return None

    try:
        data = json.loads(creds_path.read_text())
    except Exception:
        return None

    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    if not access_token:
        return None

    # Determine email from id_token JWT or by calling userinfo API
    email = None
    id_token_str = data.get("id_token", "")
    if id_token_str:
        try:
            import base64
            payload = id_token_str.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            email = claims.get("email")
        except Exception:
            pass

    if not email:
        # Fallback: call userinfo API
        try:
            from models.google.oauth import get_user_info
            info = get_user_info(access_token)
            email = info.get("email")
        except Exception:
            return None

    if not email:
        return None

    # Build TokenData
    expiry_ms = data.get("expiry_date", 0)
    expiry_ts = int(expiry_ms / 1000) if expiry_ms > 1e12 else int(expiry_ms)
    expires_in = max(0, expiry_ts - int(time.time()))

    token = TokenData(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        expiry_timestamp=expiry_ts,
        email=email,
    )

    # Add/update the account
    account = add_account(email, token)
    return account


class QuotaTracker:
    """
    Tracks per-account rate limit state (429 errors).
    Compatible with models/manager.py imports.
    """

    def __init__(self):
        self._state: Dict[str, Dict[str, Any]] = {}
        self._load_state()

    def _state_path(self) -> Path:
        return ACCOUNTS_DIR / "quota_state.json"

    def _load_state(self):
        path = self._state_path()
        if path.exists():
            try:
                self._state = json.loads(path.read_text())
            except Exception:
                self._state = {}

    def _save_state(self):
        _ensure_dir()
        path = self._state_path()
        path.write_text(json.dumps(self._state, indent=2))

    def record_429(self, email: str):
        if email not in self._state:
            self._state[email] = {"count_429": 0, "first_429": 0, "cooldown_until": 0}
        s = self._state[email]
        s["count_429"] = s.get("count_429", 0) + 1
        if not s.get("first_429"):
            s["first_429"] = int(time.time())
        self._save_state()

    def record_success(self, email: str):
        if email in self._state:
            self._state[email] = {"count_429": 0, "first_429": 0, "cooldown_until": 0}
            self._save_state()

    def is_on_cooldown(self, email: str) -> bool:
        s = self._state.get(email, {})
        until = s.get("cooldown_until", 0)
        return time.time() < until

    def get_best_account(self, emails: List[str]) -> Optional[str]:
        """Pick best account (lowest 429 count, not on cooldown)."""
        best = None
        best_score = float("inf")
        for email in emails:
            if self.is_on_cooldown(email):
                continue
            s = self._state.get(email, {})
            score = s.get("count_429", 0)
            if score < best_score:
                best_score = score
                best = email
        return best or (emails[0] if emails else None)

    def get_status(self, email: str) -> Dict[str, Any]:
        return self._state.get(email, {"count_429": 0, "first_429": 0, "cooldown_until": 0})


class AccountManager:
    """
    High-level account manager for models/manager.py compatibility.
    Wraps the module-level functions.
    """

    def __init__(self):
        pass

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Return list of account dicts suitable for manager.py."""
        accounts = list_accounts()
        active = get_active_email()
        result = []
        for acc in accounts:
            result.append({
                "email": acc.email,
                "is_active": acc.email == active,
                "enabled": not acc.disabled,
                "creds_path": str(_account_path(acc.email)),
                "project_id": acc.project_id,
                "subscription_tier": acc.subscription_tier,
            })
        return result

    def get_active_email(self) -> Optional[str]:
        return get_active_email()

    def set_active(self, email: str) -> bool:
        return set_active_account(email)
