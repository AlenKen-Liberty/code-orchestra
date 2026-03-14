from __future__ import annotations

import asyncio
import json
import logging
from typing import Iterable

from config import settings

logger = logging.getLogger(__name__)


class CLIError(Exception):
    def __init__(self, message: str, exit_code: int | None = None, stderr: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.stderr = stderr


async def invoke_claude(
    prompt: str,
    model: str,
    allowed_tools: Iterable[str] | None = None,
    timeout: float | None = None,
    working_dir: str | None = None,
) -> str:
    args = ["claude", "-p", "--output-format", "json", "--model", model]
    if allowed_tools:
        args.extend(["--allowedTools", ",".join(allowed_tools)])

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
        raise CLIError("claude CLI timed out", stderr=str(exc))

    if proc.returncode != 0:
        error_text = stderr.decode(errors="ignore") if stderr else ""
        raise CLIError("claude CLI failed", exit_code=proc.returncode, stderr=error_text)

    output_text = stdout.decode(errors="ignore").strip() if stdout else ""
    if not output_text:
        return ""

    try:
        parsed = json.loads(output_text)
        if isinstance(parsed, dict):
            for key in ("result", "content", "response"):
                value = parsed.get(key)
                if isinstance(value, str):
                    return value
            return json.dumps(parsed)
        return json.dumps(parsed)
    except json.JSONDecodeError:
        return output_text
