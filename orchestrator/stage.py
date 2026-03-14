"""Data models for pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class ModelType(str, Enum):
    """Supported model types."""
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    GEMINI = "gemini"


@dataclass
class StageInput:
    """Represents an input source for a stage."""
    source: str  # e.g., "planning.architecture_plan" or "user_task"
    key: Optional[str] = None  # Optional key to rename the input

    def get_variable_name(self) -> str:
        """Get the variable name to use in prompt template."""
        return self.key if self.key else self.source.split(".")[-1]


@dataclass
class StageDefinition:
    """Defines a single stage in the pipeline."""
    stage_id: str
    name: str
    model: str
    model_type: ModelType
    description: str
    prompt_template: str
    output_key: str

    input: list[StageInput] = field(default_factory=list)
    save_artifact: bool = False
    multi_turn: bool = False
    max_rounds: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> StageDefinition:
        """Create from dictionary (parsed YAML)."""
        # Parse input (can be string or list of dicts)
        input_data = data.get("input", {})
        stage_inputs = []

        if isinstance(input_data, str):
            stage_inputs = [StageInput(source=input_data)]
        elif isinstance(input_data, dict):
            if "source" in input_data:
                stage_inputs = [StageInput(
                    source=input_data["source"],
                    key=input_data.get("key")
                )]
        elif isinstance(input_data, list):
            for item in input_data:
                if isinstance(item, dict):
                    stage_inputs.append(StageInput(
                        source=item["source"],
                        key=item.get("key")
                    ))

        model_type_str = data.get("model_type", "claude_code")
        try:
            model_type = ModelType(model_type_str)
        except ValueError:
            model_type = ModelType.CLAUDE_CODE

        return cls(
            stage_id=data["stage_id"],
            name=data["name"],
            model=data["model"],
            model_type=model_type,
            description=data["description"],
            prompt_template=data["prompt_template"],
            output_key=data["output_key"],
            input=stage_inputs,
            save_artifact=data.get("save_artifact", False),
            multi_turn=data.get("multi_turn", False),
            max_rounds=data.get("max_rounds"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class StageResult:
    """Result of executing a stage."""
    stage_id: str
    status: str  # "success" or "failed"
    output: Optional[str] = None
    error: Optional[str] = None
    raw_output: Optional[str] = None
    execution_time: float = 0.0
    model_used: Optional[str] = None
    rounds: int = 1  # For multi-turn stages

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage_id": self.stage_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "raw_output": self.raw_output,
            "execution_time": self.execution_time,
            "model_used": self.model_used,
            "rounds": self.rounds,
        }
