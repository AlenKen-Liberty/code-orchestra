# Output: test
## Summary
Ran `python3 -m pytest tests/harness/ -v` in `/home/ubuntu/scripts/code-orchestra`.

Result: `39 passed, 1 warning` in `0.73s`.

The only warning is a non-blocking `PytestConfigWarning` for unknown config option `asyncio_mode`.

## Files Changed
- artifacts/1ca2e7599aeb4361b323fa071fe6b0d4/01_test_output.md
- artifacts/1ca2e7599aeb4361b323fa071fe6b0d4/02_next_handoff.md

## Raw Output
```text
============================= test session starts ==============================
platform linux -- Python 3.10.12, pytest-9.0.2, pluggy-1.6.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /home/ubuntu/scripts/code-orchestra
configfile: pytest.ini
plugins: anyio-4.12.1, mock-3.15.1, cov-7.1.0
collecting ... collected 39 items

tests/harness/test_daemon.py::test_daemon_manager_start_stop_and_status PASSED
tests/harness/test_daemon.py::test_daemon_status_cleans_stale_pid_file PASSED
tests/harness/test_daemon.py::test_parser_supports_daemon_and_dashboard_commands PASSED
tests/harness/test_handoff.py::test_handoff_includes_previous_stage_summary PASSED
tests/harness/test_handoff.py::test_handoff_saves_stage_output PASSED
tests/harness/test_intake.py::test_intake_plans_simple_task PASSED
tests/harness/test_intake.py::test_intake_marks_complex_work PASSED
tests/harness/test_intake.py::test_intake_generates_questions_and_applies_answers PASSED
tests/harness/test_main.py::test_harness_run_once_executes_stage_and_finishes_task PASSED
tests/harness/test_main.py::test_harness_recovers_paused_quota_tasks PASSED
tests/harness/test_main.py::test_harness_inspect_includes_permission_requests PASSED
tests/harness/test_main.py::test_harness_switches_codex_account_before_execution PASSED
tests/harness/test_main.py::test_harness_dashboard_summarizes_stage_metrics PASSED
tests/harness/test_model_registry.py::test_resolve_canonical_unchanged PASSED
tests/harness/test_model_registry.py::test_resolve_alias PASSED
tests/harness/test_model_registry.py::test_resolve_unknown_returns_input PASSED
tests/harness/test_model_registry.py::test_chat2api_id PASSED
tests/harness/test_model_registry.py::test_cli_model_id PASSED
tests/harness/test_model_registry.py::test_provider PASSED
tests/harness/test_model_registry.py::test_models_for_role PASSED
tests/harness/test_model_registry.py::test_models_for_unknown_role_returns_all PASSED
tests/harness/test_model_registry.py::test_available_canonical_names PASSED
tests/harness/test_model_registry.py::test_alias_collision_raises PASSED
tests/harness/test_permission_gate.py::test_permission_gate_auto_approves_safe_commands PASSED
tests/harness/test_permission_gate.py::test_permission_gate_requires_vote_for_dangerous_commands PASSED
tests/harness/test_permission_gate.py::test_permission_gate_requires_user_for_critical_commands PASSED
tests/harness/test_permission_gate.py::test_permission_gate_approves_after_vote PASSED
tests/harness/test_permission_gate.py::test_permission_gate_falls_back_to_user_when_vote_rejects PASSED
tests/harness/test_quota_router.py::test_router_prefers_soon_expiring_codex_quota PASSED
tests/harness/test_quota_router.py::test_router_rotates_between_codex_accounts_using_account_score PASSED
tests/harness/test_quota_router.py::test_router_uses_provider_without_snapshot_when_available PASSED
tests/harness/test_quota_router.py::test_router_accepts_llm_selector_choice PASSED
tests/harness/test_quota_router.py::test_router_accepts_llm_selector_choice_for_specific_codex_account PASSED
tests/harness/test_stage_executor.py::test_stage_executor_runs_github_commands PASSED
tests/harness/test_stage_executor.py::test_stage_executor_blocks_unapproved_command PASSED
tests/harness/test_stage_executor.py::test_stage_executor_checks_raw_verify_command PASSED
tests/harness/test_stage_executor.py::test_stage_executor_extracts_codex_token_usage PASSED
tests/harness/test_task_queue.py::test_task_queue_creates_and_orders_tasks PASSED
tests/harness/test_task_queue.py::test_task_queue_updates_stage_lifecycle PASSED

=============================== warnings summary ===============================
../../.local/lib/python3.10/site-packages/_pytest/config/__init__.py:1428
  /home/ubuntu/.local/lib/python3.10/site-packages/_pytest/config/__init__.py:1428: PytestConfigWarning: Unknown config option: asyncio_mode

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 39 passed, 1 warning in 0.73s =========================
```
