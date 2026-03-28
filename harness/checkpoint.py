"""Checkpoint persistence for paused stages."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from harness.models import StageCheckpoint


class CheckpointStore:
    """Store paused stage state as JSON files alongside artifacts."""

    def __init__(self, artifact_root: str | Path = "artifacts") -> None:
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def _checkpoint_dir(self, task_id: str) -> Path:
        path = self.artifact_root / task_id / "checkpoints"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _checkpoint_path(self, task_id: str, stage_id: str) -> Path:
        return self._checkpoint_dir(task_id) / f"{stage_id}.json"

    def save(self, checkpoint: StageCheckpoint) -> Path:
        path = self._checkpoint_path(checkpoint.task_id, checkpoint.stage_id)
        path.write_text(json.dumps(asdict(checkpoint), indent=2), encoding="utf-8")
        return path

    def load(self, task_id: str, stage_id: str) -> StageCheckpoint | None:
        path = self._checkpoint_path(task_id, stage_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return StageCheckpoint(**data)

    def delete(self, task_id: str, stage_id: str) -> None:
        path = self._checkpoint_path(task_id, stage_id)
        if path.exists():
            path.unlink()

    def list_for_task(self, task_id: str) -> list[StageCheckpoint]:
        directory = self._checkpoint_dir(task_id)
        checkpoints: list[StageCheckpoint] = []
        for path in sorted(directory.glob("*.json")):
            checkpoints.append(StageCheckpoint(**json.loads(path.read_text(encoding="utf-8"))))
        return checkpoints
