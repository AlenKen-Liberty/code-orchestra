from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

try:
    import aiohttp
except ModuleNotFoundError:  # pragma: no cover - exercised in import-only environments
    aiohttp = None

from common.models import AgentManifest, Message, Run
from config import settings

logger = logging.getLogger(__name__)


class ACPClient:
    def __init__(self, base_url: str, timeout: float | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout if timeout is not None else settings.HTTP_TIMEOUT
        self._session: Any | None = None

    async def ping(self) -> bool:
        data = await self._request_json("GET", "/ping")
        return data.get("status") == "ok"

    async def list_agents(self) -> list[AgentManifest]:
        data = await self._request_json("GET", "/agents")
        return [AgentManifest.from_dict(item) for item in data]

    async def create_run(
        self,
        agent_name: str,
        messages: list[Message],
        session_id: str | None = None,
        mode: str = "sync",
    ) -> Run:
        payload = {
            "agent_name": agent_name,
            "input": [m.to_dict() for m in messages],
            "session_id": session_id,
            "mode": mode,
        }
        data = await self._request_json("POST", "/runs", json_data=payload)
        return Run.from_dict(data)

    async def get_run(self, run_id: str) -> Run:
        data = await self._request_json("GET", f"/runs/{run_id}")
        return Run.from_dict(data)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    @asynccontextmanager
    async def session(self) -> str:
        session_id = uuid.uuid4().hex[:12]
        yield session_id

    async def _get_session(self) -> aiohttp.ClientSession:
        if aiohttp is None:
            raise RuntimeError("aiohttp is required to use ACPClient. Install it before making ACP requests.")
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _request_json(self, method: str, path: str, json_data: dict | None = None) -> object:
        if aiohttp is None:
            raise RuntimeError("aiohttp is required to use ACPClient. Install it before making ACP requests.")
        url = f"{self._base_url}{path}"
        for attempt in range(settings.MAX_RETRIES + 1):
            try:
                session = await self._get_session()
                async with session.request(method, url, json=json_data) as response:
                    if response.status >= 500 and attempt < settings.MAX_RETRIES:
                        await asyncio.sleep(settings.RETRY_BACKOFF)
                        continue
                    if response.status >= 400:
                        error_text = await response.text()
                        raise RuntimeError(f"ACP request failed with status {response.status}: {error_text}")
                    try:
                        return await response.json()
                    except aiohttp.ContentTypeError:
                        text = await response.text()
                        return json.loads(text)
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
                if attempt < settings.MAX_RETRIES:
                    await asyncio.sleep(settings.RETRY_BACKOFF)
                    continue
                logger.error("ACP request failed: %s %s (%s)", method, url, exc)
                raise
        raise RuntimeError("ACP request failed after retries")
