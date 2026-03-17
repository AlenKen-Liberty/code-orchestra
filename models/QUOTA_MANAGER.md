# Unified Quota Manager for Google Antigravity & Codex

**Smart multi-account quota optimization system**

Intelligently monitors and switches between Google Antigravity and OpenAI Codex accounts to maximize API quota utilization while preventing exhaustion.

## Quick Start

### 1. View Current Status
```bash
cd ~/scripts/code-orchestra
python3 -m models.quota_cli status
```

**Output Example:**
```
╔════════════════════════════════════════════════════════════════════════════════════════════╗
║ QUOTA STATUS REPORT                                                                        ║
╠════════════════════════════════════════════════════════════════════════════════════════════╣
║ Email                                    Plan   Usage  Reset Time            Until Provider║
╟────────────────────────────────────────────────────────────────────────────────────────────╢
║ 🟢 swimming.crystalball@gmail.com         free   [     ]   1% 2026-03-23 16:02    167.0h codex║
║ 🟢 carpool.london@gmail.com               free   [     ]   1% 2026-03-23 16:08    167.1h codex║
║ 🟢 aken@liberty.edu                       free   [===  ]  19% 2026-03-21 17:54    120.9h codex║
║ 🟡 maritime2007@gmail.com                 free   [===== ] 94% 2026-03-18 09:52     40.8h codex║
║ 🔴 liuyl.david@gmail.com                  free   [=====] 100% 2026-03-17 20:07     27.1h codex║
╚════════════════════════════════════════════════════════════════════════════════════════════╝
```

### 2. Auto-Check & Switch
```bash
python3 -m models.quota_cli check
```

Output: `Decision: STAY on aken@liberty.edu (81% remaining) - Current quota (81%) > threshold (40%)`

### 3. Continuous Monitoring
```bash
python3 -m models.quota_cli watch           # Check every 60s
python3 -m models.quota_cli watch 30        # Check every 30s
```

### 4. Learn the Algorithm
```bash
python3 -m models.quota_cli explain
```

## Algorithm Overview

### Three-Rule Decision System

#### Rule 1: Threshold Rule (40%)
```
IF remaining_quota > 40%:
    → STAY (account is healthy)
ELSE:
    → EVALUATE switching
```

**Why 40%?** Provides buffer before exhaustion while maximizing utilization

#### Rule 2: Fresh Reset Rule (90%)
```
IF any account.remaining >= 90%:
    → SWITCH immediately
    Reason: Just reset, maximum quota available
```

**Priority:** Fresh resets get highest priority

#### Rule 3: Effective Quota Rule
Used when all accounts < 40% (or no fresh reset available)

```
Score = remaining_percent + reset_boost

reset_boost = {
    100 * (1 - hours_until_reset / 4)    if hours_until_reset ≤ 4
    0                                     otherwise
}
```

**Effect:** Accounts resetting soon get boosted priority because they'll have fresh quota available soon

### Why This Algorithm Works

| Aspect | Benefit |
|--------|---------|
| **Prevents exhaustion** | Switches at 40%, not 0% |
| **Maximizes utilization** | Boosts accounts about to reset |
| **Avoids thrashing** | Requires 10-point improvement to switch |
| **Remembers reset times** | Pre-emptively adapts to schedule |
| **Fair distribution** | No account gets starved |
| **Minimal waste** | Catches fresh resets immediately |

### Example Scoring

| Account | Remaining | Hours to Reset | Effective Score | Decision |
|---------|-----------|----------------|-----------------|----------|
| codex1 | 18% | 19h | 18 + 0 = **18** | Low |
| google2 | 2% | 4h | 2 + 100 = **102** | Medium |
| codex2 | 5% | 0.5h | 5 + 87.5 = **92.5** | Medium |
| google1 | 25% | 0.25h | 25 + 93.75 = **118.75** | ⭐ **HIGHEST** |

→ **SWITCH to google1** (highest effective score)

## Features

✅ **Multi-Provider Support**
- Google Antigravity
- OpenAI Codex
- Extensible to add more providers

✅ **Intelligent Switching**
- Threshold-based (40%)
- Fresh reset detection (90%)
- Effective quota scoring
- Thrash prevention (10-point improvement threshold)

✅ **Continuous Monitoring**
- Background monitoring mode
- Configurable check intervals (default: 60min)
- Rate limiting to prevent API exhaustion

✅ **State Persistence**
- Remembers account reset times
- Stored in `~/.codex/quota_manager_state.json`
- Survives across sessions

✅ **Detailed Reporting**
- Color-coded status (🟢 🟡 🔴)
- Progress bars
- Reset time forecasts
- Provider identification

## Files

```
models/
├── quota_manager.py          ← Core logic (smart algorithm)
├── quota_cli.py              ← CLI interface
└── QUOTA_MANAGER.md          ← This file
```

## Integration Example

```python
from models.quota_manager import QuotaManager

manager = QuotaManager(check_interval_minutes=60)

# Get all quotas
snapshots = manager.fetch_all_quotas()
for snap in snapshots:
    print(f"{snap.email}: {snap.remaining_percent}% remaining")

# Auto-check and switch if needed
decision = manager.check_and_switch_if_needed()
print(f"Decision: {decision}")

if decision.should_switch:
    print(f"Switched to {decision.target_email}")
```

## Persistent State

### State File Location
```
~/.codex/quota_manager_state.json
```

### Content
```json
{
  "reset_times": {
    "aken@liberty.edu": 1774130071,
    "liuyl.david@gmail.com": 1773614197,
    ...
  }
}
```

**Purpose:** Remembers when each account resets, used for effective quota calculation and pre-emptive switching

## Configuration

### Default Settings
| Setting | Value | Purpose |
|---------|-------|---------|
| Quota Threshold | 40% | Switch point |
| Fresh Reset | 90% | Immediate switch trigger |
| Urgent Reset Window | 4 hours | Apply boost if resetting soon |
| Improvement Threshold | 10 points | Minimum to justify switch |
| Check Interval | 60 minutes | Rate limiting |

### Customization
Edit `quota_manager.py` constants:
```python
class QuotaManager:
    QUOTA_THRESHOLD = 40          # Switch when ≤ 40%
    FRESH_QUOTA_THRESHOLD = 90    # Consider "fresh" if ≥ 90%
    URGENT_RESET_HOURS = 4        # Reset within 4h = urgent
```

## Comparison with Simple Strategies

### Strategy A: Round-Robin
```
Cycle through accounts sequentially
✗ Wastes quota by skipping before depletion
✗ Misses reset optimization
```

### Strategy B: Switch at 10%
```
Only switch when very low
✗ Starves accounts
✗ Unfair distribution
✗ Reactive, not proactive
```

### Strategy C: Smart + Reset-Aware (Ours)
```
✓ Proactive (40% threshold)
✓ Reset-aware (boost accounts resetting soon)
✓ Fair (all accounts treated equally)
✓ Efficient (minimizes wasted quota)
✓ Resilient (adapts to unexpected resets)
```

## Monitoring Workflow

### Single Check
```bash
python3 -m models.quota_cli check
# One-time decision, no persistent monitoring
```

### Continuous Monitor (Development)
```bash
python3 -m models.quota_cli watch 30
# Check every 30 seconds, useful for testing
```

### Continuous Monitor (Production)
```bash
# In background or cron job:
python3 -m models.quota_cli watch 3600
# Check every hour (3600 seconds)
```

## Error Handling

### Token Expiry
- Automatically handled during quota fetch
- Tokens refresh before API calls
- No manual intervention needed

### Provider Unavailable
- Logged as warning, continues with other providers
- No blocking errors
- System degrades gracefully

### Network Issues
- Connection timeouts logged
- Next check will retry
- State preserved between checks

## Future Enhancements

Potential improvements:

1. **Load-based switching** — Switch based on active request load, not just quota
2. **Cost optimization** — Prefer cheaper models when multiple available
3. **Predictive analytics** — Pre-calculate optimal switching schedule
4. **Cost tracking** — Monitor cumulative usage + costs
5. **Custom rules** — User-defined switching policies
6. **Web dashboard** — Real-time quota monitoring UI

## FAQ

**Q: How often should I run checks?**
A: 60 minutes (default) is ideal. More frequent = more API calls. Less frequent = slower reaction to resets.

**Q: What happens if I manually switch accounts?**
A: Next check will detect the new active account and adapt accordingly.

**Q: Can I use this with only Google or only Codex?**
A: Yes, system detects available providers and adapts.

**Q: What's the startup time overhead?**
A: First check fetches all quotas (parallel, typically 1-2 seconds). Subsequent checks use cached reset times (instant).

**Q: How are reset times remembered?**
A: Saved in `~/.codex/quota_manager_state.json`, survives restarts.

**Q: Can I customize the threshold?**
A: Yes, edit `QUOTA_THRESHOLD` constant in `quota_manager.py`.

## Support

For issues or questions:
1. Run `python3 -m models.quota_cli explain` to review algorithm
2. Check `~/.codex/quota_manager_state.json` for stored state
3. Review warning messages in output (they tell you what failed)

---

**Status**: ✅ Production Ready
**Tested**: 2026-03-16
**Last Updated**: 2026-03-16
