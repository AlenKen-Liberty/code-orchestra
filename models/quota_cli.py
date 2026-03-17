#!/usr/bin/env python3
"""
Quota Manager CLI - Monitor and auto-switch between Google Antigravity and Codex accounts.

Usage:
    python -m models.quota_cli status           # Show all account quotas
    python -m models.quota_cli check            # Check and switch if needed
    python -m models.quota_cli watch [INTERVAL] # Continuous monitoring (60s default)
    python -m models.quota_cli explain          # Explain the smart switching algorithm
"""

import argparse
import sys
import time
from models.quota_manager import QuotaManager, print_quota_report


def cmd_status(_: argparse.Namespace) -> int:
    """Show current quota status for all accounts."""
    manager = QuotaManager()
    snapshots = manager.fetch_all_quotas()
    print_quota_report(snapshots, manager)
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    """Check quotas and auto-switch if necessary."""
    manager = QuotaManager(check_interval_minutes=0)  # Force check
    decision = manager.check_and_switch_if_needed()
    print()
    print(f"Decision: {decision}")
    print()
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Continuous monitoring mode."""
    interval = int(args.interval or 60)
    manager = QuotaManager(check_interval_minutes=interval // 60)

    print(f"Starting quota monitor (check every {interval}s)")
    print("Press Ctrl+C to stop")
    print()

    iteration = 0
    try:
        while True:
            iteration += 1
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{iteration}] {timestamp} - Checking quotas...")

            snapshots = manager.fetch_all_quotas()
            print_quota_report(snapshots, manager)

            decision = manager.check_and_switch_if_needed()
            print(f"Decision: {decision}")

            if decision.should_switch:
                print(f"✓ Auto-switched to {decision.target_email}")

            print(f"\nNext check in {interval} seconds...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        return 0


def cmd_explain(_: argparse.Namespace) -> int:
    """Explain the smart switching algorithm."""
    print("""
╔════════════════════════════════════════════════════════════════════════════════════════╗
║                   WASTE-AWARE SMART QUOTA OPTIMIZATION ALGORITHM                      ║
╚════════════════════════════════════════════════════════════════════════════════════════╝

THREE GOALS (in priority order):

  1. WASTE PREVENTION  — Use quota before it resets (don't lose unused quota)
  2. TASK SAFETY       — Ensure >40% remaining when starting new tasks
  3. CONTINUITY        — Avoid unnecessary switching (anti-thrash)

═══════════════════════════════════════════════════════════════════════════════════════════

UNIFIED SCORING FORMULA:

  score = remaining + waste_urgency + safety_bonus + inertia

  ┌──────────────────┬────────────────────────────────────────────────────┐
  │ Component        │ Formula                                            │
  ├──────────────────┼────────────────────────────────────────────────────┤
  │ remaining        │ Current remaining % (0-100)                        │
  │ waste_urgency    │ remaining × (6 - hours_to_reset) / 6              │
  │                  │ Only when hours_to_reset < 6h, else 0              │
  │ safety_bonus     │ +15 if remaining > 40% (can sustain a full task)  │
  │ inertia          │ +5 for current account (avoid switching for noise) │
  │                  │ +20 extra if current is healthy (>40% remaining)  │
  └──────────────────┴────────────────────────────────────────────────────┘

  Switch only when: best_candidate.score - current.score > 10

═══════════════════════════════════════════════════════════════════════════════════════════

HOW EACH COMPONENT WORKS:

1. WASTE URGENCY (use-it-or-lose-it)
   ──────────────────────────────────
   If an account has quota about to reset, that quota will be LOST if unused.
   The waste_urgency boosts accounts proportionally to how much will be wasted
   and how soon the reset happens.

   Example: 50% remaining, 2h until reset
     waste_urgency = 50 × (6-2)/6 = 50 × 0.67 = 33.3

   Example: 10% remaining, 0.5h until reset
     waste_urgency = 10 × (6-0.5)/6 = 10 × 0.92 = 9.2

   → Accounts with MORE remaining AND closer to reset get the biggest boost

2. SAFETY BONUS (task readiness)
   ──────────────────────────────
   Accounts with >40% get +15, making them preferred for new tasks.
   This ensures you don't start a task on a nearly-depleted account.

3. INERTIA (anti-thrash)
   ──────────────────────
   Current account gets +5 base inertia.
   If current is healthy (>40%), gets +20 EXTRA "healthy inertia".
   → When you're in a good state, only waste prevention can pull you away.
   → Prevents pointless switching between two healthy accounts.

═══════════════════════════════════════════════════════════════════════════════════════════

EXAMPLE SCORING:

  Scenario: 5 accounts, you're on codex_A

  ┌─────────────────────────────────────────────┬──────┬───────┬──────┬─────────┬───────┐
  │ Account                                     │ Rem% │ Reset │Waste │Inertia  │ Score │
  ├─────────────────────────────────────────────┼──────┼───────┼──────┼─────────┼───────┤
  │ codex_A  (current)  50% remaining, 120h     │   50 │    0  │  +15 │ +5 +20  │  90.0 │
  │ codex_B             20% remaining, 2h       │   20 │ 13.3  │   +0 │    +0   │  33.3 │
  │ google_1            45% remaining, 3h       │   45 │ 22.5  │  +15 │    +0   │  82.5 │
  │ google_2            80% remaining, 48h      │   80 │    0  │  +15 │    +0   │  95.0 │
  │ codex_C              5% remaining, 0.5h     │    5 │  4.6  │   +0 │    +0   │   9.6 │
  └─────────────────────────────────────────────┴──────┴───────┴──────┴─────────┴───────┘

  Decision: STAY on codex_A (score 90.0 vs google_2 95.0, Δ5 < 10)
  Reason: Current healthy, not enough improvement to justify switch

  But if codex_A drops to 30% (unhealthy):
    codex_A: 30 + 0 + 0 + 5 = 35   (no safety bonus, no healthy inertia)
    google_2: 80 + 0 + 15 = 95
  → SWITCH to google_2 (Δ60, task-safe with 80% remaining)

  Waste prevention scenario — google_1 has 45% expiring in 3h:
    google_1: 45 + 45×(6-3)/6 + 15 = 45 + 22.5 + 15 = 82.5
    codex_A (30%): 30 + 0 + 0 + 5 = 35
  → SWITCH to google_1 (waste prevention: use 45% before reset)

═══════════════════════════════════════════════════════════════════════════════════════════

WHY THIS WORKS:

✓ PREVENTS WASTE
  Waste urgency naturally pulls you toward accounts with expiring quota.
  You use their quota before it disappears on reset.

✓ TASK SAFETY
  Safety bonus ensures you prefer >40% accounts for new tasks.
  You won't run out of quota mid-task.

✓ NO THRASHING
  Inertia (+5) + switch threshold (>10) = stability.
  You only switch when there's a clear benefit.

✓ ADAPTS AUTOMATICALLY
  As reset times approach, waste_urgency increases smoothly.
  No sudden jumps — the scoring is continuous.

✓ SINGLE FORMULA
  One unified score handles all cases: healthy, low, expiring, fresh.
  No complex if/else chains or special-case rules.

═══════════════════════════════════════════════════════════════════════════════════════════

CONFIGURATION:

  TASK_SAFETY_THRESHOLD = 40%    # Safety bonus kicks in above this
  WASTE_WINDOW_HOURS   = 6      # Waste urgency active within this window
  SAFETY_BONUS         = 15     # Bonus points for >40% accounts
  INERTIA_BONUS        = 5      # Base bonus for staying on current
  HEALTHY_INERTIA      = 20     # Extra bonus when current is healthy (>40%)
  SWITCH_THRESHOLD     = 10     # Minimum score delta to trigger switch

═══════════════════════════════════════════════════════════════════════════════════════════
""")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quota Manager - Monitor and auto-switch between accounts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m models.quota_cli status                    # Show current status
  python -m models.quota_cli check                     # Check and switch if needed
  python -m models.quota_cli watch                     # Continuous monitoring (60s interval)
  python -m models.quota_cli watch 30                  # Monitor every 30 seconds
  python -m models.quota_cli explain                   # Show algorithm details
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show quota status for all accounts")
    subparsers.add_parser("check", help="Check and auto-switch if necessary")

    watch_parser = subparsers.add_parser("watch", help="Continuous monitoring")
    watch_parser.add_argument(
        "interval",
        nargs="?",
        type=int,
        default=60,
        help="Check interval in seconds (default: 60)",
    )

    subparsers.add_parser("explain", help="Explain the smart switching algorithm")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        return cmd_status(args)
    elif args.command == "check":
        return cmd_check(args)
    elif args.command == "watch":
        return cmd_watch(args)
    elif args.command == "explain":
        return cmd_explain(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
