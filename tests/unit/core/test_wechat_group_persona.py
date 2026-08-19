from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from xbot.api.v1.wechat import (
    WechatConversationPersonaUpdate,
    get_wechat_conversation_persona,
    reset_wechat_conversation_persona_session,
    update_wechat_conversation_persona,
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
        settings=SimpleNamespace(
            agent=SimpleNamespace(
                llm=SimpleNamespace(
                    model="model-default",
                    enabled_models=["model-default", "model-group"],
                )
            )
        ),
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
    saved = await update_wechat_conversation_persona(
        conversation_id,
        WechatConversationPersonaUpdate(enabled=True, prompt=" 你叫小群，只说简短中文。 ", model="model-group"),
        persona_context,
    )
    loaded = await get_wechat_conversation_persona(conversation_id, persona_context)

    assert saved["data"]["enabled"] is True
    assert loaded["data"]["prompt"] == "你叫小群，只说简短中文。"
    assert loaded["data"]["model"] == "model-group"
    assert loaded["data"]["default_model"] == "model-default"
    assert loaded["data"]["enabled_models"] == ["model-default", "model-group"]
    assert loaded["data"]["updated_at"]
    assert persona_context.agent.sources == ["channel:wechat:wechat869:group-1@chatroom"]

    disabled = await update_wechat_conversation_persona(
        conversation_id,
        WechatConversationPersonaUpdate(enabled=False, prompt=loaded["data"]["prompt"], model=None),
        persona_context,
    )
    assert disabled["data"]["enabled"] is False
    assert disabled["data"]["prompt"] == loaded["data"]["prompt"]
    assert disabled["data"]["model"] is None
    assert persona_context.agent.sources == [
        "channel:wechat:wechat869:group-1@chatroom",
        "channel:wechat:wechat869:group-1@chatroom",
    ]


@pytest.mark.anyio
async def test_private_persona_can_be_saved_and_read(persona_context):
    conversation_id = "wechat:wechat869:private:user-1"

    saved = await update_wechat_conversation_persona(
        conversation_id,
        WechatConversationPersonaUpdate(
            enabled=True,
            prompt="你是这个联系人的专属法律顾问。",
            model="model-group",
        ),
        persona_context,
    )
    loaded = await get_wechat_conversation_persona(conversation_id, persona_context)

    assert saved["data"]["scope"] == "private"
    assert loaded["data"]["enabled"] is True
    assert loaded["data"]["prompt"] == "你是这个联系人的专属法律顾问。"
    assert loaded["data"]["model"] == "model-group"
    assert persona_context.agent.sources == ["channel:wechat:wechat869:user-1"]


@pytest.mark.anyio
async def test_conversation_persona_rejects_empty_prompt_and_disabled_model(persona_context):
    with pytest.raises(HTTPException, match="人设内容不能为空"):
        await update_wechat_conversation_persona(
            "wechat:wechat869:group:group-1@chatroom",
            WechatConversationPersonaUpdate(enabled=True, prompt="   "),
            persona_context,
        )
    with pytest.raises(HTTPException, match="不在管理员启用的模型池"):
        await update_wechat_conversation_persona(
            "wechat:wechat869:group:group-1@chatroom",
            WechatConversationPersonaUpdate(enabled=False, prompt="", model="not-allowed"),
            persona_context,
        )


@pytest.mark.anyio
async def test_persona_session_reset_targets_only_selected_conversation(persona_context):
    result = await reset_wechat_conversation_persona_session(
        "wechat:wechat869:group:group-1@chatroom",
        persona_context,
    )

    assert result["data"]["session_id"] == "cleared"
    assert persona_context.agent.sources == ["channel:wechat:wechat869:group-1@chatroom"]
