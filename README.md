# ACP Multi-LLM Pipeline Orchestrator

This project implements a multi-stage LLM orchestration pipeline, where different large language models sequentially collaborate on tasks (e.g., Design → Code → Review).

## Quick Overview

The pipeline supports chaining multiple CLI-based LLM agents:
- **Claude Code** (e.g., `claude` CLI for Opus, Haiku)
- **Codex** (e.g., `codex` CLI for GPT-5.2-Codex)
- **Gemini** (e.g., `geminicli` for Gemini 3.1 Pro Preview)

Each stage passes its output sequentially to the next model based on a configurable YAML workflow. 

## Quick Start

Run the current 3-stage pipeline (Opus Design → Codex Implement → Haiku Review):

```bash
python3 scripts/run_pipeline.py \
  --pipeline workflows/current_pipeline.yaml \
  --task "Build a Python script that scrapes a website and saves data to CSV" \
  --output results.json
```

All intermediate artifacts are automatically saved to `./artifacts/`.

## Documentation

For detailed information on configuring the pipeline, multi-LLM capabilities, and adding new stages, refer to the documents below:

- [QUICK_START.md](./QUICK_START.md) - For a fast, visually-guided introduction.
- [PIPELINE_USAGE.md](./PIPELINE_USAGE.md) - For full documentation on CLI flags, configurations, environment variables, and troubleshooting.
- [DESIGN.md](./DESIGN.md) - Detailed architecture design of the multi-agent orchestrator.

## Testing

To run the test suite, install dependencies via `pip install pytest pytest-asyncio`, then run:
```bash
pytest
```
