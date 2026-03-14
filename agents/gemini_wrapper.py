from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from agents.claude_code_wrapper import CLIError
from config import settings

logger = logging.getLogger(__name__)

_CODE_BLOCK_RE = re.compile(r"```(?:\w*)\n(.*?)```", re.DOTALL)


def _extract_response(text: str) -> str:
    """Extract code blocks from Gemini output, falling back to full text."""
    blocks = _CODE_BLOCK_RE.findall(text)
    if blocks:
        return "\n\n".join(block.strip() for block in blocks)
    return text


async def invoke_gemini(
    prompt: str,
    model: str = "gemini-3.1-pro-preview",
    timeout: Optional[float] = None,
    working_dir: Optional[str] = None,
) -> str:
    """
    Invoke Gemini CLI with the specified prompt and model.

    Assumes the gemini command is available in PATH.
    Command format: gemini --model <model> <prompt>
    """
    args = ["gemini", "--model", model]

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
        raise CLIError("geminicli timed out", stderr=str(exc))

    if proc.returncode != 0:
        error_text = stderr.decode(errors="ignore") if stderr else ""
        raise CLIError("geminicli failed", exit_code=proc.returncode, stderr=error_text)

    output_text = stdout.decode(errors="ignore").strip() if stdout else ""
    if not output_text:
        return ""

    # Try to parse JSON response, fallback to text
    try:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output_text, re.DOTALL)
        clean_text = match.group(1) if match else output_text
        parsed = json.loads(clean_text)
        if isinstance(parsed, dict):
            for key in ("result", "content", "response", "text"):
                value = parsed.get(key)
                if isinstance(value, str):
                    return value
            return json.dumps(parsed)
        return json.dumps(parsed)
    except json.JSONDecodeError:
        return _extract_response(output_text)
