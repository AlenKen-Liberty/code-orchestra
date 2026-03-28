import os
import time
from unittest.mock import MagicMock, patch

from harness.stage_monitor import StageMonitor

def test_stage_monitor_progress(tmp_path):
    # Setup mock git status output
    mock_git_output = " M file1.py\n?? new_file.py"
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = mock_git_output
        mock_run.return_value.returncode = 0
        
        monitor = StageMonitor(
            working_dir=str(tmp_path),
            expected_duration_sec=300.0,
        )
        
        # Test basic active status
        snapshot = monitor.check_progress(stall_timeout_sec=300.0)
        assert snapshot.status == "active"
        assert snapshot.duration_sec >= 0
        assert not snapshot.is_overtime

def test_stage_monitor_stall_detection(tmp_path):
    monitor = StageMonitor(
        working_dir=str(tmp_path),
        expected_duration_sec=300.0,
    )
    
    # Fast forward time to trigger stall
    monitor.start_time = time.time() - 400
    monitor.last_activity_time = time.time() - 400
    
    snapshot = monitor.check_progress(stall_timeout_sec=300.0)
    assert snapshot.status == "stalled"
    assert snapshot.is_overtime is True

def test_stage_monitor_process_liveness(tmp_path):
    monitor = StageMonitor(
        working_dir=str(tmp_path),
        expected_duration_sec=300.0,
        pid=999999999, # likely non-existent pid
    )
    
    # Process lookup error expected to set status to completed
    snapshot = monitor.check_progress(stall_timeout_sec=300.0)
    assert snapshot.status == "completed"
