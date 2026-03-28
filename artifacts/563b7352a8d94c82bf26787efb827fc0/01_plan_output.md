# Output: plan
## Summary
Implement the robustness work in three slices with tests after each slice:

1. Codex account rotation
- Keep `QuotaRouter.select_model()` side-effect free so `can_run_stage()` remains safe.
- Extend routing to choose the best Codex account among all Codex quota snapshots using the existing use-it-or-lose-it scoring, and preserve the chosen `account_email` in `ModelChoice`.
- Add a separate activation step before Codex execution that calls `models.codex.account.set_active_account()` only when the chosen Codex account differs from the current active account.
- Log/surface the selected account in the routing reason and stage telemetry.

2. Daemon lifecycle
- Add a small daemon manager module instead of embedding process control directly in CLI branches.
- Use a detached `subprocess.Popen(..., start_new_session=True)` worker for a portable nohup-style background process.
- Add `daemon start`, `daemon stop`, and `daemon status` CLI subcommands plus a hidden worker command that runs `Harness.run_forever()`.
- Persist daemon metadata in a PID file, detect stale PID files, and install a `SIGTERM` handler that lets the current iteration finish and exits cleanly.

3. Logging, monitoring, and dashboard
- Add one centralized logging setup for the harness CLI/daemon path.
- Emit structured JSONL events for stage start, completion, retry, quota pause, permission pause, and failure.
- Compute dashboard aggregates from the DB plus the JSONL event stream: task counts by status, stage counts by status, total/average duration, total token usage, and execution error rate.
- Include daemon state, recent failures, and quota/permission pause counts in the dashboard output.

## File Targets
- `harness/quota_router.py`
- `harness/main.py`
- `harness/stage_executor.py`
- `harness/task_queue.py`
- `config/settings.py`
- New modules are likely justified for daemon/process management and telemetry aggregation.

## Test Plan
- Add router tests for multi-account Codex selection and no-side-effect feasibility checks.
- Add harness/main tests for Codex account activation before execution.
- Add daemon tests for PID lifecycle, stale PID detection, and stop/status behavior.
- Add telemetry/dashboard tests for JSONL event emission and aggregate summaries.
- Final verification: `python3 -m pytest tests/harness/ -v`

## Baseline
Current baseline is green: `python3 -m pytest tests/harness/ -q` passed with `21 passed`.
