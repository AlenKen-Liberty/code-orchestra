"""Autonomous harness package."""

from harness.checkpoint import CheckpointStore
from harness.db import HarnessDB
from harness.handoff import HandoffProtocol
from harness.intake import IntakeAgent
from harness.models import (
    ClarificationQuestion,
    IntakeResult,
    ModelChoice,
    PermissionDecision,
    PlannedStage,
    StageCheckpoint,
    StageExecutionResult,
    StageRecord,
    StageStatus,
    TaskRecord,
    TaskStatus,
)
from harness.permission_gate import PermissionGate
from harness.task_queue import TaskQueue

__all__ = [
    "CheckpointStore",
    "ClarificationQuestion",
    "HarnessDB",
    "HandoffProtocol",
    "IntakeAgent",
    "IntakeResult",
    "ModelChoice",
    "PermissionDecision",
    "PermissionGate",
    "PlannedStage",
    "StageCheckpoint",
    "StageExecutionResult",
    "StageRecord",
    "StageStatus",
    "TaskQueue",
    "TaskRecord",
    "TaskStatus",
]
