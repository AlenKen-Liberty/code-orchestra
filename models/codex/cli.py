from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import account
from . import quota


def _format_bar(remaining_percent: int, width: int = 10) -> str:
    """Progress bar showing remaining quota (filled = remaining)."""
    remaining_percent = max(0, min(100, int(remaining_percent)))
    filled = int(round(remaining_percent / 100 * width))
    filled = max(0, min(width, filled))
    return "[" + ("█" * filled) + ("░" * (width - filled)) + "]"


def _format_reset(reset_at: int) -> str:
    if not reset_at:
        return "n/a"
    diff = max(0, int(reset_at) - int(time.time()))
    days = diff // 86400
    hours = (diff % 86400) // 3600
    return f"{days}d {hours}h"


def _fetch_quota_for_account(acc: account.CodexAccount) -> quota.CodexQuota:
    acc = account.refresh_account_tokens(acc)
    try:
        return quota.fetch_quota(acc.access_token, acc.account_id)
    except quota.QuotaError as exc:
        if exc.status_code == 403:
            acc = account.refresh_account_tokens(acc, force=True)
            return quota.fetch_quota(acc.access_token, acc.account_id)
        raise


def _fetch_quotas_parallel(
    accounts: list[account.CodexAccount],
) -> tuple[list[tuple[account.CodexAccount, quota.CodexQuota]], list[tuple[account.CodexAccount, Exception]]]:
    results: list[tuple[account.CodexAccount, quota.CodexQuota]] = []
    errors: list[tuple[account.CodexAccount, Exception]] = []

    with ThreadPoolExecutor(max_workers=min(8, len(accounts))) as executor:
        futures = {executor.submit(_fetch_quota_for_account, acc): acc for acc in accounts}
        for future in as_completed(futures):
            acc = futures[future]
            try:
                results.append((acc, future.result()))
            except Exception as exc:
                errors.append((acc, exc))

    return results, errors


def _load_accounts_in_order() -> list[account.CodexAccount]:
    emails = account.list_accounts()
    accounts = []
    for email in emails:
        try:
            accounts.append(account.load_account(email))
        except FileNotFoundError:
            continue
    return accounts


def cmd_status(_: argparse.Namespace) -> int:
    accounts = _load_accounts_in_order()
    if not accounts:
        print("No accounts found. Use `python -m models.codex.cli import` after logging in.")
        return 1

    active_email = account.get_active_email()
    results, errors = _fetch_quotas_parallel(accounts)

    quota_by_email: dict[str, quota.CodexQuota] = {}
    for acc, quo in results:
        quota_by_email[acc.email] = quo
        if quo.plan_type:
            acc.plan_type = quo.plan_type
        if quo.raw:
            acc.quota_snapshot = quo.raw
        account.save_account(acc)

    errors_by_email = {acc.email: exc for acc, exc in errors}

    max_email = max(len(acc.email) for acc in accounts)
    header = "Codex Account Status"
    print(header)
    print()
    print(
        f"{'Account'.ljust(max_email)}  Plan   Remaining           Resets"
    )
    print(
        f"{'-' * max_email}  ----   -----------------  ------"
    )

    for acc in accounts:
        marker = ">" if acc.email == active_email else " "
        if acc.email in quota_by_email:
            quo = quota_by_email[acc.email]
            remaining = 100 - quo.weekly_used_percent
            bar = _format_bar(remaining)
            pct = f"{remaining:>3}%"
            reset = _format_reset(quo.weekly_reset_at)
            icon = "🟢" if remaining > 40 else "🟡" if remaining > 5 else "🔴"
            warn = " ⚠" if (quo.weekly_limit_reached or remaining <= 5) else ""
            plan = (quo.plan_type or acc.plan_type or "unknown").capitalize()
            print(
                f"{marker} {icon} {acc.email.ljust(max_email)}  {plan.ljust(5)}  {bar} {pct}  {reset}{warn}"
            )
        else:
            err = errors_by_email.get(acc.email)
            plan = (acc.plan_type or "unknown").capitalize()
            err_msg = str(err) if err else "unknown error"
            print(
                f"{marker} {acc.email.ljust(max_email)}  {plan.ljust(5)}  error: {err_msg}"
            )

    return 0


def cmd_list(_: argparse.Namespace) -> int:
    accounts = _load_accounts_in_order()
    active_email = account.get_active_email()
    for acc in accounts:
        marker = ">" if acc.email == active_email else " "
        print(f"{marker} {acc.email}")
    return 0


def cmd_switch(args: argparse.Namespace) -> int:
    target = account.set_active_account(args.email)
    print(f"Active account set to {target.email}")
    return 0


def cmd_import(_: argparse.Namespace) -> int:
    acc = account.import_current_account()
    print(f"Imported account {acc.email}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    cmd = ["codex", "login"]
    if args.device_auth:
        cmd.append("--device-auth")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        print("codex CLI not found on PATH", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"codex login failed: {exc}", file=sys.stderr)
        return exc.returncode or 1
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    account.remove_account(args.email)
    print(f"Removed account {args.email}")
    return 0


def cmd_rotate(_: argparse.Namespace) -> int:
    accounts = _load_accounts_in_order()
    if not accounts:
        print("No accounts found.")
        return 1

    results, errors = _fetch_quotas_parallel(accounts)
    if errors:
        for acc, err in errors:
            print(f"Warning: failed to fetch quota for {acc.email}: {err}", file=sys.stderr)

    candidates = [
        (acc, quo)
        for acc, quo in results
        if not quo.weekly_limit_reached and not acc.disabled
    ]
    if not candidates:
        print("All accounts are exhausted or disabled.")
        return 1

    best_acc, best_quota = min(candidates, key=lambda item: item[1].weekly_used_percent)
    active_email = account.get_active_email()

    best_remaining = 100 - best_quota.weekly_used_percent
    if best_acc.email == active_email:
        print(f"Already on best account {best_acc.email} ({best_remaining}% remaining).")
        return 0

    account.set_active_account(best_acc.email)
    print(
        f"Switched to {best_acc.email} ({best_remaining}% remaining)."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex multi-account manager")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show quota status for all accounts")
    sub.add_parser("list", help="List accounts")

    switch_parser = sub.add_parser("switch", help="Switch active account")
    switch_parser.add_argument("email")

    sub.add_parser("import", help="Import current ~/.codex/auth.json")

    login_parser = sub.add_parser("login", help="Run codex login")
    login_parser.add_argument("--device-auth", action="store_true")

    remove_parser = sub.add_parser("remove", help="Remove an account")
    remove_parser.add_argument("email")

    sub.add_parser("rotate", help="Switch to account with most quota remaining")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        return cmd_status(args)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "switch":
        return cmd_switch(args)
    if args.command == "import":
        return cmd_import(args)
    if args.command == "login":
        return cmd_login(args)
    if args.command == "remove":
        return cmd_remove(args)
    if args.command == "rotate":
        return cmd_rotate(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
