from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import xbot.community.service as community_service
from xbot.community.config import CommunityConfig
from xbot.community.service import CommunityConflictError, CommunityService
from xbot.community.weiban_token_client import (
    TokenGrantError,
    grant_character_image_count,
    grant_token_pack,
)
from xbot.messaging.models import Message
from xbot.plugins.loader import PluginLoader
from xbot.storage.models import Base, ConversationMessageRecord


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def bind_user(session, *, user_id: str, invite_code: str, adapter: str = "qq"):
    return await CommunityService(session).bind(
        platform="qq",
        adapter=adapter,
        user_id=user_id,
        nickname=f"用户{user_id}",
        conversation_id="qq:group:test",
        invite_code=invite_code,
    )


@pytest.mark.asyncio
async def test_binding_is_idempotent_and_invite_code_cannot_be_claimed_twice(session_factory):
    async with session_factory() as session, session.begin():
        first = await bind_user(session, user_id="user-1", invite_code="ABCDEFG1")
        repeated = await bind_user(session, user_id="user-1", invite_code="ABCDEFG1")

        assert first == {"already_bound": False, "balance": 0}
        assert repeated == {"already_bound": True, "balance": 0}
        with pytest.raises(CommunityConflictError, match="已绑定其他 QQ 用户"):
            await bind_user(session, user_id="user-2", invite_code="ABCDEFG1")


@pytest.mark.asyncio
async def test_checkin_is_idempotent(session_factory):
    config = CommunityConfig(
        checkin_base_reward=5,
        checkin_streak_3_bonus=3,
    )
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="user-1", invite_code="ABCDEFG1")
        service = CommunityService(session)
        first = await service.checkin(
            platform="qq",
            adapter="qq",
            user_id="user-1",
            nickname="甲",
            conversation_id="qq:group:test",
            config=config,
        )
        repeated = await service.checkin(
            platform="qq",
            adapter="qq",
            user_id="user-1",
            nickname="甲",
            conversation_id="qq:group:test",
            config=config,
        )

        assert first["reward"] == 5
        assert repeated == {"already": True, "streak": 1, "reward": 5, "balance": 5}


@pytest.mark.asyncio
async def test_activity_ranking_uses_message_count_then_reach_time(session_factory):
    config = CommunityConfig(activity_min_messages=2)
    base = datetime(2026, 8, 10, 1, 0, 0, tzinfo=UTC)
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="user-1", invite_code="ABCDEFG1")
        await bind_user(session, user_id="user-2", invite_code="ABCDEFG2")
        for user_id, nickname, offsets in (
            ("user-1", "甲", (0, 2)),
            ("user-2", "乙", (1, 3)),
        ):
            for index, offset in enumerate(offsets):
                session.add(
                    ConversationMessageRecord(
                        conversation_id="qq:group:test",
                        message_id=f"{user_id}-{index}",
                        platform="qq",
                        adapter="qq",
                        sender_id=user_id,
                        sender_name=nickname,
                        type="text",
                        content="有效发言",
                        raw_json="{}",
                        created_at=base + timedelta(minutes=offset),
                    )
                )
        await session.flush()

        rows = await CommunityService(session).activity_ranking(
            "qq:group:test",
            base.date(),
            config,
        )

        assert [row["nickname"] for row in rows] == ["甲", "乙"]
        assert [row["message_count"] for row in rows] == [2, 2]


@pytest.mark.asyncio
async def test_activity_settlement_is_idempotent(session_factory):
    config = CommunityConfig(activity_min_messages=1, activity_rewards=[20, 15, 10, 5, 3])
    created_at = datetime(2026, 8, 10, 2, 0, 0, tzinfo=UTC)
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="user-1", invite_code="ABCDEFG1")
        session.add(
            ConversationMessageRecord(
                conversation_id="qq:group:test",
                message_id="message-1",
                platform="qq",
                adapter="qq",
                sender_id="user-1",
                sender_name="甲",
                type="text",
                content="有效发言",
                raw_json="{}",
                created_at=created_at,
            )
        )
        await session.flush()
        service = CommunityService(session)

        first = await service.settle_activity_day(created_at.date(), config)
        repeated = await service.settle_activity_day(created_at.date(), config)
        account = await service.account_summary("qq", "qq", "user-1")

        assert first[0]["awards"][0]["reward"] == 20
        assert repeated == []
        assert account["balance"] == 20


@pytest.mark.asyncio
async def test_daily_sixty_message_milestone_awards_once(session_factory):
    config = CommunityConfig(
        activity_milestone_enabled=True,
        activity_milestone_messages=60,
        activity_milestone_reward=5,
    )
    created_at = datetime.now(UTC).replace(tzinfo=None)
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="user-1", invite_code="ABCDEFG1")
        session.add_all(
            [
                ConversationMessageRecord(
                    conversation_id="qq:group:test",
                    message_id=f"message-{index}",
                    platform="qq",
                    adapter="qq",
                    sender_id="user-1",
                    sender_name="甲",
                    type="text",
                    content="有效发言",
                    raw_json="{}",
                    created_at=created_at,
                )
                for index in range(60)
            ]
        )
        await session.flush()
        service = CommunityService(session)

        first = await service.award_activity_milestone(
            platform="qq",
            adapter="qq",
            user_id="user-1",
            conversation_id="qq:group:test",
            config=config,
        )
        repeated = await service.award_activity_milestone(
            platform="qq",
            adapter="qq",
            user_id="user-1",
            conversation_id="qq:group:test",
            config=config,
        )
        account = await service.account_summary("qq", "qq", "user-1")

        assert first["awarded"] is True
        assert first["message_count"] == 60
        assert first["reward"] == 5
        assert repeated["awarded"] is False
        assert account["balance"] == 5


@pytest.mark.asyncio
async def test_admin_ledger_does_not_duplicate_multi_channel_account(session_factory):
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="qq-user", invite_code="ABCDEFG1")
        await bind_user(
            session,
            user_id="wechat-user",
            invite_code="ABCDEFG1",
            adapter="wechat_ilink",
        )
        service = CommunityService(session)
        account = await service.account_summary("qq", "qq", "qq-user")
        await service.adjust_points(account["account_id"], 8, "人工补发")

        rows = await service.admin_ledger()

        assert len(rows) == 1
        assert rows[0]["delta"] == 8


@pytest.mark.asyncio
async def test_config_update_reloads_plugin_and_is_visible_to_new_sessions(session_factory):
    from xbot.api.v1.community import update_config

    reloads: list[str] = []

    async def reload_plugin(name: str) -> bool:
        reloads.append(name)
        return True

    context = SimpleNamespace(
        storage=SimpleNamespace(session_factory=session_factory),
        plugins=SimpleNamespace(reload=reload_plugin),
    )
    payload = CommunityConfig(enabled_adapters=["qq", "wechat_ilink"], rps_win_reward=8)

    response = await update_config(payload, context)

    assert reloads == ["WeibanCommunity"]
    assert response["data"]["rps_win_reward"] == 8
    async with session_factory() as session, session.begin():
        loaded, _ = await CommunityService(session).get_config()
    assert loaded.enabled_adapters == ["qq", "wechat_ilink"]


@pytest.mark.asyncio
async def test_plugin_does_not_claim_unrecognized_agent_conversation():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig()
    message = Message(
        id="ordinary-message",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        content="@小x 帮我分析一下这个问题",
        raw={"scope": "group", "mentions_bot": True, "bot_name": "小x"},
    )

    result = await plugin.on_message(message, SimpleNamespace())

    assert result is False


@pytest.mark.asyncio
async def test_plugin_formats_qq_help_as_keyboard_with_text_fallback():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig()
    message = Message(
        id="help-message",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="小银pro",
        content="@小x 社区帮助",
        raw={"scope": "group", "mentions_bot": True, "bot_name": "小x"},
    )

    result = await plugin.on_message(message, SimpleNamespace())

    assert result.type == "keyboard"
    assert result.content.startswith("@小银pro\n\n**🎮 微伴社区 · 今日菜单**")
    assert "`绑定 8位邀请码`" in result.content
    assert result.metadata["fallback_text"].startswith("微伴社区玩法")
    rows = result.metadata["keyboard"]["content"]["rows"]
    assert [len(row["buttons"]) for row in rows] == [2, 2, 2, 2, 2]
    assert [
        button["action"]["data"]
        for row in rows
        for button in row["buttons"]
    ] == [
        "签到",
        "会员信息",
            "我的积分",
            "积分明细",
            "游戏中心",
            "积分排行",
            "今日发言排行",
            "兑换Token",
            "今日运势",
            "发红包",
        ]
    assert rows[0]["buttons"][0]["render_data"]["label"] == "✅ 每日签到"


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["菜单", "帮助", "社区菜单"])
async def test_plugin_routes_exact_qq_help_without_mention(command):
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig(require_mention=True)
    message = Message(
        id=f"public-help-{command}",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="小银pro",
        content=command,
        raw={"scope": "group", "mentions_bot": False, "bot_name": "小x"},
    )

    result = await plugin.on_message(message, SimpleNamespace())

    assert result.type == "keyboard"
    assert result.content.startswith("@小银pro\n\n**🎮 微伴社区 · 今日菜单**")
    assert result.quote_message_id == message.id


@pytest.mark.asyncio
async def test_plugin_routes_qq_button_interaction_without_mention():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig()
    message = Message(
        id="interaction-1",
        platform="qq",
        adapter="qq",
        type="event",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="小银pro",
        content="ignored",
        raw={
            "scope": "group",
            "mentions_bot": False,
            "qq_event_type": "INTERACTION_CREATE",
            "interaction_type": 11,
            "button_data": "社区帮助",
            "event_id": "interaction-1",
        },
    )

    result = await plugin.on_message(message, SimpleNamespace())

    assert result.type == "keyboard"
    assert result.content.startswith("@小银pro\n\n**🎮 微伴社区")
    assert result.metadata["event_id"] == "interaction-1"
    assert result.quote_message_id is None


@pytest.mark.asyncio
async def test_plugin_accepts_common_binding_formats(monkeypatch):
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    calls = []

    async def fake_bind(message, invite_code):
        calls.append(invite_code)
        return "ok"

    monkeypatch.setattr(plugin, "_bind", fake_bind)
    message = Message(
        id="bind-message",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        content="",
        raw={"scope": "group", "mentions_bot": True},
    )

    commands = (
        "绑定ABCD1234",
        "绑定 ABCD1234",
        "绑定+ABCD1234",
        "+绑定ABCD1234",
        "绑定 邀请码 ABCD1234",
        "ABCD1234绑定",
        "ABCD1234 绑定",
    )
    for command in commands:
        assert await plugin._dispatch_command(message, command) == "ok"
    assert calls == ["ABCD1234"] * len(commands)
    assert "8 位永久邀请码" in await plugin._dispatch_command(message, "绑定123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    ["绑定ABCD1234", "绑定 ABCD1234", "绑定+ABCD1234", "ABCD1234绑定"],
)
async def test_plugin_routes_unmentioned_qq_binding_command(command, monkeypatch):
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig(require_mention=True)

    async def fake_bind(message, invite_code):
        return f"已绑定 {invite_code}"

    monkeypatch.setattr(plugin, "_bind", fake_bind)
    message = Message(
        id=f"public-bind-{command}",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="小银pro",
        content=command,
        raw={"scope": "group", "mentions_bot": False, "bot_name": "小x"},
    )

    result = await plugin.on_message(message, SimpleNamespace())

    assert result.type == "keyboard"
    assert "🔗 账号绑定" in result.content
    assert "已绑定 ABCD1234" in result.content
    assert result.quote_message_id == message.id


@pytest.mark.asyncio
async def test_plugin_accepts_plus_between_mention_and_binding(monkeypatch):
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig(require_mention=True)

    async def fake_bind(message, invite_code):
        return f"已绑定 {invite_code}"

    monkeypatch.setattr(plugin, "_bind", fake_bind)
    message = Message(
        id="mentioned-plus-bind",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="小银pro",
        content="@小x+绑定ABCD1234",
        raw={"scope": "group", "mentions_bot": True, "bot_name": "小x"},
    )

    result = await plugin.on_message(message, SimpleNamespace())

    assert "已绑定 ABCD1234" in result.content


@pytest.mark.asyncio
async def test_plugin_does_not_wake_for_unmentioned_binding_conversation():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig(require_mention=True)
    message = Message(
        id="ordinary-binding-chat",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        content="这个账号为什么绑定不上",
        raw={"scope": "group", "mentions_bot": False, "bot_name": "小x"},
    )

    assert await plugin.on_message(message, SimpleNamespace()) is False


def test_plugin_formats_rankings_with_medals():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))

    content = plugin._markdown(
        "积分排行",
        '{"day":[{"nickname":"甲","points":5}],'
        '"week":[{"nickname":"甲","points":5}],'
        '"month":[{"nickname":"甲","points":5}],'
        '"total":[{"nickname":"甲","points":20}]}',
    )

    assert "群积分风云榜" in content
    assert "☀️ 今日 · 📅 本周 · 🗓️ 本月" in content
    assert content.count("甲　**+5**") == 1
    assert "当前总榜" in content
    assert "甲　**20 分**" in content


def test_plugin_formats_activity_ranking_with_rules_and_rewards():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    content = plugin._markdown(
        "今日发言排行",
        "今日发言榜\n1. 叶宝  37条\n2. Sanfia Lord  24条",
    )

    assert "今日群聊活跃榜" in content
    assert "仅统计已绑定用户" in content
    assert "🥇 **叶宝**" in content
    assert "`37条`" in content
    assert "暂列奖励 `20 积分`" in content
    assert "次日 00:05" in content
    assert "发言满 60 条" in content


def test_ranking_cards_are_not_auto_recalled():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    message = Message(
        id="ranking-card",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="甲",
        content="今日发言排行",
        raw={"scope": "group", "mentions_bot": True},
    )

    for command in ("积分排行", "总榜", "周榜", "月榜", "今日发言排行", "昨日发言排行"):
        reply = plugin._reply(message, command, "暂无数据")
        assert "auto_recall_seconds" not in reply.metadata


def test_plugin_formats_member_level_and_quota_without_identity_data():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))

    content = plugin._format_member_card(
        {
            "is_active": True,
            "plan_code": "pro",
            "plan_expires_at": "2026-12-31T00:00:00Z",
            "token_usage": {
                "five_hour": {"usage": 2, "limit": 10, "remaining": 8, "unlimited": False},
                "weekly": {"usage": 5, "limit": 0, "remaining": None, "unlimited": True},
                "monthly": {
                    "usage": 75,
                    "limit": 100,
                    "remaining": 25,
                    "unlimited": False,
                    "reset_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                    "reset_known": True,
                },
            },
            "token_wallet": {
                "usage": 20,
                "limit": 100_000,
                "remaining": 99_980,
                "unlimited": False,
            },
            "character_image": {
                "limit": 12,
                "used": 3,
                "remaining": 9,
                "period": "lifetime",
            },
        },
        66,
    )

    assert "会员等级：👑 Pro" in content
    assert "有效期至：2026-12-31" in content
    assert "本周：不限量（已用 5）" in content
    assert "本月：75 / 100，剩余 25" in content
    assert "后重置 ·" in content
    assert "加油包 TOKEN：20 / 100,000，剩余 99,980" in content
    assert "手动生图：已用 3 / 12 次，剩余 9 次" in content
    assert "社区积分：🪙 66" in content


@pytest.mark.asyncio
async def test_token_exchange_opens_second_level_card_with_four_tiers():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig(token_exchange_enabled=True)
    message = Message(
        id="token-menu",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="小银pro",
        content="兑换Token",
        raw={"scope": "group", "mentions_bot": True, "bot_name": "小x"},
    )

    result = await plugin.on_message(message, SimpleNamespace())

    assert result.type == "keyboard"
    assert "100 积分兑换 100,000 Token" in result.content
    assert "1,000 积分兑换 1,100,000 Token" in result.content
    assert "200 积分兑换 1 次" in result.content
    rows = result.metadata["keyboard"]["content"]["rows"]
    assert any(
        button["action"]["data"] == "兑换生图:200"
        for row in rows
        for button in row["buttons"]
    )
    assert [button["action"]["data"] for row in rows for button in row["buttons"]] == [
        "兑换Token:100",
        "兑换Token:200",
        "兑换Token:500",
        "兑换Token:1000",
        "兑换生图:200",
        "兑换生图:1000",
        "社区帮助",
    ]


@pytest.mark.asyncio
async def test_character_image_exchange_charges_points_and_grants_once(
    session_factory, monkeypatch
):
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="image-user", invite_code="IMAGE001")
        account = await CommunityService(session).account_summary("qq", "qq", "image-user")
        await CommunityService(session).adjust_points(account["account_id"], 1_000, "测试充值")
    loader = PluginLoader()
    plugin = loader.load_instance(Path("plugins/WeibanCommunity"), loader.load_manifest(Path("plugins/WeibanCommunity")))
    plugin.config = CommunityConfig(token_exchange_enabled=True)

    @asynccontextmanager
    async def repository_provider():
        async with session_factory() as session, session.begin():
            yield SimpleNamespace(session=session)

    plugin.ctx = SimpleNamespace(conversations=SimpleNamespace(repository_provider=repository_provider))
    granted = {}

    async def fake_grant(**kwargs):
        granted.update(kwargs)
        return {"applied": True, "after": {"remaining": 5}}

    monkeypatch.setattr(plugin, "_load_weiban_env", lambda: None)
    monkeypatch.setitem(plugin._exchange_character_images.__func__.__globals__, "grant_character_image_count", fake_grant)
    message = Message(
        id="image-exchange",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="image-user",
        sender_name="生图用户",
        content="兑换生图:1000",
        raw={"scope": "group", "mentions_bot": True},
    )
    result = await plugin.on_message(message, SimpleNamespace())
    assert "已增加 5 次手动生图" in result.content
    assert granted["amount"] == 5
    async with session_factory() as session, session.begin():
        account = await CommunityService(session).account_summary("qq", "qq", "image-user")
        assert account["balance"] == 0
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("points_cost", "token_amount"),
    [(100, 100_000), (200, 210_000), (500, 550_000), (1_000, 1_100_000)],
)
async def test_token_exchange_tier_callback_uses_exact_points_and_tokens(
    session_factory, monkeypatch, points_cost, token_amount
):
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="user-1", invite_code="ABCDEFG1")
        account = await CommunityService(session).account_summary("qq", "qq", "user-1")
        await CommunityService(session).adjust_points(account["account_id"], 2_000, "测试充值")

    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    plugin.config = CommunityConfig(token_exchange_enabled=True)
    @asynccontextmanager
    async def repository_provider():
        async with session_factory() as session, session.begin():
            yield SimpleNamespace(session=session)

    plugin.ctx = SimpleNamespace(
        conversations=SimpleNamespace(repository_provider=repository_provider)
    )
    granted = {}

    async def fake_grant_token_pack(**kwargs):
        granted.update(kwargs)
        return {"applied": True}

    monkeypatch.setattr(plugin, "_load_weiban_env", lambda: None)
    monkeypatch.setitem(
        plugin._exchange_tokens.__func__.__globals__,
        "grant_token_pack",
        fake_grant_token_pack,
    )
    message = Message(
        id=f"token-tier-{points_cost}",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="小银pro",
        content=f"兑换Token:{points_cost}",
        raw={"scope": "group", "mentions_bot": True},
    )

    result = await plugin.on_message(message, SimpleNamespace())

    assert f"已到账 {token_amount:,} Token" in result.content
    assert f"本次消耗 {points_cost} 积分" in result.content
    assert granted["amount_tokens"] == token_amount
    async with session_factory() as session, session.begin():
        account = await CommunityService(session).account_summary("qq", "qq", "user-1")
        assert account["balance"] == 2_000 - points_cost


@pytest.mark.asyncio
async def test_token_exchange_holds_points_once_and_refunds_once(session_factory):
    config = CommunityConfig(token_exchange_enabled=True)
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="user-1", invite_code="ABCDEFG1")
        account = await CommunityService(session).account_summary("qq", "qq", "user-1")
        await CommunityService(session).adjust_points(account["account_id"], 200, "测试充值")

    async with session_factory() as session, session.begin():
        service = CommunityService(session)
        first = await service.begin_token_exchange(
            platform="qq",
            adapter="qq",
            user_id="user-1",
            nickname="甲",
            conversation_id="qq:group:test",
            points_cost=100,
            token_amount=100_000,
            config=config,
        )
        repeated = await service.begin_token_exchange(
            platform="qq",
            adapter="qq",
            user_id="user-1",
            nickname="甲",
            conversation_id="qq:group:test",
            points_cost=100,
            token_amount=100_000,
            config=config,
        )
        account = await service.account_summary("qq", "qq", "user-1")
        assert first["exchange_id"] == repeated["exchange_id"]
        assert repeated["existing"] is True
        assert account["balance"] == 100

    async with session_factory() as session, session.begin():
        service = CommunityService(session)
        await service.fail_token_exchange(first["exchange_id"], "weiban_http_404")
        await service.fail_token_exchange(first["exchange_id"], "weiban_http_404")
        account = await service.account_summary("qq", "qq", "user-1")
        assert account["balance"] == 200


@pytest.mark.asyncio
async def test_token_pack_client_uses_invite_contract_and_idempotency(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "user_id": 123,
                "amount_tokens": 100_000,
                "applied": True,
                "replayed": False,
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, json=json)
            return Response()

    monkeypatch.setenv("WEIBAN_BASE_URL", "https://weiban.example.test/base")
    monkeypatch.setenv("WEIBAN_ADMIN_API_KEY", "secret")
    monkeypatch.setattr(
        "xbot.community.weiban_token_client.httpx.AsyncClient", lambda **kwargs: Client()
    )

    result = await grant_token_pack(
        invite_code="ABCDEFG1",
        amount_tokens=100_000,
        idempotency_key="exchange-1",
        reason="积分兑换",
    )

    assert captured["url"].endswith(
        "/base/api/admin/token-grants"
    )
    assert captured["json"] == {
        "identifier": "ABCDEFG1",
        "amount_tokens": 100_000,
        "idempotency_key": "exchange-1",
        "reason": "积分兑换",
    }
    assert result["applied"] is True


@pytest.mark.asyncio
async def test_token_pack_client_treats_missing_endpoint_as_safe_failure(monkeypatch):
    class Response:
        status_code = 404

        @staticmethod
        def json():
            return {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            return Response()

    monkeypatch.setenv("WEIBAN_BASE_URL", "https://weiban.example.test")
    monkeypatch.setenv("WEIBAN_ADMIN_API_KEY", "secret")
    monkeypatch.setattr(
        "xbot.community.weiban_token_client.httpx.AsyncClient", lambda **kwargs: Client()
    )

    with pytest.raises(TokenGrantError) as caught:
        await grant_token_pack(
            invite_code="ABCDEFG1",
            amount_tokens=100_000,
            idempotency_key="exchange-1",
            reason="积分兑换",
        )

    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_system_red_packet_claims_once_and_completes(session_factory):
    config = CommunityConfig()
    async with session_factory() as session, session.begin():
        for index in range(1, 11):
            await bind_user(
                session,
                user_id=f"user-{index}",
                invite_code=f"ABCDEF{index:02d}",
            )
        service = CommunityService(session)
        packet = await service.create_red_packet(
            platform="qq",
            adapter="qq",
            user_id="admin-1",
            nickname="管理员",
            conversation_id="qq:group:test",
            system_funded=True,
        )
        assert 5 <= packet["packet_count"] <= 10
        assert packet["packet_count"] <= packet["total_points"] <= packet["packet_count"] * 10

        first = await service.claim_red_packet(
            packet_id=packet["packet_id"],
            platform="qq",
            adapter="qq",
            user_id="user-1",
            nickname="甲",
            conversation_id="qq:group:test",
            config=config,
        )
        repeated = await service.claim_red_packet(
            packet_id=packet["packet_id"],
            platform="qq",
            adapter="qq",
            user_id="user-1",
            nickname="甲",
            conversation_id="qq:group:test",
            config=config,
        )
        assert 1 <= first["amount"] <= 10
        assert repeated["duplicate"] is True
        assert repeated["amount"] == first["amount"]

        for index in range(2, packet["packet_count"] + 1):
            last = await service.claim_red_packet(
                packet_id=packet["packet_id"],
                platform="qq",
                adapter="qq",
                user_id=f"user-{index}",
                nickname=f"用户{index}",
                conversation_id="qq:group:test",
                config=config,
            )
        assert last["status"] == "completed"
        assert last["remaining_count"] == 0


@pytest.mark.asyncio
async def test_user_red_packet_requires_confirmation_and_debits_once(session_factory):
    config = CommunityConfig()
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="sender", invite_code="ABCDEFG1")
        await bind_user(session, user_id="receiver", invite_code="ABCDEFG2")
        service = CommunityService(session)
        sender = await service.identity_account("qq", "qq", "sender", lock=True)
        await service.adjust_points(sender[1].id, 100, "测试充值")
        packet = await service.create_red_packet(
            platform="qq",
            adapter="qq",
            user_id="sender",
            nickname="发起人",
            conversation_id="qq:group:test",
            system_funded=False,
        )
        assert packet["status"] == "pending_confirmation"
        assert sender[1].points_balance == 100

        confirmed = await service.confirm_red_packet(
            packet_id=packet["packet_id"],
            platform="qq",
            adapter="qq",
            user_id="sender",
            nickname="发起人",
            conversation_id="qq:group:test",
            config=config,
        )
        repeated = await service.confirm_red_packet(
            packet_id=packet["packet_id"],
            platform="qq",
            adapter="qq",
            user_id="sender",
            nickname="发起人",
            conversation_id="qq:group:test",
            config=config,
        )
        assert confirmed["status"] == "active"
        assert repeated["existing"] is True
        assert sender[1].points_balance == 100 - packet["total_points"]


@pytest.mark.asyncio
async def test_rps_rewards_win_and_draw_without_loss_penalty(
    session_factory, monkeypatch
):
    monkeypatch.setattr(
        community_service,
        "_RANDOM",
        SimpleNamespace(choice=lambda choices: "石头"),
    )
    config = CommunityConfig(rps_win_reward=3, rps_draw_reward=1)
    async with session_factory() as session, session.begin():
        service = CommunityService(session)
        for user_id, invite_code in (
            ("rps-win", "RPSWIN01"),
            ("rps-draw", "RPSDRAW1"),
            ("rps-lose", "RPSLOSE1"),
        ):
            await bind_user(session, user_id=user_id, invite_code=invite_code)
            account = (await service.identity_account("qq", "qq", user_id, lock=True))[1]
            await service.adjust_points(account.id, 110, "测试已有积分")

        won = await service.rock_paper_scissors(
            platform="qq", adapter="qq", user_id="rps-win",
            conversation_id="qq:group:test", choice="布", message_id="rps-win-1",
            config=config,
        )
        draw = await service.rock_paper_scissors(
            platform="qq", adapter="qq", user_id="rps-draw",
            conversation_id="qq:group:test", choice="石头", message_id="rps-draw-1",
            config=config,
        )
        lost = await service.rock_paper_scissors(
            platform="qq", adapter="qq", user_id="rps-lose",
            conversation_id="qq:group:test", choice="剪刀", message_id="rps-lose-1",
            config=config,
        )

        assert (won["outcome"], won["reward"], won["balance"]) == ("win", 3, 113)
        assert (draw["outcome"], draw["reward"], draw["balance"]) == ("draw", 1, 111)
        assert (lost["outcome"], lost["reward"], lost["balance"]) == ("lose", 0, 110)


@pytest.mark.asyncio
async def test_treasure_claim_is_daily_idempotent(session_factory, monkeypatch):
    monkeypatch.setattr(
        community_service,
        "_RANDOM",
        SimpleNamespace(randint=lambda minimum, maximum: maximum),
    )
    config = CommunityConfig(treasure_min_reward=5, treasure_max_reward=10)
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="treasure-user", invite_code="TREASURE")
        service = CommunityService(session)

        first = await service.claim_treasure(
            platform="qq",
            adapter="qq",
            user_id="treasure-user",
            nickname="宝箱玩家",
            conversation_id="qq:group:test",
            box_number=2,
            config=config,
        )
        repeated = await service.claim_treasure(
            platform="qq",
            adapter="qq",
            user_id="treasure-user",
            nickname="宝箱玩家",
            conversation_id="qq:group:other",
            box_number=3,
            config=config,
        )

        assert first == {
            "reward": 10,
            "box_number": 2,
            "balance": 10,
            "duplicate": False,
        }
        assert repeated == {
            "reward": 10,
            "box_number": 2,
            "balance": 10,
            "duplicate": True,
        }


@pytest.mark.asyncio
async def test_daily_boss_kill_splits_exact_pool_between_participants(
    session_factory, monkeypatch
):
    monkeypatch.setattr(
        community_service,
        "_RANDOM",
        SimpleNamespace(randint=lambda minimum, maximum: maximum),
    )
    config = CommunityConfig(
        boss_daily_hp=4,
        boss_min_damage=1,
        boss_max_damage=2,
        boss_min_reward=2,
        boss_max_reward=2,
        boss_kill_reward_pool=1_000,
    )
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="boss-user-1", invite_code="BOSS0001")
        await bind_user(session, user_id="boss-user-2", invite_code="BOSS0002")
        service = CommunityService(session)

        first = await service.attack_boss(
            platform="qq",
            adapter="qq",
            user_id="boss-user-1",
            nickname="甲",
            conversation_id="qq:group:test",
            event_id="boss-event-1",
            config=config,
        )
        last = await service.attack_boss(
            platform="qq",
            adapter="qq",
            user_id="boss-user-2",
            nickname="乙",
            conversation_id="qq:group:test",
            event_id="boss-event-2",
            config=config,
        )
        replay = await service.attack_boss(
            platform="qq",
            adapter="qq",
            user_id="boss-user-2",
            nickname="乙",
            conversation_id="qq:group:test",
            event_id="boss-event-2",
            config=config,
        )
        account_1 = (await service.identity_account("qq", "qq", "boss-user-1"))[1]
        account_2 = (await service.identity_account("qq", "qq", "boss-user-2"))[1]

        assert first["remaining_hp"] == 2
        assert last["status"] == "defeated"
        assert last["participant_count"] == 2
        assert last["payout_total"] == 1_000
        assert last["pool_reward"] == 500
        assert account_1.points_balance == 502
        assert account_2.points_balance == 502
        assert replay["duplicate"] is True
        assert replay["pool_reward"] == 500
        assert replay["balance"] == 502


@pytest.mark.asyncio
async def test_daily_boss_limits_each_user_to_one_attack(session_factory, monkeypatch):
    monkeypatch.setattr(
        community_service,
        "_RANDOM",
        SimpleNamespace(randint=lambda minimum, maximum: minimum),
    )
    config = CommunityConfig(boss_daily_hp=1_000)
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="boss-limit-user", invite_code="BOSSLIM1")
        service = CommunityService(session)
        result = await service.attack_boss(
            platform="qq",
            adapter="qq",
            user_id="boss-limit-user",
            nickname="每日一击",
            conversation_id="qq:group:test",
            event_id="boss-limit-event-1",
            config=config,
        )
        assert result["attack_index"] == 1
        assert result["attacks_left"] == 0
        assert result["damage"] == 10
        assert result["reward"] == 10

        with pytest.raises(CommunityConflictError, match="攻击 1 次"):
            await service.attack_boss(
                platform="qq",
                adapter="qq",
                user_id="boss-limit-user",
                nickname="每日一击",
                conversation_id="qq:group:test",
                event_id="boss-limit-event-11",
                config=config,
            )


@pytest.mark.asyncio
async def test_six_hour_horse_race_locks_choice_and_splits_exact_pool(
    session_factory, monkeypatch
):
    monkeypatch.setattr(
        community_service,
        "_RANDOM",
        SimpleNamespace(choice=lambda supported: supported[0]),
    )
    config = CommunityConfig(horse_race_prize_pool=200)
    play_at = datetime(2026, 8, 11, 9, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    draw_at = datetime(2026, 8, 11, 9, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
    async with session_factory() as session, session.begin():
        for user_id, invite_code in (
            ("horse-user-1", "HORSE001"),
            ("horse-user-2", "HORSE002"),
            ("horse-user-3", "HORSE003"),
        ):
            await bind_user(session, user_id=user_id, invite_code=invite_code)
        service = CommunityService(session)

        first = await service.join_horse_race(
            platform="qq", adapter="qq", user_id="horse-user-1", nickname="甲",
            conversation_id="qq:group:test", horse_number=2, config=config, now=play_at,
        )
        repeated = await service.join_horse_race(
            platform="qq", adapter="qq", user_id="horse-user-1", nickname="甲",
            conversation_id="qq:group:test", horse_number=2, config=config, now=play_at,
        )
        with pytest.raises(CommunityConflictError, match="不能修改"):
            await service.join_horse_race(
                platform="qq", adapter="qq", user_id="horse-user-1", nickname="甲",
                conversation_id="qq:group:test", horse_number=4, config=config, now=play_at,
            )
        await service.join_horse_race(
            platform="qq", adapter="qq", user_id="horse-user-2", nickname="乙",
            conversation_id="qq:group:test", horse_number=2, config=config, now=play_at,
        )
        await service.join_horse_race(
            platform="qq", adapter="qq", user_id="horse-user-3", nickname="丙",
            conversation_id="qq:group:test", horse_number=4, config=config, now=play_at,
        )

        settled = await service.settle_due_horse_races(config, now=draw_at)
        repeated_settlement = await service.settle_due_horse_races(config, now=draw_at)
        next_round = await service.horse_race_status(
            platform="qq",
            adapter="qq",
            conversation_id="qq:group:test",
            config=config,
            now=datetime(2026, 8, 11, 15, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        balances = [
            (await service.identity_account("qq", "qq", user_id))[1].points_balance
            for user_id in ("horse-user-1", "horse-user-2", "horse-user-3")
        ]

        assert first["duplicate"] is False
        assert repeated["duplicate"] is True
        assert settled[0]["winning_horse"] == 2
        assert settled[0]["participant_count"] == 3
        assert settled[0]["winner_count"] == 2
        assert settled[0]["payout_total"] == 200
        assert next_round["previous"]["winning_horse"] == 2
        assert next_round["previous"]["winners"] == [
            {"nickname": "甲", "reward": 100},
            {"nickname": "乙", "reward": 100},
        ]
        assert balances == [100, 100, 0]
        assert repeated_settlement == []


@pytest.mark.asyncio
async def test_six_hour_schedule_still_settles_existing_horse_race_round(
    session_factory, monkeypatch
):
    monkeypatch.setattr(
        community_service,
        "_RANDOM",
        SimpleNamespace(choice=lambda supported: supported[0]),
    )
    old_config = CommunityConfig(horse_race_interval_hours=1)
    new_config = CommunityConfig()
    timezone = ZoneInfo("Asia/Shanghai")

    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="legacy-horse-user", invite_code="OLDHORSE")
        service = CommunityService(session)
        await service.join_horse_race(
            platform="qq",
            adapter="qq",
            user_id="legacy-horse-user",
            nickname="旧场玩家",
            conversation_id="qq:group:legacy",
            horse_number=3,
            config=old_config,
            now=datetime(2026, 8, 11, 10, 10, tzinfo=timezone),
        )

        settled = await service.settle_due_horse_races(
            new_config,
            now=datetime(2026, 8, 11, 10, 55, tzinfo=timezone),
        )

        assert len(settled) == 1
        assert settled[0]["race_hour"] == 10
        assert settled[0]["winning_horse"] == 3
        assert settled[0]["payout_total"] == 200


@pytest.mark.asyncio
async def test_high_low_click_settles_fixed_stake_once(
    session_factory, monkeypatch
):
    rolls = iter((80, 20))
    monkeypatch.setattr(
        community_service,
        "_RANDOM",
        SimpleNamespace(randint=lambda minimum, maximum: next(rolls)),
    )
    config = CommunityConfig(high_low_daily_limit=2)
    async with session_factory() as session, session.begin():
        await bind_user(session, user_id="high-low-user", invite_code="HIGHLOW1")
        service = CommunityService(session)
        account = (await service.identity_account("qq", "qq", "high-low-user"))[1]
        await service.adjust_points(account.id, 50, "测试充值")

        won = await service.play_high_low(
            platform="qq", adapter="qq", user_id="high-low-user", nickname="玩家",
            conversation_id="qq:group:test", choice="大", event_id="high-low-win",
            config=config,
        )
        repeated = await service.play_high_low(
            platform="qq", adapter="qq", user_id="high-low-user", nickname="玩家",
            conversation_id="qq:group:test", choice="大", event_id="high-low-win",
            config=config,
        )
        lost = await service.play_high_low(
            platform="qq", adapter="qq", user_id="high-low-user", nickname="玩家",
            conversation_id="qq:group:test", choice="大", event_id="high-low-lose",
            config=config,
        )
        with pytest.raises(CommunityConflictError, match="已经玩过 2 次"):
            await service.play_high_low(
                platform="qq", adapter="qq", user_id="high-low-user", nickname="玩家",
                conversation_id="qq:group:test", choice="小", event_id="high-low-limit",
                config=config,
            )

        assert (won["roll"], won["won"], won["payout"], won["net_points"]) == (
            80, True, 10, 5
        )
        assert repeated["duplicate"] is True
        assert repeated["balance"] == 55
        assert won["remaining"] == 1
        assert repeated["remaining"] == 1
        assert (lost["roll"], lost["won"], lost["payout"], lost["net_points"]) == (
            20, False, 0, -5
        )
        assert lost["balance"] == 50
        assert lost["remaining"] == 0


def test_horse_race_schedule_runs_every_six_hours_before_draw():
    config = CommunityConfig()
    timezone = ZoneInfo("Asia/Shanghai")

    assert CommunityService._horse_race_slot(
        config, datetime(2026, 8, 11, 8, 59, tzinfo=timezone)
    ) is None
    assert CommunityService._horse_race_slot(
        config, datetime(2026, 8, 11, 9, 0, tzinfo=timezone)
    ) == (date(2026, 8, 11), 9)
    assert CommunityService._horse_race_slot(
        config, datetime(2026, 8, 11, 10, 0, tzinfo=timezone)
    ) is None
    assert CommunityService._horse_race_slot(
        config, datetime(2026, 8, 11, 15, 54, tzinfo=timezone)
    ) == (date(2026, 8, 11), 15)
    assert CommunityService._horse_race_slot(
        config, datetime(2026, 8, 11, 15, 55, tzinfo=timezone)
    ) is None
    assert CommunityService._horse_race_slot(
        config, datetime(2026, 8, 11, 21, 54, tzinfo=timezone)
    ) == (date(2026, 8, 11), 21)
    assert CommunityService._horse_race_slot(
        config, datetime(2026, 8, 11, 22, 0, tzinfo=timezone)
    ) is None


@pytest.mark.asyncio
async def test_horse_race_result_card_is_not_auto_recalled():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    replies = []

    async def capture_reply(reply):
        replies.append(reply)

    plugin.ctx = SimpleNamespace(send_reply=capture_reply)

    await plugin._send_horse_race_result(
        {
            "platform": "qq",
            "adapter": "qq",
            "conversation_id": "qq:group:test",
            "winning_horse": 1,
            "winner_count": 12,
            "payout_total": 200,
            "winners": [
                {"nickname": f"中奖者{index}", "reward": 20}
                for index in range(1, 13)
            ],
        }
    )

    assert len(replies) == 1
    assert replies[0].type == "keyboard"
    assert "auto_recall_seconds" not in replies[0].metadata
    assert "1. 中奖者1　+20 积分" in replies[0].content
    assert "10. 中奖者10　+20 积分" in replies[0].content
    assert "中奖者11" not in replies[0].content
    assert "另有 2 人中奖" in replies[0].content


def test_all_community_keyboard_buttons_use_direct_callback():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    keyboards = [
        plugin._help_keyboard(),
        plugin._token_exchange_keyboard(),
        plugin._back_to_menu_keyboard(),
        plugin._red_packet_keyboard("a" * 32),
        plugin._red_packet_confirm_keyboard("b" * 32, "user-1"),
        plugin._game_keyboard(),
        plugin._treasure_keyboard(),
        plugin._boss_keyboard(),
        plugin._horse_race_keyboard(),
        plugin._high_low_choice_keyboard("user-1"),
    ]
    for keyboard in keyboards:
        buttons = [
            button
            for row in keyboard["content"]["rows"]
            for button in row["buttons"]
        ]
        actions = [
            button["action"] for button in buttons
        ]
        assert actions
        assert all(len(button["render_data"]["label"]) <= 10 for button in buttons)
        assert all(action["type"] == 1 for action in actions)
        assert all("enter" not in action and "reply" not in action for action in actions)


def test_plain_qq_community_reply_is_rendered_as_keyboard_card():
    loader = PluginLoader()
    plugin_dir = Path("plugins/WeibanCommunity")
    plugin = loader.load_instance(plugin_dir, loader.load_manifest(plugin_dir))
    message = Message(
        id="member-card",
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        sender_id="user-1",
        sender_name="小银pro",
        content="会员信息",
        raw={"scope": "group", "mentions_bot": True},
    )

    result = plugin._reply(
        message,
        "会员信息",
        "会员中心\n账号状态：✅ 正常\n会员等级：👑 Lite",
    )

    assert result.type == "keyboard"
    assert "**账号状态**　✅ 正常" in result.content
    assert result.metadata["auto_recall_seconds"] == 10
    button = result.metadata["keyboard"]["content"]["rows"][0]["buttons"][0]
    assert button["action"] == {
        "type": 1,
        "permission": {"type": 2},
        "data": "社区帮助",
    }
