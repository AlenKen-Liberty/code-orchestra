"""Harness entry point and scheduler loop."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import uuid
from collections import Counter
from dataclasses import asdict
from dataclasses import replace
from pathlib import Path
from typing import Optional

from config import settings
from harness.chat2api_client import Chat2APIClient
from harness.checkpoint import CheckpointStore
from harness.codex_runtime import CodexAccountRuntime
from harness.daemon import DaemonManager
from harness.db import HarnessDB
from harness.handoff import HandoffProtocol
from harness.intake import IntakeAgent
from harness.logging_utils import configure_logging
from harness.model_registry import ModelRegistry
from harness.models import (
    IntakeResult,
    PermissionRequestRecord,
    QuotaEventRecord,
    StageCheckpoint,
    StageRecord,
    StageStatus,
    TaskRecord,
    TaskStatus,
)
from harness.permission_gate import PermissionGate
from harness.quota_router import AllQuotaExhaustedError, QuotaRouter
from harness.stage_executor import PermissionBlockedError, QuotaExhaustedError, StageExecutionError, StageExecutor
from harness.task_queue import TaskQueue, utcnow_iso
from harness.telemetry import HarnessTelemetry

logger = logging.getLogger(__name__)


class Harness:
    """Main scheduler that turns queued tasks into stage executions."""

    def __init__(
        self,
        *,
        db_path: str | Path = settings.HARNESS_DB_PATH,
        artifact_root: str | Path = settings.HARNESS_ARTIFACT_DIR,
        intake_agent: Optional[IntakeAgent] = None,
        quota_router: Optional[QuotaRouter] = None,
        stage_executor: Optional[StageExecutor] = None,
        telemetry: Optional[HarnessTelemetry] = None,
        codex_runtime: Optional[CodexAccountRuntime] = None,
    ) -> None:
        self.db = HarnessDB(db_path)
        self.task_queue = TaskQueue(self.db)
        self.handoff = HandoffProtocol(artifact_root)
        self.checkpoints = CheckpointStore(artifact_root)
        self.intake = intake_agent or IntakeAgent()
        self.router = quota_router or QuotaRouter()
        self.executor = stage_executor or StageExecutor()
        self.telemetry = telemetry or HarnessTelemetry()
        self.codex_runtime = codex_runtime or CodexAccountRuntime()

    def submit_task(
        self,
        description: str,
        *,
        title: Optional[str] = None,
        goal: Optional[str] = None,
        verify_cmd: Optional[str] = None,
        priority: int = 50,
        working_dir: Optional[str] = None,
    ) -> TaskRecord:
        intake = self.intake.plan_task(description, goal=goal, verify_cmd=verify_cmd)
        if title:
            intake = replace(intake, title=title)
        return self.submit_intake(intake, priority=priority, working_dir=working_dir)

    def submit_intake(
        self,
        intake: IntakeResult,
        *,
        priority: int = 50,
        working_dir: Optional[str] = None,
        status: TaskStatus = TaskStatus.EXECUTING,
    ) -> TaskRecord:
        task = self.task_queue.create_task(
            title=intake.title,
            description=intake.description,
            goal=intake.goal,
            verify_cmd=intake.verify_cmd,
            complexity=intake.complexity,
            priority=priority,
            status=status,
            working_dir=working_dir,
        )
        self.task_queue.save_stages(task.task_id, intake.stages)
        return task

    async def run_once(self) -> Optional[TaskRecord]:
        await self._recover_paused_quota_tasks()
        task = self.task_queue.pick_next_runnable_task()
        if task is None:
            return None

        if self.task_queue.count_stages(task.task_id) == 0:
            await self._plan_missing_stages(task)
            task = self.task_queue.get_task(task.task_id) or task

        stage = self.task_queue.next_pending_stage(task.task_id)
        if stage is None:
            await self._finish_task(task)
            return self.task_queue.get_task(task.task_id)

        await self._run_stage(task, stage)
        return self.task_queue.get_task(task.task_id)

    async def run_forever(
        self,
        poll_interval_sec: int = settings.HARNESS_POLL_INTERVAL_SEC,
        *,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        while stop_event is None or not stop_event.is_set():
            task = await self.run_once()
            if task is None:
                if stop_event is None:
                    await asyncio.sleep(poll_interval_sec)
                else:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_sec)
                    except asyncio.TimeoutError:
                        pass

    def status_report(self) -> list[dict[str, object]]:
        report: list[dict[str, object]] = []
        for task in self.task_queue.list_tasks():
            report.append(
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "status": task.status.value,
                    "priority": task.priority,
                    "complexity": task.complexity,
                    "working_dir": task.working_dir,
                    "stages": [
                        {
                            "stage_type": stage.stage_type,
                            "status": stage.status.value,
                            "assigned_model": stage.assigned_model,
                            "retry_count": stage.retry_count,
                        }
                        for stage in self.task_queue.list_stages(task.task_id)
                    ],
                }
            )
        return report

    def inspect_task(self, task_id: str) -> dict[str, object]:
        task = self.task_queue.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        stages = self.task_queue.list_stages(task_id)
        return {
            "task": {
                "task_id": task.task_id,
                "title": task.title,
                "description": task.description,
                "goal": task.goal,
                "verify_cmd": task.verify_cmd,
                "status": task.status.value,
                "priority": task.priority,
                "complexity": task.complexity,
                "working_dir": task.working_dir,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            },
            "stages": [
                {
                    "stage_id": stage.stage_id,
                    "stage_type": stage.stage_type,
                    "model_role": stage.model_role,
                    "status": stage.status.value,
                    "assigned_model": stage.assigned_model,
                    "assigned_provider": stage.assigned_provider,
                    "handoff_doc_path": stage.handoff_doc_path,
                    "result_summary": stage.result_summary,
                    "retry_count": stage.retry_count,
                    "verify_cmd": stage.verify_cmd,
                    "metadata": stage.metadata,
                }
                for stage in stages
            ],
            "permission_requests": [
                {
                    "request_id": item.request_id,
                    "stage_id": item.stage_id,
                    "action": item.action,
                    "risk_level": item.risk_level.value,
                    "decision": item.decision,
                    "voters": item.voters,
                    "decided_at": item.decided_at,
                }
                for stage in stages
                for item in self.task_queue.list_permission_requests(stage.stage_id)
            ],
            "checkpoints": [
                asdict(checkpoint) for checkpoint in self.checkpoints.list_for_task(task_id)
            ],
        }

    def pause_task(self, task_id: str) -> None:
        self.task_queue.update_task_status(task_id, TaskStatus.PAUSED_PERMISSION)

    def resume_task(self, task_id: str) -> None:
        task = self.task_queue.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if task.status in {TaskStatus.DONE, TaskStatus.FAILED}:
            raise ValueError(f"Cannot resume task in terminal status {task.status.value}")
        self.task_queue.update_task_status(task_id, TaskStatus.EXECUTING)

    def quota_report(self) -> list[dict[str, object]]:
        snapshots = self.router.quota_manager.fetch_all_quotas()
        return [
            {
                "provider": snapshot.provider.value,
                "email": snapshot.email,
                "remaining_percent": snapshot.remaining_percent,
                "reset_at": snapshot.reset_at_readable,
                "time_until_reset_hours": round(snapshot.time_until_reset_hours, 1),
            }
            for snapshot in snapshots
        ]

    def dashboard_report(
        self,
        *,
        daemon_status: Optional[dict[str, object]] = None,
        recent_events: int = settings.HARNESS_DASHBOARD_RECENT_EVENTS,
    ) -> dict[str, object]:
        tasks = self.task_queue.list_tasks()
        stages = [stage for task in tasks for stage in self.task_queue.list_stages(task.task_id)]
        permission_requests = [
            item
            for stage in stages
            for item in self.task_queue.list_permission_requests(stage.stage_id)
        ]
        quota_events = self.task_queue.list_quota_events()
        telemetry = self.telemetry.summarize(recent_limit=recent_events)

        task_statuses = Counter(task.status.value for task in tasks)
        stage_statuses = Counter(stage.status.value for stage in stages)
        running_stages = [
            {
                "task_id": stage.task_id,
                "stage_id": stage.stage_id,
                "stage_type": stage.stage_type,
                "assigned_model": stage.assigned_model,
                "assigned_provider": stage.assigned_provider,
                "account_email": stage.metadata.get("selected_account_email"),
            }
            for stage in stages
            if stage.status == StageStatus.RUNNING
        ]

        return {
            "generated_at": utcnow_iso(),
            "daemon": daemon_status or {},
            "tasks": {
                "total": len(tasks),
                "by_status": dict(sorted(task_statuses.items())),
            },
            "stages": {
                "total": len(stages),
                "by_status": dict(sorted(stage_statuses.items())),
                "running": running_stages,
                "metrics": telemetry["overall"],
                "by_stage_type": telemetry["by_stage_type"],
            },
            "quota": {
                "event_count": len(quota_events),
                "recent": [
                    {
                        "provider": item.provider,
                        "account_email": item.account_email,
                        "event_type": item.event_type,
                        "created_at": item.created_at,
                        "details": item.details,
                    }
                    for item in quota_events[-5:]
                ],
            },
            "permissions": {
                "request_count": len(permission_requests),
                "recent": [
                    {
                        "stage_id": item.stage_id,
                        "action": item.action,
                        "decision": item.decision,
                        "risk_level": item.risk_level.value,
                        "decided_at": item.decided_at,
                    }
                    for item in permission_requests[-5:]
                ],
            },
            "recent_events": telemetry["recent_events"],
        }

    async def _plan_missing_stages(self, task: TaskRecord) -> None:
        self.task_queue.update_task_status(task.task_id, TaskStatus.PLANNING)
        intake = self.intake.plan_task(task.description, goal=task.goal, verify_cmd=task.verify_cmd)
        self.task_queue.save_stages(task.task_id, intake.stages)
        self.task_queue.update_task_status(task.task_id, TaskStatus.EXECUTING)

    async def _recover_paused_quota_tasks(self) -> None:
        for task in self.task_queue.list_tasks(TaskStatus.PAUSED_QUOTA):
            stage = self.task_queue.next_pending_stage(task.task_id)
            if stage is None:
                continue
            if self.router.can_run_stage(task, stage):
                self.task_queue.update_task_status(task.task_id, TaskStatus.EXECUTING)
                self.task_queue.log_quota_event(
                    QuotaEventRecord(
                        event_id=uuid.uuid4().hex,
                        provider=stage.assigned_provider or "unknown",
                        account_email=None,
                        event_type="recovered",
                        details={"task_id": task.task_id, "stage_id": stage.stage_id},
                        created_at=utcnow_iso(),
                    )
                )
                self.telemetry.emit(
                    "task_resumed_quota",
                    task_id=task.task_id,
                    stage_id=stage.stage_id,
                    stage_type=stage.stage_type,
                    provider=stage.assigned_provider,
                )

    async def _run_stage(self, task: TaskRecord, stage: StageRecord) -> None:
        try:
            if not stage.assigned_model or not stage.assigned_provider:
                choice = self.router.select_model(task, stage)
                self.task_queue.assign_stage_model(
                    stage.stage_id,
                    choice.model,
                    choice.provider,
                    account_email=choice.account_email,
                    reason=choice.reason,
                )
                stage = self.task_queue.get_stage(stage.stage_id) or stage

            self._ensure_stage_runtime(stage)
            previous = self.task_queue.list_completed_stages(task.task_id)
            handoff_path = self.handoff.write_handoff(task, stage, previous)
            self.task_queue.mark_stage_running(stage.stage_id, str(handoff_path))
            stage = self.task_queue.get_stage(stage.stage_id) or stage
            self._emit_stage_event("stage_started", task, stage)

            result = await self.executor.execute(stage, str(handoff_path), task.working_dir)
            if stage.verify_cmd and task.working_dir:
                verification = await self.executor.run_verify_cmd(stage.verify_cmd, task.working_dir)
                if verification.returncode != 0:
                    raise StageExecutionError(verification.stderr.strip() or verification.stdout.strip() or stage.verify_cmd)

            self.handoff.save_stage_output(task, stage, result)
            self.task_queue.complete_stage(
                stage.stage_id,
                result_summary=result.summary,
                token_used=result.token_used,
                duration_sec=result.duration_sec,
            )
            self.checkpoints.delete(task.task_id, stage.stage_id)
            self.task_queue.update_task_status(task.task_id, TaskStatus.EXECUTING)
            self._emit_stage_event(
                "stage_succeeded",
                task,
                stage,
                duration_sec=result.duration_sec,
                token_used=result.token_used,
                summary=result.summary,
                files_changed=result.files_changed,
            )

            if self.task_queue.next_pending_stage(task.task_id) is None:
                await self._finish_task(task)
        except AllQuotaExhaustedError as exc:
            self.task_queue.update_task_status(task.task_id, TaskStatus.PAUSED_QUOTA)
            self._emit_stage_event("stage_paused_quota", task, stage, error=str(exc))
        except QuotaExhaustedError as exc:
            retry_count = stage.retry_count + 1
            account_email = self._stage_account_email(stage)
            within_same_model_budget = retry_count <= settings.QUOTA_SAME_MODEL_RETRIES

            if within_same_model_budget:
                # Keep assigned_model — retry the same model after a brief pause
                self.task_queue.reset_stage_to_pending(
                    stage.stage_id,
                    retry_count=retry_count,
                    clear_model=False,
                )
                self.task_queue.update_task_status(task.task_id, TaskStatus.EXECUTING)
                self._emit_stage_event(
                    "stage_quota_retry_same_model",
                    task,
                    stage,
                    error=str(exc),
                    provider=exc.provider,
                    retry_count=retry_count,
                    max_same_model=settings.QUOTA_SAME_MODEL_RETRIES,
                )
            else:
                # Exhausted same-model retries — clear model and pause for fallback
                self.task_queue.reset_stage_to_pending(stage.stage_id, retry_count=retry_count)
                self.task_queue.update_task_status(task.task_id, TaskStatus.PAUSED_QUOTA)
                checkpoint = StageCheckpoint(
                    stage_id=stage.stage_id,
                    task_id=task.task_id,
                    model_used=stage.assigned_model or "",
                    handoff_doc_path=stage.handoff_doc_path or str(self.handoff.handoff_path(task, stage)),
                    files_modified=[],
                    retry_count=retry_count,
                    paused_reason="quota_exhausted",
                    paused_at=utcnow_iso(),
                    partial_output=exc.partial_output,
                )
                self.checkpoints.save(checkpoint)
                self._emit_stage_event(
                    "stage_paused_quota",
                    task,
                    stage,
                    error=str(exc),
                    provider=exc.provider,
                )

            self.task_queue.log_quota_event(
                QuotaEventRecord(
                    event_id=uuid.uuid4().hex,
                    provider=exc.provider,
                    account_email=account_email,
                    event_type="quota_retry" if within_same_model_budget else "exhausted",
                    details={"stage_id": stage.stage_id, "task_id": task.task_id, "retry_count": retry_count},
                    created_at=utcnow_iso(),
                )
            )
        except PermissionBlockedError as exc:
            self.task_queue.reset_stage_to_pending(stage.stage_id, retry_count=stage.retry_count)
            self.task_queue.update_task_status(task.task_id, TaskStatus.PAUSED_PERMISSION)
            self.task_queue.log_permission_request(
                PermissionRequestRecord(
                    request_id=uuid.uuid4().hex,
                    stage_id=stage.stage_id,
                    action=exc.command,
                    context=f"task={task.task_id} stage={stage.stage_type}",
                    risk_level=exc.decision.risk_level,
                    decision=exc.decision.decision,
                    voters=[
                        {"model": vote.model, "vote": vote.vote, "reason": vote.reason}
                        for vote in exc.decision.votes
                    ],
                    decided_at=utcnow_iso(),
                )
            )
            self._emit_stage_event(
                "stage_paused_permission",
                task,
                stage,
                error=str(exc),
                command=exc.command,
                decision=exc.decision.decision,
            )
        except StageExecutionError as exc:
            retry_count = stage.retry_count + 1
            if retry_count > settings.MAX_RETRIES:
                self.task_queue.fail_stage(stage.stage_id, result_summary=str(exc), retry_count=retry_count)
                self.task_queue.update_task_status(task.task_id, TaskStatus.FAILED)
                self._emit_stage_event("stage_failed", task, stage, error=str(exc), retry_count=retry_count)
                self.telemetry.emit("task_finished", task_id=task.task_id, status=TaskStatus.FAILED.value)
            else:
                self.task_queue.reset_stage_to_pending(stage.stage_id, retry_count=retry_count)
                self.task_queue.update_task_status(task.task_id, TaskStatus.EXECUTING)
                self._emit_stage_event("stage_retry", task, stage, error=str(exc), retry_count=retry_count)

    async def _finish_task(self, task: TaskRecord) -> None:
        if task.verify_cmd and task.working_dir:
            verification = await self.executor.run_verify_cmd(task.verify_cmd, task.working_dir)
            if verification.returncode != 0:
                self.task_queue.update_task_status(task.task_id, TaskStatus.FAILED)
                self.telemetry.emit("task_finished", task_id=task.task_id, status=TaskStatus.FAILED.value)
                return
        self.task_queue.update_task_status(task.task_id, TaskStatus.DONE)
        self.telemetry.emit("task_finished", task_id=task.task_id, status=TaskStatus.DONE.value)

    def _ensure_stage_runtime(self, stage: StageRecord) -> None:
        if stage.assigned_provider != "codex":
            return
        self.codex_runtime.ensure_active(self._stage_account_email(stage))

    def _stage_account_email(self, stage: StageRecord) -> str | None:
        account_email = stage.metadata.get("selected_account_email")
        return account_email if isinstance(account_email, str) and account_email else None

    def _emit_stage_event(
        self,
        event_type: str,
        task: TaskRecord,
        stage: StageRecord,
        **payload: object,
    ) -> None:
        event_payload = {
            "task_id": task.task_id,
            "task_status": task.status.value,
            "stage_id": stage.stage_id,
            "stage_type": stage.stage_type,
            "model_role": stage.model_role,
            "assigned_model": stage.assigned_model,
            "assigned_provider": stage.assigned_provider,
            "account_email": self._stage_account_email(stage),
            "retry_count": stage.retry_count,
        }
        event_payload.update(payload)
        self.telemetry.emit(event_type, **event_payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomous multi-LLM harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit", help="Submit a task into the harness queue")
    submit.add_argument("description", help="Task description")
    submit.add_argument("--title", help="Override generated title")
    submit.add_argument("--goal", help="Acceptance goal")
    submit.add_argument("--verify-cmd", help="Verification command")
    submit.add_argument("--priority", type=int, default=50)
    submit.add_argument("--working-dir", help="Task working directory")

    chat = subparsers.add_parser("chat", help="Interactive requirement clarification")
    chat.add_argument("description", nargs="?", help="Initial task description")
    chat.add_argument("--priority", type=int, default=50)
    chat.add_argument("--working-dir", help="Task working directory")

    inspect = subparsers.add_parser("inspect", help="Show a task in detail")
    inspect.add_argument("task_id")

    pause = subparsers.add_parser("pause", help="Pause a task")
    pause.add_argument("task_id")

    resume = subparsers.add_parser("resume", help="Resume a task")
    resume.add_argument("task_id")

    subparsers.add_parser("quota", help="Show quota snapshot")
    subparsers.add_parser("run-once", help="Run one scheduling iteration")
    subparsers.add_parser("status", help="Show queued tasks")
    dashboard = subparsers.add_parser("dashboard", help="Show current harness overview")
    dashboard.add_argument("--recent-events", type=int, default=settings.HARNESS_DASHBOARD_RECENT_EVENTS)

    daemon = subparsers.add_parser("daemon", help="Manage the background harness worker")
    daemon_subparsers = daemon.add_subparsers(dest="daemon_command", required=True)
    daemon_start = daemon_subparsers.add_parser("start", help="Start the background worker")
    daemon_start.add_argument("--poll-interval", type=int, default=settings.HARNESS_POLL_INTERVAL_SEC)
    daemon_stop = daemon_subparsers.add_parser("stop", help="Stop the background worker")
    daemon_stop.add_argument("--timeout", type=float, default=settings.HARNESS_DAEMON_STOP_TIMEOUT_SEC)
    daemon_subparsers.add_parser("status", help="Show background worker status")

    worker = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("--poll-interval", type=int, default=settings.HARNESS_POLL_INTERVAL_SEC)
    return parser


async def _prompt_user_approval(command: str, context: str) -> bool | None:
    if not sys.stdin.isatty():
        return None
    print(f"Permission request for command: {command}")
    if context:
        print(f"Context: {context}")
    answer = await asyncio.to_thread(input, "Allow? [y/N]: ")
    lowered = answer.strip().lower()
    if lowered in {"y", "yes"}:
        return True
    if lowered in {"n", "no", ""}:
        return False
    return None


def build_cli_harness() -> Harness:
    registry = ModelRegistry()
    chat_client = Chat2APIClient()
    permission_gate = PermissionGate(user_approver=_prompt_user_approval)
    stage_executor = StageExecutor(chat_client=chat_client, registry=registry, permission_gate=permission_gate)
    quota_router = QuotaRouter(registry=registry, chat_client=chat_client)
    return Harness(quota_router=quota_router, stage_executor=stage_executor)


def build_daemon_manager() -> DaemonManager:
    return DaemonManager(cwd=Path(__file__).resolve().parent.parent)


def _read_multiline_description() -> str:
    print("Describe the task. Press Enter twice to finish:")
    lines: list[str] = []
    while True:
        line = input()
        if not line and (not lines or not lines[-1]):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _run_chat_submission(harness: Harness, description: str | None, priority: int, working_dir: str | None) -> TaskRecord:
    initial_description = description or _read_multiline_description()
    if not initial_description:
        raise ValueError("Task description cannot be empty.")

    base = harness.intake.plan_task(initial_description)
    questions = harness.intake.generate_questions(initial_description, base.complexity)
    answers: dict[str, str] = {}
    for question in questions:
        suffix = f" [{question.default}]" if question.default else ""
        response = input(f"{question.prompt}{suffix}: ").strip()
        answers[question.key] = response or (question.default or "")

    intake = harness.intake.apply_answers(initial_description, answers)
    return harness.submit_intake(intake, priority=priority, working_dir=working_dir)


async def _main_async(args: argparse.Namespace) -> int:
    if args.command == "submit":
        harness = build_cli_harness()
        task = harness.submit_task(
            args.description,
            title=args.title,
            goal=args.goal,
            verify_cmd=args.verify_cmd,
            priority=args.priority,
            working_dir=args.working_dir,
        )
        print(task.task_id)
        return 0
    if args.command == "chat":
        harness = build_cli_harness()
        task = _run_chat_submission(harness, args.description, args.priority, args.working_dir)
        print(json.dumps({"task_id": task.task_id, "title": task.title}, ensure_ascii=False))
        return 0
    if args.command == "run-once":
        harness = build_cli_harness()
        task = await harness.run_once()
        print(task.task_id if task else "idle")
        return 0
    if args.command == "status":
        harness = build_cli_harness()
        for item in harness.status_report():
            print(json.dumps(item, ensure_ascii=False))
        return 0
    if args.command == "inspect":
        harness = build_cli_harness()
        print(json.dumps(harness.inspect_task(args.task_id), ensure_ascii=False, indent=2))
        return 0
    if args.command == "pause":
        harness = build_cli_harness()
        harness.pause_task(args.task_id)
        print(args.task_id)
        return 0
    if args.command == "resume":
        harness = build_cli_harness()
        harness.resume_task(args.task_id)
        print(args.task_id)
        return 0
    if args.command == "quota":
        harness = build_cli_harness()
        for item in harness.quota_report():
            print(json.dumps(item, ensure_ascii=False))
        return 0
    if args.command == "dashboard":
        harness = build_cli_harness()
        daemon_status = build_daemon_manager().status()
        print(json.dumps(harness.dashboard_report(daemon_status=daemon_status, recent_events=args.recent_events), ensure_ascii=False, indent=2))
        return 0
    if args.command == "daemon":
        manager = build_daemon_manager()
        if args.daemon_command == "start":
            print(json.dumps(manager.start(poll_interval_sec=args.poll_interval), ensure_ascii=False, indent=2))
            return 0
        if args.daemon_command == "stop":
            print(json.dumps(manager.stop(timeout_sec=args.timeout), ensure_ascii=False, indent=2))
            return 0
        if args.daemon_command == "status":
            print(json.dumps(manager.status(), ensure_ascii=False, indent=2))
            return 0
    if args.command == "_worker":
        harness = build_cli_harness()
        stop_event = asyncio.Event()
        _install_signal_handlers(stop_event)
        await harness.run_forever(args.poll_interval, stop_event=stop_event)
        return 0
    return 1


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    def _request_stop() -> None:
        logger.info("Received shutdown signal; stopping after current iteration.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: _request_stop())


if __name__ == "__main__":
    main()
