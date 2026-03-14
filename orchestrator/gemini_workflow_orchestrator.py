"""Multi-agent orchestrator with Gemini integration: Opus → Gemini → Codex → Haiku"""
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


class GeminiWorkflowOrchestrator:
    """
    Workflow: Opus (design) → Gemini (review design) → Codex (implement) → Haiku (review code)
    """

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

    async def run_workflow(self, task: str) -> WorkflowResult:
        """
        Execute workflow: plan → design_review → implement → code_review
        """
        session_id = uuid.uuid4().hex[:12]
        reviews: list[ReviewResult] = []
        plan: str | None = None
        design_feedback: str | None = None
        code: str | None = None
        final_code: str | None = None

        try:
            # Stage 1: Opus Design
            logger.info("=" * 70)
            logger.info("Stage 1: Opus Design")
            logger.info("=" * 70)
            plan = await self.plan_task(task, session_id)
            logger.info(f"✅ Design complete (length: {len(plan)} chars)")

            # Stage 2: Gemini Design Review
            logger.info("=" * 70)
            logger.info("Stage 2: Gemini Design Review")
            logger.info("=" * 70)
            design_feedback = await self.review_design(plan, session_id)
            logger.info(f"✅ Design review complete (length: {len(design_feedback)} chars)")

            # Stage 3: Codex Implementation
            logger.info("=" * 70)
            logger.info("Stage 3: Codex Implementation")
            logger.info("=" * 70)
            code = await self.implement_plan(plan, design_feedback, session_id)
            final_code = code
            logger.info(f"✅ Implementation complete (length: {len(code)} chars)")

            # Stage 4: Haiku Code Review
            logger.info("=" * 70)
            logger.info("Stage 4: Haiku Code Review")
            logger.info("=" * 70)
            review = await self.review_code(plan, final_code, session_id)
            reviews.append(review)
            logger.info(f"✅ Code review complete - Verdict: {review.verdict}")

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
        """Stage 1: Opus generates design plan"""
        message = Message(
            role="user",
            parts=[
                MessagePart(
                    content=(
                        "You are an expert system architect. Create a detailed implementation plan:\n\n"
                        f"{task}\n\n"
                        "Provide:\n"
                        "1. System architecture overview\n"
                        "2. Component design\n"
                        "3. Implementation steps\n"
                        "4. Key considerations"
                    )
                )
            ],
        )
        run = await self._call_agent("claude_planner", [message], session_id, step="plan_task")
        return self._extract_text(run)

    async def review_design(self, design: str, session_id: str) -> str:
        """Stage 2: Gemini reviews the design"""
        message = Message(
            role="agent/claude_planner",
            parts=[
                MessagePart(
                    content=(
                        "You are an expert code reviewer. Review this design plan and provide:\n"
                        "1. Confirmation if the design is clear and implementable\n"
                        "2. Any improvements or optimizations suggested\n"
                        "3. Specific requirements for the implementation\n\n"
                        f"Design Plan:\n{design}"
                    )
                )
            ],
        )
        run = await self._call_agent("gemini_reviewer", [message], session_id, step="review_design")
        return self._extract_text(run)

    async def implement_plan(self, plan: str, feedback: str, session_id: str) -> str:
        """Stage 3: Codex implements the code"""
        message = Message(
            role="agent/gemini_reviewer",
            parts=[
                MessagePart(
                    content=(
                        "Implement the following design plan. Output complete, production-ready code.\n\n"
                        f"Design Plan:\n{plan}\n\n"
                        f"Review Feedback:\n{feedback}\n\n"
                        "Provide:\n"
                        "1. Complete implementation\n"
                        "2. Error handling\n"
                        "3. Tests\n"
                        "4. Usage documentation"
                    )
                )
            ],
        )
        run = await self._call_agent("codex_coder", [message], session_id, step="implement_plan")
        return self._extract_text(run)

    async def review_code(self, design: str, code: str, session_id: str) -> ReviewResult:
        """Stage 4: Haiku reviews the implementation"""
        message = Message(
            role="agent/codex_coder",
            parts=[
                MessagePart(
                    content=(
                        "You are an expert code reviewer. Review this implementation against the design.\n\n"
                        f"Design Plan:\n{design}\n\n"
                        f"Implementation:\n{code}\n\n"
                        "Provide review in this JSON format:\n"
                        '{"verdict": "approved" | "revise", "comments": "detailed feedback"}\n\n'
                        "Then provide detailed review comments."
                    )
                )
            ],
        )
        run = await self._call_agent("claude_reviewer", [message], session_id, step="review_code")
        output = self._extract_text(run)
        return self._parse_review_output(output)

    async def close(self) -> None:
        await asyncio.gather(*(client.close() for client in self.clients.values()), return_exceptions=True)

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
        """Parse review output to extract verdict and comments"""
        import re

        cleaned = text.strip()
        if not cleaned:
            return ReviewResult(verdict="revise", comments="")

        lines = cleaned.splitlines()
        verdict = None
        comments = cleaned

        # Try to find JSON in first line or code block
        for line in lines:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", line, re.DOTALL)
            clean_line = match.group(1) if match else line
            try:
                parsed = json.loads(clean_line)
                if isinstance(parsed, dict):
                    verdict_value = parsed.get("verdict", "").lower()
                    if verdict_value in {"approved", "revise"}:
                        verdict = verdict_value
                        comments = parsed.get("comments", cleaned)
                        break
            except json.JSONDecodeError:
                continue

        # Fallback: search for keywords
        if verdict is None:
            lower = cleaned.lower()
            if "approved" in lower:
                verdict = "approved"
            else:
                verdict = "revise"

        return ReviewResult(verdict=verdict, comments=comments)
