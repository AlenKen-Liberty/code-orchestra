# ACP Multi-LLM Pipeline Orchestrator

This project implements a multi-stage LLM orchestration pipeline, where different large language models sequentially collaborate on tasks (e.g., Design → Code → Review).

## Quick Overview

The pipeline supports chaining multiple LLM agents over the ACP protocol:
- **Claude Planner & Reviewer**
- **Codex Coder**
- **Gemini Reviewer**

Each stage passes its output sequentially to the next model based on a configurable YAML workflow. 

Start the agent HTTP servers in the background:
```bash
PYTHONPATH=. venv/bin/python scripts/run_claude_server.py &
PYTHONPATH=. venv/bin/python scripts/run_codex_server.py &
PYTHONPATH=. venv/bin/python scripts/run_gemini_server.py &
```

Then run the interactive pipeline orchestrator:

```bash
PYTHONPATH=. venv/bin/python scripts/orchestra_cli.py
```

You can optionally run it headless with flags:
```bash
PYTHONPATH=. venv/bin/python scripts/orchestra_cli.py --workflow workflows/multi_llm_pipeline.yaml --task "Build a Python script that scrapes a website and saves data to CSV"
```

All intermediate artifacts and code steps are processed automatically by the agents.

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
