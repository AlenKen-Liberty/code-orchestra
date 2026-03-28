from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

try:
    from aiohttp import web
except ModuleNotFoundError:  # pragma: no cover - exercised in import-only environments
    web = None

from common.models import AgentManifest, Message, MessagePart, Run, RunStatus, Session
from common.session_store import SessionStore
from config import settings

logger = logging.getLogger(__name__)

AgentHandler = Callable[[list[Message], "AgentContext"], Awaitable[list[MessagePart]]]


@dataclass
class AgentRegistration:
    manifest: AgentManifest
    handler: AgentHandler


class AgentContext:
    def __init__(self, session: Session, run: Run) -> None:
        self.session = session
        self.run = run

    @property
    def session_history_as_prompt(self) -> str:
        blocks: list[str] = []
        for message in self.session.history:
            text = message.text
            if text:
                blocks.append(f"[{message.role}]: {text}")
        return "\n\n".join(blocks)


class ACPServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        persist_to_disk: bool | None = None,
        data_dir: str | None = None,
    ) -> None:
        if web is None:
            raise RuntimeError("aiohttp is required to run ACPServer. Install it before starting server components.")
        self._host = host
        self._port = port
        self._runs: dict[str, Run] = {}
        self._agents: dict[str, AgentRegistration] = {}
        self._app: Any = web.Application()
        self._runner: Any = None
        self._site: Any = None

        persist = settings.SESSION_PERSIST_TO_DISK if persist_to_disk is None else persist_to_disk
        data_path = settings.SESSION_DATA_DIR if data_dir is None else data_dir
        self._session_store = SessionStore(persist_to_disk=persist, data_dir=data_path)

        self._setup_routes()

    def agent(self, name: str, description: str, metadata: dict | None = None) -> Callable[[AgentHandler], AgentHandler]:
        def decorator(handler: AgentHandler) -> AgentHandler:
            if name in self._agents:
                raise ValueError(f"Agent already registered: {name}")
            manifest = AgentManifest(name=name, description=description, metadata=metadata)
            self._agents[name] = AgentRegistration(manifest=manifest, handler=handler)
            return handler

        return decorator

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        logger.info("ACPServer running on %s:%s", self._host, self._port)
        await asyncio.Event().wait()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    def _setup_routes(self) -> None:
        self._app.add_routes(
            [
                web.get("/ping", self._handle_ping),
                web.get("/agents", self._handle_list_agents),
                web.get(r"/agents/{name}", self._handle_get_agent),
                web.post("/runs", self._handle_create_run),
                web.get(r"/runs/{run_id}", self._handle_get_run),
            ]
        )

    async def _handle_ping(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_list_agents(self, request: web.Request) -> web.Response:
        manifests = [reg.manifest.to_dict() for reg in self._agents.values()]
        return web.json_response(manifests)

    async def _handle_get_agent(self, request: web.Request) -> web.Response:
        name = request.match_info.get("name")
        if not name or name not in self._agents:
            return web.json_response({"error": "agent not found"}, status=404)
        manifest = self._agents[name].manifest.to_dict()
        return web.json_response(manifest)

    async def _handle_create_run(self, request: web.Request) -> web.Response:
        start_time = time.time()
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        agent_name = payload.get("agent_name")
        if not agent_name:
            return web.json_response({"error": "agent_name required"}, status=400)
        registration = self._agents.get(agent_name)
        if registration is None:
            return web.json_response({"error": "agent not found"}, status=404)

        input_messages = [Message.from_dict(m) for m in payload.get("input", [])]
        session_id = payload.get("session_id")
        run = Run(agent_name=agent_name, session_id=session_id, status=RunStatus.IN_PROGRESS)
        run.input_messages = input_messages
        self._runs[run.run_id] = run

        session = await self._session_store.get_or_create(session_id)
        run.session_id = session.session_id

        for message in input_messages:
            await self._session_store.append_message(session.session_id, message)

        context = AgentContext(session=session, run=run)
        try:
            output_parts = await registration.handler(input_messages, context)
            output_message = Message(role=f"agent/{agent_name}", parts=output_parts)
            await self._session_store.append_message(session.session_id, output_message)
            run.output_messages = [output_message]
            run.status = RunStatus.COMPLETED
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent %s handler failed for run %s", agent_name, run.run_id)
            run.status = RunStatus.FAILED
            run.error = str(exc)
        finally:
            run.updated_at = time.time()
            elapsed_ms = int((run.updated_at - start_time) * 1000)
            logger.info(
                "agent=%s session=%s run=%s status=%s elapsed_ms=%s",
                agent_name,
                run.session_id,
                run.run_id,
                run.status.value,
                elapsed_ms,
            )

        return web.json_response(run.to_dict())

    async def _handle_get_run(self, request: web.Request) -> web.Response:
        run_id = request.match_info.get("run_id")
        run = self._runs.get(run_id)
        if run is None:
            return web.json_response({"error": "run not found"}, status=404)
        return web.json_response(run.to_dict())
