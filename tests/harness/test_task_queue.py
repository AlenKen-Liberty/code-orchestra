from harness.db import HarnessDB
from harness.models import PlannedStage, TaskStatus
from harness.task_queue import TaskQueue


def test_task_queue_creates_and_orders_tasks(tmp_path) -> None:
    queue = TaskQueue(HarnessDB(tmp_path / "harness.db"))

    low = queue.create_task("low", "low priority task", priority=10, status=TaskStatus.PENDING)
    high = queue.create_task("high", "high priority task", priority=90, status=TaskStatus.EXECUTING)
    queue.save_stages(high.task_id, [PlannedStage(stage_type="code", stage_order=1, model_role="coder")])
    queue.save_stages(low.task_id, [PlannedStage(stage_type="code", stage_order=1, model_role="coder")])

    picked = queue.pick_next_runnable_task()

    assert picked is not None
    assert picked.task_id == high.task_id
    assert queue.next_pending_stage(high.task_id).stage_type == "code"


def test_task_queue_updates_stage_lifecycle(tmp_path) -> None:
    queue = TaskQueue(HarnessDB(tmp_path / "harness.db"))
    task = queue.create_task("task", "desc", status=TaskStatus.EXECUTING)
    [stage] = queue.save_stages(
        task.task_id,
        [
            PlannedStage(
                stage_type="code",
                stage_order=1,
                model_role="coder",
                verify_cmd="pytest tests/test_feature.py",
            )
        ],
    )

    queue.assign_stage_model(
        stage.stage_id,
        "gpt-5.4-codex",
        "codex",
        account_email="codex-2@test",
        reason="use-it-or-lose-it",
    )
    queue.mark_stage_running(stage.stage_id, "/tmp/handoff.md")
    queue.complete_stage(stage.stage_id, result_summary="Implemented feature.", token_used=123, duration_sec=4.5)

    loaded = queue.get_stage(stage.stage_id)
    assert loaded is not None
    assert loaded.assigned_model == "gpt-5.4-codex"
    assert loaded.handoff_doc_path == "/tmp/handoff.md"
    assert loaded.result_summary == "Implemented feature."
    assert loaded.token_used == 123
    assert loaded.duration_sec == 4.5
    assert loaded.metadata["selected_account_email"] == "codex-2@test"
    assert loaded.metadata["selection_reason"] == "use-it-or-lose-it"
