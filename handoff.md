# Handoff: review -> code

## Findings
1. User-specified stage assignments are not durable across retries. `Harness._run_stage()` resets stages back to pending with the default `clear_model=True` on permission pauses and generic execution retries, and quota exhaustion eventually clears the assignment too. That drops the explicit `(assigned_model, assigned_provider)` pair and the next attempt falls back to `QuotaRouter`, which breaks the feature promise.
2. Alias normalization is only implemented in the CLI submit path. `IntakeAgent.plan_task()` accepts API `model_overrides` but persists the raw tuple directly, so API callers that pass aliases like `gemini` keep the alias instead of the canonical model name. That misses the "CLI and API, with alias resolution" requirement.

## Verification
`python3 -m pytest tests/harness/ -v` passed: 43 passed, 3 skipped, 1 warning (`asyncio_mode` unknown config option).

## Next Step
Preserve explicit assignments when resetting stages that were user-pinned, move model normalization into a shared API path instead of only `_main_async()`, and add tests that cover API alias resolution plus retry/pause behavior for pre-assigned stages.
