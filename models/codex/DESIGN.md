# Codex Account Manager — Design Document

## Overview

Manage 5 OpenAI Codex CLI accounts with quota monitoring and automatic account switching, mirroring the Google Antigravity account management pattern.

### Accounts

| Email | Plan |
|-------|------|
| liuyl.david@gmail.com | Free |
| carpool.london@gmail.com | Free |
| maritime2007@gmail.com | Free |
| swimming.crystalball@gmail.com | Free |
| aken@liberty.edu | Free |

## Architecture

### Storage Layout

```
~/.codex/accounts/              <- Our multi-account storage
    accounts.json               <- Index: list of emails + active account
    {email}.json                <- Per-account: tokens, plan, quota snapshot

~/.codex/                       <- Codex CLI native config (single-account)
    auth.json                   <- Current active account tokens
    config.toml                 <- Model, features, trust settings
```

### How Codex CLI Auth Works

Codex CLI stores a single account in `~/.codex/auth.json`:

```json
{
  "auth_mode": "chatgpt",
  "OPENAI_API_KEY": null,
  "tokens": {
    "id_token": "<JWT>",
    "access_token": "<JWT>",
    "refresh_token": "<refresh_token>",
    "account_id": "<uuid>"
  },
  "last_refresh": "<ISO-8601>"
}
```

Key details:
- **Auth mode**: `chatgpt` (OAuth via ChatGPT account, not API key)
- **OAuth issuer**: `https://auth.openai.com`
- **Client ID**: `app_EMoamEEZ73f0CkXaXp7hrann`
- **Token lifetime**: `expires_in: 863999` (~10 days)
- **Refresh**: Standard OAuth2 `refresh_token` grant
- The `access_token` JWT contains `https://api.openai.com/auth` claims including `chatgpt_account_id`, `chatgpt_plan_type`, `chatgpt_user_id`

### Account Switching Mechanism

Codex CLI has no built-in multi-account support. Switching requires:

1. Save current account's tokens to our `~/.codex/accounts/{email}.json`
2. Write the target account's tokens to `~/.codex/auth.json`
3. Codex CLI picks up the new identity on next launch

This is safe because:
- Codex reads `auth.json` at startup, not continuously
- Token refresh is transparent (Codex refreshes via `https://auth.openai.com/oauth/token`)
- `account_id` in the JWT maps requests to the correct ChatGPT account

### Verification

After switching, run `codex login status` to confirm. The `/status` command inside Codex TUI will show the new account email and quota.

## API Endpoints

### 1. Token Refresh

```
POST https://auth.openai.com/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
&refresh_token=<refresh_token>
&client_id=app_EMoamEEZ73f0CkXaXp7hrann
```

Response:
```json
{
  "access_token": "<new JWT>",
  "expires_in": 863999,
  "id_token": "<new JWT>",
  "refresh_token": "<new refresh_token>",
  "scope": "openid profile email offline_access ...",
  "token_type": "bearer"
}
```

Notes:
- Refresh token rotates on each use (new `refresh_token` in response)
- Must save the new refresh_token immediately
- Token expiry is ~10 days

### 2. Weekly Quota (Usage)

```
GET https://chatgpt.com/backend-api/wham/usage
Headers:
  Authorization: Bearer <access_token>
  ChatGPT-Account-Id: <account_id>
  User-Agent: CodexBar
  Accept: application/json
```

Response:
```json
{
  "user_id": "user-xxx",
  "account_id": "user-xxx",
  "email": "aken@liberty.edu",
  "plan_type": "free",
  "rate_limit": {
    "allowed": true,
    "limit_reached": false,
    "primary_window": {
      "used_percent": 12,
      "limit_window_seconds": 604800,
      "reset_after_seconds": 441240,
      "reset_at": 1774130071
    },
    "secondary_window": null
  },
  "code_review_rate_limit": {
    "allowed": true,
    "limit_reached": false,
    "primary_window": {
      "used_percent": 0,
      "limit_window_seconds": 604800,
      "reset_after_seconds": 604800,
      "reset_at": 1774293631
    },
    "secondary_window": null
  },
  "additional_rate_limits": null,
  "credits": null,
  "promo": null
}
```

Fields:
- `rate_limit.primary_window`: Weekly (604800s = 7 days) coding usage
- `rate_limit.primary_window.used_percent`: 0-100, percentage of weekly limit used
- `rate_limit.primary_window.reset_at`: Unix timestamp when limit resets
- `rate_limit.primary_window.limit_reached`: Boolean, true when fully exhausted
- `code_review_rate_limit`: Separate quota for code review tasks
- `rate_limit.secondary_window`: 3-5 hour burst window (null on Free plan, present on paid plans)
- `plan_type`: `free`, `plus`, `pro`, `team`, `edu`, `enterprise`
- `credits`: Balance info (paid plans only)

### 3. Login (Initial Account Setup)

Browser-based OAuth flow with PKCE:

```
codex login
```

Opens browser to `https://auth.openai.com/authorize` with:
- `client_id=app_EMoamEEZ73f0CkXaXp7hrann`
- `response_type=code`
- `scope=openid profile email offline_access`
- `code_challenge=<PKCE S256>`
- `redirect_uri=http://localhost:<ephemeral_port>/callback`

After browser auth, exchanges code for tokens at `/oauth/token`.

Alternative: Device auth flow:
```
codex login --device-auth
```
Shows a user code and URL, user authorizes in any browser.

## Module Design

### Files

```
models/codex/
    __init__.py
    DESIGN.md           <- This document
    account.py          <- Account CRUD, token storage, switching
    auth.py             <- OAuth token refresh, JWT decode
    quota.py            <- Quota fetching from wham/usage API
    cli.py              <- CLI entry point (status, switch, list, login)
```

### account.py

Mirrors `models/google/account.py`:

```python
ACCOUNTS_DIR = Path.home() / ".codex" / "accounts"

@dataclass
class CodexAccount:
    email: str
    access_token: str
    refresh_token: str
    id_token: str
    account_id: str          # ChatGPT account UUID
    plan_type: str           # free, plus, pro, etc.
    quota_snapshot: dict     # Last wham/usage response
    disabled: bool
    created_at: int
    last_used: int

@dataclass
class AccountIndex:
    accounts: List[str]      # list of emails
    active_account: str
```

Key operations:
- `add_account(email, tokens)` -> Save tokens, update index
- `list_accounts()` -> All accounts
- `get_active_account()` -> Currently active
- `set_active_account(email)` -> Switch: save current to file, write target to `~/.codex/auth.json`
- `import_current_account()` -> Import the current `~/.codex/auth.json` into our multi-account store
- `remove_account(email)` -> Remove from index and delete file

### auth.py

```python
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = "https://auth.openai.com/oauth/token"

def refresh_token(refresh_token: str) -> dict:
    """Refresh OAuth tokens. Returns new {access_token, refresh_token, id_token, expires_in}."""

def decode_jwt_claims(token: str) -> dict:
    """Decode JWT payload (no signature verification) to extract email, account_id, plan."""

def read_codex_auth() -> dict:
    """Read ~/.codex/auth.json"""

def write_codex_auth(tokens: dict):
    """Write ~/.codex/auth.json (atomic)"""
```

### quota.py

```python
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

@dataclass
class CodexQuota:
    email: str
    plan_type: str
    weekly_used_percent: int       # 0-100
    weekly_reset_at: int           # Unix timestamp
    weekly_limit_reached: bool
    burst_used_percent: int        # Secondary window (paid plans)
    burst_reset_at: int
    code_review_used_percent: int
    code_review_reset_at: int

def fetch_quota(access_token: str, account_id: str) -> CodexQuota:
    """Fetch usage from wham/usage API."""

def fetch_all_quotas(accounts: List[CodexAccount]) -> List[CodexQuota]:
    """Fetch quota for all accounts (parallel with ThreadPoolExecutor)."""
```

### cli.py

```
python -m models.codex.cli status         # Quota dashboard for all accounts
python -m models.codex.cli list           # List accounts with active marker
python -m models.codex.cli switch <email> # Switch active account
python -m models.codex.cli import         # Import current ~/.codex/auth.json
python -m models.codex.cli login          # Run codex login interactively
python -m models.codex.cli remove <email> # Remove account
python -m models.codex.cli rotate         # Auto-switch to account with most quota remaining
```

#### Status Dashboard Output

```
╭─────────────────────────────────────────────────────────────────╮
│  Codex Account Status                                           │
╰─────────────────────────────────────────────────────────────────╯

  Account                          Plan   Weekly Quota    Resets
  ─────────────────────────────── ────── ─────────────── ─────────
► aken@liberty.edu                 Free   [████░░░░░░] 12%  5d 2h
  liuyl.david@gmail.com           Free   [██████░░░░] 45%  3d 8h
  carpool.london@gmail.com        Free   [█░░░░░░░░░]  5%  6d 1h
  maritime2007@gmail.com          Free   [████████░░] 78%  2d 4h
  swimming.crystalball@gmail.com  Free   [██████████] 99%  0d 5h ⚠

► = active account    ⚠ = limit nearly reached
```

## Account Setup Workflow

### First-time Setup (per account)

1. Switch to the account in Codex:
   ```bash
   codex logout
   codex login   # Log in with target account in browser
   ```

2. Import into our multi-account store:
   ```bash
   python -m models.codex.cli import
   ```

3. Repeat for all 5 accounts.

### Alternative: Semi-automated

Since we have the refresh tokens from browser login, after importing the first account we can:

1. Log in account 1 via `codex login` -> import
2. Log in account 2 via `codex login` -> import
3. ... repeat for all 5

The `import` command reads `~/.codex/auth.json`, decodes the JWT to extract email, and stores everything.

## Switching Mechanism Details

When `set_active_account(email)` is called:

1. **Read** current `~/.codex/auth.json`
2. **Decode** JWT to find current email
3. **Save** current tokens back to `~/.codex/accounts/{current_email}.json`
4. **Load** target account from `~/.codex/accounts/{email}.json`
5. **Refresh** target's tokens if expired (via `auth.openai.com/oauth/token`)
6. **Write** target's tokens to `~/.codex/auth.json`
7. **Update** `accounts.json` index with new active

### Verification after switch

```bash
codex login status
# Expected: "Logged in using ChatGPT"

# Or launch codex and run /status to see:
# Account: <target_email> (Free)
# Weekly limit: [██████████████████░░] 89% left
```

## Edge Cases

### Token Expiry

- Access tokens last ~10 days
- We proactively refresh before API calls
- If refresh_token is revoked (user changed password, etc.), mark account as disabled

### Rate Limit Reached

- `rate_limit.limit_reached == true` means the account is exhausted for this week
- `rotate` command will skip exhausted accounts and pick the one with lowest `used_percent`

### Concurrent Access

- Codex CLI reads auth.json at startup only
- Our switching is safe as long as Codex isn't actively running when we switch
- Add a check: if codex process is running, warn the user to restart it after switch

### chatgpt.com 403 on Quota API

- The `wham/usage` endpoint is on chatgpt.com which may block non-browser requests
- Tested and confirmed working with proper headers (`User-Agent: CodexBar`, `Accept: application/json`)
- If 403 occurs, token may be expired -> refresh first and retry
- If still 403, the endpoint may have added browser fingerprinting -> fallback to parsing `codex /status` output

## Integration with Code Orchestra

The Codex account manager integrates into the pipeline via:

```python
from models.codex.account import get_active_account, set_active_account
from models.codex.quota import fetch_quota

# Before running a Codex agent task:
account = get_active_account()
quota = fetch_quota(account.access_token, account.account_id)
if quota.weekly_limit_reached:
    # Auto-rotate to next available account
    set_active_account(find_best_account())
```
