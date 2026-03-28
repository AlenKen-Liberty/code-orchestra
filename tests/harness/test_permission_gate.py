import asyncio

from harness.models import RiskLevel
from harness.permission_gate import PermissionGate


def test_permission_gate_auto_approves_safe_commands() -> None:
    gate = PermissionGate()
    decision = gate.evaluate("git diff")

    assert decision.risk_level == RiskLevel.SAFE
    assert decision.decision == "auto_approved"
    assert decision.requires_user is False


def test_permission_gate_requires_vote_for_dangerous_commands() -> None:
    gate = PermissionGate()
    decision = gate.evaluate("git push origin feature-branch")

    assert decision.risk_level == RiskLevel.DANGEROUS
    assert decision.requires_voting is True
    assert decision.decision == "needs_model_vote"


def test_permission_gate_requires_user_for_critical_commands() -> None:
    gate = PermissionGate()
    decision = gate.evaluate("rm -rf /")

    assert decision.risk_level == RiskLevel.CRITICAL
    assert decision.requires_user is True
    assert decision.decision == "needs_user_approval"


class DummyVoting:
    def __init__(self, result):
        self.result = result

    async def vote(self, **kwargs):
        return self.result


def test_permission_gate_approves_after_vote() -> None:
    from harness.models import ModelVote, VoteResult

    gate = PermissionGate(
        voting=DummyVoting(
            VoteResult(
                decision="APPROVE",
                votes=[ModelVote(model="gpt-5.4-codex", vote="APPROVE", reason="safe")],
                unanimous=True,
                needs_escalation=False,
            )
        )
    )

    decision = asyncio.run(gate.decide("git push origin feature-branch", context="tests passed"))

    assert decision.decision == "model_approved"
    assert decision.votes[0].vote == "APPROVE"


def test_permission_gate_falls_back_to_user_when_vote_rejects() -> None:
    from harness.models import ModelVote, VoteResult

    async def user_approver(command: str, context: str):
        return False

    gate = PermissionGate(
        voting=DummyVoting(
            VoteResult(
                decision="REJECT",
                votes=[ModelVote(model="gpt-5.4-codex", vote="REJECT", reason="too risky")],
                unanimous=True,
                needs_escalation=True,
            )
        ),
        user_approver=user_approver,
    )

    decision = asyncio.run(gate.decide("git push origin main", context="prod branch"))

    assert decision.decision == "user_rejected"
