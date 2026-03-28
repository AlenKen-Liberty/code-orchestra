from __future__ import annotations

import asyncio


async def invoke_claude(
    prompt: str,
    *,
    model: str,
    allowed_tools: list[str] | None = None,
    cwd: str | None = None,
) -> str:
    command = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--model",
        model,
    ]
    if allowed_tools:
        command.extend(["--allowedTools", ",".join(allowed_tools)])
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
        raise RuntimeError(stderr.decode("utf-8", errors="replace") or "Claude CLI invocation failed")
    return stdout.decode("utf-8", errors="replace").strip()
