"""Handoff document generation and artifact storage."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from harness.models import StageExecutionResult, StageRecord, TaskRecord


class HandoffProtocol:
    """Persist stage inputs and outputs as markdown artifacts."""

    def __init__(self, artifact_root: str | Path = "artifacts") -> None:
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def task_dir(self, task_id: str) -> Path:
        path = self.artifact_root / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def handoff_path(self, task: TaskRecord, stage: StageRecord) -> Path:
        return self.task_dir(task.task_id) / f"{stage.stage_order:02d}_{stage.stage_type}_handoff.md"

    def output_path(self, task: TaskRecord, stage: StageRecord) -> Path:
        return self.task_dir(task.task_id) / f"{stage.stage_order:02d}_{stage.stage_type}_output.md"

    def generate(
        self,
        task: TaskRecord,
        stage: StageRecord,
        previous_stages: Iterable[StageRecord],
    ) -> str:
        previous = list(previous_stages)
        previous_stage_name = previous[-1].stage_type if previous else "bootstrap"

        lines = [
            f"# Handoff: {previous_stage_name} -> {stage.stage_type}",
            "## Task",
            task.title,
            "",
            "## Description",
            task.description,
            "",
        ]

        if task.goal:
            lines.extend(["## Goal", task.goal, ""])

        lines.extend(
            [
                "## Context",
                f"- Complexity: {task.complexity}",
                f"- Current Stage: {stage.stage_type} ({stage.model_role})",
                f"- Working Directory: {task.working_dir or '.'}",
                "",
            ]
        )

        if previous:
            lines.append("## Previous Stage Output")
            for previous_stage in previous:
                summary = previous_stage.result_summary or "No summary recorded."
                lines.extend(
                    [
                        f"### {previous_stage.stage_type}",
                        summary.strip(),
                        "",
                    ]
                )

        lines.append("## Current Stage Instructions")
        instruction = stage.metadata.get("instructions") if stage.metadata else None
        if instruction:
            lines.append(str(instruction).strip())
        else:
            lines.append(
                f"Complete the `{stage.stage_type}` stage for this task in `{task.working_dir or '.'}`."
            )
        lines.append("")

        verify_cmd = stage.verify_cmd or task.verify_cmd
        if verify_cmd:
            lines.extend(["## Verification", f"Run: `{verify_cmd}`", ""])

        return "\n".join(lines).rstrip() + "\n"

    def write_handoff(
        self,
        task: TaskRecord,
        stage: StageRecord,
        previous_stages: Iterable[StageRecord],
    ) -> Path:
        content = self.generate(task, stage, previous_stages)
        path = self.handoff_path(task, stage)
        path.write_text(content, encoding="utf-8")
        return path

    def save_stage_output(
        self,
        task: TaskRecord,
        stage: StageRecord,
        result: StageExecutionResult,
    ) -> Path:
        path = self.output_path(task, stage)
        lines = [
            f"# Output: {stage.stage_type}",
            "## Summary",
            result.summary or "No summary generated.",
            "",
        ]
        if result.files_changed:
            lines.append("## Files Changed")
            lines.extend(f"- {path_item}" for path_item in result.files_changed)
            lines.append("")
        if result.raw_output:
            lines.extend(["## Raw Output", "```text", result.raw_output.rstrip(), "```", ""])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path
