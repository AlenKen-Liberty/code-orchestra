# Handoff: bootstrap -> plan
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
- Current Stage: plan (planner)
- Working Directory: /home/ubuntu/scripts/code-orchestra

## Current Stage Instructions
Execute the `plan` stage and leave a concise handoff for the next stage.

## Verification
Run: `python3 -m pytest tests/harness/ -v`
