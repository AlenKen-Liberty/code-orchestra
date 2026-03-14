from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time
import uuid


class RunStatus(str, Enum):
    CREATED = "created"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING = "awaiting"


@dataclass
class MessagePart:
    content_type: str = "text/plain"
    content: Optional[str] = None
    content_url: Optional[str] = None
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "content_type": self.content_type,
            "content": self.content,
            "content_url": self.content_url,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessagePart":
        return cls(
            content_type=data.get("content_type", "text/plain"),
            content=data.get("content"),
            content_url=data.get("content_url"),
            metadata=data.get("metadata"),
        )


@dataclass
class Message:
    role: str
    parts: list[MessagePart] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(
            part.content
            for part in self.parts
            if part.content is not None and part.content_type == "text/plain"
        )

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "parts": [part.to_dict() for part in self.parts],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        parts_data = data.get("parts", [])
        return cls(
            role=data.get("role", ""),
            parts=[MessagePart.from_dict(p) for p in parts_data],
        )


@dataclass
class Run:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_name: str = ""
    session_id: Optional[str] = None
    status: RunStatus = RunStatus.CREATED
    input_messages: list[Message] = field(default_factory=list)
    output_messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "session_id": self.session_id,
            "status": self.status.value,
            "input_messages": [m.to_dict() for m in self.input_messages],
            "output_messages": [m.to_dict() for m in self.output_messages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Run":
        status_value = data.get("status", RunStatus.CREATED.value)
        try:
            status = RunStatus(status_value)
        except ValueError:
            status = RunStatus.CREATED
        return cls(
            run_id=data.get("run_id", uuid.uuid4().hex[:12]),
            agent_name=data.get("agent_name", ""),
            session_id=data.get("session_id"),
            status=status,
            input_messages=[Message.from_dict(m) for m in data.get("input_messages", [])],
            output_messages=[Message.from_dict(m) for m in data.get("output_messages", [])],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            error=data.get("error"),
        )


@dataclass
class AgentManifest:
    name: str
    description: str
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentManifest":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            metadata=data.get("metadata"),
        )


@dataclass
class Session:
    session_id: str
    history: list[Message] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "history": [m.to_dict() for m in self.history],
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            session_id=data.get("session_id", uuid.uuid4().hex[:12]),
            history=[Message.from_dict(m) for m in data.get("history", [])],
            state=data.get("state", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class ReviewResult:
    verdict: str
    comments: str


@dataclass
class WorkflowResult:
    plan: Optional[str] = None
    code: Optional[str] = None
    reviews: list[ReviewResult] = field(default_factory=list)
    final_code: Optional[str] = None
    status: str = "ok"
    error: Optional[str] = None
