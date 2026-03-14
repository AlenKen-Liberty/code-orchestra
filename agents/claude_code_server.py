from __future__ import annotations

import asyncio
import logging

from common.acp_server import ACPServer, AgentContext
from common.models import Message, MessagePart
from config import settings
from agents.claude_code_wrapper import invoke_claude

logger = logging.getLogger(__name__)


def _build_prompt(history_text: str, user_input: str, system_prefix: str | None = None) -> str:
    parts: list[str] = []
    if system_prefix:
        parts.append(system_prefix.strip())
    if history_text:
        parts.append(history_text)
    if user_input:
        parts.append(user_input)
    return "\n\n".join(parts)


def create_server(port: int | None = None) -> ACPServer:
    server = ACPServer(port=port or settings.CLAUDE_PORT)

    @server.agent(
        name="claude_planner",
        description="Planning and architectural design agent",
        metadata={"model": settings.CLAUDE_PLANNER_MODEL},
    )
    async def handle_planner(messages: list[Message], context: AgentContext) -> list[MessagePart]:
        history_text = context.session_history_as_prompt
        user_input = messages[-1].text if messages else ""
        prompt = _build_prompt(history_text, user_input)
        result = await invoke_claude(
            prompt,
            model=settings.CLAUDE_PLANNER_MODEL,
            allowed_tools=["Read", "Bash"],
        )
        return [MessagePart(content=result)]

    @server.agent(
        name="claude_reviewer",
        description="Code review agent",
        metadata={"model": settings.CLAUDE_REVIEWER_MODEL},
    )
    async def handle_reviewer(messages: list[Message], context: AgentContext) -> list[MessagePart]:
        history_text = context.session_history_as_prompt
        user_input = messages[-1].text if messages else ""
        system_prefix = (
            "You are a code reviewer. Evaluate the code provided. Start your response with a JSON line: "
            '{"verdict": "approved" | "revise"}\nThen provide detailed review comments.'
        )
        prompt = _build_prompt(history_text, user_input, system_prefix=system_prefix)
        result = await invoke_claude(
            prompt,
            model=settings.CLAUDE_REVIEWER_MODEL,
        )
        return [MessagePart(content=result, metadata={"role": "reviewer"})]

    return server


def main(port: int | None = None) -> None:
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    server = create_server(port)
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
