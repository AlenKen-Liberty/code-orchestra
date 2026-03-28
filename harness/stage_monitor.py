import asyncio
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class StageProgressSnapshot:
    status: str  # "active" | "stalled" | "completed" | "error"
    files_changed_since_start: int
    latest_file_activity: str
    duration_sec: float
    is_overtime: bool
    summary: str


class StageMonitor:
    def __init__(self, working_dir: str, expected_duration_sec: float, pid: int | None = None) -> None:
        self.working_dir = Path(working_dir)
        self.expected_duration_sec = expected_duration_sec
        self.pid = pid
        self.start_time = time.time()
        self.last_activity_time = self.start_time
        
        # Capture initial state
        self._initial_files = self._get_tracked_files()
        self._initial_mtimes = {f: self._get_mtime(f) for f in self._initial_files}

    def _get_tracked_files(self) -> set[Path]:
        try:
            # Files modified or untracked
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.working_dir, capture_output=True, text=True, check=False
            )
            files = set()
            for line in status.stdout.splitlines():
                if len(line) > 3:
                    file_path = self.working_dir / line[3:].strip()
                    files.add(file_path)
            return files
        except OSError:
            return set()

    def _get_mtime(self, file_path: Path) -> float:
        try:
            return file_path.stat().st_mtime
        except OSError:
            return 0.0

    def check_progress(self, stall_timeout_sec: float) -> StageProgressSnapshot:
        current_time = time.time()
        duration_sec = current_time - self.start_time
        is_overtime = duration_sec > self.expected_duration_sec
        
        # Check process liveness if pid is available
        status = "active"
        if self.pid is not None:
            try:
                # Send signal 0 to check if process exists
                os.kill(self.pid, 0)
            except ProcessLookupError:
                status = "completed"  # Or error, but we don't know exit code here
        
        # Check files
        current_files = self._get_tracked_files()
        changed_count = 0
        latest_mtime = self.start_time
        
        # Look at both previously tracked files and newly tracked ones
        all_files_to_check = current_files.union(self._initial_files)
        
        for f in all_files_to_check:
            mtime = self._get_mtime(f)
            if mtime == 0.0:
                continue # File deleted or not accessible
                
            if f not in self._initial_mtimes or mtime > self._initial_mtimes[f]:
                changed_count += 1
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    
        # Stalled check
        if latest_mtime > self.last_activity_time:
            self.last_activity_time = latest_mtime
            
        time_since_activity = current_time - self.last_activity_time
        if status == "active" and time_since_activity > stall_timeout_sec:
            status = "stalled"
            
        # Format latest activity
        activity_sec = int(current_time - self.last_activity_time)
        latest_file_activity = f"{activity_sec}s ago"
        
        # Build summary
        summary = f"{changed_count} files changed"
        if status == "stalled":
            summary += f" (no activity for {activity_sec}s)"
            
        return StageProgressSnapshot(
            status=status,
            files_changed_since_start=changed_count,
            latest_file_activity=latest_file_activity,
            duration_sec=duration_sec,
            is_overtime=is_overtime,
            summary=summary,
        )
