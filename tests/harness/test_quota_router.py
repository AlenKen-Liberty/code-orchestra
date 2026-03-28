from harness.models import StageRecord, StageStatus, TaskRecord, TaskStatus
from harness.quota_router import QuotaRouter
from models.quota_manager import Provider, QuotaSnapshot


class DummyQuotaManager:
    def __init__(self, snapshots):
        self._snapshots = snapshots

    def fetch_all_quotas(self):
        return list(self._snapshots)


class DummyChatClient:
    def __init__(self, models, response):
        self._models = models
        self._response = response

    def list_models(self):
        return list(self._models)

    def chat(self, **kwargs):
        return self._response


def make_task() -> TaskRecord:
    return TaskRecord(
        task_id="task-router",
        title="Task",
        description="desc",
        goal=None,
        verify_cmd=None,
        complexity="medium",
        priority=50,
        status=TaskStatus.EXECUTING,
        working_dir="/repo",
        created_at="2026-03-27T00:00:00+00:00",
        updated_at="2026-03-27T00:00:00+00:00",
    )


def make_stage(role: str) -> StageRecord:
    return StageRecord(
        stage_id=f"stage-{role}",
        task_id="task-router",
        stage_type="code",
        stage_order=1,
        model_role=role,
        assigned_model=None,
        assigned_provider=None,
        status=StageStatus.PENDING,
        handoff_doc_path=None,
        result_summary=None,
        token_used=0,
        duration_sec=0.0,
        started_at=None,
        finished_at=None,
    )


def test_router_prefers_soon_expiring_codex_quota() -> None:
    snapshots = [
        QuotaSnapshot(
            provider=Provider.CODEX,
            email="codex-1@test",
            account_id="codex-1",
            plan_type="pro",
            used_percent=40,
            reset_at=0,
            reset_at_readable="soon",
            time_until_reset_hours=1.0,
        ),
        QuotaSnapshot(
            provider=Provider.GOOGLE,
            email="gemini-1@test",
            account_id="gemini-1",
            plan_type="free",
            used_percent=10,
            reset_at=0,
            reset_at_readable="later",
            time_until_reset_hours=24.0,
        ),
    ]
    router = QuotaRouter(quota_manager=DummyQuotaManager(snapshots))

    choice = router.select_model(
        make_task(),
        make_stage("coder"),
        available_models=["gpt-5.4-codex", "gemini-3.1-pro"],
    )

    assert choice.model == "gpt-5.4-codex"
    assert choice.provider == "codex"
    assert choice.account_email == "codex-1@test"


def test_router_rotates_between_codex_accounts_using_account_score() -> None:
    snapshots = [
        QuotaSnapshot(
            provider=Provider.CODEX,
            email="codex-expiring@test",
            account_id="codex-1",
            plan_type="pro",
            used_percent=50,
            reset_at=0,
            reset_at_readable="soon",
            time_until_reset_hours=1.0,
        ),
        QuotaSnapshot(
            provider=Provider.CODEX,
            email="codex-fresh@test",
            account_id="codex-2",
            plan_type="pro",
            used_percent=10,
            reset_at=0,
            reset_at_readable="later",
            time_until_reset_hours=24.0,
        ),
    ]
    router = QuotaRouter(quota_manager=DummyQuotaManager(snapshots), enable_llm_selector=False)

    choice = router.select_model(
        make_task(),
        make_stage("coder"),
        available_models=["gpt-5.4-codex"],
    )

    assert choice.model == "gpt-5.4-codex"
    assert choice.account_email == "codex-expiring@test"


def test_router_uses_provider_without_snapshot_when_available() -> None:
    router = QuotaRouter(quota_manager=DummyQuotaManager([]), enable_llm_selector=False)

    choice = router.select_model(
        make_task(),
        make_stage("github_ops"),
        available_models=["gpt-4o"],
    )

    assert choice.model == "gpt-4o"
    assert choice.provider == "github"


def test_router_accepts_llm_selector_choice() -> None:
    snapshots = [
        QuotaSnapshot(
            provider=Provider.CODEX,
            email="codex-1@test",
            account_id="codex-1",
            plan_type="pro",
            used_percent=35,
            reset_at=0,
            reset_at_readable="soon",
            time_until_reset_hours=2.0,
        ),
        QuotaSnapshot(
            provider=Provider.GOOGLE,
            email="gemini-1@test",
            account_id="gemini-1",
            plan_type="free",
            used_percent=5,
            reset_at=0,
            reset_at_readable="later",
            time_until_reset_hours=18.0,
        ),
    ]
    router = QuotaRouter(
        quota_manager=DummyQuotaManager(snapshots),
        chat_client=DummyChatClient(
            # DummyChatClient.list_models returns chat2api IDs (matching chat2api_id in role_models.yaml)
            ["copilot-gpt4o", "codex", "gemini-pro"],
            '{"model":"gemini-3.1-pro","provider":"google","account":"gemini-1@test","reason":"review fits"}',
        ),
    )

    choice = router.select_model(make_task(), make_stage("reviewer"))

    assert choice.model == "gemini-3.1-pro"
    assert choice.provider == "google"
    assert choice.account_email == "gemini-1@test"


def test_router_accepts_llm_selector_choice_for_specific_codex_account() -> None:
    snapshots = [
        QuotaSnapshot(
            provider=Provider.CODEX,
            email="codex-1@test",
            account_id="codex-1",
            plan_type="pro",
            used_percent=20,
            reset_at=0,
            reset_at_readable="later",
            time_until_reset_hours=18.0,
        ),
        QuotaSnapshot(
            provider=Provider.CODEX,
            email="codex-2@test",
            account_id="codex-2",
            plan_type="pro",
            used_percent=30,
            reset_at=0,
            reset_at_readable="soon",
            time_until_reset_hours=2.0,
        ),
    ]
    router = QuotaRouter(
        quota_manager=DummyQuotaManager(snapshots),
        chat_client=DummyChatClient(
            ["copilot-gpt4o", "codex", "gemini-pro"],
            '{"model":"gpt-5.4-codex","provider":"codex","account":"codex-2@test","reason":"expiring sooner"}',
        ),
    )

    choice = router.select_model(make_task(), make_stage("coder"))

    assert choice.model == "gpt-5.4-codex"
    assert choice.provider == "codex"
    assert choice.account_email == "codex-2@test"
