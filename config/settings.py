import os


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
ORCHESTRATOR_PORT = _get_env_int("ORCHESTRATOR_PORT", 8000)

CLAUDE_BASE_URL = _get_env("CLAUDE_BASE_URL", "http://localhost:8001")
CODEX_BASE_URL = _get_env("CODEX_BASE_URL", "http://localhost:8002")

CLI_TIMEOUT = _get_env_float("CLI_TIMEOUT", 120.0)
HTTP_TIMEOUT = _get_env_float("HTTP_TIMEOUT", 180.0)

MAX_REVIEW_ROUNDS = _get_env_int("MAX_REVIEW_ROUNDS", 3)
MAX_RETRIES = _get_env_int("MAX_RETRIES", 2)
RETRY_BACKOFF = _get_env_float("RETRY_BACKOFF", 1.0)

LOG_LEVEL = _get_env("LOG_LEVEL", "INFO")

SESSION_PERSIST_TO_DISK = _get_env_bool("SESSION_PERSIST_TO_DISK", False)
SESSION_DATA_DIR = _get_env("SESSION_DATA_DIR", "./data/sessions")

CLAUDE_PLANNER_MODEL = _get_env("CLAUDE_PLANNER_MODEL", "opus4.6")
CLAUDE_REVIEWER_MODEL = _get_env("CLAUDE_REVIEWER_MODEL", "haiku4.5")

CODEX_MODEL = _get_env("CODEX_MODEL", "gpt-5.2-codex")
CODEX_TIER = _get_env("CODEX_TIER", "xhigh")
