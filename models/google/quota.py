"""
quota.py — Per-account model quota fetching for Antigravity.

Two-step process matching Antigravity Manager's quota.rs:
1. loadCodeAssist → get project_id + subscription tier
2. fetchAvailableModels → get per-model remaining fraction + reset time

Endpoints:
- loadCodeAssist:       https://daily-cloudcode-pa.sandbox.googleapis.com
- fetchAvailableModels: https://cloudcode-pa.googleapis.com
"""

import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

# Endpoints (from Antigravity Manager quota.rs)
LOAD_CODE_ASSIST_URL = "https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:loadCodeAssist"
FETCH_MODELS_URL = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"

USER_AGENT = "vscode/1.X.X (Antigravity/4.1.28)"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ModelQuota:
    """Per-model quota info."""
    name: str                     # e.g. "gemini-2.5-pro-exp-03-25"
    percentage: int               # remaining percentage 0-100
    reset_time: str               # ISO-8601 reset timestamp
    display_name: str = ""        # e.g. "Gemini 2.5 Pro"
    supports_thinking: bool = False
    recommended: bool = False

    @property
    def family(self) -> str:
        """Categorize model into a family based on its name/display_name."""
        n = self.name.lower()
        dn = self.display_name.lower()

        if "claude" in n or "claude" in dn or "gpt" in n or "gpt" in dn:
            return "Claude & GPT"
        
        if "imagen" in n or "imagen" in dn or (("gemini" in n or "gemini" in dn) and "image" in dn):
            return "Imagen"

        if "gemini" in n or "gemini" in dn:
            # Group into the 3 major buckets: Flash Lite, Flash, Pro
            if "lite" in n or "lite" in dn:
                return "Gemini Flash Lite"
            if "flash" in n or "flash" in dn:
                return "Gemini Flash"
            if "pro" in n or "pro" in dn:
                return "Gemini Pro"
            return "Gemini"

        if "image" in n or "image" in dn:
            return "Imagen"
        return self.display_name

    @property
    def is_exhausted(self) -> bool:
        return self.percentage <= 0

    @property
    def remaining_str(self) -> str:
        return f"{self.percentage}%"

    @property
    def time_until_reset_secs(self) -> Optional[float]:
        """Seconds until reset, or None if no reset_time."""
        if not self.reset_time:
            return None
        try:
            reset_dt = datetime.fromisoformat(self.reset_time.replace("Z", "+00:00"))
            delta = reset_dt - datetime.now(timezone.utc)
            return max(0, delta.total_seconds())
        except Exception:
            return None


@dataclass
class QuotaData:
    """Aggregated quota for one account."""
    models: List[ModelQuota] = field(default_factory=list)
    subscription_tier: Optional[str] = None
    is_forbidden: bool = False
    last_updated: int = 0

    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = int(time.time())


# ---------------------------------------------------------------------------
# Step 1: loadCodeAssist → project_id + tier
# ---------------------------------------------------------------------------

def fetch_project_id(access_token: str, ide_type: str = "IDE_UNSPECIFIED") -> Tuple[Optional[str], Optional[str]]:
    """
    Call loadCodeAssist to discover project_id and subscription tier.
    Returns (project_id, subscription_tier) or (None, None) on failure.
    """
    metadata = {"ideType": ide_type}
    if ide_type == "IDE_UNSPECIFIED":
        metadata["pluginType"] = "GEMINI"
        metadata["platform"] = "PLATFORM_UNSPECIFIED"
    body = json.dumps({"metadata": metadata}).encode("utf-8")

    req = urllib.request.Request(LOAD_CODE_ASSIST_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", USER_AGENT)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None, None

    project_id = data.get("cloudaicompanionProject")

    # Tier extraction: paid > current > allowed (matching quota.rs logic)
    tier = None
    paid = data.get("paidTier")
    if paid:
        tier = paid.get("name") or paid.get("id")

    if not tier:
        is_ineligible = bool(data.get("ineligibleTiers"))
        current = data.get("currentTier")
        if current and not is_ineligible:
            tier = current.get("name") or current.get("id")
        elif is_ineligible:
            allowed = data.get("allowedTiers", [])
            for t in allowed:
                if t.get("is_default"):
                    name = t.get("name") or t.get("id")
                    if name:
                        tier = f"{name} (Restricted)"
                    break

    return project_id, tier


# ---------------------------------------------------------------------------
# Step 2: fetchAvailableModels → per-model quota
# ---------------------------------------------------------------------------

# Models we care about (exclude internal/chat models)
_MODEL_PREFIXES = ("gemini", "claude", "gpt", "image", "imagen")


def fetch_available_models(access_token: str, project_id: Optional[str] = None, ide_type: str = "IDE_UNSPECIFIED") -> QuotaData:
    """
    Call fetchAvailableModels or retrieveUserQuota depending on ide_type.
    Returns QuotaData with per-model remaining fractions.
    """
    is_gemini_cli = (ide_type == "IDE_UNSPECIFIED")
    url = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota" if is_gemini_cli else FETCH_MODELS_URL
    user_agent = "GeminiCLI/1.0.0" if is_gemini_cli else USER_AGENT

    payload = {"project": project_id} if project_id else {}
    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", user_agent)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return QuotaData(is_forbidden=True)
        raise

    quota = QuotaData()
    
    if is_gemini_cli:
        buckets = data.get("buckets", [])
        for bucket in buckets:
            name = bucket.get("modelId", "")
            if not any(name.startswith(p) for p in _MODEL_PREFIXES):
                continue
            
            remaining_frac = bucket.get("remainingFraction", 0.0)
            percentage = int(remaining_frac * 100)
            reset_time = bucket.get("resetTime", "")
            
            display_name = name.replace("-", " ").title()
            
            # Use the ModelQuota class to compute family and assign it as display_name for grouping
            mq = ModelQuota(
                name=name,
                percentage=percentage,
                reset_time=reset_time,
                display_name=display_name,
                supports_thinking=False,
                recommended=False,
            )
            
            # Override display_name with family so the cli.py grouper works correctly
            mq.display_name = mq.family
            
            quota.models.append(mq)
    else:
        models_dict = data.get("models", {})
    
        for name, info in models_dict.items():
            # Filter to models we care about
            if not any(name.startswith(p) for p in _MODEL_PREFIXES):
                continue
    
            quota_info = info.get("quotaInfo", {})
            remaining_frac = quota_info.get("remainingFraction", 0.0)
            percentage = int(remaining_frac * 100)
            reset_time = quota_info.get("resetTime", "")
    
            display_name = info.get("displayName", name)
            supports_thinking = info.get("supportsThinking", False)
            recommended = info.get("recommended", False)
    
            quota.models.append(ModelQuota(
                name=name,
                percentage=percentage,
                reset_time=reset_time,
                display_name=display_name,
                supports_thinking=supports_thinking,
                recommended=recommended,
            ))

    return quota


# ---------------------------------------------------------------------------
# Combined: fetch quota for one account
# ---------------------------------------------------------------------------

def fetch_account_quota(
    access_token: str,
    cached_project_id: Optional[str] = None,
    ide_type: str = "IDE_UNSPECIFIED",
) -> Tuple[QuotaData, Optional[str]]:
    """
    Fetch per-model quota for one account.

    Steps:
    1. If cached_project_id is provided, skip loadCodeAssist
    2. Otherwise call loadCodeAssist to discover project_id
    3. Call fetchAvailableModels with project_id

    Returns (QuotaData, project_id) — project_id for caching.
    """
    project_id = cached_project_id
    tier = None

    if not project_id:
        project_id, tier = fetch_project_id(access_token, ide_type=ide_type)

    # Even without project_id, try fetchAvailableModels with empty body
    # (less accurate for exhausted accounts, but still returns data)

    quota = fetch_available_models(access_token, project_id, ide_type=ide_type)
    if tier:
        quota.subscription_tier = tier

    return quota, project_id
