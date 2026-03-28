from harness.handoff import HandoffProtocol
from harness.models import StageCheckpoint, StageExecutionResult, StageRecord, StageStatus, TaskRecord, TaskStatus


def make_task() -> TaskRecord:
    return TaskRecord(
        task_id="task-1",
        title="Blacklist support",
        description="Add blacklist support to the scheduler.",
        goal="Scheduler skips blocked subreddits.",
        verify_cmd="pytest tests/test_blacklist.py",
        complexity="simple",
        priority=50,
        status=TaskStatus.EXECUTING,
        working_dir="/repo",
        created_at="2026-03-27T00:00:00+00:00",
        updated_at="2026-03-27T00:00:00+00:00",
    )


def make_stage(stage_id: str, stage_type: str, order: int, summary: str | None = None) -> StageRecord:
    return StageRecord(
        stage_id=stage_id,
        task_id="task-1",
        stage_type=stage_type,
        stage_order=order,
        model_role="coder" if stage_type == "code" else "planner",
        assigned_model="gpt-5.4-codex",
        assigned_provider="codex",
        status=StageStatus.DONE if summary else StageStatus.PENDING,
        handoff_doc_path=None,
        result_summary=summary,
        token_used=0,
        duration_sec=0.0,
        started_at=None,
        finished_at=None,
    )


def test_handoff_includes_previous_stage_summary(tmp_path) -> None:
    protocol = HandoffProtocol(tmp_path / "artifacts")
    task = make_task()
    previous = make_stage("stage-plan", "plan", 1, summary="Use config/blacklist.yaml and add tests.")
    current = make_stage("stage-code", "code", 2)
    current.verify_cmd = "pytest tests/test_blacklist.py"

    handoff_path = protocol.write_handoff(task, current, [previous])
    content = handoff_path.read_text(encoding="utf-8")

    assert handoff_path.exists()
    assert "# Handoff: plan -> code" in content
    assert "Use config/blacklist.yaml and add tests." in content
    assert "Run: `pytest tests/test_blacklist.py`" in content


def test_handoff_saves_stage_output(tmp_path) -> None:
    protocol = HandoffProtocol(tmp_path / "artifacts")
    task = make_task()
    stage = make_stage("stage-code", "code", 2)
    result = StageExecutionResult(
        stage_id=stage.stage_id,
        status=StageStatus.DONE,
        raw_output="Implemented blacklist filtering.",
        summary="Implemented blacklist filtering.",
        files_changed=["scheduler/planner.py", "tests/test_blacklist.py"],
    )

    output_path = protocol.save_stage_output(task, stage, result)
    content = output_path.read_text(encoding="utf-8")

    assert output_path.exists()
    assert "scheduler/planner.py" in content
    assert "Implemented blacklist filtering." in content


def test_handoff_includes_checkpoint_resume_context(tmp_path) -> None:
    protocol = HandoffProtocol(tmp_path / "artifacts")
    task = make_task()
    previous = make_stage("stage-plan", "plan", 1, summary="Plan done.")
    current = make_stage("stage-code", "code", 2)

    checkpoint = StageCheckpoint(
        stage_id=current.stage_id,
        task_id=task.task_id,
        model_used="gemini-3.1-pro",
        handoff_doc_path="",
        files_modified=["scheduler/planner.py", "config/blacklist.yaml"],
        retry_count=1,
        paused_reason="quota_exhausted",
        paused_at="2026-03-28T12:00:00+00:00",
        partial_output="Implemented filtering logic, pending tests...",
        git_diff="--- a/scheduler/planner.py\n+++ b/scheduler/planner.py\n@@ -10 +10 @@\n+    blocked = load_blacklist()",
        git_status=" M scheduler/planner.py\n?? config/blacklist.yaml",
    )

    handoff_path = protocol.write_handoff(task, current, [previous], checkpoint=checkpoint)
    content = handoff_path.read_text(encoding="utf-8")

    # Checkpoint section is present
    assert "Resuming from checkpoint" in content
    assert "gemini-3.1-pro" in content
    assert "quota_exhausted" in content
    # Git diff injected
    assert "load_blacklist()" in content
    assert "scheduler/planner.py" in content
    # Partial output injected
    assert "Implemented filtering logic" in content
    # Resume instructions
    assert "CONTINUE from where it left off" in content
    assert "Do NOT redo work" in content


def test_handoff_without_checkpoint_has_no_resume_section(tmp_path) -> None:
    protocol = HandoffProtocol(tmp_path / "artifacts")
    task = make_task()
    current = make_stage("stage-code", "code", 1)

    handoff_path = protocol.write_handoff(task, current, [], checkpoint=None)
    content = handoff_path.read_text(encoding="utf-8")

    assert "Resuming from checkpoint" not in content
    assert "CONTINUE from where it left off" not in content
