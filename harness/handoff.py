"""Handoff document generation and artifact storage."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from harness.models import StageCheckpoint, StageExecutionResult, StageRecord, TaskRecord


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
        *,
        checkpoint: StageCheckpoint | None = None,
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

        if checkpoint and (checkpoint.git_diff or checkpoint.partial_output or checkpoint.files_modified):
            lines.extend(self._format_checkpoint_section(checkpoint, stage))

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

    def _format_checkpoint_section(
        self, checkpoint: StageCheckpoint, stage: StageRecord
    ) -> list[str]:
        lines = [
            "## ⚠ Resuming from checkpoint (previous attempt interrupted)",
            f"- Previous model: {checkpoint.model_used}",
            f"- Retry count: {checkpoint.retry_count}",
            f"- Paused reason: {checkpoint.paused_reason}",
            "",
            "**IMPORTANT: A previous attempt already made partial progress.**",
            "**Review the diff below and CONTINUE from where it left off.**",
            "**Do NOT redo work that is already done.**",
            "",
        ]
        if checkpoint.files_modified:
            lines.append("### Files already modified")
            for f in checkpoint.files_modified:
                lines.append(f"- `{f}`")
            lines.append("")
        if checkpoint.git_diff:
            lines.append("### Changes already applied (git diff)")
            lines.append("```diff")
            # Cap diff in handoff to keep it readable
            diff_text = checkpoint.git_diff
            if len(diff_text) > 15000:
                diff_text = diff_text[:15000] + "\n... (truncated, run `git diff` for full output)"
            lines.append(diff_text.rstrip())
            lines.append("```")
            lines.append("")
        if checkpoint.git_status:
            lines.append("### Working tree status")
            lines.append("```")
            lines.append(checkpoint.git_status.rstrip())
            lines.append("```")
            lines.append("")
        if checkpoint.partial_output:
            lines.append("### Partial output from previous attempt")
            partial = checkpoint.partial_output
            if len(partial) > 5000:
                partial = partial[:5000] + "\n... (truncated)"
            lines.append("```")
            lines.append(partial.rstrip())
            lines.append("```")
            lines.append("")
        return lines

    def write_handoff(
        self,
        task: TaskRecord,
        stage: StageRecord,
        previous_stages: Iterable[StageRecord],
        *,
        checkpoint: StageCheckpoint | None = None,
    ) -> Path:
        content = self.generate(task, stage, previous_stages, checkpoint=checkpoint)
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
