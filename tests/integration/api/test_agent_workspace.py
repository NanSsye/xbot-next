import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from xbot.agent.runtime import AgentRuntime
from xbot.api.v1.agent import WebTurnRequest, stream_web_turn
from xbot.api.v1.router import router
from xbot.app.deps import get_context
from xbot.app.security import ApiTokenAuthMiddleware
from xbot.core.config import AgentConfig, Settings
from xbot.core.exceptions import XBotError
from xbot.storage.models import Base
from xbot.storage.repositories.agent_repo import AgentRepository

WEB = f"terminal:control-ui:{'a' * 32}"
OTHER_WEB = f"terminal:control-ui:{'b' * 32}"


@pytest.mark.asyncio
async def test_web_agent_stream_and_history(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agent.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def repository():
            async with sessions.begin() as session:
                yield AgentRepository(session)

        runtime = AgentRuntime(AgentConfig(), None, None, repository_provider=repository)
        started, release = asyncio.Event(), asyncio.Event()

        async def run_llm(task_id, text, **_):
            if text == "hold":
                started.set()
                await release.wait()
            if text == "bad":
                raise XBotError("模型回复失败")
            await runtime._add_event("unrelated", "llm.delta", {"delta": "other task"}, persist=False)
            await runtime._add_event(task_id, "llm.delta", {"delta": "回"}, persist=False)
            await runtime._add_event(task_id, "tool.started", {"tool": "read_file", "input": "private"})
            await runtime._add_event(task_id, "llm.delta", {"delta": "复"}, persist=False)
            return "回复"

        monkeypatch.setattr(runtime, "_run_llm", run_llm)
        await runtime.run_task("channel text", source="channel:qq:test:123")
        await runtime.run_task("legacy text", source="terminal:control-ui")
        await runtime.run_task("other web", source=OTHER_WEB)

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        settings = Settings()
        settings.api.auth_enabled = True
        settings.api.token = "test-only-agent-token"
        app.add_middleware(ApiTokenAuthMiddleware, settings=settings)
        app.dependency_overrides[get_context] = lambda: SimpleNamespace(agent=runtime)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1/",
        ) as client:
            assert (await client.get("agent/chat/history")).status_code == 401
            client.headers["Authorization"] = f"Bearer {settings.api.token}"
            assert (await client.get("community/config")).status_code == 404
            payload = {"input": "  重复  ", "source": WEB}
            assert (await client.post("agent/chat/stream", json={**payload, "input": "  "})).status_code == 422
            assert (await client.post("agent/chat/stream", json={**payload, "source": "channel:qq:test:123"})).status_code == 422

            ids = []
            for _ in range(2):
                response = await client.post("agent/chat/stream", json=payload)
                assert response.status_code == 200
                frames = [json.loads(line) for line in response.text.splitlines()]
                assert [frame["type"] for frame in frames] == ["accepted", "delta", "tool.started", "delta", "done"]
                assert frames[2] == {"type": "tool.started", "tool": "read_file"}
                task = frames[-1]["task"]
                assert task["task_id"] == frames[0]["task_id"]
                assert task["output"] == "回复"
                ids.append(task["task_id"])
            failed = await client.post("agent/chat/stream", json={**payload, "input": "bad"})
            failed_task = json.loads(failed.text.splitlines()[-1])["task"]
            assert failed_task["status"] == "failed"

            history = (await client.get("agent/chat/history", params={"source": WEB})).json()["data"]
            assert [row["input"] for row in history] == ["bad", "重复", "重复"]
            assert {row["task_id"] for row in history[1:]} == set(ids)
            page = await client.get("agent/chat/history", params={"source": WEB, "limit": 1, "offset": 1})
            assert page.json()["data"][0]["task_id"] == history[1]["task_id"]
            web = (await client.get("agent/chat/history")).json()["data"]
            assert {row["source"] for row in web} == {WEB, OTHER_WEB, "terminal:control-ui"}
            assert await runtime.list_events(task_id=ids[0])
            assert all(event["type"] != "llm.delta" for event in await runtime.list_events(task_id=ids[0]))

            # ASGITransport buffers response bodies, so drive this stream directly to simulate disconnect.
            response = await stream_web_turn(WebTurnRequest(input="hold", source=WEB), SimpleNamespace(agent=runtime))
            iterator = response.body_iterator
            accepted = json.loads(await anext(iterator))
            worker = runtime.web_turns[WEB]
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                overlap = await client.post("agent/chat/stream", json=payload)
                assert overlap.status_code == 409
                parallel = await client.post("agent/chat/stream", json={**payload, "source": OTHER_WEB})
                assert parallel.status_code == 200
                await iterator.aclose()
                assert not worker.done()
            finally:
                release.set()
                await asyncio.wait_for(worker, timeout=2)
            assert WEB not in runtime.web_turns
            detail = (await client.get(f"agent/tasks/{accepted['task_id']}")).json()["data"]
            assert (detail["task"]["status"], detail["task"]["output"]) == ("completed", "回复")
    finally:
        await engine.dispose()
