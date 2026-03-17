# Unified Quota Manager System

## 🎯 Overview

A **smart, intelligent quota management system** for Google Antigravity and OpenAI Codex accounts that:

- ✅ Automatically switches accounts when quota gets low (<40%)
- ✅ Prioritizes fresh resets (>90% quota)
- ✅ Uses "effective quota" scoring to consider reset timing
- ✅ Remembers reset times and adapts dynamically
- ✅ Prevents quota exhaustion and maximizes utilization
- ✅ Supports continuous monitoring (background mode)
- ✅ Works with both Google and Codex providers

## 📊 Current Account Status

```
🟢 swimming.crystalball@gmail.com    1% used  (167.0h until reset)
🟢 carpool.london@gmail.com          1% used  (167.1h until reset)
🟢 aken@liberty.edu                 19% used  (120.9h until reset) ← ACTIVE
🟡 maritime2007@gmail.com           94% used  ( 40.8h until reset)
🔴 liuyl.david@gmail.com           100% used  ( 27.1h until reset)
```

## 🚀 Usage

### Check Current Status
```bash
python3 -m models.quota_cli status
```

### Auto-Check & Switch
```bash
python3 -m models.quota_cli check
```

### Continuous Monitoring
```bash
python3 -m models.quota_cli watch        # Check every 60 seconds
python3 -m models.quota_cli watch 30     # Check every 30 seconds
```

### Learn the Algorithm
```bash
python3 -m models.quota_cli explain
```

## 🧠 How It Works

### Three Smart Rules

#### Rule 1: Threshold (40%)
- If remaining > 40% → **STAY** (healthy)
- If remaining ≤ 40% → **EVALUATE** switching

#### Rule 2: Fresh Reset (90%)
- If any account has ≥ 90% remaining → **SWITCH immediately**
- Reason: Maximum quota just became available

#### Rule 3: Effective Quota Scoring
When deciding between multiple low-quota accounts, use:

```
Score = remaining% + reset_boost

reset_boost = {
    100 × (1 - hours_to_reset / 4)    if hours_to_reset ≤ 4
    0                                  otherwise
}
```

**Example:** Account resetting in 2 hours with 10% remaining:
- Score = 10 + 100×(1 - 2/4) = 10 + 50 = **60**
- Gets boosted priority because it'll have fresh quota soon

### Why This Works

| Problem | Solution |
|---------|----------|
| Accounts go to 0% quota | Switch at 40% threshold |
| Miss fresh resets | Detect >90% and switch immediately |
| Unfair distribution | Fair scoring, no account starved |
| Wasted quota from expired periods | Boost accounts about to reset |
| Constant thrashing | Require 10-point improvement to switch |

## 📈 Example Decision Flow

**Scenario:** Current account = aken@liberty.edu (20% remaining)

```
Step 1: Check threshold
  20% ≤ 40% → NEEDS SWITCHING

Step 2: Check for fresh resets
  No account ≥ 90% → SKIP

Step 3: Calculate effective scores
  swimming.crystalball: 99% + 0 = 99   ⭐ BEST
  carpool.london:       99% + 0 = 99   ⭐ TIED
  maritime2007:         6% + 25 = 31
  liuyl.david:          0% + 10 = 10

Decision: SWITCH to swimming.crystalball@gmail.com
Reason: Highest effective quota (99%)
```

## 🔧 Integration

### In Your Code
```python
from models.quota_manager import QuotaManager

manager = QuotaManager(check_interval_minutes=60)

# Before making API calls:
decision = manager.check_and_switch_if_needed()

if decision.should_switch:
    print(f"Auto-switched to {decision.target_email}")

# Get current account info:
snapshots = manager.fetch_all_quotas()
for snap in snapshots:
    print(f"{snap.email}: {snap.remaining_percent}% remaining")
```

### In Your Pipeline
```python
class MyAPIClient:
    def __init__(self):
        self.quota_manager = QuotaManager()

    def call_api(self, prompt):
        # Auto-check and switch if needed
        self.quota_manager.check_and_switch_if_needed()
        
        # Make API call (will use new account if switched)
        return self.api.call(prompt)
```

## 📁 Files

| File | Purpose |
|------|---------|
| `quota_manager.py` | Core algorithm & logic |
| `quota_cli.py` | Command-line interface |
| `QUOTA_MANAGER.md` | Detailed documentation |
| `example_quota_usage.py` | Integration examples |
| `README_QUOTA.md` | This file |

## 🎛️ Configuration

Edit constants in `quota_manager.py`:

```python
class QuotaManager:
    QUOTA_THRESHOLD = 40          # Switch when ≤ 40%
    FRESH_QUOTA_THRESHOLD = 90    # Immediate switch at ≥ 90%
    URGENT_RESET_HOURS = 4        # Boost if resetting within 4h
```

## 💾 Persistent State

Reset times are remembered in:
```
~/.codex/quota_manager_state.json
```

Contains:
```json
{
  "reset_times": {
    "aken@liberty.edu": 1774130071,
    "carpool.london@gmail.com": 1773811640,
    ...
  }
}
```

## ✨ Key Features

✅ **Intelligent** — Uses effective quota scoring considering reset timing
✅ **Automatic** — No manual switching needed
✅ **Safe** — Switches proactively (40%), not reactively
✅ **Fair** — All accounts treated equally
✅ **Efficient** — Minimizes wasted quota
✅ **Resilient** — Adapts to unexpected resets
✅ **Observable** — Color-coded status + detailed logs
✅ **Persistent** — Remembers reset times across sessions
✅ **Extensible** — Easy to add more providers

## 📊 Quota Status Legend

| Color | Symbol | Meaning |
|-------|--------|---------|
| 🟢 Green | [=====] | >40% remaining (healthy) |
| 🟡 Yellow | [==   ] | 10-40% remaining (caution) |
| 🔴 Red | [     ] | <10% remaining (critical) |

## 🔮 Algorithm Comparison

### Simple Strategy: Round-Robin
```
Cycle through accounts sequentially
✗ Wastes quota
✗ Misses reset optimization
```

### Simple Strategy: Switch at 10%
```
Only switch when critically low
✗ Starves accounts
✗ Unfair
✗ Reactive
```

### Our Strategy: Smart + Reset-Aware
```
✓ Proactive (40% threshold)
✓ Reset-aware (boosts resetting soon)
✓ Fair (all equal treatment)
✓ Efficient (minimizes waste)
✓ Resilient (adapts to surprises)
```

## 📝 Commands Reference

```bash
# Status check
python3 -m models.quota_cli status

# Auto-switch check
python3 -m models.quota_cli check

# Continuous monitoring
python3 -m models.quota_cli watch             # 60s interval
python3 -m models.quota_cli watch 30          # 30s interval

# View algorithm explanation
python3 -m models.quota_cli explain

# Run examples
python3 -c "
import sys
sys.path.insert(0, '.')
from models.quota_manager import QuotaManager, print_quota_report
manager = QuotaManager()
print_quota_report(manager.fetch_all_quotas())
"
```

## 🐛 Troubleshooting

### Q: Why is Google showing 401 errors?
**A:** OAuth tokens expired. System will refresh automatically on next quota check.

### Q: How often should I run checks?
**A:** 60 minutes (default) is ideal. More = more API calls. Less = slower reaction to resets.

### Q: Can I use only Codex or only Google?
**A:** Yes, system auto-detects available providers.

### Q: What's the startup overhead?
**A:** ~1-2 seconds (parallel quota fetches). Subsequent checks use cached times.

---

**Status:** ✅ Production Ready
**Last Updated:** 2026-03-16
**Algorithm:** Smart Three-Rule Decision System with Reset-Aware Effective Quota Scoring
