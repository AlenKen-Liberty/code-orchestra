# Google Account Manager — OpenClaw Integration

## Overview

This module manages Google OAuth accounts for the **Antigravity** (Cloud Code Assist) API, with integration into [OpenClaw](https://github.com/AlenKen-Liberty/openclaw-tool).

## Architecture

```
~/.gemini/accounts/          ← Our CLI's account storage
    accounts.json            ← Index: list of emails + active
    {email}.json             ← Per-account: token, project_id, quota

~/.openclaw/
    openclaw.json            ← OpenClaw config: auth profiles list, model selection
    agents/main/agent/
        auth-profiles.json   ← OpenClaw runtime: OAuth tokens, lastGood, usageStats
```

## How OpenClaw Uses Antigravity OAuth

### OAuth Credentials

Both our CLI and OpenClaw use the **same** OAuth client:
- **Client ID**: `1071006060591-...` (Antigravity Manager)
- **Client Secret**: `[REDACTED]`
- **Scopes**: `cloud-platform`, `userinfo.email`, `userinfo.profile`, `cclog`, `experimentsandconfigs`

Tokens are interchangeable between our CLI and OpenClaw.

### Profile Selection Flow

OpenClaw resolves which profile to use via `resolveAuthProfileOrder()`:

1. **List candidates** from `openclaw.json → auth.profiles` (in config order)
2. **Filter** by validity: OAuth profiles need `access` or `refresh` token
3. **Separate** into available vs in-cooldown pools
4. **Iterate** in order, calling `resolveApiKeyForProfile()` for each

### Critical: The `expires: 0` Requirement

> [!CAUTION]
> Injected profiles MUST have `"expires": 0` in `auth-profiles.json`.

**Why**: OpenClaw has a bug in `buildOAuthApiKey()`:
- For `google-gemini-cli`: returns `JSON.stringify({token, projectId})` ✅
- For `google-antigravity`: returns `credentials.access` (plain string) ❌

The provider code (`google-gemini-cli.js`) does `JSON.parse(apiKeyRaw)`, which fails on a plain string → "Invalid Google Cloud Code Assist credentials".

**Workaround**: When `expires < Date.now()`, OpenClaw calls the provider's `refreshToken()` → `getApiKey()` which correctly returns JSON `{token, projectId}`. Setting `expires: 0` forces this path.

### API Endpoint

```
POST https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse
POST https://cloudcode-pa.googleapis.com/v1internal:generateContent  (non-streaming)
```

Request body:
```json
{
  "project": "<projectId>",
  "model": "gemini-3-flash",
  "request": {
    "contents": [{"role": "user", "parts": [{"text": "..."}]}],
    "generationConfig": {"maxOutputTokens": 200}
  },
  "userAgent": "antigravity",
  "requestType": "agent",
  "requestId": "agent-<timestamp>-<random>"
}
```

Headers:
```
Authorization: Bearer <access_token>
User-Agent: antigravity/1.15.8 linux/arm64
X-Goog-Api-Client: google-cloud-sdk vscode_cloudshelleditor/0.1
```

## Adding Accounts to OpenClaw

### 1. `auth-profiles.json` — Add profile with `expires: 0`

```json
"google-antigravity:<email>": {
  "type": "oauth",
  "provider": "google-antigravity",
  "access": "<access_token>",
  "refresh": "<refresh_token>",
  "expires": 0,
  "email": "<email>",
  "projectId": "<project_id>"
}
```

### 2. `openclaw.json` — Register in auth.profiles

```json
"google-antigravity:<email>": {
  "provider": "google-antigravity",
  "mode": "oauth",
  "email": "<email>"
}
```

### 3. Set `lastGood` (optional)

In `auth-profiles.json`:
```json
"lastGood": {
  "google-antigravity": "google-antigravity:<email>"
}
```

## Quota System

- **Daily quotas** (Gemini): `resetTime ≤ 24h`, resets every ~5h window
- **Weekly quotas** (Claude, GPT-OSS): `resetTime > 24h` (~150h), shared pool
- `remainingFraction > 0` does **NOT** mean rate-limited — API calls still work
- Only `remainingFraction == 0` (`EXHAUSTED`) means truly blocked

## CLI Commands

```bash
python -m models.google.cli login          # OAuth login
python -m models.google.cli status         # Show all accounts + quota
python -m models.google.cli switch <email> # Switch active account
python -m models.google.cli list           # List accounts
```

## Direct LLM Test

```bash
python3 /tmp/test_llm_call.py <email> <model> "<prompt>"
# Examples:
python3 /tmp/test_llm_call.py user@example.com gemini-3-flash "Hello"
python3 /tmp/test_llm_call.py user@example.com claude-opus-4-6-thinking "Hello"
```
