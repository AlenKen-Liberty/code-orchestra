#!/usr/bin/env python3
"""
Example: Using the Quota Manager in your application

Demonstrates how to integrate automatic quota checking and switching
into your pipeline or application.
"""

from models.quota_manager import QuotaManager, print_quota_report


def example_1_simple_status():
    """Example 1: Get current quota status."""
    print("=" * 80)
    print("EXAMPLE 1: Simple Status Check")
    print("=" * 80)

    manager = QuotaManager()
    snapshots = manager.fetch_all_quotas()
    print_quota_report(snapshots)


def example_2_auto_switching():
    """Example 2: Auto-switch if quota is low."""
    print("=" * 80)
    print("EXAMPLE 2: Auto-Switching Based on Quota")
    print("=" * 80)

    manager = QuotaManager(check_interval_minutes=0)  # Force check
    decision = manager.check_and_switch_if_needed()

    print(f"\nDecision: {decision}")
    print()

    if decision.should_switch:
        print(f"✓ Automatically switched to {decision.target_email}")
        print(f"  Reason: {decision.reason}")
    else:
        print(f"✓ Staying on {decision.current_email}")
        print(f"  Reason: {decision.reason}")
    print()


def example_3_before_api_call():
    """Example 3: Check quota before making API calls."""
    print("=" * 80)
    print("EXAMPLE 3: Pre-flight Check Before API Calls")
    print("=" * 80)

    manager = QuotaManager(check_interval_minutes=0)
    decision = manager.check_and_switch_if_needed()

    if decision.current_remaining is not None:
        remaining = decision.current_remaining

        if remaining > 50:
            print(f"✓ Quota healthy ({remaining}%)")
            print("  → Safe to make API calls")
        elif remaining > 20:
            print(f"⚠ Quota moderate ({remaining}%)")
            print("  → Make API calls, monitor closely")
        else:
            print(f"🔴 Quota low ({remaining}%)")
            print("  → Consider switching or limiting requests")
    print()


def example_4_effective_quota_analysis():
    """Example 4: Analyze effective quota considering reset times."""
    print("=" * 80)
    print("EXAMPLE 4: Effective Quota Analysis (Reset-Aware)")
    print("=" * 80)

    manager = QuotaManager()
    snapshots = manager.fetch_all_quotas()

    print("\nDetailed Analysis (sorted by effective score):")
    print("-" * 80)

    scored = [
        (snapshot, manager._calculate_effective_quota(snapshot))
        for snapshot in snapshots
    ]

    for snapshot, score in sorted(scored, key=lambda x: -x[1]):
        marker = "🥇" if snapshot.remaining_percent >= 90 else "✓"
        print(
            f"{marker} {snapshot.email:<40} | "
            f"Remaining: {snapshot.remaining_percent:>3}% | "
            f"Resets in: {snapshot.time_until_reset_hours:>6.1f}h | "
            f"Effective Score: {score:>6.1f}"
        )
    print()


def example_5_continuous_monitoring():
    """Example 5: Continuous monitoring (simulated)."""
    print("=" * 80)
    print("EXAMPLE 5: Continuous Monitoring (Demo)")
    print("=" * 80)

    manager = QuotaManager(check_interval_minutes=0)

    print("\nRunning 3 checks...\n")

    for i in range(1, 4):
        print(f"Check #{i}:")
        decision = manager.check_and_switch_if_needed()
        print(f"  {decision}")
        print()


def example_6_integration_with_pipeline():
    """Example 6: Integration with a hypothetical API pipeline."""
    print("=" * 80)
    print("EXAMPLE 6: Pipeline Integration Pattern")
    print("=" * 80)

    print("""
# Your pipeline code:

class APIClient:
    def __init__(self):
        self.quota_manager = QuotaManager(check_interval_minutes=60)

    def call_api(self, prompt: str, model: str) -> str:
        # Pre-flight check: ensure good quota
        decision = self.quota_manager.check_and_switch_if_needed()

        if decision.should_switch:
            print(f"Auto-switched to {decision.target_email}")

        # Get current account
        current_email = decision.current_email
        remaining = decision.current_remaining

        if remaining < 10:
            raise RuntimeError(f"Critical: {current_email} has {remaining}% quota")

        # Make the actual API call
        # ... API call code ...

        return "API response"


# Usage:
client = APIClient()
response = client.call_api("Hello", "gpt-5")
    """)
    print()


def main():
    """Run all examples."""
    try:
        example_1_simple_status()
        example_2_auto_switching()
        example_3_before_api_call()
        example_4_effective_quota_analysis()
        example_5_continuous_monitoring()
        example_6_integration_with_pipeline()

        print("=" * 80)
        print("ALL EXAMPLES COMPLETED")
        print("=" * 80)

    except Exception as e:
        print(f"Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
