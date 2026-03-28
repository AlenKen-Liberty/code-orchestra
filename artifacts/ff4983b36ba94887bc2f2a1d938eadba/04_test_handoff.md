# Handoff: review -> test
## Task
feat: user-specified pipeline model assignments

## Description
Add a user-specified pipeline feature to the orchestra harness.

Currently the QuotaRouter intelligently selects which model handles each stage.
Add an option for users to explicitly specify which model handles each stage when submitting a task.

Requirements:
1. PlannedStage should accept optional assigned_model and assigned_provider fields
2. TaskQueue.save_stages should persist these pre-assignments
3. Harness._run_stage should skip QuotaRouter when model is pre-assigned (this already works)
4. IntakeAgent.plan_task should accept an optional model_overrides dict mapping stage_type to (model, provider)
5. CLI submit command should accept --model-override flags like: --model-override "code=gemini-3.1-pro" --model-override "review=gpt-5.4-codex"
6. ModelRegistry.resolve() should be used to normalize user-provided model names (aliases supported)

The working directory is /home/ubuntu/scripts/code-orchestra.
Test command: python3 -m pytest tests/harness/ -v


## Goal
Users can specify per-stage model assignments via CLI and API, with alias resolution

## Context
- Complexity: medium
- Current Stage: test (tester)
- Working Directory: /home/ubuntu/scripts/code-orchestra

## Previous Stage Output
### plan
{"type":"thread.started","thread_id":"019d357f-f608-7770-8bc9-91fba3e31b45"} {"type":"turn.started"} {"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"I’m treating this as the planning pass only: I’ll inspect the harness, queue, intake, CLI, and mod...

### code
I have completed the implementation for the user-specified pipeline model assignments. All requirements have been met, and tests have successfully passed. Here is a summary of the changes: 1. **`harness/models.py`**: Added `assigned_model` and `assigned_provider` fields to the...

### review
{"type":"thread.started","thread_id":"019d358c-1f69-72d3-a7f9-f362ea1aa22e"} {"type":"turn.started"} {"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"Reviewing the implementation for per-stage model overrides. I’m checking the diff, reading the tou...

## Current Stage Instructions
Execute the `test` stage and leave a concise handoff for the next stage.

## Verification
Run: `python3 -m pytest tests/harness/ -v`
