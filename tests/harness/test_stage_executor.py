import asyncio

from harness.models import PermissionDecision, RiskLevel, StageRecord, StageStatus
from harness.permission_gate import PermissionGate
from harness.stage_executor import CommandExecution, PermissionBlockedError, StageExecutor


class DummyPermissionGate:
    def __init__(self, decision):
        self.decision = decision

    async def decide(self, command, **kwargs):
        return self.decision


class DummyVoting:
    def __init__(self, decision):
        self.decision = decision

    async def vote(self, **kwargs):
        return self.decision


async def _runner(command, cwd, **kwargs):
    return CommandExecution(returncode=0, stdout="ok", stderr="")


def make_stage(provider: str, metadata=None) -> StageRecord:
    return StageRecord(
        stage_id="stage",
        task_id="task",
        stage_type="github_ops" if provider == "github" else "code",
        stage_order=1,
        model_role="github_ops" if provider == "github" else "coder",
        assigned_model="gpt-4o" if provider == "github" else "gpt-5.4-codex",
        assigned_provider=provider,
        status=StageStatus.PENDING,
        handoff_doc_path=None,
        result_summary=None,
        token_used=0,
        duration_sec=0.0,
        started_at=None,
        finished_at=None,
        metadata=metadata or {},
    )


def test_stage_executor_runs_github_commands(tmp_path) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text("hello", encoding="utf-8")
    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.MODERATE, decision="auto_approved", reason="ok")
        ),
        runner=_runner,
    )

    result = asyncio.run(
        executor.execute(
            make_stage("github", {"commands": ["echo pushed"]}),
            str(handoff),
            str(tmp_path),
        )
    )

    assert result.status == StageStatus.DONE
    assert result.summary == "ok"


def test_stage_executor_blocks_unapproved_command(tmp_path) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text("hello", encoding="utf-8")
    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(
                risk_level=RiskLevel.DANGEROUS,
                decision="needs_user_approval",
                reason="blocked",
            )
        ),
        runner=_runner,
    )

    try:
        asyncio.run(executor.run_verify_cmd("git push origin main", str(tmp_path)))
    except PermissionBlockedError as exc:
        assert "blocked" in str(exc)
        assert "git push origin main" in exc.command
    else:
        raise AssertionError("Expected PermissionBlockedError")


def test_stage_executor_checks_raw_verify_command(tmp_path) -> None:
    from harness.models import ModelVote, VoteResult

    async def user_approver(command: str, context: str):
        return False

    executor = StageExecutor(
        permission_gate=PermissionGate(
            voting=DummyVoting(
                VoteResult(
                    decision="REJECT",
                    votes=[ModelVote(model="gpt-5.4-codex", vote="REJECT", reason="blocked")],
                    unanimous=True,
                    needs_escalation=True,
                )
            ),
            user_approver=user_approver,
        ),
        runner=_runner,
    )

    try:
        asyncio.run(executor.run_verify_cmd("git push origin main", str(tmp_path)))
    except PermissionBlockedError as exc:
        assert exc.command == "git push origin main"
    else:
        raise AssertionError("Expected PermissionBlockedError")


def test_stage_executor_extracts_codex_token_usage(tmp_path) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text("hello", encoding="utf-8")

    async def codex_runner(command, cwd, **kwargs):
        return CommandExecution(
            returncode=0,
            stdout='{"output_text":"implemented feature","usage":{"input_tokens":11,"output_tokens":7}}',
            stderr="",
        )

    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.SAFE, decision="auto_approved", reason="ok")
        ),
        runner=codex_runner,
    )

    result = asyncio.run(executor.execute(make_stage("codex"), str(handoff), str(tmp_path)))

    assert result.raw_output == "implemented feature"
    assert result.token_used == 18


# ── Gemini CLI command building tests ────────────────────────────


def make_gemini_stage(model: str = "gemini-3.1-pro-preview") -> StageRecord:
    return StageRecord(
        stage_id="gemini_stage",
        task_id="task",
        stage_type="code",
        stage_order=1,
        model_role="coder",
        assigned_model=model,
        assigned_provider="google",
        status=StageStatus.PENDING,
        handoff_doc_path=None,
        result_summary=None,
        token_used=0,
        duration_sec=0.0,
        started_at=None,
        finished_at=None,
        metadata={},
    )


def test_gemini_command_has_yolo_flag(tmp_path) -> None:
    """Gemini CLI MUST have -y (yolo) flag to allow file writes."""
    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.SAFE, decision="auto_approved", reason="ok")
        ),
        runner=_runner,
    )
    cmd = executor.build_command(make_gemini_stage(), "Create hello.py", str(tmp_path))
    assert "-y" in cmd, f"Missing -y (yolo) flag in Gemini command: {cmd}"


def test_gemini_command_has_prompt_flag(tmp_path) -> None:
    """Gemini CLI MUST have -p flag for non-interactive headless mode."""
    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.SAFE, decision="auto_approved", reason="ok")
        ),
        runner=_runner,
    )
    cmd = executor.build_command(make_gemini_stage(), "Create hello.py", str(tmp_path))
    assert "-p" in cmd, f"Missing -p flag in Gemini command: {cmd}"
    # -p must come before the prompt text
    p_idx = cmd.index("-p")
    assert cmd[p_idx + 1] == "Create hello.py"


def test_gemini_command_uses_correct_model(tmp_path) -> None:
    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.SAFE, decision="auto_approved", reason="ok")
        ),
        runner=_runner,
    )
    cmd = executor.build_command(make_gemini_stage("gemini-2.5-pro"), "test", str(tmp_path))
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "gemini-2.5-pro"


def test_gemini_command_flag_order(tmp_path) -> None:
    """Ensure flags are in correct order: gemini --model X -y -p PROMPT"""
    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.SAFE, decision="auto_approved", reason="ok")
        ),
        runner=_runner,
    )
    cmd = executor.build_command(make_gemini_stage(), "do stuff", str(tmp_path))
    assert cmd[0] == "gemini"
    assert cmd[1] == "--model"
    # -y must be before -p (yolo must be set before prompt is processed)
    y_idx = cmd.index("-y")
    p_idx = cmd.index("-p")
    assert y_idx < p_idx, f"-y (idx={y_idx}) must come before -p (idx={p_idx})"


def test_prompt_over_max_arg_len_written_to_file(tmp_path, monkeypatch) -> None:
    from config import settings
    monkeypatch.setattr(settings, "PROMPT_MAX_ARG_LEN", 100)
    monkeypatch.setattr(settings, "HARNESS_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    
    handoff = tmp_path / "handoff.md"
    long_prompt = "A" * 200
    handoff.write_text(long_prompt, encoding="utf-8")

    async def codex_runner(command, cwd, **kwargs):
        return CommandExecution(
            returncode=0,
            stdout='{"output_text":"ok"}',
            stderr="",
        )

    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.SAFE, decision="auto_approved", reason="ok")
        ),
        runner=codex_runner,
    )

    stage = make_stage("codex")
    result = asyncio.run(executor.execute(stage, str(handoff), str(tmp_path)))

    assert result.status == StageStatus.DONE
    artifacts_dir = tmp_path / "artifacts" / stage.task_id
    prompt_file = artifacts_dir / f"{stage.stage_id}_prompt.txt"
    assert prompt_file.exists()
    assert prompt_file.read_text(encoding="utf-8") == long_prompt


def test_provider_command_lists_no_raw_prompt_text_when_large(tmp_path, monkeypatch) -> None:
    from config import settings
    monkeypatch.setattr(settings, "PROMPT_MAX_ARG_LEN", 100)
    monkeypatch.setattr(settings, "HARNESS_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    
    long_prompt = "A" * 200
    handoff = tmp_path / "handoff.md"
    handoff.write_text(long_prompt, encoding="utf-8")
    
    executed_commands = []
    
    async def recording_runner(command, cwd, **kwargs):
        executed_commands.append(command)
        return CommandExecution(returncode=0, stdout='{"output_text":"ok"}', stderr="")

    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.SAFE, decision="auto_approved", reason="ok")
        ),
        runner=recording_runner,
    )

    # Test Codex
    stage = make_stage("codex")
    asyncio.run(executor.execute(stage, str(handoff), str(tmp_path)))
    assert long_prompt not in executed_commands[-1]
    
    # Test Claude
    stage.assigned_provider = "claude"
    asyncio.run(executor.execute(stage, str(handoff), str(tmp_path)))
    assert long_prompt not in executed_commands[-1]
    
    # Test Gemini
    stage.assigned_provider = "google"
    asyncio.run(executor.execute(stage, str(handoff), str(tmp_path)))
    assert long_prompt not in executed_commands[-1]
    # Check that Gemini got the file path reference
    prompt_file = tmp_path / "artifacts" / stage.task_id / f"{stage.stage_id}_prompt.txt"
    assert any(str(prompt_file) in arg for arg in executed_commands[-1])


def test_codex_always_has_full_auto_flag(tmp_path, monkeypatch) -> None:
    """Codex --full-auto flag must be present regardless of prompt size."""
    from config import settings
    monkeypatch.setattr(settings, "PROMPT_MAX_ARG_LEN", 10)
    monkeypatch.setattr(settings, "HARNESS_ARTIFACT_DIR", str(tmp_path / "artifacts"))

    handoff = tmp_path / "handoff.md"
    handoff.write_text("A" * 100, encoding="utf-8")

    executed_commands = []

    async def recording_runner(command, cwd, **kwargs):
        executed_commands.append(command)
        return CommandExecution(returncode=0, stdout='{"output_text":"ok"}', stderr="")

    executor = StageExecutor(
        permission_gate=DummyPermissionGate(
            PermissionDecision(risk_level=RiskLevel.SAFE, decision="auto_approved", reason="ok")
        ),
        runner=recording_runner,
    )

    stage = make_stage("codex")
    asyncio.run(executor.execute(stage, str(handoff), str(tmp_path)))
    assert "--full-auto" in executed_commands[-1], f"Missing --full-auto in: {executed_commands[-1]}"

