#!/usr/bin/env python3
"""Run a pipeline defined in YAML."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from orchestrator.pipeline import PipelineDefinition, PipelineError
from scripts.orchestra_cli import CLIExecutor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a multi-stage LLM pipeline"
    )
    parser.add_argument(
        "--pipeline",
        required=True,
        help="Path to pipeline YAML definition",
    )
    parser.add_argument(
        "--task",
        required=True,
        help="Task description for the pipeline",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file for results (default: stdout)",
    )
    parser.add_argument(
        "--config",
        default="config/agents.yaml",
        help="Path to agents.yaml",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load pipeline definition
    try:
        pipeline_def = PipelineDefinition(args.pipeline)
        logger.info(f"Loaded pipeline: {pipeline_def.config.get('name', 'unknown')}")
    except PipelineError as e:
        logger.error(f"Failed to load pipeline: {e}")
        sys.exit(1)

    # Create executor and run
    executor = CLIExecutor(pipeline_def, args.config)

    try:
        results = asyncio.run(executor.execute(args.task))
        output_data = executor.get_final_results()

        # Print results
        output_json = json.dumps(output_data, indent=2)
        print(output_json)

        # Optionally save to file
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                f.write(output_json)
            logger.info(f"Results saved to {output_path}")

        # Exit with error if any stage failed
        for result in results.values():
            if result.status == "failed":
                logger.error(f"Pipeline had failures")
                sys.exit(1)

    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        asyncio.run(executor.cleanup())


if __name__ == "__main__":
    main()
