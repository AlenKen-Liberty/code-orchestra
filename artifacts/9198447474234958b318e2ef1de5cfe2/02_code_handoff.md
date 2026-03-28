# Handoff: plan -> code
## Task
Phase 4: 健壮性 for code-orchestra harness

## Context Gathered
- `QuotaRouter` currently collapses each provider to a single best snapshot in [harness/quota_router.py](/home/ubuntu/scripts/code-orchestra/harness/quota_router.py), which is not enough for Codex multi-account rotation.
- `Harness._run_stage()` in [harness/main.py](/home/ubuntu/scripts/code-orchestra/harness/main.py) persists model/provider selection but has no Codex account activation, no daemon hooks, and no telemetry hooks.
- `models.codex.account.set_active_account()` already handles token refresh + auth file switching in [models/codex/account.py](/home/ubuntu/scripts/code-orchestra/models/codex/account.py); the harness should integrate it as a runtime step, not from the router.
- `StageExecutionResult` already has `token_used` and `duration_sec`, and the stages table already persists both via [harness/task_queue.py](/home/ubuntu/scripts/code-orchestra/harness/task_queue.py).
- Baseline verification is green: `python3 -m pytest tests/harness/ -q` => `21 passed`.

## Recommended Implementation Order
1. Codex rotation
- Update router eligibility/fallback logic so Codex models consider all eligible Codex snapshots, keeping the chosen `account_email`.
- Persist the selected account on the stage.
- Add a small helper in the harness path to activate the selected Codex account just before execution.
- Add tests first for router ranking, then for harness-side activation.

2. Daemon mode
- Add a dedicated daemon helper module with PID file read/write, process liveness checks, start/stop/status, and stale PID cleanup.
- Extend the harness parser with `daemon` and a hidden worker command.
- Add `SIGTERM`-aware stop handling around `run_forever`, ideally with an `asyncio.Event` / shutdown flag seam that is easy to unit test.

3. Telemetry + dashboard
- Add centralized logging config and a JSONL event writer module.
- Emit stage lifecycle events from the harness runtime, not from the router.
- Add a dashboard summary builder that reads DB state + event log + daemon status.
- Expose it via `dashboard` in the harness CLI.

## Concrete Guidance
- Prefer stage metadata for the selected Codex account instead of widening the DB schema unless a wider schema clearly improves readability.
- Keep `can_run_stage()` pure; it is called from paused-task recovery and should not switch accounts.
- Parse token usage opportunistically in [harness/stage_executor.py](/home/ubuntu/scripts/code-orchestra/harness/stage_executor.py); do not block this phase on provider-specific token support.
- Treat [scripts/orchestra_cli.py](/home/ubuntu/scripts/code-orchestra/scripts/orchestra_cli.py) as unrelated legacy workflow UI unless you discover a hard requirement otherwise.

## Verification Target
Run `python3 -m pytest tests/harness/ -v` after each slice if possible, then once at the end.
