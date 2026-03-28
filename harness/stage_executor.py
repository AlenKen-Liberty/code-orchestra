"""CLI-backed stage execution."""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from config import settings
from harness.chat2api_client import Chat2APIClient
from harness.model_registry import ModelRegistry
from harness.models import PermissionDecision, StageExecutionResult, StageRecord, StageStatus
from harness.permission_gate import PermissionGate


@dataclass(slots=True)
class CommandExecution:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., Awaitable[CommandExecution]]


class StageExecutionError(RuntimeError):
    """Base stage execution error."""


class QuotaExhaustedError(StageExecutionError):
    """Raised when the underlying provider reports quota exhaustion."""

    def __init__(self, provider: str, message: str, partial_output: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.partial_output = partial_output


class PermissionBlockedError(StageExecutionError):
    """Raised when an action is blocked by the permission gate."""

    def __init__(self, command: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.command = command
        self.decision = decision


class StageExecutor:
    """Execute planned stages via CLI backends or lightweight API calls."""

    APPROVED_DECISIONS = {"auto_approved", "model_approved", "user_approved"}

    def __init__(
        self,
        *,
        chat_client: Optional[Chat2APIClient] = None,
        registry: Optional[ModelRegistry] = None,
        permission_gate: Optional[PermissionGate] = None,
        runner: Optional[Runner] = None,
        codex_tier: str = settings.CODEX_TIER,
    ) -> None:
        self.chat_client = chat_client or Chat2APIClient()
        self.registry = registry or ModelRegistry()
        self.permission_gate = permission_gate or PermissionGate()
        self.runner = runner or self._run_command
        self.codex_tier = codex_tier

    async def execute(self, stage: StageRecord, handoff_doc_path: str, working_dir: str | None) -> StageExecutionResult:
        started_at = time.time()
        prompt = Path(handoff_doc_path).read_text(encoding="utf-8")
        provider = stage.assigned_provider or self._infer_provider(stage.assigned_model or "")
        cwd = working_dir or "."

        if provider == "chat2api":
            raw_output = await asyncio.to_thread(
                self.chat_client.chat,
                model=stage.assigned_model or "",
                prompt=prompt,
            )
            duration = time.time() - started_at
            return StageExecutionResult(
                stage_id=stage.stage_id,
                status=StageStatus.DONE,
                raw_output=raw_output,
                summary=self._summarize(raw_output),
                duration_sec=duration,
            )

        if provider == "github":
            return await self._run_github_ops(stage, prompt, cwd, started_at)

        command = self.build_command(stage, prompt, cwd)
        completed = await self._run_checked_command(
            command,
            cwd,
            context=f"stage={stage.stage_type} role={stage.model_role}",
            stdin_text=prompt,
        )
        combined_output = completed.stdout.strip() or completed.stderr.strip()

        if self._looks_like_quota_exhaustion(completed.stdout, completed.stderr, completed.returncode):
            raise QuotaExhaustedError(provider or "unknown", combined_output, partial_output=completed.stdout)
        if completed.returncode != 0:
            raise StageExecutionError(combined_output or f"Stage failed with exit code {completed.returncode}")

        duration = time.time() - started_at
        files_changed = self._list_changed_files(cwd)
        raw_output = self._normalize_output(completed.stdout, stage.assigned_provider)
        return StageExecutionResult(
            stage_id=stage.stage_id,
            status=StageStatus.DONE,
            raw_output=raw_output,
            summary=self._summarize(raw_output),
            files_changed=files_changed,
            duration_sec=duration,
            token_used=self._extract_token_usage(completed.stdout, stage.assigned_provider),
        )

    def build_command(self, stage: StageRecord, prompt: str, working_dir: str) -> list[str]:
        """Build CLI command. Prompt is passed via stdin, not as an argument."""
        provider = stage.assigned_provider or self._infer_provider(stage.assigned_model or "")
        model = stage.assigned_model or ""
        cli_model = self.registry.cli_model_id(model)
        if provider == "claude":
            # Prompt is piped via stdin; no positional prompt argument needed.
            return [
                "claude",
                "-p",
                "--verbose",
                "--output-format",
                "stream-json",
                "--model",
                cli_model,
                "--allowedTools",
                "Edit,Read,Bash,Grep,Glob,Write",
            ]
        if provider == "codex":
            return [
                "codex",
                "exec",
                "--json",
                "-C",
                working_dir,
                "--full-auto",
                prompt,
            ]
        if provider == "google":
            return [
                "gemini",
                "--model",
                cli_model,
                "-y",
                "-p",
                prompt,
            ]
        # NOTE: claude uses stdin for prompt (no positional arg); codex/gemini use positional.
        raise StageExecutionError(f"Unsupported provider for CLI execution: {provider}")

    async def run_verify_cmd(self, verify_cmd: str, working_dir: str | None) -> CommandExecution:
        return await self._run_checked_command(
            ["bash", "-lc", verify_cmd],
            working_dir or ".",
            context="verification command",
            display_command=verify_cmd,
        )

    async def _run_github_ops(
        self,
        stage: StageRecord,
        prompt: str,
        working_dir: str,
        started_at: float,
    ) -> StageExecutionResult:
        commands = [str(item) for item in stage.metadata.get("commands", [])]
        if not commands:
            summary = "GitHub stage had no commands configured."
            return StageExecutionResult(
                stage_id=stage.stage_id,
                status=StageStatus.DONE,
                raw_output=summary,
                summary=summary,
                duration_sec=time.time() - started_at,
            )

        commit_summary = self._extract_commit_summary(prompt, stage)

        outputs: list[str] = []
        for raw_command in commands:
            rendered = raw_command.format(
                summary=commit_summary,
                stage_type=stage.stage_type,
                working_dir=working_dir,
                prompt=prompt,
                task_id=stage.task_id,
            )
            completed = await self._run_checked_command(
                ["bash", "-lc", rendered],
                working_dir,
                context=f"github_ops stage={stage.stage_type}",
                display_command=rendered,
            )
            if completed.returncode != 0:
                raise StageExecutionError(completed.stderr.strip() or completed.stdout.strip() or rendered)
            output = completed.stdout.strip() or completed.stderr.strip() or f"Executed: {rendered}"
            outputs.append(output)

        raw_output = "\n".join(outputs).strip()
        return StageExecutionResult(
            stage_id=stage.stage_id,
            status=StageStatus.DONE,
            raw_output=raw_output,
            summary=self._summarize(raw_output),
            files_changed=self._list_changed_files(working_dir),
            duration_sec=time.time() - started_at,
        )

    async def _run_checked_command(
        self,
        command: list[str],
        cwd: str,
        *,
        context: str,
        display_command: Optional[str] = None,
        stdin_text: Optional[str] = None,
    ) -> CommandExecution:
        command_text = display_command or self._display_command(command)
        decision = await self.permission_gate.decide(
            command_text,
            context=context,
            available_models=self._safe_list_available_models(),
        )
        if decision.decision not in self.APPROVED_DECISIONS:
            raise PermissionBlockedError(command_text, decision)
        return await self.runner(command, cwd, stdin_text=stdin_text)

    async def _run_command(self, command: list[str], cwd: str, *, stdin_text: Optional[str] = None) -> CommandExecution:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE if stdin_text else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdin_bytes = stdin_text.encode("utf-8") if stdin_text else None
        stdout, stderr = await process.communicate(input=stdin_bytes)
        return CommandExecution(
            returncode=process.returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    def _normalize_output(self, stdout: str, provider: Optional[str]) -> str:
        text = stdout.strip()
        if provider != "codex" or not text:
            return text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, dict):
            if "output_text" in parsed and isinstance(parsed["output_text"], str):
                return parsed["output_text"]
            if "message" in parsed and isinstance(parsed["message"], str):
                return parsed["message"]
        return text

    def _extract_token_usage(self, stdout: str, provider: Optional[str]) -> int:
        text = stdout.strip()
        if provider != "codex" or not text:
            return 0
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return 0
        return max(0, self._find_token_total(parsed))

    def _summarize(self, text: str) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= 280:
            return cleaned
        return cleaned[:277] + "..."

    def _extract_commit_summary(self, prompt: str, stage: StageRecord) -> str:
        """Build a short commit message from the handoff doc."""
        # Look for "# Task: <title>" in the handoff markdown
        for line in prompt.splitlines():
            stripped = line.strip()
            if stripped.startswith("# Task:") or stripped.startswith("# "):
                title = stripped.lstrip("# ").removeprefix("Task:").strip()
                if title:
                    return title[:120]
        return f"task {stage.task_id}"

    def _infer_provider(self, model: str) -> str:
        if model.startswith("claude-"):
            return "claude"
        if "codex" in model:
            return "codex"
        if model.startswith("gemini-"):
            return "google"
        if model.startswith("gpt-4o") or model.startswith("gpt-4.1"):
            return "github"
        return ""

    def _looks_like_quota_exhaustion(self, stdout: str, stderr: str, returncode: int = 1) -> bool:
        """Detect provider quota/rate-limit errors.

        Only triggers on non-zero exit codes to avoid false positives when
        the model output itself discusses quotas (e.g. planning a quota feature).
        """
        if returncode == 0:
            return False
        text = f"{stdout}\n{stderr}".lower()
        return any(token in text for token in ("rate limit", "limit reached", "quota exceeded", "quota exhausted", "rate_limit_exceeded"))

    def _list_changed_files(self, working_dir: str) -> list[str]:
        try:
            completed = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=working_dir,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return []
        if completed.returncode != 0:
            return []
        return [line for line in completed.stdout.splitlines() if line.strip()]

    def _safe_list_available_models(self) -> list[str] | None:
        try:
            return self.chat_client.list_models()
        except Exception:
            return None

    def _display_command(self, command: list[str]) -> str:
        return subprocess.list2cmdline(command)

    def _find_token_total(self, payload: object) -> int:
        if isinstance(payload, dict):
            for key in ("total_tokens", "token_used"):
                value = self._coerce_int(payload.get(key))
                if value is not None:
                    return value

            usage = payload.get("usage")
            if isinstance(usage, dict):
                total = self._coerce_int(usage.get("total_tokens"))
                if total is not None:
                    return total
                input_tokens = self._coerce_int(usage.get("input_tokens")) or 0
                output_tokens = self._coerce_int(usage.get("output_tokens")) or 0
                if input_tokens or output_tokens:
                    return input_tokens + output_tokens

            for value in payload.values():
                nested = self._find_token_total(value)
                if nested:
                    return nested

        if isinstance(payload, list):
            totals = [self._find_token_total(item) for item in payload]
            return sum(total for total in totals if total)

        return 0

    def _coerce_int(self, value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
