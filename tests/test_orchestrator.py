import asyncio
import importlib

import pytest

from common.models import Message, MessagePart, Run, RunStatus
from common.session_store import SessionStore


def test_imports() -> None:
    modules = [
        "config.settings",
        "common.models",
        "common.session_store",
        "common.acp_server",
        "common.acp_client",
        "agents.claude_code_wrapper",
        "agents.codex_wrapper",
        "agents.claude_code_server",
        "agents.codex_server",
        "orchestrator.multi_agent_orchestrator",
    ]
    for module_name in modules:
        importlib.import_module(module_name)


def test_message_run_roundtrip() -> None:
    part = MessagePart(content="hello")
    message = Message(role="user", parts=[part])
    run = Run(
        agent_name="test_agent",
        session_id="session123",
        status=RunStatus.COMPLETED,
        input_messages=[message],
        output_messages=[message],
    )
    data = run.to_dict()
    loaded = Run.from_dict(data)
    assert loaded.agent_name == run.agent_name
    assert loaded.session_id == run.session_id
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.input_messages[0].text == "hello"


def test_session_store_basic(tmp_path) -> None:
    async def _run() -> None:
        store = SessionStore(persist_to_disk=False, data_dir=str(tmp_path))
        session = await store.get_or_create(None)
        assert session.session_id

        message = Message(role="user", parts=[MessagePart(content="hi")])
        await store.append_message(session.session_id, message)

        history = await store.load_history(session.session_id)
        assert len(history) == 1
        assert history[0].text == "hi"

        state = {"foo": "bar"}
        await store.store_state(session.session_id, state)
        loaded_state = await store.load_state(session.session_id)
        assert loaded_state == state

    asyncio.run(_run())


@pytest.mark.integration
def test_integration_placeholder() -> None:
    assert True
