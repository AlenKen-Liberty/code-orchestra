import os
from pathlib import Path


def _get_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _get_env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


CLAUDE_PORT = _get_env_int("CLAUDE_PORT", 8001)
CODEX_PORT = _get_env_int("CODEX_PORT", 8002)
GEMINI_PORT = _get_env_int("GEMINI_PORT", 8003)
ORCHESTRATOR_PORT = _get_env_int("ORCHESTRATOR_PORT", 8000)

CLAUDE_BASE_URL = _get_env("CLAUDE_BASE_URL", "http://localhost:8001")
CODEX_BASE_URL = _get_env("CODEX_BASE_URL", "http://localhost:8002")
GEMINI_BASE_URL = _get_env("GEMINI_BASE_URL", "http://localhost:8003")

CLI_TIMEOUT = _get_env_float("CLI_TIMEOUT", 300.0)
HTTP_TIMEOUT = _get_env_float("HTTP_TIMEOUT", 350.0)

MAX_REVIEW_ROUNDS = _get_env_int("MAX_REVIEW_ROUNDS", 3)
MAX_RETRIES = _get_env_int("MAX_RETRIES", 2)
RETRY_BACKOFF = _get_env_float("RETRY_BACKOFF", 1.0)

# How many times to retry the *same* model on a quota/rate-limit error
# before clearing the assignment and falling back to another model.
QUOTA_SAME_MODEL_RETRIES = _get_env_int("QUOTA_SAME_MODEL_RETRIES", 3)
QUOTA_RETRY_BACKOFF_SEC = _get_env_float("QUOTA_RETRY_BACKOFF_SEC", 15.0)

LOG_LEVEL = _get_env("LOG_LEVEL", "INFO")

SESSION_PERSIST_TO_DISK = _get_env_bool("SESSION_PERSIST_TO_DISK", False)
SESSION_DATA_DIR = _get_env("SESSION_DATA_DIR", "./data/sessions")

CLAUDE_PLANNER_MODEL = _get_env("CLAUDE_PLANNER_MODEL", "claude-opus-4-6")
CLAUDE_REVIEWER_MODEL = _get_env("CLAUDE_REVIEWER_MODEL", "claude-haiku-4-5")

CODEX_MODEL = _get_env("CODEX_MODEL", "gpt-5.2-codex")
CODEX_TIER = _get_env("CODEX_TIER", "xhigh")

GEMINI_MODEL = _get_env("GEMINI_MODEL", "gemini-3.1-pro-preview")

_REPO_ROOT = Path(__file__).resolve().parent.parent

CHAT2API_BASE_URL = _get_env("CHAT2API_BASE_URL", "http://127.0.0.1:7860")
CHAT2API_TIMEOUT = _get_env_float("CHAT2API_TIMEOUT", 30.0)

HARNESS_DB_PATH = _get_env("HARNESS_DB_PATH", str(_REPO_ROOT / "data" / "harness.db"))
HARNESS_ARTIFACT_DIR = _get_env("HARNESS_ARTIFACT_DIR", str(_REPO_ROOT / "artifacts"))
HARNESS_ROLE_MODELS_PATH = _get_env(
    "HARNESS_ROLE_MODELS_PATH",
    str(_REPO_ROOT / "config" / "role_models.yaml"),
)
HARNESS_MIN_QUOTA_PCT = _get_env_int("HARNESS_MIN_QUOTA_PCT", 5)
HARNESS_POLL_INTERVAL_SEC = _get_env_int("HARNESS_POLL_INTERVAL_SEC", 30)
HARNESS_RUNTIME_DIR = _get_env("HARNESS_RUNTIME_DIR", str(_REPO_ROOT / "data" / "harness-runtime"))
HARNESS_EVENT_LOG_PATH = _get_env(
    "HARNESS_EVENT_LOG_PATH",
    str(Path(HARNESS_RUNTIME_DIR) / "events.jsonl"),
)
HARNESS_DAEMON_PID_FILE = _get_env(
    "HARNESS_DAEMON_PID_FILE",
    str(Path(HARNESS_RUNTIME_DIR) / "orchestra.pid"),
)
HARNESS_DAEMON_STATE_PATH = _get_env(
    "HARNESS_DAEMON_STATE_PATH",
    str(Path(HARNESS_RUNTIME_DIR) / "orchestra-daemon.json"),
)
HARNESS_DAEMON_LOG_PATH = _get_env(
    "HARNESS_DAEMON_LOG_PATH",
    str(Path(HARNESS_RUNTIME_DIR) / "orchestra-daemon.log"),
)
HARNESS_DAEMON_STOP_TIMEOUT_SEC = _get_env_float("HARNESS_DAEMON_STOP_TIMEOUT_SEC", 10.0)
HARNESS_DASHBOARD_RECENT_EVENTS = _get_env_int("HARNESS_DASHBOARD_RECENT_EVENTS", 20)
