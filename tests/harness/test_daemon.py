import signal

from harness.daemon import DaemonManager
from harness.main import build_parser


class FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


def test_daemon_manager_start_stop_and_status(tmp_path) -> None:
    running = {4321: False}
    launched = {}
    signals = []

    def popen_factory(command, **kwargs):
        launched["command"] = command
        launched["kwargs"] = kwargs
        running[4321] = True
        return FakeProcess(4321)

    def is_process_running(pid: int) -> bool:
        return running.get(pid, False)

    def signal_process(pid: int, sig: int) -> None:
        signals.append((pid, sig))
        running[pid] = False

    manager = DaemonManager(
        pid_file=tmp_path / "orchestra.pid",
        state_file=tmp_path / "orchestra.json",
        log_file=tmp_path / "orchestra.log",
        cwd=tmp_path,
        popen_factory=popen_factory,
        is_process_running=is_process_running,
        signal_process=signal_process,
        sleep_fn=lambda _seconds: None,
    )

    started = manager.start(poll_interval_sec=7)
    stopped = manager.stop(timeout_sec=1.0)

    assert started["running"] is True
    assert started["action"] == "started"
    assert launched["command"][-2:] == ["--poll-interval", "7"]
    assert launched["kwargs"]["start_new_session"] is True
    assert signals == [(4321, signal.SIGTERM)]
    assert stopped["action"] == "stopped"
    assert stopped["graceful"] is True
    assert not (tmp_path / "orchestra.pid").exists()


def test_daemon_status_cleans_stale_pid_file(tmp_path) -> None:
    pid_file = tmp_path / "orchestra.pid"
    state_file = tmp_path / "orchestra.json"
    pid_file.write_text("9999\n", encoding="utf-8")
    state_file.write_text('{"pid": 9999, "command": ["python"]}', encoding="utf-8")

    manager = DaemonManager(
        pid_file=pid_file,
        state_file=state_file,
        log_file=tmp_path / "orchestra.log",
        is_process_running=lambda _pid: False,
    )

    status = manager.status()

    assert status["running"] is False
    assert status["stale_pid"] is True
    assert not pid_file.exists()
    assert not state_file.exists()


def test_parser_supports_daemon_and_dashboard_commands() -> None:
    parser = build_parser()

    dashboard = parser.parse_args(["dashboard", "--recent-events", "5"])
    daemon = parser.parse_args(["daemon", "start", "--poll-interval", "3"])

    assert dashboard.command == "dashboard"
    assert dashboard.recent_events == 5
    assert daemon.command == "daemon"
    assert daemon.daemon_command == "start"
    assert daemon.poll_interval == 3
