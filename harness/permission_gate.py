"""Permission classification and default approval policy."""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable, Optional

from harness.models import PermissionDecision, RiskLevel
from harness.voting import ModelVoting


SAFE_PATTERNS = [
    r"^(cat|head|tail|ls|pwd|echo|grep|find|wc|sort|diff|rg)\b",
    r"^(python|python3|node|pytest|npm test|cargo test)\b",
    r"^git (status|log|diff|branch|show)\b",
]

DANGEROUS_PATTERNS = [
    r"^rm\s+(-rf?|--recursive)",
    r"^git\s+(push|reset\s+--hard|clean\s+-f|branch\s+-D)",
    r"^(chmod|chown)\s+",
    r"^(curl|wget)\s+.*\|\s*(bash|sh)",
    r"^(npm|pip)\s+(publish|upload)",
    r"^docker\s+(rm|rmi|system\s+prune)",
    r"^sudo\b",
]

CRITICAL_PATTERNS = [
    r"^rm\s+-rf\s+[/~]",
    r"^(DROP|DELETE|TRUNCATE)\b",
    r">\s*/etc/",
]


class PermissionGate:
    """Classify shell commands into automatic, review, or user-gated actions."""

    def __init__(
        self,
        *,
        voting: Optional[ModelVoting] = None,
        user_approver: Optional[Callable[[str, str], Awaitable[bool | None]]] = None,
    ) -> None:
        self.safe_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in SAFE_PATTERNS]
        self.dangerous_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in DANGEROUS_PATTERNS]
        self.critical_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in CRITICAL_PATTERNS]
        self.voting = voting or ModelVoting()
        self.user_approver = user_approver

    def classify(self, command: str) -> RiskLevel:
        command = command.strip()
        if any(pattern.search(command) for pattern in self.critical_patterns):
            return RiskLevel.CRITICAL
        if any(pattern.search(command) for pattern in self.dangerous_patterns):
            return RiskLevel.DANGEROUS
        if any(pattern.search(command) for pattern in self.safe_patterns):
            return RiskLevel.SAFE
        return RiskLevel.MODERATE

    def evaluate(self, command: str) -> PermissionDecision:
        risk = self.classify(command)
        if risk is RiskLevel.SAFE:
            return PermissionDecision(
                risk_level=risk,
                decision="auto_approved",
                reason="Matched safe command pattern.",
            )
        if risk is RiskLevel.MODERATE:
            return PermissionDecision(
                risk_level=risk,
                decision="auto_approved",
                reason="No dangerous pattern matched; recorded as moderate.",
            )
        if risk is RiskLevel.DANGEROUS:
            return PermissionDecision(
                risk_level=risk,
                decision="needs_model_vote",
                reason="Dangerous command requires committee review.",
                requires_voting=True,
            )
        return PermissionDecision(
            risk_level=risk,
            decision="needs_user_approval",
            reason="Critical command requires explicit user approval.",
            requires_user=True,
        )

    async def decide(
        self,
        command: str,
        *,
        context: str = "",
        available_models: Optional[list[str]] = None,
    ) -> PermissionDecision:
        initial = self.evaluate(command)
        if initial.decision == "auto_approved":
            return initial

        if initial.requires_voting:
            vote_result = await self.voting.vote(
                question=f"Should this command be allowed? {command}",
                context=context,
                available_models=available_models,
            )
            approve_votes = sum(1 for vote in vote_result.votes if vote.vote == "APPROVE")
            reject_votes = sum(1 for vote in vote_result.votes if vote.vote == "REJECT")

            if approve_votes >= max(1, reject_votes) and not vote_result.needs_escalation:
                return PermissionDecision(
                    risk_level=initial.risk_level,
                    decision="model_approved",
                    reason="Committee approved the command.",
                    votes=vote_result.votes,
                )

            if self.user_approver is not None:
                approved = await self.user_approver(command, context)
                if approved is True:
                    return PermissionDecision(
                        risk_level=initial.risk_level,
                        decision="user_approved",
                        reason="User approved the command.",
                        votes=vote_result.votes,
                    )
                if approved is False:
                    return PermissionDecision(
                        risk_level=initial.risk_level,
                        decision="user_rejected",
                        reason="User rejected the command.",
                        votes=vote_result.votes,
                    )

            return PermissionDecision(
                risk_level=initial.risk_level,
                decision="needs_user_approval",
                reason="Committee did not reach a safe automatic approval.",
                requires_user=True,
                votes=vote_result.votes,
            )

        if self.user_approver is not None:
            approved = await self.user_approver(command, context)
            if approved is True:
                return PermissionDecision(
                    risk_level=initial.risk_level,
                    decision="user_approved",
                    reason="User approved the command.",
                )
            if approved is False:
                return PermissionDecision(
                    risk_level=initial.risk_level,
                    decision="user_rejected",
                    reason="User rejected the command.",
                )

        return initial
