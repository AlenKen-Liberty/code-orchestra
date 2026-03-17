"""
cli.py — CLI entry point for Google Antigravity account management.

Usage:
    python -m models.google.cli login          # OAuth login via browser
    python -m models.google.cli status         # Quota dashboard
    python -m models.google.cli list           # List accounts
    python -m models.google.cli switch <email> # Switch active account
    python -m models.google.cli remove <email> # Remove account
    python -m models.google.cli rotate         # Auto-rotate OpenClaw to best account
"""

import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_RED = "\033[41m"


# ---------------------------------------------------------------------------
# Progress bar helper
# ---------------------------------------------------------------------------

def _progress_bar(fraction_used: float, width: int = 15) -> str:
    """Render a progress bar. fraction_used is 0.0 (empty) to 1.0 (full)."""
    filled = int(fraction_used * width)
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    if fraction_used >= 0.9:
        return f"{C.RED}{bar}{C.RESET}"
    elif fraction_used >= 0.6:
        return f"{C.YELLOW}{bar}{C.RESET}"
    else:
        return f"{C.GREEN}{bar}{C.RESET}"


def _format_duration(seconds: float, is_100_percent: bool = False) -> str:
    """Format seconds as Xh Ym Zs."""
    if seconds <= 0:
        return "now"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h >= 24 and is_100_percent:
        return "24h"
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    elif m > 0:
        return f"{m}m{s:02d}s"
    else:
        return f"{s}s"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_login():
    """Interactive OAuth login via browser callback."""
    from models.google.oauth import run_oauth_flow
    from models.google.account import add_account

    print(f"\n  {C.BOLD}🔐 Google Account Login{C.RESET}")
    print(f"  ─────────────────────────────────────\n")

    try:
        token = run_oauth_flow(open_browser=True)
    except Exception as e:
        print(f"  {C.RED}❌ Login failed: {e}{C.RESET}")
        return

    if not token.email:
        print(f"  {C.RED}❌ Could not determine email from token{C.RESET}")
        return

    account = add_account(token.email, token)

    print(f"  {C.GREEN}✅ Successfully logged in as {C.BOLD}{token.email}{C.RESET}")
    print(f"  {C.DIM}   Credentials saved to ~/.gemini/accounts/{token.email}.json{C.RESET}\n")

    # Try to fetch project_id immediately
    from models.google.quota import fetch_project_id
    print(f"  {C.DIM}   Discovering project ID...{C.RESET}", end="", flush=True)
    try:
        pid, tier = fetch_project_id(token.access_token)
        if pid:
            account.project_id = pid
            account.subscription_tier = tier
            from models.google.account import save_account
            save_account(account)
            print(f" {C.GREEN}✓{C.RESET} {pid}")
            if tier:
                print(f"  {C.DIM}   Subscription: {tier}{C.RESET}")
        else:
            print(f" {C.YELLOW}(not found){C.RESET}")
    except Exception:
        print(f" {C.YELLOW}(skipped){C.RESET}")

    print()


def cmd_status(ide_type: str = "IDE_UNSPECIFIED"):
    """Display quota dashboard for all accounts."""
    from models.google.account import list_accounts, get_active_email, save_account
    from models.google.oauth import ensure_fresh_token
    from models.google.quota import fetch_account_quota

    accounts = list_accounts()
    active_email = get_active_email()

    if not accounts:
        print(f"\n  {C.YELLOW}No accounts registered. Run 'login' first.{C.RESET}\n")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 65}")
    print(f"  {C.BOLD}📊 Google Account Quota Dashboard ({ide_type}){C.RESET}")
    print(f"{'=' * 65}")
    print(f"  {C.DIM}Time: {now}{C.RESET}\n")

    for acc in accounts:
        is_active = acc.email == active_email
        prefix = f"  → {C.CYAN}ACTIVE{C.RESET} " if is_active else "    "
        print(f"{prefix}{C.BOLD}{acc.email}{C.RESET}")

        if acc.disabled:
            print(f"    {C.DIM}Status: {C.RED}DISABLED{C.RESET} {C.DIM}({acc.disabled_reason or 'unknown'}){C.RESET}")
            print()
            continue

        # Refresh token if needed
        try:
            acc.token = ensure_fresh_token(acc.token)
            save_account(acc)
        except Exception as e:
            print(f"    {C.RED}Status: TOKEN INVALID ({e}){C.RESET}")
            print()
            continue

        print(f"    {C.DIM}Status: {C.GREEN}🟢 OK{C.RESET}")
        if acc.subscription_tier:
            print(f"    {C.DIM}Tier: {acc.subscription_tier}{C.RESET}")

        # Fetch per-model quota
        print(f"\n    {C.DIM}Models (Per-Account Quota):{C.RESET}")
        try:
            quota, new_pid = fetch_account_quota(
                acc.token.access_token,
                cached_project_id=acc.project_id,
                ide_type=ide_type,
            )

            # Cache project_id if discovered
            if new_pid and new_pid != acc.project_id:
                acc.project_id = new_pid
                save_account(acc)

            if quota.is_forbidden:
                print(f"      {C.RED}⛔ Account forbidden (403){C.RESET}")
            elif not quota.models:
                print(f"      {C.DIM}(No quota data available){C.RESET}")
            else:
                # Group by family
                families = {}  # family_name -> ModelQuota
                for mq in quota.models:
                    f_name = mq.family
                    if f_name not in families:
                        families[f_name] = mq
                    else:
                        # Keep the one with lowest percentage
                        if mq.percentage < families[f_name].percentage:
                            families[f_name] = mq
                
                # Sort: exhausted first, then by family name
                sorted_families = sorted(families.values(), key=lambda m: (not m.is_exhausted, m.family))

                for mq in sorted_families:
                    family_name = mq.family
                    name_padded = f"{family_name[:30]:<30}"
                    fraction_used = 1.0 - (mq.percentage / 100.0)
                    bar = _progress_bar(fraction_used, width=15)

                    secs = mq.time_until_reset_secs

                    if mq.percentage == 0 and mq.is_exhausted:
                        status_str = f"{C.RED}⛔ EXHAUSTED{C.RESET}"
                    elif secs is not None and secs > 86400 and mq.percentage < 100:
                        # Long reset + reduced quota = soft-limited (but still callable)
                        status_str = f"{C.YELLOW}⚠ {mq.remaining_str:>3} remaining{C.RESET}"
                    elif mq.is_exhausted:
                        status_str = f"{C.RED}EXHAUSTED{C.RESET}"
                    else:
                        status_str = f"{mq.remaining_str:>4} remaining"

                    reset_str = ""
                    if secs is not None and secs > 0:
                        reset_str = f" {C.DIM}(Resets in: {_format_duration(secs, is_100_percent=(mq.percentage == 100))}){C.RESET}"

                    print(f"      {name_padded} {bar} {status_str}{reset_str}")

            # Save quota snapshot
            if quota.models:
                acc.quota = {"models": [{"name": m.name, "pct": m.percentage} for m in quota.models],
                             "ts": int(time.time())}
                save_account(acc)

        except Exception as e:
            print(f"      {C.RED}Error: {e}{C.RESET}")

        print()

    # Recommendation
    print(f"{'─' * 65}")
    if active_email:
        print(f"  {C.GREEN}✅ Active account: {active_email}{C.RESET}")
    print()


def cmd_rotate(model_filter: str = "claude-opus-4-6-thinking", threshold: int = 20, ide_type: str = "IDE_UNSPECIFIED"):
    """Auto-rotate OpenClaw's google-antigravity to the best available account."""
    from .account import list_accounts, sync_openclaw_rotate
    from .quota import fetch_available_models
    from .oauth import ensure_fresh_token

    print(f"\n  🔄 Rotating OpenClaw account (ide: {ide_type}, model: {model_filter}, threshold: {threshold}%)")
    print()

    accounts = list_accounts()
    if not accounts:
        print(f"  {C.RED}No accounts found.{C.RESET}")
        return

    # Collect quota info
    candidates = []  # (email, pct, project_id)
    for acc in accounts:
        if acc.disabled:
            continue

        try:
            acc.token = ensure_fresh_token(acc.token)
        except Exception:
            print(f"  {C.DIM}  {acc.email}: ⚠ token refresh failed{C.RESET}")
            continue

        try:
            quota = fetch_available_models(acc.token.access_token, acc.project_id, ide_type=ide_type)
        except Exception:
            print(f"  {C.DIM}  {acc.email}: ⚠ quota fetch failed{C.RESET}")
            continue

        # Find matching model
        target_pct = None
        for mq in quota.models:
            if mq.name == model_filter or model_filter.lower() in mq.display_name.lower() or model_filter.lower() in mq.family.lower():
                target_pct = mq.percentage
                break

        if target_pct is None:
            print(f"  {C.DIM}  {acc.email}: model {model_filter} not found{C.RESET}")
            continue

        status = "✅" if target_pct > threshold else "⚠" if target_pct > 0 else "⛔"
        print(f"    {status} {acc.email}: {target_pct}% remaining")
        candidates.append((acc.email, target_pct, acc.project_id))

    if not candidates:
        print(f"\n  {C.RED}No candidates found for {model_filter}{C.RESET}")
        return

    # Sort by remaining percentage descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_email, best_pct, _ = candidates[0]

    if best_pct == 0:
        print(f"\n  {C.RED}⛔ All accounts exhausted for {model_filter}{C.RESET}")
        return

    print(f"\n  → Best: {C.GREEN}{best_email}{C.RESET} ({best_pct}% remaining)")

    # Apply rotation
    if sync_openclaw_rotate(best_email):
        print(f"  {C.GREEN}✅ OpenClaw lastGood updated to {best_email}{C.RESET}")
        print(f"  {C.DIM}   Restart OpenClaw gateway to apply.{C.RESET}")
    else:
        print(f"  {C.RED}❌ Failed to update auth-profiles.json{C.RESET}")
        print(f"  {C.DIM}   Does google-antigravity:{best_email} exist in auth-profiles.json?{C.RESET}")
    print()


def cmd_list():
    """List all registered accounts."""
    from models.google.account import list_accounts, get_active_email

    accounts = list_accounts()
    active = get_active_email()

    if not accounts:
        print(f"\n  {C.YELLOW}No accounts registered.{C.RESET}\n")
        return

    print(f"\n  {C.BOLD}Registered Accounts:{C.RESET}\n")
    for acc in accounts:
        marker = f"{C.CYAN}→{C.RESET}" if acc.email == active else " "
        status = f"{C.GREEN}OK{C.RESET}" if not acc.disabled else f"{C.RED}DISABLED{C.RESET}"
        print(f"  {marker} {acc.email}  [{status}]")
    print()


def cmd_switch(email: str):
    """Switch the active account."""
    from models.google.account import set_active_account

    if set_active_account(email):
        print(f"\n  {C.GREEN}✅ Switched active account to {email}{C.RESET}")
        print(f"  {C.DIM}   (Also synced to ~/.openclaw/google_accounts.json){C.RESET}\n")
    else:
        print(f"\n  {C.RED}❌ Account '{email}' not found{C.RESET}\n")


def cmd_sync():
    """Sync token from Gemini CLI into our account manager."""
    from models.google.account import sync_from_gemini_cli

    print(f"\n  {C.BOLD}🔄 Syncing from Gemini CLI...{C.RESET}")

    account = sync_from_gemini_cli()
    if account:
        print(f"  {C.GREEN}✅ Synced {account.email}{C.RESET}")
        print(f"  {C.DIM}   Token valid, saved to accounts.{C.RESET}\n")
    else:
        print(f"  {C.RED}❌ No token found in ~/.gemini/oauth_creds.json{C.RESET}")
        print(f"  {C.DIM}   Run 'gemini' and login first.{C.RESET}\n")


def cmd_sync_all():
    """Sync all Gemini CLI accounts by switching and syncing each one."""
    from models.google.account import sync_from_gemini_cli

    gemini_accounts_path = Path.home() / ".gemini" / "google_accounts.json"
    if not gemini_accounts_path.exists():
        print(f"  {C.RED}No Gemini CLI accounts found.{C.RESET}")
        return

    import json
    data = json.loads(gemini_accounts_path.read_text())
    active = data.get("active", "")
    old = data.get("old", [])
    all_emails = ([active] if active else []) + old

    if not all_emails:
        print(f"  {C.RED}No Gemini CLI accounts found.{C.RESET}")
        return

    print(f"\n  {C.BOLD}🔄 Syncing {len(all_emails)} Gemini CLI accounts...{C.RESET}\n")

    # The current oauth_creds.json is for the active account
    account = sync_from_gemini_cli()
    if account:
        print(f"  {C.GREEN}✅ {account.email}{C.RESET}")
    else:
        print(f"  {C.YELLOW}⚠ Could not sync active account{C.RESET}")

    remaining = [e for e in all_emails if e != (account.email if account else "")]
    if remaining:
        print(f"\n  {C.DIM}Other accounts need individual login:{C.RESET}")
        for email in remaining:
            print(f"  {C.DIM}  • {email} (switch in Gemini CLI, then run sync){C.RESET}")

    print()


def cmd_remove(email: str):
    """Remove an account."""
    from models.google.account import remove_account

    if remove_account(email):
        print(f"\n  {C.GREEN}✅ Removed account {email}{C.RESET}\n")
    else:
        print(f"\n  {C.RED}❌ Account '{email}' not found{C.RESET}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(f"""
  {C.BOLD}Google Account & Quota Manager (CLI){C.RESET}

  Usage: python -m models.google.cli <command>

  Commands:
    login              OAuth login via browser
    sync               Import token from Gemini CLI (after 'gemini' login)
    status [--ide X]   Quota dashboard for all accounts (X: ANTIGRAVITY, GEMINI_CLI)
    list               List registered accounts
    switch <email>     Switch active account
    remove <email>     Remove account
    rotate [--model X] [--threshold N] [--ide Z]
                       Auto-rotate OpenClaw to best account
""")
        return

    cmd = sys.argv[1].lower()

    if cmd == "login":
        cmd_login()
    elif cmd == "status":
        ide_type = "IDE_UNSPECIFIED"
        args = sys.argv[2:]
        if "--ide" in args:
            idx = args.index("--ide")
            if idx + 1 < len(args):
                ide_type = args[idx + 1].upper()
        cmd_status(ide_type)
    elif cmd == "sync":
        cmd_sync()
    elif cmd == "list":
        cmd_list()
    elif cmd == "switch":
        if len(sys.argv) < 3:
            print(f"  {C.RED}Usage: switch <email>{C.RESET}")
            return
        cmd_switch(sys.argv[2])
    elif cmd == "remove":
        if len(sys.argv) < 3:
            print(f"  {C.RED}Usage: remove <email>{C.RESET}")
            return
        cmd_remove(sys.argv[2])
    elif cmd == "rotate":
        # Parse optional --model, --threshold and --ide flags
        model_filter = "claude-opus-4-6-thinking"
        threshold = 20
        ide_type = "IDE_UNSPECIFIED"
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--model" and i + 1 < len(args):
                model_filter = args[i + 1]
                i += 2
            elif args[i] == "--threshold" and i + 1 < len(args):
                threshold = int(args[i + 1])
                i += 2
            elif args[i] == "--ide" and i + 1 < len(args):
                ide_type = args[i + 1].upper()
                i += 2
            else:
                i += 1
        cmd_rotate(model_filter, threshold, ide_type)
    else:
        print(f"  {C.RED}Unknown command: {cmd}{C.RESET}")
        print(f"  {C.DIM}Run without arguments to see usage.{C.RESET}")


if __name__ == "__main__":
    main()
