from __future__ import annotations

import asyncio

from config import settings


async def invoke_codex(
    prompt: str,
    *,
    model: str | None = None,
    tier: str | None = None,
    cwd: str | None = None,
) -> str:
    command = [
        "codex",
        "exec",
        "--json",
        "--model",
        model or settings.CODEX_MODEL,
        "--tier",
        tier or settings.CODEX_TIER,
    ]
    if cwd:
        command.extend(["--cwd", cwd])
    command.append(prompt)

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace") or "Codex CLI invocation failed")
    return stdout.decode("utf-8", errors="replace").strip()
