from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

import yaml

from common.acp_client import ACPClient
from common.models import Message, MessagePart, ReviewResult, Run, RunStatus, WorkflowResult
from config import settings

logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    def __init__(self, agent_config_path: str = "config/agents.yaml") -> None:
        self.agent_config_path = agent_config_path
        self.clients: dict[str, ACPClient] = {}
        self._load_agent_config()

    def _load_agent_config(self) -> None:
        with open(self.agent_config_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        agents = data.get("agents", {})
        for name, info in agents.items():
            base_url = info.get("base_url")
            if not base_url:
                raise ValueError(f"Missing base_url for agent {name}")
            self.clients[name] = ACPClient(base_url)

    async def run_workflow(self, task: str, max_review_rounds: int | None = None) -> WorkflowResult:
        session_id = uuid.uuid4().hex[:12]
        reviews: list[ReviewResult] = []
        plan: str | None = None
        code: str | None = None
        final_code: str | None = None
        try:
            rounds = max_review_rounds if max_review_rounds is not None else settings.MAX_REVIEW_ROUNDS
            plan = await self.plan_task(task, session_id)
            code = await self.implement_plan(plan, session_id)
            final_code = code
            for _ in range(rounds):
                review = await self.review_code(final_code, session_id)
                reviews.append(review)
                if review.verdict == "approved":
                    break
                final_code = await self.apply_review_feedback(review, session_id)
            return WorkflowResult(
                plan=plan,
                code=code,
                reviews=reviews,
                final_code=final_code,
                status="ok",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Workflow failed")
            return WorkflowResult(
                plan=plan,
                code=code,
                reviews=reviews,
                final_code=final_code,
                status="error",
                error=str(exc),
            )
        finally:
            await self.close()

    async def plan_task(self, task: str, session_id: str) -> str:
        message = Message(
            role="user",
            parts=[
                MessagePart(
                    content=(
                        "Create a detailed implementation plan for the following task:\n\n"
                        f"{task}"
                    )
                )
            ],
        )
        run = await self._call_agent("claude_planner", [message], session_id, step="plan_task")
        return self._extract_text(run)

    async def implement_plan(self, plan: str, session_id: str) -> str:
        message = Message(
            role="agent/claude_planner",
            parts=[
                MessagePart(
                    content=(
                        "Implement the following plan. Output the complete code.\n\n" f"{plan}"
                    )
                )
            ],
        )
        run = await self._call_agent("codex_coder", [message], session_id, step="implement_plan")
        return self._extract_text(run)

    async def review_code(self, code: str, session_id: str) -> ReviewResult:
        message = Message(
            role="agent/codex_coder",
            parts=[
                MessagePart(
                    content=(
                        "Review the following code. Provide verdict (approved/revise) and detailed feedback.\n\n"
                        f"{code}"
                    )
                )
            ],
        )
        run = await self._call_agent("claude_reviewer", [message], session_id, step="review_code")
        output = self._extract_text(run)
        return self._parse_review_output(output)

    async def apply_review_feedback(self, review: ReviewResult, session_id: str) -> str:
        message = Message(
            role="agent/claude_reviewer",
            parts=[
                MessagePart(
                    content=(
                        "Revise your code based on this review feedback:\n\n" f"{review.comments}"
                    )
                )
            ],
        )
        run = await self._call_agent("codex_coder", [message], session_id, step="apply_review_feedback")
        return self._extract_text(run)

    async def close(self) -> None:
        await asyncio.gather(*(client.close() for client in self.clients.values()))

    async def _call_agent(
        self,
        agent_name: str,
        messages: list[Message],
        session_id: str,
        step: str,
    ) -> Run:
        client = self.clients.get(agent_name)
        if client is None:
            raise ValueError(f"Unknown agent: {agent_name}")

        start_time = time.time()
        run = await client.create_run(agent_name, messages, session_id=session_id)
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "workflow step=%s agent=%s session=%s run=%s elapsed_ms=%s",
            step,
            agent_name,
            run.session_id,
            run.run_id,
            elapsed_ms,
        )
        if run.status != RunStatus.COMPLETED:
            raise RuntimeError(f"Agent {agent_name} failed: {run.error}")
        return run

    def _extract_text(self, run: Run) -> str:
        if not run.output_messages:
            return ""
        return run.output_messages[0].text

    def _parse_review_output(self, text: str) -> ReviewResult:
        cleaned = text.strip()
        if not cleaned:
            return ReviewResult(verdict="revise", comments="")

        lines = cleaned.splitlines()
        first_line = next((line for line in lines if line.strip()), "")
        remaining = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        verdict = None
        if first_line:
            try:
                parsed = json.loads(first_line)
                if isinstance(parsed, dict):
                    verdict_value = parsed.get("verdict")
                    if isinstance(verdict_value, str):
                        verdict_value = verdict_value.lower()
                        if verdict_value in {"approved", "revise"}:
                            verdict = verdict_value
            except json.JSONDecodeError:
                verdict = None

        if verdict is None:
            lower = cleaned.lower()
            if "approved" in lower and "revise" not in lower:
                verdict = "approved"
            elif "revise" in lower and "approved" not in lower:
                verdict = "revise"
            elif "approved" in lower and "revise" in lower:
                verdict = "approved" if lower.find("approved") < lower.find("revise") else "revise"
            else:
                verdict = "revise"

        comments = remaining if remaining else cleaned
        return ReviewResult(verdict=verdict, comments=comments)
