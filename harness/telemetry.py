"""Structured JSONL telemetry for harness stage activity."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from config import settings
from harness.task_queue import utcnow_iso

ERROR_EVENTS = {
    "stage_failed",
    "stage_paused_permission",
    "stage_paused_quota",
    "stage_retry",
}


class HarnessTelemetry:
    """Append-only JSONL event log plus lightweight aggregate summaries."""

    def __init__(self, path: str | Path = settings.HARNESS_EVENT_LOG_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, **payload: Any) -> dict[str, Any]:
        record = {"timestamp": utcnow_iso(), "event": event_type, **payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return record

    def read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
        return events

    def tail(self, limit: int = settings.HARNESS_DASHBOARD_RECENT_EVENTS) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        events = self.read_events()
        return events[-limit:]

    def summarize(self, *, recent_limit: int = settings.HARNESS_DASHBOARD_RECENT_EVENTS) -> dict[str, Any]:
        events = self.read_events()
        attempts: Counter[str] = Counter()
        successes: Counter[str] = Counter()
        errors: Counter[str] = Counter()
        token_totals: defaultdict[str, int] = defaultdict(int)
        duration_totals: defaultdict[str, float] = defaultdict(float)

        for event in events:
            stage_type = str(event.get("stage_type") or "")
            if not stage_type:
                continue
            kind = str(event.get("event") or "")
            if kind == "stage_started":
                attempts[stage_type] += 1
            elif kind == "stage_succeeded":
                successes[stage_type] += 1
                token_totals[stage_type] += int(event.get("token_used") or 0)
                duration_totals[stage_type] += float(event.get("duration_sec") or 0.0)
            elif kind in ERROR_EVENTS:
                errors[stage_type] += 1

        stage_types = sorted(set(attempts) | set(successes) | set(errors))
        by_stage_type: list[dict[str, Any]] = []
        for stage_type in stage_types:
            attempt_count = attempts[stage_type]
            success_count = successes[stage_type]
            error_count = errors[stage_type]
            total_duration = duration_totals[stage_type]
            by_stage_type.append(
                {
                    "stage_type": stage_type,
                    "attempts": attempt_count,
                    "successes": success_count,
                    "errors": error_count,
                    "error_rate": round(error_count / attempt_count, 3) if attempt_count else 0.0,
                    "total_token_used": token_totals[stage_type],
                    "total_duration_sec": round(total_duration, 3),
                    "avg_duration_sec": round(total_duration / success_count, 3) if success_count else 0.0,
                }
            )

        total_attempts = sum(attempts.values())
        total_errors = sum(errors.values())
        total_duration_sec = round(sum(duration_totals.values()), 3)
        total_token_used = sum(token_totals.values())

        return {
            "path": str(self.path),
            "total_events": len(events),
            "overall": {
                "attempts": total_attempts,
                "successes": sum(successes.values()),
                "errors": total_errors,
                "error_rate": round(total_errors / total_attempts, 3) if total_attempts else 0.0,
                "total_token_used": total_token_used,
                "total_duration_sec": total_duration_sec,
                "avg_duration_sec": round(total_duration_sec / sum(successes.values()), 3)
                if sum(successes.values())
                else 0.0,
            },
            "by_stage_type": by_stage_type,
            "recent_events": events[-recent_limit:] if recent_limit > 0 else [],
        }
