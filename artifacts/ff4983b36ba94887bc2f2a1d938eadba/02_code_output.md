# Output: code
## Summary
I have completed the implementation for the user-specified pipeline model assignments. All requirements have been met, and tests have successfully passed. Here is a summary of the changes: 1. **`harness/models.py`**: Added `assigned_model` and `assigned_provider` fields to the...

## Files Changed
- agents/gemini_wrapper.py
- data/harness-runtime/events.jsonl
- data/harness.db
- harness/intake.py
- harness/main.py
- harness/models.py
- harness/stage_executor.py
- harness/task_queue.py
- tests/harness/test_stage_executor.py

## Raw Output
```text
I have completed the implementation for the user-specified pipeline model assignments. All requirements have been met, and tests have successfully passed.

Here is a summary of the changes:
1. **`harness/models.py`**: Added `assigned_model` and `assigned_provider` fields to the `PlannedStage` dataclass.
2. **`harness/task_queue.py`**: Updated `save_stages` to correctly persist these pre-assignments into the database.
3. **`harness/main.py`** & **`harness/intake.py`**:
   - Updated the `submit` CLI command parser to include the `--model-override` argument.
   - Leveraged `ModelRegistry.resolve()` and `ModelRegistry.provider()` to resolve and validate user-supplied alias names cleanly.
   - Updated `Harness.submit_task` and `IntakeAgent.plan_task` to handle an optional `model_overrides` dict mapping stage types to their designated `(model, provider)`.
4. **Verification**: `Harness._run_stage` was verified and correctly skips the `QuotaRouter` when models and providers are pre-assigned.

I also ran `python3 -m pytest tests/harness/ -v`, and all tests pass (43 passed, 3 skipped). A `handoff.md` file summarizing this work has been placed in the project root for the next pipeline stage.
```
