"""SQLite-backed task and stage queue."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from harness.db import HarnessDB
from harness.models import (
    PermissionRequestRecord,
    PlannedStage,
    QuotaEventRecord,
    RiskLevel,
    StageRecord,
    StageStatus,
    TaskRecord,
    TaskStatus,
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class TaskQueue:
    """CRUD layer for tasks, stages, and audit tables."""

    def __init__(self, db: HarnessDB) -> None:
        self.db = db

    def create_task(
        self,
        title: str,
        description: str,
        *,
        goal: Optional[str] = None,
        verify_cmd: Optional[str] = None,
        complexity: str = "medium",
        priority: int = 50,
        status: TaskStatus = TaskStatus.PENDING,
        working_dir: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> TaskRecord:
        now = utcnow_iso()
        record = TaskRecord(
            task_id=task_id or uuid.uuid4().hex,
            title=title,
            description=description,
            goal=goal,
            verify_cmd=verify_cmd,
            complexity=complexity,
            priority=priority,
            status=status,
            working_dir=working_dir,
            created_at=now,
            updated_at=now,
        )
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, title, description, goal, verify_cmd, complexity,
                    priority, status, working_dir, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_id,
                    record.title,
                    record.description,
                    record.goal,
                    record.verify_cmd,
                    record.complexity,
                    record.priority,
                    record.status.value,
                    record.working_dir,
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[TaskRecord]:
        query = "SELECT * FROM tasks"
        params: tuple[object, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += " ORDER BY priority DESC, created_at ASC"
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_task(row) for row in rows]

    def pick_next_runnable_task(self) -> Optional[TaskRecord]:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status IN (?, ?, ?)
                ORDER BY
                    CASE status
                        WHEN ? THEN 0
                        WHEN ? THEN 1
                        ELSE 2
                    END,
                    priority DESC,
                    created_at ASC
                LIMIT 1
                """,
                (
                    TaskStatus.EXECUTING.value,
                    TaskStatus.PENDING.value,
                    TaskStatus.PLANNING.value,
                    TaskStatus.EXECUTING.value,
                    TaskStatus.PENDING.value,
                ),
            ).fetchone()
        return self._row_to_task(row) if row else None

    def update_task_status(self, task_id: str, status: TaskStatus) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status.value, utcnow_iso(), task_id),
            )

    def update_task_working_dir(self, task_id: str, working_dir: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE tasks SET working_dir = ?, updated_at = ? WHERE task_id = ?",
                (working_dir, utcnow_iso(), task_id),
            )

    def save_stages(self, task_id: str, stages: Iterable[PlannedStage]) -> list[StageRecord]:
        now = utcnow_iso()
        records: list[StageRecord] = []
        with self.db.connect() as conn:
            for planned in stages:
                record = StageRecord(
                    stage_id=uuid.uuid4().hex,
                    task_id=task_id,
                    stage_type=planned.stage_type,
                    stage_order=planned.stage_order,
                    model_role=planned.model_role,
                    assigned_model=planned.assigned_model,
                    assigned_provider=planned.assigned_provider,
                    status=StageStatus.PENDING,
                    handoff_doc_path=None,
                    result_summary=None,
                    token_used=0,
                    duration_sec=0.0,
                    started_at=None,
                    finished_at=None,
                    retry_count=0,
                    verify_cmd=planned.verify_cmd,
                    metadata=dict(planned.metadata),
                )
                conn.execute(
                    """
                    INSERT INTO stages (
                        stage_id, task_id, stage_type, stage_order, model_role,
                        assigned_model, assigned_provider, status, handoff_doc_path,
                        result_summary, token_used, duration_sec, started_at,
                        finished_at, retry_count, verify_cmd, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.stage_id,
                        record.task_id,
                        record.stage_type,
                        record.stage_order,
                        record.model_role,
                        record.assigned_model,
                        record.assigned_provider,
                        record.status.value,
                        record.handoff_doc_path,
                        record.result_summary,
                        record.token_used,
                        record.duration_sec,
                        record.started_at,
                        record.finished_at,
                        record.retry_count,
                        record.verify_cmd,
                        json.dumps(record.metadata),
                    ),
                )
                records.append(record)
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                (now, task_id),
            )
        return records

    def count_stages(self, task_id: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM stages WHERE task_id = ?", (task_id,)).fetchone()
        return int(row["count"])

    def get_stage(self, stage_id: str) -> Optional[StageRecord]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM stages WHERE stage_id = ?", (stage_id,)).fetchone()
        return self._row_to_stage(row) if row else None

    def list_stages(self, task_id: str) -> list[StageRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM stages WHERE task_id = ? ORDER BY stage_order ASC",
                (task_id,),
            ).fetchall()
        return [self._row_to_stage(row) for row in rows]

    def list_completed_stages(self, task_id: str) -> list[StageRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM stages
                WHERE task_id = ? AND status IN (?, ?)
                ORDER BY stage_order ASC
                """,
                (task_id, StageStatus.DONE.value, StageStatus.SKIPPED.value),
            ).fetchall()
        return [self._row_to_stage(row) for row in rows]

    def next_pending_stage(self, task_id: str) -> Optional[StageRecord]:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM stages
                WHERE task_id = ? AND status = ?
                ORDER BY stage_order ASC
                LIMIT 1
                """,
                (task_id, StageStatus.PENDING.value),
            ).fetchone()
        return self._row_to_stage(row) if row else None

    def assign_stage_model(
        self,
        stage_id: str,
        model: str,
        provider: str,
        *,
        account_email: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        metadata = self._load_stage_metadata(stage_id)
        metadata["selected_account_email"] = account_email
        if reason:
            metadata["selection_reason"] = reason
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE stages
                SET assigned_model = ?, assigned_provider = ?, metadata = ?
                WHERE stage_id = ?
                """,
                (model, provider, json.dumps(metadata), stage_id),
            )

    def update_stage_metadata(self, stage_id: str, metadata_patch: dict[str, Any]) -> None:
        metadata = self._load_stage_metadata(stage_id)
        metadata.update(metadata_patch)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE stages SET metadata = ? WHERE stage_id = ?",
                (json.dumps(metadata), stage_id),
            )

    def mark_stage_running(self, stage_id: str, handoff_doc_path: str) -> None:
        now = utcnow_iso()
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE stages
                SET status = ?, handoff_doc_path = ?, started_at = ?
                WHERE stage_id = ?
                """,
                (StageStatus.RUNNING.value, handoff_doc_path, now, stage_id),
            )

    def complete_stage(
        self,
        stage_id: str,
        *,
        result_summary: Optional[str] = None,
        token_used: int = 0,
        duration_sec: float = 0.0,
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE stages
                SET status = ?, result_summary = ?, token_used = ?, duration_sec = ?,
                    finished_at = ?
                WHERE stage_id = ?
                """,
                (
                    StageStatus.DONE.value,
                    result_summary,
                    token_used,
                    duration_sec,
                    utcnow_iso(),
                    stage_id,
                ),
            )

    def skip_stage(self, stage_id: str, *, result_summary: Optional[str] = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE stages
                SET status = ?, result_summary = ?, finished_at = ?
                WHERE stage_id = ?
                """,
                (StageStatus.SKIPPED.value, result_summary, utcnow_iso(), stage_id),
            )

    def reset_stage_to_pending(
        self, stage_id: str, *, retry_count: Optional[int] = None, clear_model: bool = True
    ) -> None:
        query = "UPDATE stages SET status = ?, started_at = NULL"
        params: list[object] = [StageStatus.PENDING.value]
        if clear_model:
            query += ", assigned_model = NULL, assigned_provider = NULL"
        if retry_count is not None:
            query += ", retry_count = ?"
            params.append(retry_count)
        query += " WHERE stage_id = ?"
        params.append(stage_id)
        with self.db.connect() as conn:
            conn.execute(query, tuple(params))

    def fail_stage(self, stage_id: str, *, result_summary: Optional[str], retry_count: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE stages
                SET status = ?, result_summary = ?, retry_count = ?, finished_at = ?
                WHERE stage_id = ?
                """,
                (
                    StageStatus.FAILED.value,
                    result_summary,
                    retry_count,
                    utcnow_iso(),
                    stage_id,
                ),
            )

    def log_permission_request(self, record: PermissionRequestRecord) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO permission_requests (
                    request_id, stage_id, action, context, risk_level,
                    decision, voters, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.request_id,
                    record.stage_id,
                    record.action,
                    record.context,
                    record.risk_level.value,
                    record.decision,
                    json.dumps(record.voters),
                    record.decided_at,
                ),
            )

    def list_permission_requests(self, stage_id: Optional[str] = None) -> list[PermissionRequestRecord]:
        query = "SELECT * FROM permission_requests"
        params: tuple[object, ...] = ()
        if stage_id is not None:
            query += " WHERE stage_id = ?"
            params = (stage_id,)
        query += " ORDER BY decided_at ASC, request_id ASC"
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        records: list[PermissionRequestRecord] = []
        for row in rows:
            records.append(
                PermissionRequestRecord(
                    request_id=row["request_id"],
                    stage_id=row["stage_id"],
                    action=row["action"],
                    context=row["context"],
                    risk_level=RiskLevel(row["risk_level"]),
                    decision=row["decision"],
                    voters=json.loads(row["voters"] or "[]"),
                    decided_at=row["decided_at"],
                )
            )
        return records

    def log_quota_event(self, record: QuotaEventRecord) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO quota_events (
                    event_id, provider, account_email, event_type, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.provider,
                    record.account_email,
                    record.event_type,
                    json.dumps(record.details),
                    record.created_at,
                ),
            )

    def list_quota_events(self, provider: Optional[str] = None) -> list[QuotaEventRecord]:
        query = "SELECT * FROM quota_events"
        params: tuple[object, ...] = ()
        if provider is not None:
            query += " WHERE provider = ?"
            params = (provider,)
        query += " ORDER BY created_at ASC, event_id ASC"
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        records: list[QuotaEventRecord] = []
        for row in rows:
            records.append(
                QuotaEventRecord(
                    event_id=row["event_id"],
                    provider=row["provider"],
                    account_email=row["account_email"],
                    event_type=row["event_type"],
                    details=json.loads(row["details"] or "{}"),
                    created_at=row["created_at"],
                )
            )
        return records

    def _row_to_task(self, row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            title=row["title"],
            description=row["description"],
            goal=row["goal"],
            verify_cmd=row["verify_cmd"],
            complexity=row["complexity"],
            priority=row["priority"],
            status=TaskStatus(row["status"]),
            working_dir=row["working_dir"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_stage(self, row) -> StageRecord:
        metadata = row["metadata"]
        parsed_metadata = json.loads(metadata) if metadata else {}
        return StageRecord(
            stage_id=row["stage_id"],
            task_id=row["task_id"],
            stage_type=row["stage_type"],
            stage_order=row["stage_order"],
            model_role=row["model_role"],
            assigned_model=row["assigned_model"],
            assigned_provider=row["assigned_provider"],
            status=StageStatus(row["status"]),
            handoff_doc_path=row["handoff_doc_path"],
            result_summary=row["result_summary"],
            token_used=row["token_used"],
            duration_sec=row["duration_sec"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            retry_count=row["retry_count"],
            verify_cmd=row["verify_cmd"],
            metadata=parsed_metadata,
        )

    def _load_stage_metadata(self, stage_id: str) -> dict[str, Any]:
        stage = self.get_stage(stage_id)
        if stage is None:
            return {}
        return dict(stage.metadata)
