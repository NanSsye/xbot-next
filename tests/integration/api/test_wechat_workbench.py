from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from xbot.adapters.wechat869.client import Wechat869Client
from xbot.api.v1.wechat import router
from xbot.app.deps import get_context
from xbot.core.config import Settings, StorageConfig
from xbot.messaging.models import Message, Reply
from xbot.runtime.context import build_context
from xbot.runtime.scheduler import enqueue_reply
from xbot.storage.models import ContactRecord, ReplyOutboxRecord

PEER = "wxid_test_peer"
CONVERSATION = f"wechat:wechat869:private:{PEER}"
AVATAR = "https://example.test/wechat-avatar.jpg"


@pytest.fixture
async def workbench(tmp_path):
    settings = Settings(storage=StorageConfig(type="sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'workbench.db'}"))
    settings.adapters.wechat869.enabled = True
    ctx = build_context(settings)
    await ctx.storage.init_schema()
    try:
        wx = Wechat869Client("localhost", 8080)
        wx.call_path = AsyncMock()
        ctx.adapters.get("wechat869").client = wx
        incoming = Message(platform="wechat", adapter="wechat869", conversation_id=PEER,
                           sender_id=PEER, sender_name="测试联系人", content="测试消息")
        await ctx.conversations.touch(incoming)
        await ctx.conversations.append_message(PEER, incoming)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_context] = lambda: ctx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
            yield ctx, wx.call_path, api
    finally:
        await ctx.storage.close()


@pytest.mark.anyio
async def test_private_sync_reports_and_applies_869_avatar(workbench):
    ctx, call, api = workbench
    async with ctx.storage.session_factory.begin() as session:
        session.add(ContactRecord(platform="wechat", adapter="wechat_ilink", user_id=PEER,
                                  avatar_url="https://example.test/wrong-channel.jpg"))
    call.return_value = {"ContactList": [
        {"UserName": {"str": PEER}, "SmallHeadImgUrl": {"str": AVATAR}},
        {"UserName": {"str": "unrequested"}, "BigHeadImgUrl": "https://example.test/unrequested.jpg"},
    ]}
    response = await api.post("/sync")
    assert response.json()["data"]["private_avatars_received"] == 1
    call.assert_awaited_once_with("/friend/GetContactDetailsList", body={"UserNames": [PEER]})
    assert (await api.get("/conversations")).json()["data"][0]["avatar_url"] == AVATAR
    history = (await api.get(f"/conversations/{CONVERSATION}/messages")).json()["data"]
    assert history[0]["sender_avatar_url"] == AVATAR
    async with ctx.storage.session_factory() as session:
        assert await session.scalar(select(ContactRecord.id).where(ContactRecord.user_id == "unrequested")) is None
    assert (await api.post("/sync")).json()["data"]["updated_contacts"] == 0

    call.return_value = {"ContactList": [{"UserName": PEER, "BigHeadImgUrl": "javascript:invalid"}]}
    assert (await api.post("/sync")).json()["data"]["private_avatars_received"] == 0
    assert (await api.get("/conversations")).json()["data"][0]["avatar_url"] == AVATAR
    call.side_effect = TimeoutError
    assert (await api.post("/sync")).status_code == 502


@pytest.mark.anyio
async def test_confirmed_bot_and_manual_sends_persist_once_and_publish(workbench):
    ctx, call, api = workbench
    published = AsyncMock()
    ctx.events.subscribe("message.created", published)
    reply = Reply(platform="wechat", adapter="wechat869", conversation_id=PEER, content="自动回复")

    for rejected in ({"Ret": -1, "NewMsgId": 40}, {}):
        call.return_value = [rejected]
        with pytest.raises(RuntimeError, match="869"):
            await ctx.engine.send_reply(reply)
    published.assert_not_awaited()
    assert (await api.get(f"/conversations/{CONVERSATION}/messages")).json()["data"][0]["content"] == "测试消息"

    call.return_value = [{"NewMsgId": 41}]
    await ctx.engine.send_reply(reply)
    call.return_value = [{"resp": {"chat_send_ret_list": [{"ret": 0, "NewMsgId": 42}]}}]
    async with ctx.storage.session_factory.begin() as session:
        assert await enqueue_reply(session, reply.model_copy(update={"content": "队列回复"}),
                                   idempotency_key="workbench-test", source="test")
    assert await ctx.scheduler.dispatch_outbox_once() == 1
    assert await ctx.scheduler.dispatch_outbox_once() == 0
    async with ctx.storage.session_factory() as session:
        outbox = await session.scalar(select(ReplyOutboxRecord))
        assert (outbox.status, outbox.platform_message_id) == ("sent", "42")
    call.return_value = [{"NewMsgId": 43}]
    response = await api.post(f"/conversations/{CONVERSATION}/send", data={"text": "手动回复"})
    assert response.status_code == 200

    history = (await api.get(f"/conversations/{CONVERSATION}/messages")).json()["data"]
    assert [m["content"] for m in history] == ["测试消息", "自动回复", "队列回复", "手动回复"]
    assert [m["raw"]["direction"] for m in history[1:]] == ["outgoing"] * 3
    events = [c.args[0]["message"] for c in published.await_args_list]
    assert [m["id"] for m in events] == [m["id"] for m in history[1:]]
    assert {m["conversation_id"] for m in events} == {CONVERSATION}
    assert response.json()["data"]["id"] == history[-1]["id"]
