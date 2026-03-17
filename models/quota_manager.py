"""
Unified Quota Manager for Google (Antigravity) and Codex accounts.

Smart switching algorithm — optimizes for:
1. WASTE PREVENTION: Use quota before it expires (don't let resets waste unused quota)
2. TASK SAFETY: Ensure >40% remaining when starting new tasks
3. CONTINUITY: Avoid unnecessary switching (anti-thrash)

Unified scoring formula per account:
  score = remaining + waste_urgency + safety_bonus + inertia

Where:
  - remaining: current remaining % (0-100)
  - waste_urgency: remaining × (WASTE_WINDOW - hours_to_reset) / WASTE_WINDOW
    → Boosts accounts with quota about to be lost on reset
  - safety_bonus: +15 if remaining > 40% (enough for a full task)
  - inertia: +5 for current account (avoid switching for marginal gains)

Switch when best candidate's score exceeds current by > 10 points.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from models.codex.account import load_account as load_codex_account
from models.codex.account import list_accounts as list_codex_accounts
from models.codex.account import set_active_account as set_active_codex_account
from models.codex.account import get_active_email as get_active_codex_email
from models.codex.quota import fetch_quota as fetch_codex_quota
from models.google.account import load_account as load_google_account
from models.google.account import list_accounts as list_google_accounts_fn
from models.google.account import set_active_account as set_active_google_account
from models.google.account import get_active_email as get_active_google_email
from models.google.account import save_account as save_google_account
from models.google.oauth import ensure_fresh_token as ensure_fresh_google_token
from models.google.quota import fetch_account_quota as fetch_google_quota


class Provider(str, Enum):
    CODEX = "codex"
    GOOGLE = "google"


@dataclass
class QuotaSnapshot:
    """Point-in-time quota snapshot for an account."""
    provider: Provider
    email: str
    account_id: str
    plan_type: str
    used_percent: int
    reset_at: int                    # Unix timestamp
    reset_at_readable: str           # Human-readable
    time_until_reset_hours: float

    @property
    def remaining_percent(self) -> int:
        return max(0, 100 - self.used_percent)

    @property
    def is_exhausted(self) -> bool:
        """True if quota is essentially depleted (>= 95%)."""
        return self.used_percent >= 95

    @property
    def is_fresh(self) -> bool:
        """True if just reset or will reset very soon."""
        return self.remaining_percent >= 90 or self.time_until_reset_hours < 0.5

    def __str__(self) -> str:
        return (
            f"{self.email:<40} {self.plan_type:<6} "
            f"[{self.used_percent:>3}%] "
            f"{self.time_until_reset_hours:>5.1f}h"
        )


@dataclass
class SwitchDecision:
    """Result of quota analysis and switching decision."""
    should_switch: bool
    reason: str
    target_email: Optional[str]
    target_remaining: Optional[int]
    current_email: Optional[str]
    current_remaining: Optional[int]

    def __str__(self) -> str:
        if not self.should_switch:
            return f"STAY on {self.current_email} ({self.current_remaining}% remaining) - {self.reason}"
        return (
            f"SWITCH {self.current_email} → {self.target_email} "
            f"({self.current_remaining}% → {self.target_remaining}%) - {self.reason}"
        )


class QuotaManager:
    """
    Intelligent quota manager for multi-provider, multi-account systems.

    Optimizes for three goals (in priority order):
    1. WASTE PREVENTION — Use quota before it resets (don't lose unused quota)
    2. TASK SAFETY — Prefer accounts with >40% for new tasks
    3. CONTINUITY — Avoid unnecessary mid-session switching

    Uses a unified scoring formula:
      score = remaining + waste_urgency + safety_bonus + inertia
    """

    TASK_SAFETY_THRESHOLD = 40              # Prefer accounts > 40% for new tasks
    FRESH_QUOTA_THRESHOLD = 90              # Consider "fresh" if >= 90%
    WASTE_WINDOW_HOURS = 6                  # Boost accounts resetting within 6h
    SAFETY_BONUS = 15                       # Score bonus for accounts > 40%
    INERTIA_BONUS = 5                       # Score bonus for staying on current
    HEALTHY_INERTIA = 20                    # Extra inertia when current is healthy (>40%)
    SWITCH_THRESHOLD = 10                   # Minimum score improvement to switch

    def __init__(self, check_interval_minutes: int = 60):
        self.check_interval_minutes = check_interval_minutes
        self.last_check_time = 0
        self.account_reset_times: dict[str, int] = {}  # email -> reset_at timestamp
        self.last_switch_time = 0
        self.state_file = Path.home() / ".codex" / "quota_manager_state.json"
        self._load_state()

    def _load_state(self) -> None:
        """Load persistent state (reset times)."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                self.account_reset_times = {k: int(v) for k, v in data.get("reset_times", {}).items()}
            except Exception:
                self.account_reset_times = {}

    def _save_state(self) -> None:
        """Save persistent state."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(
                {"reset_times": self.account_reset_times},
                f,
                indent=2,
            )

    def fetch_all_quotas(self) -> list[QuotaSnapshot]:
        """Fetch quota for all accounts (both providers)."""
        snapshots: list[QuotaSnapshot] = []
        now = int(time.time())

        # Codex accounts
        try:
            for email in list_codex_accounts():
                try:
                    account = load_codex_account(email)
                    quota = fetch_codex_quota(account.access_token, account.account_id)
                    reset_at = quota.weekly_reset_at
                    time_until_reset = (reset_at - now) / 3600.0  # hours

                    snapshot = QuotaSnapshot(
                        provider=Provider.CODEX,
                        email=account.email,
                        account_id=account.account_id,
                        plan_type=quota.plan_type or "unknown",
                        used_percent=quota.weekly_used_percent,
                        reset_at=reset_at,
                        reset_at_readable=datetime.fromtimestamp(reset_at).strftime("%Y-%m-%d %H:%M"),
                        time_until_reset_hours=time_until_reset,
                    )
                    snapshots.append(snapshot)
                    self.account_reset_times[account.email] = reset_at
                except Exception as e:
                    print(f"Warning: failed to fetch Codex quota for {email}: {e}")
        except Exception as e:
            print(f"Warning: failed to load Codex accounts: {e}")

        # Google accounts
        try:
            accounts = list_google_accounts_fn()
            # Google's list_accounts returns Account objects directly
            for account in accounts:
                try:
                    # Refresh token if expired
                    account.token = ensure_fresh_google_token(account.token)
                    save_google_account(account)
                    quota, _ = fetch_google_quota(account.token.access_token, account.project_id)
                    # Google quotas are per-model, find the max usage
                    max_used_percent = 0
                    max_reset_at = 0
                    for model_quota in quota.models:
                        used = 100 - (model_quota.percentage or 0)
                        if used > max_used_percent:
                            max_used_percent = used
                        if model_quota.reset_time:
                            try:
                                reset_ts = int(datetime.fromisoformat(
                                    model_quota.reset_time.replace("Z", "+00:00")
                                ).timestamp())
                                if reset_ts > max_reset_at:
                                    max_reset_at = reset_ts
                            except Exception:
                                pass

                    if max_reset_at == 0:
                        max_reset_at = now + 86400  # Default 24h if unknown

                    time_until_reset = (max_reset_at - now) / 3600.0

                    snapshot = QuotaSnapshot(
                        provider=Provider.GOOGLE,
                        email=account.email,
                        account_id=account.project_id or "",
                        plan_type=quota.subscription_tier or "unknown",
                        used_percent=max_used_percent,
                        reset_at=max_reset_at,
                        reset_at_readable=datetime.fromtimestamp(max_reset_at).strftime("%Y-%m-%d %H:%M"),
                        time_until_reset_hours=time_until_reset,
                    )
                    snapshots.append(snapshot)
                    self.account_reset_times[account.email] = max_reset_at
                except Exception as e:
                    print(f"Warning: failed to fetch Google quota for {account.email}: {e}")
        except Exception as e:
            print(f"Warning: failed to load Google accounts: {e}")

        self._save_state()
        return sorted(snapshots, key=lambda s: (-s.remaining_percent, s.time_until_reset_hours))

    def _score_account(self, snapshot: QuotaSnapshot, is_current: bool = False) -> float:
        """
        Unified scoring formula for an account.

        score = remaining + waste_urgency + safety_bonus + inertia

        Components:
        - remaining: base value (0-100)
        - waste_urgency: boosts accounts with quota about to expire
          = remaining × (WASTE_WINDOW - hours_to_reset) / WASTE_WINDOW
          Only applies when hours_to_reset < WASTE_WINDOW
        - safety_bonus: +15 for accounts with >40% (can sustain a full task)
        - inertia: +5 for current account (anti-thrash)

        Examples:
        - Account A: 50% remaining, 2h until reset, current
          → 50 + 50*(6-2)/6 + 15 + 5 = 50 + 33.3 + 15 + 5 = 103.3
        - Account B: 80% remaining, 120h until reset, not current
          → 80 + 0 + 15 + 0 = 95
        - Account C: 20% remaining, 1h until reset, not current
          → 20 + 20*(6-1)/6 + 0 + 0 = 20 + 16.7 + 0 = 36.7
        → Switch to A (use its 50% before reset), even though B has more remaining
        """
        remaining = snapshot.remaining_percent

        # Waste urgency: boost accounts with quota about to be lost on reset
        waste_urgency = 0.0
        hours = snapshot.time_until_reset_hours
        if 0 < hours <= self.WASTE_WINDOW_HOURS and remaining > 0:
            waste_urgency = remaining * (self.WASTE_WINDOW_HOURS - hours) / self.WASTE_WINDOW_HOURS

        # Safety bonus: prefer accounts that can sustain a full task
        safety = self.SAFETY_BONUS if remaining > self.TASK_SAFETY_THRESHOLD else 0

        # Inertia: preference for staying on current account
        # Extra inertia when healthy — don't switch between two good accounts
        inertia = 0
        if is_current:
            inertia = self.INERTIA_BONUS
            if remaining > self.TASK_SAFETY_THRESHOLD:
                inertia += self.HEALTHY_INERTIA

        return remaining + waste_urgency + safety + inertia

    def _is_fresh_reset(self, snapshot: QuotaSnapshot) -> bool:
        """Check if account just reset or is in immediate post-reset window."""
        return snapshot.remaining_percent >= self.FRESH_QUOTA_THRESHOLD

    def analyze_and_decide(
        self,
        current_email: str,
        current_snapshot: Optional[QuotaSnapshot],
        all_snapshots: list[QuotaSnapshot],
    ) -> SwitchDecision:
        """
        Analyze quota situation and decide whether to switch accounts.

        Uses unified scoring that balances:
        1. Waste prevention (use expiring quota before it's lost)
        2. Task safety (prefer >40% for new tasks)
        3. Continuity (inertia for current account)
        """
        if not current_snapshot:
            # No current account info — pick the best available
            if all_snapshots:
                scored = [(s, self._score_account(s)) for s in all_snapshots]
                best, best_score = max(scored, key=lambda x: x[1])
                return SwitchDecision(
                    should_switch=True,
                    reason=f"No current account — selecting best (score {best_score:.0f})",
                    target_email=best.email,
                    target_remaining=best.remaining_percent,
                    current_email=current_email,
                    current_remaining=None,
                )
            return SwitchDecision(
                should_switch=False,
                reason="No account quota available",
                target_email=None,
                target_remaining=None,
                current_email=current_email,
                current_remaining=None,
            )

        # Score current account
        current_score = self._score_account(current_snapshot, is_current=True)

        # Score all candidates
        candidates = [s for s in all_snapshots if s.email != current_email]
        if not candidates:
            return SwitchDecision(
                should_switch=False,
                reason="No other accounts available",
                target_email=None,
                target_remaining=None,
                current_email=current_email,
                current_remaining=current_snapshot.remaining_percent,
            )

        scored = [(s, self._score_account(s)) for s in candidates]
        best_snapshot, best_score = max(scored, key=lambda x: x[1])

        improvement = best_score - current_score

        # Determine reason for decision
        if improvement > self.SWITCH_THRESHOLD:
            # Explain WHY we're switching
            reason_parts = []
            best_hours = best_snapshot.time_until_reset_hours
            if (0 < best_hours <= self.WASTE_WINDOW_HOURS
                    and best_snapshot.remaining_percent > 0):
                reason_parts.append(
                    f"waste prevention: {best_snapshot.remaining_percent}% expiring in {best_hours:.1f}h"
                )
            if best_snapshot.remaining_percent > self.TASK_SAFETY_THRESHOLD:
                reason_parts.append(f"task-safe ({best_snapshot.remaining_percent}% remaining)")
            if self._is_fresh_reset(best_snapshot):
                reason_parts.append(f"fresh reset ({best_snapshot.remaining_percent}%)")

            reason = "; ".join(reason_parts) if reason_parts else f"better score"
            reason += f" (score {current_score:.0f} → {best_score:.0f}, Δ{improvement:.0f})"

            return SwitchDecision(
                should_switch=True,
                reason=reason,
                target_email=best_snapshot.email,
                target_remaining=best_snapshot.remaining_percent,
                current_email=current_email,
                current_remaining=current_snapshot.remaining_percent,
            )

        # Stay — explain why
        if current_snapshot.remaining_percent > self.TASK_SAFETY_THRESHOLD:
            reason = f"Current quota healthy ({current_snapshot.remaining_percent}% remaining)"
        else:
            reason = f"No significant improvement (Δ{improvement:.0f}, need >{self.SWITCH_THRESHOLD})"

        return SwitchDecision(
            should_switch=False,
            reason=reason,
            target_email=None,
            target_remaining=None,
            current_email=current_email,
            current_remaining=current_snapshot.remaining_percent,
        )

    def check_and_switch_if_needed(self) -> SwitchDecision:
        """
        Check all account quotas and switch if necessary.

        Returns: SwitchDecision with details about action taken.
        """
        now = int(time.time())

        # Rate limit checks (no more than once per check_interval)
        if now - self.last_check_time < self.check_interval_minutes * 60:
            return SwitchDecision(
                should_switch=False,
                reason=f"Check rate limited (next in {self.check_interval_minutes}min)",
                target_email=None,
                target_remaining=None,
                current_email=None,
                current_remaining=None,
            )

        self.last_check_time = now

        # Fetch all quotas
        snapshots = self.fetch_all_quotas()
        if not snapshots:
            return SwitchDecision(
                should_switch=False,
                reason="No accounts found",
                target_email=None,
                target_remaining=None,
                current_email=None,
                current_remaining=None,
            )

        # Determine current active account
        current_email: Optional[str] = None
        current_snapshot: Optional[QuotaSnapshot] = None

        # Try to get Codex active account
        try:
            codex_email = get_active_codex_email()
            if codex_email:
                current_email = codex_email
        except Exception:
            pass

        # Try to get Google active account if no Codex
        if not current_email:
            try:
                google_email = get_active_google_email()
                if google_email:
                    current_email = google_email
            except Exception:
                pass

        # Find current snapshot
        if current_email:
            for snapshot in snapshots:
                if snapshot.email == current_email:
                    current_snapshot = snapshot
                    break

        # Analyze and decide
        decision = self.analyze_and_decide(current_email or "unknown", current_snapshot, snapshots)

        # Execute switch if needed
        if decision.should_switch and decision.target_email:
            try:
                # Determine which provider the target belongs to
                target_snapshot = next(s for s in snapshots if s.email == decision.target_email)

                if target_snapshot.provider == Provider.CODEX:
                    set_active_codex_account(decision.target_email)
                else:  # GOOGLE
                    set_active_google_account(decision.target_email)

                self.last_switch_time = now
                decision.reason += " [SWITCHED]"
            except Exception as e:
                print(f"Switch error: {e}")
                decision.reason += f" [SWITCH FAILED: {e}]"

        return decision


def print_quota_report(snapshots: list[QuotaSnapshot], manager: Optional[QuotaManager] = None) -> None:
    """Print formatted quota report for all accounts."""
    if not snapshots:
        print("No accounts found.")
        return

    w = 120
    print()
    print("╔" + "═" * w + "╗")
    print("║ QUOTA STATUS REPORT".ljust(w + 2) + "║")
    print("╠" + "═" * w + "╣")
    print(
        "║ "
        + "Email".ljust(40)
        + " Plan   Remaining           Reset Time            Until"
        + "  Score"
        + " Provider ║"
    )
    print("╟" + "─" * w + "╢")

    for snapshot in sorted(snapshots, key=lambda s: (-s.remaining_percent, s.time_until_reset_hours)):
        remaining = snapshot.remaining_percent
        filled = int(remaining / 5)
        bar = "[" + ("█" * filled) + ("░" * (20 - filled)) + "]"
        icon = "🟢" if remaining > 40 else "🟡" if remaining > 5 else "🔴"

        score_str = ""
        if manager:
            score = manager._score_account(snapshot)
            score_str = f"{score:>6.1f}"
        else:
            score_str = "    - "

        line = (
            f"║ {icon} {snapshot.email:<38} {snapshot.plan_type:<6} "
            f"{bar} {remaining:>3}% "
            f"{snapshot.reset_at_readable:<19} {snapshot.time_until_reset_hours:>5.1f}h "
            f"{score_str}"
            f" {snapshot.provider.value:>8} ║"
        )
        print(line)

    print("╚" + "═" * w + "╝")
    print()


if __name__ == "__main__":
    manager = QuotaManager(check_interval_minutes=1)  # For testing

    snapshots = manager.fetch_all_quotas()
    print_quota_report(snapshots, manager)

    decision = manager.check_and_switch_if_needed()
    print("Decision:", decision)
