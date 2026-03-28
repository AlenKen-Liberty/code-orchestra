from __future__ import annotations

import asyncio

from config import settings


async def invoke_gemini(
    prompt: str,
    *,
    model: str | None = None,
    cwd: str | None = None,
) -> str:
    command = [
        "gemini",
        "--model",
        model or settings.GEMINI_MODEL,
        "-y",   # yolo mode: auto-approve all tool calls (write_file, shell, etc.)
    ]
    if cwd:
        command.extend(["--cwd", cwd])
    command.extend(["-p", prompt])

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace") or "Gemini CLI invocation failed")
    return stdout.decode("utf-8", errors="replace").strip()
