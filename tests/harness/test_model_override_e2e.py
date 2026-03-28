"""End-to-end tests for user-specified pipeline model assignments.

Covers the full flow: CLI parsing → submit_task → intake planning →
stage persistence → run_once (QuotaRouter skip) → execution.
"""
import asyncio

from harness.main import Harness, build_parser
from harness.model_registry import ModelRegistry
from harness.models import (
    ModelChoice,
    PlannedStage,
    StageExecutionResult,
    StageStatus,
    TaskStatus,
)
from harness.stage_executor import CommandExecution
from harness.telemetry import HarnessTelemetry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class SpyRouter:
    """Records whether select_model was called."""

    def __init__(self):
        self.called = False

    def select_model(self, task, stage, **kwargs):
        self.called = True
        return ModelChoice(model="gpt-5.4-codex", provider="codex", reason="fallback")

    def can_run_stage(self, task, stage, **kwargs):
        return True


class RecordingExecutor:
    """Records (stage_type, assigned_model, assigned_provider) for each execution."""

    def __init__(self):
        self.executed: list[tuple[str, str | None, str | None]] = []

    async def execute(self, stage, handoff_doc_path, working_dir):
        self.executed.append((stage.stage_type, stage.assigned_model, stage.assigned_provider))
        return StageExecutionResult(
            stage_id=stage.stage_id,
            status=StageStatus.DONE,
            raw_output="ok",
            summary="ok",
        )

    async def run_verify_cmd(self, verify_cmd, working_dir):
        return CommandExecution(returncode=0, stdout="ok", stderr="")


# ---------------------------------------------------------------------------
# E2E: submit_task with model_overrides → run_once skips router
# ---------------------------------------------------------------------------

def test_submit_with_model_override_skips_router(tmp_path):
    """Full flow: submit with overrides → stages persisted → router skipped."""
    router = SpyRouter()
    executor = RecordingExecutor()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=router,
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )

    # Submit a trivial task with a model override on the "code" stage
    task = harness.submit_task(
        "Fix the login bug",
        working_dir=str(tmp_path),
        model_overrides={"code": ("gemini-3.1-pro", "google")},
    )

    # Verify stages were persisted with pre-assignment
    stages = harness.task_queue.list_stages(task.task_id)
    code_stage = next(s for s in stages if s.stage_type == "code")
    assert code_stage.assigned_model == "gemini-3.1-pro"
    assert code_stage.assigned_provider == "google"

    # Run through all stages
    while True:
        result = asyncio.run(harness.run_once())
        if result is None or result.status in {TaskStatus.DONE, TaskStatus.FAILED}:
            break

    # Router should NOT have been called for the code stage (pre-assigned)
    # It may have been called for the github_ops stage (no override)
    assert router.called  # github_ops stage uses router
    # The code stage must have been executed with the pre-assigned model
    code_exec = next(e for e in executor.executed if e[0] == "code")
    assert code_exec[1] == "gemini-3.1-pro"
    assert code_exec[2] == "google"


def test_submit_with_multiple_overrides_persists_all(tmp_path):
    """Multiple --model-override flags are all persisted correctly."""
    executor = RecordingExecutor()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=SpyRouter(),
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )

    # "medium" complexity triggers: plan, code, review, test, github_ops
    task = harness.submit_task(
        "Build a quota-aware scheduler with checkpoint recovery and permission voting support.",
        working_dir=str(tmp_path),
        model_overrides={
            "code": ("gemini-3.1-pro", "google"),
            "review": ("claude-opus-4-6", "claude"),
        },
    )

    stages = harness.task_queue.list_stages(task.task_id)
    by_type = {s.stage_type: s for s in stages}

    # Overridden stages
    assert by_type["code"].assigned_model == "gemini-3.1-pro"
    assert by_type["code"].assigned_provider == "google"
    assert by_type["review"].assigned_model == "claude-opus-4-6"
    assert by_type["review"].assigned_provider == "claude"

    # Non-overridden stages remain None
    assert by_type["plan"].assigned_model is None
    assert by_type["plan"].assigned_provider is None
    assert by_type["test"].assigned_model is None


def test_no_override_uses_router(tmp_path):
    """Without model_overrides, QuotaRouter is always called."""
    router = SpyRouter()
    executor = RecordingExecutor()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=router,
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )

    task = harness.submit_task(
        "Fix the login bug",
        working_dir=str(tmp_path),
    )

    asyncio.run(harness.run_once())

    assert router.called


def test_override_for_nonexistent_stage_is_harmless(tmp_path):
    """Overriding a stage that doesn't exist in the plan is silently ignored."""
    executor = RecordingExecutor()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=SpyRouter(),
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )

    # trivial task only has code + github_ops, "review" override is extra
    task = harness.submit_task(
        "Fix typo",
        working_dir=str(tmp_path),
        model_overrides={
            "code": ("gemini-3.1-pro", "google"),
            "review": ("claude-opus-4-6", "claude"),  # no review stage for trivial
        },
    )

    stages = harness.task_queue.list_stages(task.task_id)
    stage_types = [s.stage_type for s in stages]
    assert "review" not in stage_types  # trivial doesn't have review
    code_stage = next(s for s in stages if s.stage_type == "code")
    assert code_stage.assigned_model == "gemini-3.1-pro"


# ---------------------------------------------------------------------------
# E2E: CLI argument parsing
# ---------------------------------------------------------------------------

def test_cli_parser_model_override_flag():
    """--model-override flags are parsed into args.model_override list."""
    parser = build_parser()
    args = parser.parse_args([
        "submit", "Do something",
        "--model-override", "code=gemini-3.1-pro",
        "--model-override", "review=opus",
    ])

    assert args.model_override == ["code=gemini-3.1-pro", "review=opus"]


def test_cli_parser_no_override_defaults_to_empty():
    """Without --model-override, the list is empty."""
    parser = build_parser()
    args = parser.parse_args(["submit", "Do something"])

    assert args.model_override == []


def test_cli_override_parsing_with_alias_resolution():
    """Simulates the CLI override parsing logic from _main_async with alias resolution."""
    registry = ModelRegistry()

    # Simulate what _main_async does
    raw_overrides = ["code=codex", "review=opus"]
    model_overrides = {}
    for override in raw_overrides:
        stage, model_name = override.split("=", 1)
        canonical = registry.resolve(model_name.strip())
        provider = registry.provider(model_name.strip()) or "unknown"
        model_overrides[stage.strip()] = (canonical, provider)

    # "codex" should resolve to canonical name with provider
    assert model_overrides["code"][0] == registry.resolve("codex")
    assert model_overrides["code"][1] != ""  # should have a provider

    # "opus" should resolve to canonical name
    assert model_overrides["review"][0] == registry.resolve("opus")


# ---------------------------------------------------------------------------
# E2E: Full multi-stage run with partial overrides
# ---------------------------------------------------------------------------

def test_full_run_partial_overrides_mixed_routing(tmp_path):
    """Run a multi-stage task where some stages have overrides and some don't.

    Verifies that overridden stages keep their assignment through execution
    while non-overridden stages get routed.
    """
    router = SpyRouter()
    executor = RecordingExecutor()
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=router,
        stage_executor=executor,
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )

    # Simple task: code, review, github_ops
    task = harness.submit_task(
        "Add a blacklist setting to the scheduler, wire config loading, and cover it with tests.",
        working_dir=str(tmp_path),
        model_overrides={"code": ("gemini-3.1-pro", "google")},
    )

    # Run all stages
    for _ in range(10):  # safety limit
        result = asyncio.run(harness.run_once())
        if result is None or result.status in {TaskStatus.DONE, TaskStatus.FAILED}:
            break

    final = harness.task_queue.get_task(task.task_id)
    assert final is not None
    assert final.status == TaskStatus.DONE

    # Verify code stage kept override, others got routed
    final_stages = harness.task_queue.list_stages(task.task_id)
    code = next(s for s in final_stages if s.stage_type == "code")
    review = next(s for s in final_stages if s.stage_type == "review")

    assert code.assigned_model == "gemini-3.1-pro"
    assert code.assigned_provider == "google"
    # review was routed by SpyRouter
    assert review.assigned_model == "gpt-5.4-codex"
    assert review.assigned_provider == "codex"


def test_status_report_includes_assigned_model(tmp_path):
    """status_report() exposes assigned_model for overridden stages."""
    harness = Harness(
        db_path=tmp_path / "harness.db",
        artifact_root=tmp_path / "artifacts",
        quota_router=SpyRouter(),
        stage_executor=RecordingExecutor(),
        telemetry=HarnessTelemetry(tmp_path / "events.jsonl"),
    )

    harness.submit_task(
        "Fix typo",
        working_dir=str(tmp_path),
        model_overrides={"code": ("gemini-3.1-pro", "google")},
    )

    report = harness.status_report()
    assert len(report) == 1
    code_stage = next(s for s in report[0]["stages"] if s["stage_type"] == "code")
    assert code_stage["assigned_model"] == "gemini-3.1-pro"
