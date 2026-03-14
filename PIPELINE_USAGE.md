# Multi-LLM Pipeline Usage Guide

## Overview

This system allows you to orchestrate multi-stage workflows using different LLM models:
- **Claude Code** (Opus, Haiku) - via `claude` CLI
- **Codex** (GPT-5.2-Codex) - via `codex` CLI
- **Gemini** (3.1 Pro Preview) - via `geminicli` CLI

## Current Supported Pipelines

### 1. `current_pipeline.yaml` (Recommended for now)

Three-stage pipeline:
1. **Design** (Claude Opus) - Generate architecture design
2. **Coding** (GPT-5.2 Codex) - Implement the design
3. **Review** (Claude Haiku) - Review code quality and test coverage

```bash
python3 scripts/run_pipeline.py \
  --pipeline workflows/current_pipeline.yaml \
  --task "Build a RESTful API for a task management system" \
  --output results.json
```

### 2. `multi_llm_pipeline.yaml` (Future)

Five-stage pipeline (when Gemini integration is complete):
1. **Planning** (Claude Opus) - Design architecture
2. **Design Review** (Gemini 3.1 Pro) - Multi-round design review
3. **Coding** (GPT-5.2 Codex) - Implement code
4. **Code Review** (Gemini 3.1 Pro) - Review and test
5. **Summary** (Claude Haiku) - Generate final report

## Requirements

### Installed CLIs

Make sure you have these CLIs available in PATH:

```bash
# Check if available
which claude    # Claude Code CLI
which codex     # Codex CLI
which geminicli # Gemini CLI (for future use)
```

### Python Dependencies

```bash
pip install PyYAML  # Required for YAML parsing
```

## Output Format

The pipeline generates JSON output with results from each stage:

```json
{
  "planning": {
    "stage_id": "planning",
    "status": "success",
    "output": "... architecture plan ...",
    "execution_time": 45.2,
    "model_used": "claude-opus-4-6",
    "rounds": 1
  },
  "coding": {
    "stage_id": "coding",
    "status": "success",
    "output": "... generated code ...",
    "execution_time": 78.5,
    "model_used": "gpt-5.2-codex",
    "rounds": 1
  },
  "code_review": {
    "stage_id": "code_review",
    "status": "success",
    "output": "... review feedback ...",
    "execution_time": 32.1,
    "model_used": "claude-haiku-4-5-20251001",
    "rounds": 1
  }
}
```

## Configuration

### Stage Configuration in YAML

Each stage has:
- `stage_id` - Unique identifier
- `name` - Display name
- `model` - Model name to use
- `model_type` - Type: `claude_code`, `codex`, or `gemini`
- `description` - What the stage does
- `prompt_template` - Prompt with variables like `{variable_name}`
- `output_key` - Key name for the output
- `input` - Input from previous stages or user task
- `save_artifact` - Whether to save output to file

### Input Resolution

Inputs use dot notation to reference previous stage outputs:
- `"source": "planning.architecture_plan"` - Uses architecture_plan from planning stage
- `"source": "user_task"` - Uses the initial task description

## Extending the System

### Adding a New Stage

Edit the YAML file and add a new stage definition:

```yaml
stages:
  - stage_id: "new_stage"
    name: "New Stage Name"
    model: "model-name"
    model_type: "claude_code|codex|gemini"
    description: "What this stage does"
    prompt_template: |
      Your prompt here with variables like {input_from_previous}
    input:
      - source: "previous_stage.output_key"
        key: "variable_name"
    output_key: "output_identifier"
    save_artifact: true
```

### Adding a New Model Type

1. Create a wrapper in `agents/` (e.g., `new_model_wrapper.py`)
2. Implement `async def invoke_new_model(prompt, model, timeout, working_dir) -> str`
3. Add import to `orchestrator/pipeline.py`
4. Update `_invoke_model()` method to handle new type
5. Add new enum value to `ModelType` in `orchestrator/stage.py`

## Environment Variables

```bash
# CLI timeout in seconds
export CLI_TIMEOUT=300

# Model selections
export CLAUDE_PLANNER_MODEL=claude-opus-4-6
export CLAUDE_REVIEWER_MODEL=claude-haiku-4-5-20251001
export CODEX_MODEL=gpt-5.2-codex

# Artifact storage
export ARTIFACTS_DIR=./artifacts
```

## Troubleshooting

### "Claude CLI not found"
```bash
# Install Claude Code
pip install anthropic-claude-code
# Or ensure `claude` is in PATH
```

### "codex CLI not found"
```bash
# Ensure Codex CLI is installed and in PATH
which codex
```

### PyYAML not found
```bash
pip install PyYAML
```

### Stage timed out
- Increase `CLI_TIMEOUT` environment variable
- Check if the model CLI is responsive
- Verify the prompt is reasonable in complexity

## Development

### Running with verbose output
```bash
python3 scripts/run_pipeline.py \
  --pipeline workflows/current_pipeline.yaml \
  --task "Your task" \
  --verbose
```

### Viewing artifacts
Artifacts are saved to the directory specified in pipeline config (default: `./artifacts`)

```bash
ls -la artifacts/
cat artifacts/planning_output.txt
cat artifacts/coding_output.txt
```

### Adding logging

The system uses Python's standard logging. Configure in `run_pipeline.py`:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG for more details
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
```
