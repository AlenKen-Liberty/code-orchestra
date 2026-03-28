"""Model voting helpers."""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import Optional

from harness.chat2api_client import Chat2APIClient
from harness.model_registry import ModelRegistry
from harness.models import ModelVote, VoteResult


class ModelVoting:
    """Sequential opinion gathering across the big-three model set."""

    BIG_THREE = ("claude-opus-4-6", "gpt-5.4-codex", "gemini-3.1-pro")

    def __init__(
        self,
        client: Optional[Chat2APIClient] = None,
        registry: Optional[ModelRegistry] = None,
    ) -> None:
        self.client = client or Chat2APIClient()
        self.registry = registry or ModelRegistry()

    async def vote(
        self,
        *,
        question: str,
        context: str,
        available_models: Optional[list[str]] = None,
        options: tuple[str, str] = ("APPROVE", "REJECT"),
    ) -> VoteResult:
        eligible = [model for model in self.BIG_THREE if available_models is None or model in available_models]
        if not eligible:
            return VoteResult(decision=None, needs_escalation=True)

        votes: list[ModelVote] = []
        for model in eligible:
            prompt = (
                "You are a code-orchestra review committee member.\n\n"
                f"Question: {question}\n"
                f"Context: {context}\n"
                f"Options: {options[0]} / {options[1]}\n\n"
                'Respond with JSON: {"vote": "APPROVE|REJECT", "reason": "..."}'
            )
            try:
                chat2api_id = self.registry.chat2api_id(model)
                raw = await asyncio.to_thread(self.client.chat, model=chat2api_id, prompt=prompt)
                parsed = json.loads(raw)
                vote = str(parsed["vote"]).upper()
                reason = str(parsed.get("reason") or "")
            except Exception:
                vote = "REJECT"
                reason = "Invalid or missing vote response."
            votes.append(ModelVote(model=model, vote=vote, reason=reason))

        counts = Counter(vote.vote for vote in votes)
        decision, count = counts.most_common(1)[0]
        return VoteResult(
            decision=decision,
            votes=votes,
            unanimous=count == len(votes),
            needs_escalation=count <= len(votes) // 2,
        )
