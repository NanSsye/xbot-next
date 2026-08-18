from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from xbot.api.v1.wechat import (
    WechatGroupPersonaUpdate,
    get_wechat_group_persona,
    reset_wechat_group_persona_session,
    update_wechat_group_persona,
)
from xbot.storage.models import Base, ConversationRecord


@pytest.fixture
async def persona_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(ConversationRecord(
            id="wechat:wechat869:group:group-1@chatroom",
            platform="wechat",
            adapter="wechat869",
            scope="group",
            raw_id="group-1@chatroom",
            title="测试群",
        ))
        session.add(ConversationRecord(
            id="wechat:wechat869:private:user-1",
            platform="wechat",
            adapter="wechat869",
            scope="private",
            raw_id="user-1",
        ))

    class Agent:
        def __init__(self):
            self.sources = []

        def clear_session_history(self, source):
            self.sources.append(source)
            return {"session_id": "cleared"}

    ctx = SimpleNamespace(
        storage=SimpleNamespace(session_factory=factory),
        agent=Agent(),
    )
    try:
        yield ctx
    finally:
        await engine.dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_group_persona_can_be_saved_read_and_disabled(persona_context):
    conversation_id = "wechat:wechat869:group:group-1@chatroom"
    saved = await update_wechat_group_persona(
        conversation_id,
        WechatGroupPersonaUpdate(enabled=True, prompt=" 你叫小群，只说简短中文。 "),
        persona_context,
    )
    loaded = await get_wechat_group_persona(conversation_id, persona_context)

    assert saved["data"]["enabled"] is True
    assert loaded["data"]["prompt"] == "你叫小群，只说简短中文。"
    assert loaded["data"]["updated_at"]
    assert persona_context.agent.sources == ["channel:wechat:wechat869:group-1@chatroom"]

    disabled = await update_wechat_group_persona(
        conversation_id,
        WechatGroupPersonaUpdate(enabled=False, prompt=loaded["data"]["prompt"]),
        persona_context,
    )
    assert disabled["data"]["enabled"] is False
    assert disabled["data"]["prompt"] == loaded["data"]["prompt"]
    assert persona_context.agent.sources == [
        "channel:wechat:wechat869:group-1@chatroom",
        "channel:wechat:wechat869:group-1@chatroom",
    ]


@pytest.mark.anyio
async def test_group_persona_rejects_empty_enabled_prompt_and_private_chat(persona_context):
    with pytest.raises(HTTPException, match="人设内容不能为空"):
        await update_wechat_group_persona(
            "wechat:wechat869:group:group-1@chatroom",
            WechatGroupPersonaUpdate(enabled=True, prompt="   "),
            persona_context,
        )
    with pytest.raises(HTTPException, match="only available for WeChat groups"):
        await get_wechat_group_persona(
            "wechat:wechat869:private:user-1",
            persona_context,
        )


@pytest.mark.anyio
async def test_group_persona_session_reset_targets_only_selected_group(persona_context):
    result = await reset_wechat_group_persona_session(
        "wechat:wechat869:group:group-1@chatroom",
        persona_context,
    )

    assert result["data"]["session_id"] == "cleared"
    assert persona_context.agent.sources == ["channel:wechat:wechat869:group-1@chatroom"]
