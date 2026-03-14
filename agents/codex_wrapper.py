from __future__ import annotations

import asyncio
import logging
import re

from config import settings
from agents.claude_code_wrapper import CLIError

logger = logging.getLogger(__name__)

_CODE_BLOCK_RE = re.compile(r"```(?:\w*)\n(.*?)```", re.DOTALL)


def _extract_response(text: str) -> str:
    """Extract code blocks from Codex output, falling back to full text."""
    blocks = _CODE_BLOCK_RE.findall(text)
    if blocks:
        return "\n\n".join(block.strip() for block in blocks)
    return text


async def invoke_codex(
    prompt: str,
    timeout: float | None = None,
    working_dir: str | None = None,
) -> str:
    args = ["codex", "exec", "-"]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=timeout if timeout is not None else settings.CLI_TIMEOUT,
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise CLIError("codex CLI timed out", stderr=str(exc))

    if proc.returncode != 0:
        error_text = stderr.decode(errors="ignore") if stderr else ""
        raise CLIError("codex CLI failed", exit_code=proc.returncode, stderr=error_text)

    output_text = stdout.decode(errors="ignore").strip() if stdout else ""
    if not output_text:
        return ""

    return _extract_response(output_text)
