"""Background worker lifecycle management for the harness."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from config import settings
from harness.task_queue import utcnow_iso


class DaemonManager:
    """Manage a detached harness worker process with PID and state files."""

    def __init__(
        self,
        *,
        pid_file: str | Path = settings.HARNESS_DAEMON_PID_FILE,
        state_file: str | Path = settings.HARNESS_DAEMON_STATE_PATH,
        log_file: str | Path = settings.HARNESS_DAEMON_LOG_PATH,
        cwd: str | Path | None = None,
        worker_command_builder: Optional[Callable[[int], list[str]]] = None,
        popen_factory: Optional[Callable[..., Any]] = None,
        is_process_running: Optional[Callable[[int], bool]] = None,
        signal_process: Optional[Callable[[int, int], None]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        monotonic_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.pid_file = Path(pid_file)
        self.state_file = Path(state_file)
        self.log_file = Path(log_file)
        self.cwd = Path(cwd) if cwd is not None else Path.cwd()
        self.worker_command_builder = worker_command_builder or self._default_worker_command
        self.popen_factory = popen_factory or subprocess.Popen
        self._is_process_running = is_process_running or self._default_is_process_running
        self._signal_process = signal_process or os.kill
        self._sleep_fn = sleep_fn or time.sleep
        self._monotonic_fn = monotonic_fn or time.monotonic

    def start(self, *, poll_interval_sec: int = settings.HARNESS_POLL_INTERVAL_SEC) -> dict[str, Any]:
        current = self.status()
        if current["running"]:
            current["action"] = "already_running"
            return current

        self._ensure_runtime_dir()
        command = self.worker_command_builder(poll_interval_sec)
        log_handle = self.log_file.open("a", encoding="utf-8")
        try:
            process = self.popen_factory(
                command,
                cwd=str(self.cwd),
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            log_handle.close()

        self.pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
        self.state_file.write_text(
            json.dumps(
                {
                    "pid": process.pid,
                    "command": command,
                    "log_file": str(self.log_file),
                    "cwd": str(self.cwd),
                    "started_at": utcnow_iso(),
                    "poll_interval_sec": poll_interval_sec,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        status = self.status()
        status["action"] = "started"
        return status

    def stop(self, *, timeout_sec: float = settings.HARNESS_DAEMON_STOP_TIMEOUT_SEC) -> dict[str, Any]:
        current = self.status()
        pid = current.get("pid")
        if not current["running"] or not isinstance(pid, int):
            current["action"] = "not_running"
            return current

        self._signal_process(pid, signal.SIGTERM)
        deadline = self._monotonic_fn() + max(timeout_sec, 0.0)
        while self._monotonic_fn() < deadline:
            if not self._is_process_running(pid):
                self._clear_runtime_files()
                return {
                    **self._state_payload(),
                    "running": False,
                    "pid": None,
                    "stale_pid": False,
                    "action": "stopped",
                    "graceful": True,
                }
            self._sleep_fn(0.05)

        timed_out = self.status()
        timed_out["action"] = "stop_timeout"
        timed_out["graceful"] = False
        return timed_out

    def status(self) -> dict[str, Any]:
        payload = self._state_payload()
        pid = self._read_pid()
        payload["pid"] = pid
        if pid is None:
            payload["running"] = False
            payload["stale_pid"] = False
            return payload

        if self._is_process_running(pid):
            payload["running"] = True
            payload["stale_pid"] = False
            return payload

        self._clear_runtime_files()
        payload["running"] = False
        payload["stale_pid"] = True
        return payload

    def _state_payload(self) -> dict[str, Any]:
        state = self._read_state()
        return {
            "pid_file": str(self.pid_file),
            "state_file": str(self.state_file),
            "log_file": str(self.log_file),
            "cwd": state.get("cwd") or str(self.cwd),
            "command": state.get("command") or [],
            "started_at": state.get("started_at"),
            "poll_interval_sec": state.get("poll_interval_sec"),
        }

    def _ensure_runtime_dir(self) -> None:
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _clear_runtime_files(self) -> None:
        for path in (self.pid_file, self.state_file):
            if path.exists():
                path.unlink()

    def _read_pid(self) -> int | None:
        if not self.pid_file.exists():
            return None
        try:
            return int(self.pid_file.read_text(encoding="utf-8").strip())
        except (TypeError, ValueError):
            self._clear_runtime_files()
            return None

    def _read_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _default_worker_command(self, poll_interval_sec: int) -> list[str]:
        return [
            sys.executable,
            "-m",
            "harness.main",
            "_worker",
            "--poll-interval",
            str(poll_interval_sec),
        ]

    def _default_is_process_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
