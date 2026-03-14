from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid

from common.models import Session, Message

logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(self, persist_to_disk: bool, data_dir: str) -> None:
        self._persist_to_disk = persist_to_disk
        self._data_dir = data_dir
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        if self._persist_to_disk:
            os.makedirs(self._data_dir, exist_ok=True)

    async def get_or_create(self, session_id: str | None) -> Session:
        async with self._lock:
            return self._get_or_create_locked(session_id)

    async def append_message(self, session_id: str | None, message: Message) -> Session:
        async with self._lock:
            session = self._get_or_create_locked(session_id)
            session.history.append(message)
            session.updated_at = time.time()
            self._persist_session(session)
            return session

    async def load_history(self, session_id: str | None) -> list[Message]:
        async with self._lock:
            session = self._get_or_create_locked(session_id)
            return list(session.history)

    async def load_state(self, session_id: str | None) -> dict:
        async with self._lock:
            session = self._get_or_create_locked(session_id)
            return dict(session.state)

    async def store_state(self, session_id: str | None, state: dict) -> Session:
        async with self._lock:
            session = self._get_or_create_locked(session_id)
            session.state = dict(state)
            session.updated_at = time.time()
            self._persist_session(session)
            return session

    def _get_or_create_locked(self, session_id: str | None) -> Session:
        sid = session_id or uuid.uuid4().hex[:12]
        session = self._sessions.get(sid)
        if session is None and self._persist_to_disk:
            session = self._load_from_disk(sid)
        if session is None:
            session = Session(session_id=sid)
            self._sessions[sid] = session
            self._persist_session(session)
        return session

    def _session_path(self, session_id: str) -> str:
        filename = f"{session_id}.json"
        return os.path.join(self._data_dir, filename)

    def _load_from_disk(self, session_id: str) -> Session | None:
        path = self._session_path(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            session = Session.from_dict(data)
            self._sessions[session_id] = session
            return session
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load session %s: %s", session_id, exc)
            return None

    def _persist_session(self, session: Session) -> None:
        if not self._persist_to_disk:
            return
        path = self._session_path(session.session_id)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(session.to_dict(), handle, indent=2)
        except OSError as exc:
            logger.warning("Failed to persist session %s: %s", session.session_id, exc)
