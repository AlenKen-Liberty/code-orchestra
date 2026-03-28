"""Core data structures for the autonomous harness."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    PAUSED_QUOTA = "paused_quota"
    PAUSED_PERMISSION = "paused_permission"
    DONE = "done"
    FAILED = "failed"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class RiskLevel(str, Enum):
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


@dataclass(slots=True)
class PlannedStage:
    stage_type: str
    stage_order: int
    model_role: str
    assigned_model: Optional[str] = None
    assigned_provider: Optional[str] = None
    verify_cmd: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    title: str
    description: str
    goal: Optional[str]
    verify_cmd: Optional[str]
    complexity: str
    priority: int
    status: TaskStatus
    working_dir: Optional[str]
    created_at: str
    updated_at: str


@dataclass(slots=True)
class StageRecord:
    stage_id: str
    task_id: str
    stage_type: str
    stage_order: int
    model_role: str
    assigned_model: Optional[str]
    assigned_provider: Optional[str]
    status: StageStatus
    handoff_doc_path: Optional[str]
    result_summary: Optional[str]
    token_used: int
    duration_sec: float
    started_at: Optional[str]
    finished_at: Optional[str]
    retry_count: int = 0
    verify_cmd: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PermissionRequestRecord:
    request_id: str
    stage_id: str
    action: str
    context: Optional[str]
    risk_level: RiskLevel
    decision: Optional[str]
    voters: list[dict[str, Any]] = field(default_factory=list)
    decided_at: Optional[str] = None


@dataclass(slots=True)
class QuotaEventRecord:
    event_id: str
    provider: str
    account_email: Optional[str]
    event_type: str
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class IntakeResult:
    title: str
    description: str
    complexity: str
    stages: list[PlannedStage]
    goal: Optional[str] = None
    verify_cmd: Optional[str] = None
    questions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ClarificationQuestion:
    key: str
    prompt: str
    default: Optional[str] = None
    required: bool = False


@dataclass(slots=True)
class ModelChoice:
    model: str
    provider: str
    account_email: Optional[str] = None
    reason: str = ""


@dataclass(slots=True)
class PermissionDecision:
    risk_level: RiskLevel
    decision: str
    reason: str
    requires_voting: bool = False
    requires_user: bool = False
    votes: list["ModelVote"] = field(default_factory=list)


@dataclass(slots=True)
class StageExecutionResult:
    stage_id: str
    status: StageStatus
    raw_output: str = ""
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_sec: float = 0.0
    token_used: int = 0


@dataclass(slots=True)
class StageCheckpoint:
    stage_id: str
    task_id: str
    model_used: str
    handoff_doc_path: str
    files_modified: list[str] = field(default_factory=list)
    retry_count: int = 0
    paused_reason: str = "quota_exhausted"
    paused_at: str = ""
    partial_output: str = ""


@dataclass(slots=True)
class ModelVote:
    model: str
    vote: str
    reason: str


@dataclass(slots=True)
class VoteResult:
    decision: Optional[str]
    votes: list[ModelVote] = field(default_factory=list)
    unanimous: bool = False
    needs_escalation: bool = False
