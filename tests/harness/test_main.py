import asyncio
from pathlib import Path

from harness.main import Harness
from harness.models import ModelChoice, PlannedStage, StageExecutionResult, StageStatus, TaskStatus
from harness.stage_executor import CommandExecution, StageExecutionError
from harness.telemetry import HarnessTelemetry


class DummyRouter:
    def select_model(self, task, stage, **kwargs):
        return ModelChoice(model="gpt-5.4-codex", provider="codex", reason="test")

    def can_run_stage(self, task, stage, **kwargs):
        return True


class DummyExecutor:
    def __init__(self) -> None:
        self.executed = []

    def capture_stage_snapshot(self, working_dir):
        return {"files_modified": [], "git_diff": "", "git_status": ""}

    async def execute(self, stage, handoff_doc_path, working_dir):
        self.executed.append((stage.stage_type, handoff_doc_path, working_dir))
        return StageExecutionResult(
            stage_id=stage.stage_id,
            status=StageStatus.DONE,
            raw_output="implemented feature",
            summary="implemented feature",
            files_changed=["src/feature.py"],
        )

    async def run_verify_cmd(self, verify_cmd, working_dir):
        return CommandExecution(returncode=0, stdout="ok", stderr="")


class DummyCodexRuntime:
    def __init__(self) -> None:
        self.calls = []

    def ensure_active(self, account_email):
        self.calls.append(account_email)
        return True


class AccountSelectingRouter(DummyRouter):
    def select_model(self, task, stage, **kwargs):
        return ModelChoice(
            model="gpt-5.4-codex",
            provider="codex",
            account_email="codex-2@test",
            reason="test-account-rotation",
        )


class FlakyExecutor(DummyExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def execute(self, stage, handoff_doc_path, working_dir):
        self.calls += 1
        if self.calls == 1:
            raise StageExecutionError("temporary failure")
        return StageExecutionResult(
            stage_id=stage.stage_id,
            status=StageStatus.DONE,
            raw_output="implemented feature",
            summary="implemented feature",
            files_changed=["src/feature.py"],
            duration_sec=4.5,
            token_used=321,
        )


def test_harness_run_once_executes_stage_and_finishes_task(tmp_path) -> None:
    executor = DummyExecutor()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=DummyRouter(),
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )
    task = harness.task_queue.create_task(
        "task",
        "desc",
        status=TaskStatus.EXECUTING,
        working_dir=str(tmp_path),
    )
    harness.task_queue.save_stages(
        task.task_id,
        [PlannedStage(stage_type="code", stage_order=1, model_role="coder")],
    )

    asyncio.run(harness.run_once())

    updated_task = harness.task_queue.get_task(task.task_id)
    [stage] = harness.task_queue.list_stages(task.task_id)

    assert updated_task is not None
    assert updated_task.status == TaskStatus.DONE
    assert stage.status == StageStatus.DONE
    assert stage.handoff_doc_path is not None
    assert Path(stage.handoff_doc_path).exists()
    assert executor.executed == [("code", stage.handoff_doc_path, str(tmp_path))]


def test_harness_recovers_paused_quota_tasks(tmp_path) -> None:
    executor = DummyExecutor()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=DummyRouter(),
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )
    task = harness.task_queue.create_task(
        "task",
        "desc",
        status=TaskStatus.PAUSED_QUOTA,
        working_dir=str(tmp_path),
    )
    harness.task_queue.save_stages(
        task.task_id,
        [PlannedStage(stage_type="code", stage_order=1, model_role="coder")],
    )

    asyncio.run(harness.run_once())

    updated_task = harness.task_queue.get_task(task.task_id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.DONE


def test_harness_inspect_includes_permission_requests(tmp_path) -> None:
    executor = DummyExecutor()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=DummyRouter(),
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )
    task = harness.task_queue.create_task("task", "desc", status=TaskStatus.EXECUTING, working_dir=str(tmp_path))
    [stage] = harness.task_queue.save_stages(
        task.task_id,
        [PlannedStage(stage_type="code", stage_order=1, model_role="coder")],
    )
    from harness.models import PermissionRequestRecord, RiskLevel

    harness.task_queue.log_permission_request(
        PermissionRequestRecord(
            request_id="req-1",
            stage_id=stage.stage_id,
            action="git push origin main",
            context="task=demo",
            risk_level=RiskLevel.DANGEROUS,
            decision="needs_user_approval",
            voters=[{"model": "gpt-5.4-codex", "vote": "REJECT", "reason": "too risky"}],
            decided_at="2026-03-27T00:00:00+00:00",
        )
    )

    data = harness.inspect_task(task.task_id)

    assert data["task"]["task_id"] == task.task_id
    assert data["permission_requests"][0]["action"] == "git push origin main"


def test_harness_switches_codex_account_before_execution(tmp_path) -> None:
    executor = DummyExecutor()
    codex_runtime = DummyCodexRuntime()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=AccountSelectingRouter(),
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
        codex_runtime=codex_runtime,
    )
    task = harness.task_queue.create_task(
        "task",
        "desc",
        status=TaskStatus.EXECUTING,
        working_dir=str(tmp_path),
    )
    harness.task_queue.save_stages(
        task.task_id,
        [PlannedStage(stage_type="code", stage_order=1, model_role="coder")],
    )

    asyncio.run(harness.run_once())

    [stage] = harness.task_queue.list_stages(task.task_id)
    assert codex_runtime.calls == ["codex-2@test"]
    assert stage.metadata["selected_account_email"] == "codex-2@test"


def test_harness_dashboard_summarizes_stage_metrics(tmp_path) -> None:
    executor = FlakyExecutor()
    telemetry = HarnessTelemetry(tmp_path / "events.jsonl")
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=DummyRouter(),
        stage_executor=executor,
        telemetry=telemetry,
    )
    task = harness.task_queue.create_task(
        "task",
        "desc",
        status=TaskStatus.EXECUTING,
        working_dir=str(tmp_path),
    )
    harness.task_queue.save_stages(
        task.task_id,
        [PlannedStage(stage_type="code", stage_order=1, model_role="coder")],
    )

    asyncio.run(harness.run_once())
    asyncio.run(harness.run_once())

    report = harness.dashboard_report(daemon_status={"running": False}, recent_events=10)

    assert report["daemon"]["running"] is False
    assert report["stages"]["metrics"]["attempts"] == 2
    assert report["stages"]["metrics"]["errors"] == 1
    assert report["stages"]["metrics"]["total_token_used"] == 321
    assert report["stages"]["by_stage_type"][0]["stage_type"] == "code"
    assert report["stages"]["by_stage_type"][0]["error_rate"] == 0.5
    assert [event["event"] for event in report["recent_events"]][-2:] == ["stage_succeeded", "task_finished"]
