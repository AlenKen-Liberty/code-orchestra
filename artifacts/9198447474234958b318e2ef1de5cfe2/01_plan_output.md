# Output: plan
## Summary
Implement the robustness work in three slices, keeping `QuotaRouter` selection pure and pushing all operational side effects into the harness runtime / CLI layer.

1. Codex account rotation
- Keep `QuotaRouter.select_model()` and `can_run_stage()` side-effect free.
- Change Codex candidate selection from "best provider snapshot" to "best eligible Codex account snapshot", using the existing use-it-or-lose-it score.
- Preserve the chosen `account_email` on the selected stage, preferably in stage metadata if the DB schema should stay stable.
- Add an explicit pre-execution Codex activation step that calls `models.codex.account.get_active_email()` and `set_active_account()` only when the chosen account differs.

2. Daemon lifecycle
- Use the harness CLI in [harness/main.py](/home/ubuntu/scripts/code-orchestra/harness/main.py) as the management entrypoint, not the older workflow CLI in [scripts/orchestra_cli.py](/home/ubuntu/scripts/code-orchestra/scripts/orchestra_cli.py).
- Add `daemon start`, `daemon stop`, `daemon status`, plus a hidden worker subcommand that runs `Harness.run_forever()`.
- Prefer a portable detached `subprocess.Popen(..., start_new_session=True)` / nohup-style path for tests instead of systemd-specific logic.
- Persist PID metadata, detect stale PID files, and handle `SIGTERM` so the loop exits cleanly after the current iteration.

3. Logging, monitoring, and dashboard
- Add centralized logging setup for harness CLI + daemon startup.
- Emit structured JSONL stage events for start, success, retry, quota pause, permission pause, and terminal failure.
- Reuse persisted `stages.token_used` and `stages.duration_sec` for aggregates; parse provider output for token usage where available and leave `0` when unavailable.
- Add a `dashboard` command that combines DB state, quota/permission audit tables, daemon state, and recent JSONL events into one status summary.

## Key File Targets
- [harness/quota_router.py](/home/ubuntu/scripts/code-orchestra/harness/quota_router.py)
- [harness/main.py](/home/ubuntu/scripts/code-orchestra/harness/main.py)
- [harness/stage_executor.py](/home/ubuntu/scripts/code-orchestra/harness/stage_executor.py)
- [harness/task_queue.py](/home/ubuntu/scripts/code-orchestra/harness/task_queue.py)
- [models/codex/account.py](/home/ubuntu/scripts/code-orchestra/models/codex/account.py)
- [config/settings.py](/home/ubuntu/scripts/code-orchestra/config/settings.py)
- New modules are justified for daemon management and telemetry aggregation.

## Risks To Avoid
- Do not let quota feasibility checks mutate global Codex auth state.
- Do not add daemon logic to the legacy orchestrator CLI; keep it on the harness path.
- Do not rely on live systemd in tests; use deterministic unit seams around PID files, signals, and subprocess launch.

## Test Plan
- Extend router tests for multi-account Codex ranking and no-side-effect feasibility checks.
- Add harness tests for Codex account activation before a Codex stage executes.
- Add daemon tests for PID lifecycle, stale PID cleanup, and graceful stop/status behavior.
- Add telemetry/dashboard tests for JSONL emission and aggregate summaries.
- Final verification: `python3 -m pytest tests/harness/ -v`

## Baseline
Current baseline is green: `python3 -m pytest tests/harness/ -q` passed with `21 passed`.
