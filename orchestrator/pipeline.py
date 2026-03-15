"""Pipeline execution engine."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from orchestrator.stage import StageDefinition, StageResult, ModelType

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Base exception for pipeline errors."""
    pass


class PipelineDefinition:
    """Loads and represents a pipeline definition from YAML."""

    def __init__(self, yaml_path: str | Path):
        self.yaml_path = Path(yaml_path)
        self.config: dict[str, Any] = {}
        self.stages: list[StageDefinition] = []
        self.execution_config: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load pipeline definition from YAML file."""
        if not self.yaml_path.exists():
            raise PipelineError(f"Pipeline definition not found: {self.yaml_path}")

        with open(self.yaml_path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise PipelineError(f"Empty pipeline definition: {self.yaml_path}")

        self.config = data.get("config", {})
        self.execution_config = data.get("execution", {})

        # Parse stages
        stages_data = data.get("stages", [])
        for stage_data in stages_data:
            stage = StageDefinition.from_dict(stage_data)
            self.stages.append(stage)

        if not self.stages:
            raise PipelineError("No stages defined in pipeline")

        logger.info(f"Loaded pipeline with {len(self.stages)} stages")

    def get_stage(self, stage_id: str) -> Optional[StageDefinition]:
        """Get a stage by ID."""
        for stage in self.stages:
            if stage.stage_id == stage_id:
                return stage
        return None


class PipelineExecutor:
    """Executes a pipeline."""

    def __init__(self, pipeline_def: PipelineDefinition):
        self.pipeline = pipeline_def
        self.results: dict[str, StageResult] = {}
        self.state: dict[str, Any] = {}  # Aggregated outputs from all stages
        self.artifacts_dir: Optional[Path] = None

    async def execute(
        self,
        task_description: str,
        initial_state: Optional[dict[str, Any]] = None,
    ) -> dict[str, StageResult]:
        """
        Execute the entire pipeline.

        Args:
            task_description: The initial task/prompt for the pipeline
            initial_state: Optional initial state to merge with

        Returns:
            Dictionary of stage_id -> StageResult
        """
        # Initialize state
        self.state = {"task_description": task_description}
        if initial_state:
            self.state.update(initial_state)

        # Setup artifacts directory if needed
        if self.pipeline.config.get("save_artifacts"):
            artifacts_dir = self.pipeline.config.get("artifact_dir", "./artifacts")
            self.artifacts_dir = Path(artifacts_dir)
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Execute stages in order
        error_handling = self.pipeline.execution_config.get("error_handling", "fail_fast")

        for stage_def in self.pipeline.stages:
            logger.info(f"Executing stage: {stage_def.name} ({stage_def.stage_id})")

            try:
                result = await self._execute_stage(stage_def)
                self.results[stage_def.stage_id] = result

                # Update state with stage output
                output_key = stage_def.output_key
                self.state[f"{stage_def.stage_id}.{output_key}"] = result.output

                # Save artifact if requested
                if stage_def.save_artifact and self.artifacts_dir:
                    self._save_artifact(stage_def.stage_id, result)

                logger.info(f"Stage {stage_def.stage_id} completed successfully")

            except Exception as exc:
                logger.error(f"Stage {stage_def.stage_id} failed: {exc}")
                result = StageResult(
                    stage_id=stage_def.stage_id,
                    status="failed",
                    error=str(exc),
                )
                self.results[stage_def.stage_id] = result

                if error_handling == "fail_fast":
                    raise PipelineError(
                        f"Pipeline stopped at stage {stage_def.stage_id}: {exc}"
                    ) from exc

        return self.results

    async def _execute_stage(self, stage_def: StageDefinition) -> StageResult:
        """Execute a single stage."""
        start_time = time.time()

        try:
            # Prepare prompt by substituting variables
            prompt = self._prepare_prompt(stage_def)

            logger.debug(f"Prompt for {stage_def.stage_id}:\n{prompt}")

            # Invoke the appropriate model
            output = await self._invoke_model(stage_def, prompt)

            execution_time = time.time() - start_time

            return StageResult(
                stage_id=stage_def.stage_id,
                status="success",
                output=output,
                raw_output=output,
                execution_time=execution_time,
                model_used=stage_def.model,
            )

        except Exception as exc:
            execution_time = time.time() - start_time
            return StageResult(
                stage_id=stage_def.stage_id,
                status="failed",
                error=str(exc),
                execution_time=execution_time,
                model_used=stage_def.model,
            )

    def _prepare_prompt(self, stage_def: StageDefinition) -> str:
        """Prepare the prompt by substituting variables from state."""
        prompt = stage_def.prompt_template

        # Prepare input values from state
        input_values = {}
        for stage_input in stage_def.input:
            var_name = stage_input.get_variable_name()
            value = self._resolve_state_value(stage_input.source)
            input_values[var_name] = value

        # Also add the template variables as keywords
        # This allows both {var} and {original_key} to work
        for stage_input in stage_def.input:
            orig_key = stage_input.source.split(".")[-1]
            value = self._resolve_state_value(stage_input.source)
            if orig_key not in input_values:
                input_values[orig_key] = value

        # Format the template
        try:
            prompt = prompt.format(**input_values)
        except KeyError as e:
            logger.warning(f"Missing template variable: {e}")

        return prompt

    def _resolve_state_value(self, source: str) -> str:
        """Resolve a value from state using dot notation."""
        # source can be "user_task" or "planning.architecture_plan"
        if "." in source:
            parts = source.split(".", 1)
            stage_id, key = parts
            state_key = f"{stage_id}.{key}"
            return str(self.state.get(state_key, ""))
        else:
            # Direct key lookup
            return str(self.state.get(source, ""))

    async def _invoke_model(self, stage_def: StageDefinition, prompt: str) -> str:
        """Invoke the appropriate model based on stage definition (override in CLI)."""
        raise NotImplementedError("Model invocation must be handled by the executor subclass (e.g. CLIExecutor)")

    def _save_artifact(self, stage_id: str, result: StageResult) -> None:
        """Save stage output as artifact."""
        if not self.artifacts_dir:
            return

        artifact_path = self.artifacts_dir / f"{stage_id}_output.txt"
        try:
            with open(artifact_path, "w") as f:
                if result.output:
                    f.write(result.output)
            logger.info(f"Saved artifact: {artifact_path}")
        except Exception as e:
            logger.warning(f"Failed to save artifact {artifact_path}: {e}")

    def get_final_results(self) -> dict[str, Any]:
        """Get results as a dictionary for JSON serialization."""
        return {
            stage_id: result.to_dict()
            for stage_id, result in self.results.items()
        }
