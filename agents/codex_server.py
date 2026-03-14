from __future__ import annotations

import asyncio
import logging

from common.acp_server import ACPServer, AgentContext
from common.models import Message, MessagePart
from config import settings
from agents.codex_wrapper import invoke_codex

logger = logging.getLogger(__name__)


def _build_prompt(history_text: str, user_input: str) -> str:
    parts: list[str] = []
    if history_text:
        parts.append(history_text)
    if user_input:
        parts.append(user_input)
    return "\n\n".join(parts)


def create_server(port: int | None = None) -> ACPServer:
    server = ACPServer(port=port or settings.CODEX_PORT)

    @server.agent(
        name="codex_coder",
        description="Code implementation agent",
        metadata={"model": settings.CODEX_MODEL, "tier": settings.CODEX_TIER},
    )
    async def handle_coder(messages: list[Message], context: AgentContext) -> list[MessagePart]:
        history_text = context.session_history_as_prompt
        user_input = messages[-1].text if messages else ""
        prompt = _build_prompt(history_text, user_input)
        result = await invoke_codex(prompt)
        return [MessagePart(content=result)]

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
