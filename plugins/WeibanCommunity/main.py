from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

import anyio
from loguru import logger
from sqlalchemy.exc import IntegrityError

from xbot.community.config import CommunityConfig
from xbot.community.service import (
    CommunityError,
    CommunityService,
    local_date,
)
from xbot.community.weiban_token_client import (
    TokenGrantError,
    grant_character_image_count,
    grant_token_pack,
)
from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext
from xbot.runtime.scheduler import enqueue_reply

_INVITE_CODE = re.compile(r"^[A-Z0-9]{8}$")
_MENTION = re.compile(r"<@!?[^>]+>")
_BIND_PREFIX = re.compile(
    r"^(?:[+＋]\s*)?绑定[\s+＋:：_-]*(?:账号|邀请码)?"
    r"[\s+＋:：_-]*([A-Za-z0-9]{8})$",
    re.IGNORECASE,
)
_BIND_SUFFIX = re.compile(
    r"^(?:[+＋]\s*)?([A-Za-z0-9]{8})[\s+＋:：_-]*(?:账号|邀请码)?"
    r"[\s+＋:：_-]*绑定$",
    re.IGNORECASE,
)
_BIND_INTENT = re.compile(
    r"^(?:[+＋]\s*)?(?:"
    r"绑定[\s+＋:：_-]*(?:账号|邀请码)?[\s+＋:：_-]*[A-Za-z0-9]*|"
    r"[A-Za-z0-9]+[\s+＋:：_-]*(?:账号|邀请码)?[\s+＋:：_-]*绑定"
    r")$",
    re.IGNORECASE,
)
_HORSE_NAMES = {1: "赤焰", 2: "闪电", 3: "追风", 4: "黑曜"}
_HELP_COMMANDS = {"菜单", "帮助", "社区菜单", "娱乐帮助", "积分帮助", "社区帮助"}
_TOKEN_EXCHANGE_TIERS = {
    100: 100_000,
    200: 210_000,
    500: 550_000,
    1_000: 1_100_000,
}
_CHARACTER_IMAGE_EXCHANGE_TIERS = {200: 1, 1_000: 5}
_SETTLEMENT_JOB_NAME = "weiban-community-settlement"
_REASON_LABELS = {
    "checkin": "每日签到",
    "daily_activity_rank": "群发言榜",
    "daily_activity_milestone": "每日发言奖励",
    "game_rps_win": "猜拳胜利",
    "game_rps_draw": "猜拳平局",
    "game_rps_lose": "猜拳参与",
    "game_fortune": "每日运势",
    "game_treasure": "幸运宝箱",
    "game_boss_attack": "每日 Boss 攻击",
    "game_boss_kill": "每日 Boss 击杀奖励",
    "game_horse_race": "群体赛马奖励",
    "game_high_low_stake": "押大小投入",
    "game_high_low_payout": "押大小返奖",
    "admin_adjustment": "管理员调整",
    "token_exchange": "Token 加油包",
    "token_exchange_refund": "Token 兑换退回",
    "character_image_exchange": "手动生图兑换",
    "character_image_exchange_refund": "手动生图兑换退回",
    "red_packet_send": "发红包",
    "red_packet_claim": "抢红包",
}
_COMMAND_TITLES = {
    "签到": "✅ 每日签到",
    "积分": "🪙 我的积分",
    "我的积分": "🪙 我的积分",
    "积分明细": "📒 积分明细",
    "我的账号": "🔗 账号状态",
    "账号状态": "🔗 账号状态",
    "会员信息": "👑 会员中心",
    "我的会员": "👑 会员中心",
    "会员等级": "👑 会员中心",
    "兑换Token": "⛽ Token 加油包",
    "Token兑换": "⛽ Token 加油包",
    "兑换状态": "⛽ Token 加油包",
    "兑换生图状态": "🎨 手动生图次数",
    "发言奖励": "🔥 每日发言奖励",
    "积分排行": "🏆 积分总榜",
    "总榜": "🏆 积分总榜",
    "周榜": "🏆 本周积分榜",
    "月榜": "🏆 本月积分榜",
    "今日发言": "🔥 今日发言榜",
    "今日发言排行": "🔥 今日发言榜",
    "昨日发言": "🔥 昨日发言榜",
    "昨日发言排行": "🔥 昨日发言榜",
    "每日运势": "✨ 今日运势",
    "今日运势": "✨ 今日运势",
    "游戏中心": "🎮 游戏中心",
    "幸运宝箱": "🎁 幸运宝箱",
    "宝箱": "🎁 幸运宝箱",
    "每日Boss": "👹 每日 Boss",
    "Boss": "👹 每日 Boss",
    "群体赛马": "🏇 群体赛马",
    "赛马": "🏇 群体赛马",
    "押大小": "🎲 押大小",
}


class WeibanCommunityPlugin(PluginBase):
    name = "WeibanCommunity"
    version = "1.0.0"

    def __init__(self) -> None:
        self.ctx: PluginContext | None = None
        self.config = CommunityConfig()
        self.config_created_at = datetime.now(UTC).replace(tzinfo=None)
        self._settlement_task: asyncio.Task | None = None
        self._scheduler_registered = False
        self._message_event_unsubscribe: Callable[[], None] | None = None
        self._activity_tasks: set[asyncio.Task] = set()
        self._loaded = False
        self._sender_names: dict[str, str] = {}
        self._game_lock = asyncio.Lock()

    async def on_load(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        provider = getattr(ctx.conversations, "repository_provider", None)
        if provider is None:
            self.config = CommunityConfig(enabled=False)
            logger.warning("WeibanCommunity 需要持久化数据库，插件已暂停。")
            return
        async with provider() as repo:
            self.config, record = await CommunityService(repo.session).get_config()
            self.config_created_at = record.created_at
        self._loaded = True
        if ctx.events is not None:
            self._message_event_unsubscribe = ctx.events.subscribe(
                "message.created", self._queue_activity_observer
            )
        if ctx.scheduler is not None:
            ctx.scheduler.register(
                _SETTLEMENT_JOB_NAME,
                interval_seconds=60,
                handler=self._run_settlement_cycle,
                source=self.name,
            )
            self._scheduler_registered = True
        else:
            self._settlement_task = asyncio.create_task(
                self._settlement_loop(), name=_SETTLEMENT_JOB_NAME
            )
        logger.info(
            "WeibanCommunity 已加载: enabled={} adapters={} groups={}",
            self.config.enabled,
            self.config.enabled_adapters,
            len(self.config.allowed_conversation_ids),
        )

    async def on_unload(self) -> None:
        self._loaded = False
        if self._scheduler_registered and self.ctx and self.ctx.scheduler is not None:
            await self.ctx.scheduler.unregister(_SETTLEMENT_JOB_NAME)
            self._scheduler_registered = False
        if self._message_event_unsubscribe is not None:
            self._message_event_unsubscribe()
            self._message_event_unsubscribe = None
        tasks = list(self._activity_tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._activity_tasks.clear()
        if self._settlement_task is not None:
            self._settlement_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._settlement_task
            self._settlement_task = None

    async def on_message(self, message: Message, ctx: PluginContext):
        if not self._message_enabled(message):
            return False
        message = await self._resolve_sender_name(message)
        mentioned = bool(message.raw.get("mentions_bot")) or self._is_button_interaction(message)
        command = self._clean_content(message)
        public_qq_command = message.adapter == "qq" and (
            command in _HELP_COMMANDS or self._is_binding_command(command)
        )
        if self.config.require_mention and not mentioned and not public_qq_command:
            return False
        if not command:
            return False
        keyboard = None
        try:
            result = await self._dispatch_command(message, command)
            if isinstance(result, tuple):
                content, keyboard = result
            else:
                content = result
        except CommunityError as exc:
            content = str(exc)
        except IntegrityError:
            content = "绑定或积分记录发生冲突，请稍后重试。"
        except Exception as exc:
            logger.exception(
                "WeibanCommunity 命令失败: message_id={} conversation={} error={}",
                message.id,
                message.conversation_id,
                exc,
            )
            content = "功能暂时不可用，请稍后再试。"
        if content is None:
            return False
        return self._reply(message, command, content, keyboard=keyboard)

    async def _queue_activity_observer(self, payload: dict[str, Any]) -> None:
        if not self._loaded:
            return
        task = asyncio.create_task(
            self._observe_message_created(payload),
            name="weiban-community-activity",
        )
        self._activity_tasks.add(task)
        task.add_done_callback(self._activity_tasks.discard)

    async def _observe_message_created(self, payload: dict[str, Any]) -> None:
        try:
            message = Message.model_validate(payload.get("message"))
        except Exception as exc:
            logger.debug("WeibanCommunity 忽略无效消息事件: {}", exc)
            return
        if not self._message_enabled(message):
            return
        message = await self._resolve_sender_name(message)
        milestone = await self._award_activity_milestone(message)
        if milestone is None or self.ctx is None or self.ctx.send_reply is None:
            return
        try:
            await self.ctx.send_reply(self._milestone_reply(message, milestone))
        except Exception as exc:
            logger.warning(
                "WeibanCommunity 发言达标通知失败: message_id={} error={}",
                message.id,
                exc,
            )

    async def _award_activity_milestone(self, message: Message) -> dict[str, Any] | None:
        if self._is_button_interaction(message) or message.type != "text":
            return None
        try:
            async with self._provider()() as repo:
                result = await CommunityService(repo.session).award_activity_milestone(
                    platform=message.platform,
                    adapter=message.adapter,
                    user_id=message.sender_id,
                    conversation_id=message.conversation_id,
                    config=self.config,
                )
        except (CommunityError, IntegrityError):
            return None
        except Exception as exc:
            logger.warning(
                "WeibanCommunity 发言达标检查失败: message_id={} error={}",
                message.id,
                exc,
            )
            return None
        return result if result.get("awarded") else None

    def _milestone_reply(self, message: Message, milestone: dict[str, Any]) -> Reply:
        return self._reply(message, "发言奖励", self._milestone_text(milestone))

    @staticmethod
    def _milestone_text(milestone: dict[str, Any]) -> str:
        return (
            f"今日发言达到 {int(milestone['message_count'])} 条，"
            f"获得 {int(milestone['reward'])} 积分。"
            f"当前 {int(milestone['balance'])} 积分。"
        )

    def _reply(
        self,
        message: Message,
        command: str,
        content: str,
        *,
        keyboard: dict[str, Any] | None = None,
    ) -> Reply:
        if message.adapter != "qq":
            return Reply(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                type="text",
                content=content,
            )
        fallback = self._address_plain(message, content)
        metadata: dict[str, Any] = {"fallback_text": fallback}
        reply_type = "markdown"
        if keyboard is not None:
            reply_type = "keyboard"
            metadata["keyboard"] = keyboard
        elif command in _HELP_COMMANDS:
            reply_type = "keyboard"
            metadata["keyboard"] = self._help_keyboard()
        elif command in {"兑换Token", "Token兑换"} and self.config.token_exchange_enabled:
            reply_type = "keyboard"
            metadata["keyboard"] = self._token_exchange_keyboard()
        else:
            reply_type = "keyboard"
            metadata["keyboard"] = self._back_to_menu_keyboard()
        event_id = str(message.raw.get("event_id") or "") if self._is_button_interaction(message) else ""
        if event_id:
            metadata["event_id"] = event_id
        persistent_card = (
            command in _HELP_COMMANDS
            or command in {
                "兑换Token", "Token兑换", "红包", "发红包", "游戏中心",
                "幸运宝箱", "宝箱", "每日Boss", "Boss", "boss", "群体赛马", "赛马",
                "押大小",
                "积分排行", "总榜", "周榜", "月榜",
                "今日发言", "今日发言排行", "昨日发言", "昨日发言排行",
            }
            or command.startswith("确认红包:")
        )
        if not persistent_card:
            metadata["auto_recall_seconds"] = 10
        rendered = self._markdown(command, content)
        ranking_commands = {
            "积分排行", "总榜", "周榜", "月榜",
            "今日发言", "今日发言排行", "昨日发言", "昨日发言排行",
        }
        if command not in ranking_commands:
            rendered = self._address_markdown(message, rendered)
        return Reply(
            platform=message.platform,
            adapter=message.adapter,
            conversation_id=message.conversation_id,
            type=reply_type,
            content=rendered,
            metadata=metadata,
            quote_message_id=None if event_id else message.id,
        )

    @staticmethod
    def _address_plain(message: Message, content: str) -> str:
        if not WeibanCommunityPlugin._is_button_interaction(message):
            return content
        nickname = str(message.sender_name or "").strip()
        return f"@{nickname} {content}" if nickname else content

    @staticmethod
    def _address_markdown(message: Message, content: str) -> str:
        if str(message.raw.get("scope") or "") != "group":
            return content
        nickname = str(message.sender_name or "").strip()
        return f"@{nickname}\n\n{content}" if nickname else content

    async def _resolve_sender_name(self, message: Message) -> Message:
        nickname = str(message.sender_name or "").strip()
        if nickname:
            self._sender_names[message.sender_id] = nickname
            return message
        if not self._is_button_interaction(message):
            return message
        nickname = self._sender_names.get(message.sender_id, "")
        if not nickname:
            try:
                async with self._provider()() as repo:
                    identity, _ = await CommunityService(repo.session).identity_account(
                        message.platform,
                        message.adapter,
                        message.sender_id,
                    )
                nickname = str(identity.nickname or "").strip()
            except CommunityError:
                nickname = ""
        return message.model_copy(update={"sender_name": nickname}) if nickname else message

    @staticmethod
    def _help_keyboard() -> dict[str, Any]:
        rows = (
            (("✅ 每日签到", "签到"), ("👑 会员信息", "会员信息")),
            (("🪙 我的积分", "我的积分"), ("📒 积分明细", "积分明细")),
            (("🎮 游戏中心", "游戏中心"), ("🏆 积分排行", "积分排行")),
            (("🔥 发言排行", "今日发言排行"), ("⛽ Token 加油", "兑换Token")),
            (("🔮 今日运势", "今日运势"), ("🧧 发红包", "发红包")),
        )
        return {
            "content": {
                "rows": [
                    {
                        "buttons": [
                            {
                                "id": f"weiban_{row_index}_{button_index}",
                                "render_data": {
                                    "label": label,
                                    "visited_label": label,
                                    "style": 1,
                                },
                                "action": {
                                    "type": 1,
                                    "permission": {"type": 2},
                                    "data": command,
                                },
                            }
                            for button_index, (label, command) in enumerate(buttons, start=1)
                        ]
                    }
                    for row_index, buttons in enumerate(rows, start=1)
                ]
            }
        }

    @staticmethod
    def _game_keyboard() -> dict[str, Any]:
        rows = (
            (("🎁 幸运宝箱", "幸运宝箱"), ("👹 每日 Boss", "每日Boss")),
            (("✊ 猜拳", "猜拳 石头"), ("🔮 今日运势", "今日运势")),
            (("🏇 群体赛马", "群体赛马"), ("🎲 押大小", "押大小")),
        )
        return WeibanCommunityPlugin._callback_rows("weiban_game", rows)

    @staticmethod
    def _treasure_keyboard() -> dict[str, Any]:
        rows = (
            (("🎁 1号宝箱", "开启宝箱:1"), ("🎁 2号宝箱", "开启宝箱:2")),
            (("🎁 3号宝箱", "开启宝箱:3"),),
        )
        return WeibanCommunityPlugin._callback_rows("weiban_treasure", rows, style=3)

    @staticmethod
    def _boss_keyboard() -> dict[str, Any]:
        return WeibanCommunityPlugin._single_callback_keyboard(
            button_id="weiban_daily_boss_attack",
            label="⚔️ 攻击 Boss",
            visited_label="⚔️ 再攻击",
            data="攻击Boss",
        )

    @staticmethod
    def _horse_race_keyboard() -> dict[str, Any]:
        rows = (
            (("🏇 1号 · 赤焰", "支持赛马:1"), ("🐎 2号 · 闪电", "支持赛马:2")),
            (("🏇 3号 · 追风", "支持赛马:3"), ("🐎 4号 · 黑曜", "支持赛马:4")),
        )
        return WeibanCommunityPlugin._callback_rows("weiban_horse_race", rows, style=3)

    @staticmethod
    def _high_low_choice_keyboard(user_id: str) -> dict[str, Any]:
        rows = ((("🔺 押大", "押大小选择:大"), ("🔻 押小", "押大小选择:小")),)
        return WeibanCommunityPlugin._callback_rows(
            "weiban_high_low_choice", rows, style=3, user_id=user_id
        )

    @staticmethod
    def _callback_rows(
        prefix: str,
        rows: tuple[tuple[tuple[str, str], ...], ...],
        *,
        style: int = 1,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        permission: dict[str, Any] = {"type": 2}
        if user_id:
            permission = {"type": 0, "specify_user_ids": [user_id]}
        return {
            "content": {
                "rows": [
                    {
                        "buttons": [
                            {
                                "id": f"{prefix}_{row_index}_{button_index}"[:64],
                                "render_data": {
                                    "label": label,
                                    "visited_label": label,
                                    "style": style,
                                },
                                "action": {
                                    "type": 1,
                                    "permission": permission,
                                    "data": command,
                                },
                            }
                            for button_index, (label, command) in enumerate(buttons, start=1)
                        ]
                    }
                    for row_index, buttons in enumerate(rows, start=1)
                ]
            }
        }

    @staticmethod
    def _token_exchange_keyboard() -> dict[str, Any]:
        rows = (
            (("100分→10万", "兑换Token:100"), ("200分→21万", "兑换Token:200")),
            (("500分→55万", "兑换Token:500"), ("1000分→110万", "兑换Token:1000")),
            (("生图1次·200分", "兑换生图:200"), ("生图5次·1000分", "兑换生图:1000")),
            (("↩ 返回菜单", "社区帮助"),),
        )
        return WeibanCommunityPlugin._callback_rows("weiban_token_exchange", rows, style=3)

    @staticmethod
    def _back_to_menu_keyboard() -> dict[str, Any]:
        return WeibanCommunityPlugin._single_callback_keyboard(
            button_id="weiban_back_to_menu",
            label="🎮 返回菜单",
            visited_label="🎮 返回菜单",
            data="社区帮助",
        )

    @staticmethod
    def _red_packet_keyboard(packet_id: str) -> dict[str, Any]:
        return WeibanCommunityPlugin._single_callback_keyboard(
            button_id=f"weiban_red_packet_claim_{packet_id}",
            label="🧧 抢红包",
            visited_label="已抢",
            data=f"抢红包:{packet_id}",
        )

    @staticmethod
    def _red_packet_confirm_keyboard(packet_id: str, user_id: str) -> dict[str, Any]:
        return WeibanCommunityPlugin._single_callback_keyboard(
            button_id=f"weiban_red_packet_confirm_{packet_id}",
            label="确认发红包",
            visited_label="已确认",
            data=f"确认红包:{packet_id}",
            user_id=user_id,
        )

    @staticmethod
    def _single_callback_keyboard(
        *,
        button_id: str,
        label: str,
        visited_label: str,
        data: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        permission: dict[str, Any] = {"type": 2}
        if user_id:
            permission = {"type": 0, "specify_user_ids": [user_id]}
        return {
            "content": {
                "rows": [
                    {
                        "buttons": [
                            {
                                "id": button_id[:64],
                                "render_data": {
                                    "label": label,
                                    "visited_label": visited_label,
                                    "style": 3,
                                },
                                "action": {
                                    "type": 1,
                                    "permission": permission,
                                    "data": data,
                                },
                            }
                        ]
                    }
                ]
            }
        }

    def _markdown(self, command: str, content: str) -> str:
        if command in _HELP_COMMANDS:
            return (
                "**🎮 微伴社区 · 今日菜单**\n\n"
                "> ✨ 签到攒积分 · 玩游戏 · 冲榜单\n\n"
                "**🪪 新人入口**  \n"
                "`绑定 8位邀请码`\n\n"
                "**🎲 更多玩法**  \n"
                "`周榜`　`月榜`　`我的账号`\n\n"
                "> 👇 常用功能，一键直达"
            )
        if command == "游戏中心":
            return (
                "**🎮 微伴社区 · 游戏中心**\n\n"
                f"> 🎁 每日宝箱 · 👹 全群 Boss · 🏇 每 {self.config.horse_race_interval_hours} 小时赛马\n\n"
                "**每日次数有限**  \n"
                "点击按钮直接开始，不需要再次发送。"
            )
        if command in {"今日发言", "今日发言排行", "昨日发言", "昨日发言排行"}:
            return self._activity_ranking_markdown(command, content)
        if command in {"积分排行", "总榜", "周榜", "月榜"}:
            return self._points_ranking_markdown(command, content)
        if self._is_binding_command(command):
            title = "🔗 账号绑定"
        elif command.startswith(("猜拳", "石头剪刀布")):
            title = "✊ 石头剪刀布"
        elif "红包" in command:
            title = "🧧 微伴积分红包"
        elif "宝箱" in command:
            title = "🎁 幸运宝箱"
        elif "Boss" in command or "boss" in command:
            title = "👹 每日 Boss"
        elif "赛马" in command:
            title = "🏇 群体赛马"
        elif "押大小" in command:
            title = "🎲 押大小"
        elif command.startswith("兑换Token:"):
            title = "⛽ Token 加油包"
        elif command.startswith("兑换生图:"):
            title = "🎨 手动生图次数"
        else:
            title = _COMMAND_TITLES.get(command, "🎮 微伴社区")
        lines = content.splitlines()
        plain_title = title.split(" ", 1)[-1]
        if lines and lines[0].strip() == plain_title:
            lines = lines[1:]
        ranking = "榜" in title
        rendered: list[str] = []
        medals = ("🥇", "🥈", "🥉", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩")
        for line in (line.strip() for line in lines if line.strip()):
            match = re.match(r"^(\d+)\.\s*(.+)$", line)
            if ranking and match:
                index = int(match.group(1))
                prefix = medals[index - 1] if 1 <= index <= len(medals) else f"{index}."
                rendered.append(f"{prefix} {match.group(2)}")
            elif "：" in line:
                label, value = line.split("：", 1)
                rendered.append(f"**{label}**　{value.strip()}")
            else:
                rendered.append(line)
        body = "  \n".join(rendered)
        return f"**{title}**\n\n{body}"

    def _activity_ranking_markdown(self, command: str, content: str) -> str:
        today = command in {"今日发言", "今日发言排行"}
        title = "🔥 今日群聊活跃榜" if today else "📊 昨日群聊最终榜"
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        rows: list[tuple[str, str]] = []
        for line in lines[1:]:
            _, separator, body = line.partition(". ")
            if not separator or "  " not in body:
                continue
            nickname, count = body.rsplit("  ", 1)
            rows.append((nickname.strip(), count.strip()))
        if today:
            current = datetime.now(ZoneInfo(self.config.timezone)).strftime("%H:%M")
            subtitle = f"> 截至 {current} · 仅统计已绑定用户的有效群聊发言"
        else:
            subtitle = "> 昨日最终数据 · 仅统计已绑定用户的有效群聊发言"
        medals = ("🥇", "🥈", "🥉", "④", "⑤")
        sections = [f"**{title}**", subtitle]
        if not rows:
            sections.append(
                f"> 暂无用户达到上榜门槛（至少 {self.config.activity_min_messages} 条）"
            )
        for index, (nickname, count) in enumerate(rows[:5]):
            reward = self.config.activity_rewards[index]
            reward_label = "暂列奖励" if today else "名次奖励"
            sections.append(
                f"{medals[index]} **{nickname}**  \n"
                f"> `{count}`　·　{reward_label} `{reward} 积分`"
            )
        settle_time = (
            f"{self.config.activity_settle_hour:02d}:"
            f"{self.config.activity_settle_minute:02d}"
        )
        settlement_note = (
            f"> ⏰ 今日排名次日 {settle_time} 按最终名次结算，实时排名会变化。"
            if today
            else f"> ✅ 昨日名次奖励于今日 {settle_time} 结算。"
        )
        footer = [settlement_note]
        if self.config.activity_milestone_enabled:
            footer.append(
                f"> 🎁 当天发言满 {self.config.activity_milestone_messages} 条，"
                f"另得 {self.config.activity_milestone_reward} 积分（每群一次）。"
            )
        sections.append("  \n".join(footer))
        return "\n\n".join(sections)

    @staticmethod
    def _points_ranking_markdown(command: str, content: str) -> str:
        del command
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        medals = ("🥇", "🥈", "🥉", "④", "⑤")
        sections = [
            "**🏆 群积分风云榜**",
            "> `净增` 今日 / 本周 / 本月　·　`余额` 当前总榜",
        ]
        trend_groups: list[dict[str, Any]] = []
        for key, label in (("day", "☀️ 今日"), ("week", "📅 本周"), ("month", "🗓️ 本月")):
            raw_rows = payload.get(key) if isinstance(payload, dict) else None
            rows = [row for row in (raw_rows or [])[:5] if isinstance(row, dict)]
            signature = tuple(
                (str(row.get("nickname") or "群成员"), int(row.get("points") or 0))
                for row in rows
            )
            existing = next(
                (group for group in trend_groups if group["signature"] == signature), None
            )
            if existing is None:
                trend_groups.append({"labels": [label], "rows": rows, "signature": signature})
            else:
                existing["labels"].append(label)
        for group in trend_groups:
            title = " · ".join(group["labels"])
            lines = [f"**{title}**"]
            if not group["rows"]:
                lines.append("> 暂无数据")
            else:
                for index, row in enumerate(group["rows"]):
                    nickname = str(row.get("nickname") or "群成员")
                    points = int(row.get("points") or 0)
                    lines.append(f"{medals[index]} {nickname}　**{points:+d}**")
            sections.append("  \n".join(lines))
        total_rows = payload.get("total") if isinstance(payload, dict) else None
        total_lines = ["**🏆 当前总榜**"]
        if not isinstance(total_rows, list) or not total_rows:
            total_lines.append("> 暂无数据")
        else:
            for index, row in enumerate(total_rows[:5]):
                if not isinstance(row, dict):
                    continue
                nickname = str(row.get("nickname") or "群成员")
                points = int(row.get("points") or 0)
                total_lines.append(f"{medals[index]} {nickname}　**{points} 分**")
        sections.append("  \n".join(total_lines))
        sections.append(
            "> 数据实时更新 · 签到、群活动、游戏、兑换均计入"
        )
        return "\n\n".join(sections)

    def _message_enabled(self, message: Message) -> bool:
        if not self.config.enabled or (
            message.type != "text" and not self._is_button_interaction(message)
        ):
            return False
        if message.adapter not in self.config.enabled_adapters:
            return False
        if str(message.raw.get("scope") or "") != "group":
            return False
        return not (
            self.config.allowed_conversation_ids
            and message.conversation_id not in self.config.allowed_conversation_ids
        )

    @staticmethod
    def _is_button_interaction(message: Message) -> bool:
        if message.adapter != "qq" or message.type != "event":
            return False
        if str(message.raw.get("qq_event_type") or "") != "INTERACTION_CREATE":
            return False
        try:
            interaction_type = int(message.raw.get("interaction_type") or 0)
        except (TypeError, ValueError):
            return False
        return interaction_type in {11, 12} and bool(message.raw.get("button_data"))

    def _clean_content(self, message: Message) -> str:
        if self._is_button_interaction(message):
            return str(message.raw.get("button_data") or "").strip().lstrip("/／").strip()
        content = _MENTION.sub("", message.content or "")
        for candidate in (
            message.raw.get("bot_nickname"),
            message.raw.get("bot_name"),
            message.raw.get("bot_id"),
        ):
            if candidate:
                content = content.replace(f"@{candidate}", "").replace(str(candidate), "")
        return content.strip().lstrip("/／").strip()

    async def _dispatch_command(
        self, message: Message, command: str
    ) -> str | tuple[str, dict[str, Any]] | None:
        if command in _HELP_COMMANDS:
            return self._help()
        invite_code = self._binding_invite_code(command)
        if invite_code:
            return await self._bind(message, invite_code)
        if self._is_binding_command(command) or command.startswith("绑定"):
            return (
                "请输入 8 位永久邀请码，例如：绑定ABCD1234、"
                "绑定 ABCD1234 或 ABCD1234绑定。"
            )
        if command == "签到":
            return await self._checkin(message)
        if command in {"积分", "我的积分"}:
            return await self._points(message)
        if command == "积分明细":
            return await self._ledger(message)
        if command in {"我的账号", "账号状态"}:
            return await self._account_status(message)
        if command in {"会员信息", "我的会员", "会员等级"}:
            return await self._account_status(message)
        if command in {"兑换Token", "Token兑换"}:
            return self._token_exchange_offer()
        token_exchange_match = re.fullmatch(r"兑换Token[:：](100|200|500|1000)", command)
        if token_exchange_match:
            points_cost = int(token_exchange_match.group(1))
            return await self._exchange_tokens(
                message,
                points_cost=points_cost,
                token_amount=_TOKEN_EXCHANGE_TIERS[points_cost],
            )
        image_exchange_match = re.fullmatch(r"兑换生图[:：](200|1000)", command)
        if image_exchange_match:
            points_cost = int(image_exchange_match.group(1))
            return await self._exchange_character_images(
                message,
                points_cost=points_cost,
                image_amount=_CHARACTER_IMAGE_EXCHANGE_TIERS[points_cost],
            )
        if command == "兑换状态":
            return await self._exchange_tokens(
                message,
                points_cost=self.config.token_exchange_points,
                token_amount=self.config.token_exchange_tokens,
            )
        if command in {"发红包", "红包"}:
            return await self._create_red_packet(message)
        if command == "游戏中心":
            return "选择今天想玩的游戏。", self._game_keyboard()
        if command in {"幸运宝箱", "宝箱"}:
            if not self.config.treasure_enabled:
                return "幸运宝箱暂未开放。"
            return (
                f"每天可以开启一次，随机获得 "
                f"{self.config.treasure_min_reward}–{self.config.treasure_max_reward} 积分。\n"
                "三个宝箱，选一个试试手气。",
                self._treasure_keyboard(),
            )
        treasure_match = re.fullmatch(r"开启宝箱:([123])", command)
        if treasure_match:
            return await self._claim_treasure(message, int(treasure_match.group(1)))
        if command in {"每日Boss", "Boss", "boss"}:
            return await self._boss_status(message)
        if command == "攻击Boss":
            return await self._attack_boss(message)
        if command in {"群体赛马", "赛马"}:
            return await self._horse_race_status(message)
        horse_match = re.fullmatch(r"支持赛马[:：\s]*([1-4])", command)
        if horse_match:
            return await self._join_horse_race(message, int(horse_match.group(1)))
        if command == "押大小":
            return self._high_low_offer(message)
        choice_match = re.fullmatch(r"押大小选择[:：](大|小)", command)
        if choice_match:
            return await self._play_high_low(message, choice_match.group(1))
        direct_high_low = re.fullmatch(r"押大小\s*(大|小)", command)
        if direct_high_low:
            return await self._play_high_low(message, direct_high_low.group(1))
        confirm_packet = re.fullmatch(r"确认红包:([0-9a-f]{32})", command)
        if confirm_packet:
            return await self._confirm_red_packet(message, confirm_packet.group(1))
        claim_packet = re.fullmatch(r"抢红包:([0-9a-f]{32})", command)
        if claim_packet:
            return await self._claim_red_packet(message, claim_packet.group(1))
        if command in {"积分排行", "总榜", "周榜", "月榜"}:
            return await self._points_ranking(message)
        if command in {"今日发言", "今日发言排行"}:
            return await self._activity_ranking(message, 0)
        if command in {"昨日发言", "昨日发言排行"}:
            return await self._activity_ranking(message, 1)
        rps_match = re.fullmatch(r"(?:石头剪刀布|猜拳)\s*(石头|剪刀|布)", command)
        if rps_match:
            return await self._rps(message, rps_match.group(1))
        if command in {"每日运势", "今日运势"}:
            return await self._fortune(message)
        return None

    @staticmethod
    def _binding_invite_code(command: str) -> str | None:
        for pattern in (_BIND_PREFIX, _BIND_SUFFIX):
            match = pattern.fullmatch(command)
            if match:
                return match.group(1).upper()
        return None

    @classmethod
    def _is_binding_command(cls, command: str) -> bool:
        return cls._binding_invite_code(command) is not None or bool(
            _BIND_INTENT.fullmatch(command)
        )

    async def _claim_treasure(self, message: Message, box_number: int) -> str:
        async with self._game_lock:
            async with self._provider()() as repo:
                result = await CommunityService(repo.session).claim_treasure(
                    platform=message.platform,
                    adapter=message.adapter,
                    user_id=message.sender_id,
                    nickname=message.sender_name,
                    conversation_id=message.conversation_id,
                    box_number=box_number,
                    config=self.config,
                )
        if result["duplicate"]:
            return (
                f"今天已经开过 {result['box_number']} 号宝箱，获得 "
                f"{result['reward']} 积分。当前 {result['balance']} 积分。"
            )
        return (
            f"打开 {box_number} 号宝箱，获得 {result['reward']} 积分！"
            f"当前 {result['balance']} 积分。明天还能再开一次。"
        )

    async def _boss_status(
        self, message: Message
    ) -> tuple[str, dict[str, Any]] | str:
        async with self._game_lock:
            async with self._provider()() as repo:
                result = await CommunityService(repo.session).boss_status(
                    message.conversation_id, self.config
                )
        content = self._boss_status_text(result)
        return content if result["status"] == "defeated" else (content, self._boss_keyboard())

    async def _attack_boss(
        self, message: Message
    ) -> tuple[str, dict[str, Any]] | str:
        event_id = str(message.raw.get("event_id") or message.id or "")
        async with self._game_lock:
            async with self._provider()() as repo:
                result = await CommunityService(repo.session).attack_boss(
                    platform=message.platform,
                    adapter=message.adapter,
                    user_id=message.sender_id,
                    nickname=message.sender_name,
                    conversation_id=message.conversation_id,
                    event_id=event_id,
                    config=self.config,
                )
        lines = [
            f"本次造成 {result['damage']} 点伤害，获得 {result['reward']} 积分。",
            f"今日还可攻击 {result['attacks_left']} 次。",
            self._boss_status_text(result),
        ]
        if result["status"] == "defeated":
            lines.append(
                f"Boss 已被击败！{result['participant_count']} 名参与者平分 "
                f"{result['payout_total']} 积分。"
            )
            if result["pool_reward"]:
                lines.append(f"你获得击杀分红 {result['pool_reward']} 积分。")
            return "\n".join(lines)
        return "\n".join(lines), self._boss_keyboard()

    @staticmethod
    def _boss_status_text(result: dict[str, Any]) -> str:
        max_hp = max(int(result["max_hp"]), 1)
        remaining = max(int(result["remaining_hp"]), 0)
        filled = min(10, max(0, round((remaining / max_hp) * 10)))
        bar = "█" * filled + "░" * (10 - filled)
        status = "已击败" if result["status"] == "defeated" else "战斗中"
        return f"Boss 血量：{remaining} / {max_hp}\n{bar}　{status}"

    async def _horse_race_status(
        self, message: Message
    ) -> tuple[str, dict[str, Any]]:
        async with self._game_lock, self._provider()() as repo:
            result = await CommunityService(repo.session).horse_race_status(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                config=self.config,
            )
        return self._horse_race_status_text(result), self._horse_race_keyboard()

    async def _join_horse_race(
        self, message: Message, horse_number: int
    ) -> tuple[str, dict[str, Any]]:
        async with self._game_lock, self._provider()() as repo:
            result = await CommunityService(repo.session).join_horse_race(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                horse_number=horse_number,
                config=self.config,
            )
        prefix = "本轮已经支持" if result["duplicate"] else "支持成功"
        content = (
            f"{prefix}：{horse_number}号 · {_HORSE_NAMES[horse_number]}。\n"
            f"本轮不消耗积分，{result['race_hour']:02d}:"
            f"{result['draw_minute']:02d} 自动开奖。\n"
            f"{self._horse_race_status_text(result)}"
        )
        return content, self._horse_race_keyboard()

    def _horse_race_status_text(self, result: dict[str, Any]) -> str:
        counts = result["counts"]
        lines = [
            f"本轮奖池：{self.config.horse_race_prize_pool} 积分",
            f"开奖时间：{result['race_hour']:02d}:{result['draw_minute']:02d}",
            f"1号 赤焰：{counts.get(1, 0)} 人　2号 闪电：{counts.get(2, 0)} 人",
            f"3号 追风：{counts.get(3, 0)} 人　4号 黑曜：{counts.get(4, 0)} 人",
            "每人每轮只能支持一匹马，中奖阵营平分奖池。",
        ]
        previous = result.get("previous")
        if isinstance(previous, dict) and previous.get("winning_horse") in _HORSE_NAMES:
            winning_horse = int(previous["winning_horse"])
            lines.extend(
                [
                    "—— 上期开奖 ——",
                    f"{int(previous['race_hour']):02d}:{int(previous['draw_minute']):02d}　"
                    f"{winning_horse}号 · {_HORSE_NAMES[winning_horse]} 获胜",
                ]
            )
            winners = [row for row in previous.get("winners", []) if isinstance(row, dict)]
            visible = winners[:8]
            winner_text = "、".join(
                f"{str(row.get('nickname') or '群成员')} +{int(row.get('reward') or 0)}"
                for row in visible
            )
            if len(winners) > len(visible):
                winner_text += f" 等 {len(winners)} 人"
            lines.append(f"获奖名单：{winner_text or '暂无获奖用户'}")
        else:
            lines.extend(["—— 上期开奖 ——", "暂无历史开奖记录"])
        return "\n".join(lines)

    def _high_low_offer(self, message: Message) -> tuple[str, dict[str, Any]] | str:
        if not self.config.high_low_enabled:
            return "押大小暂未开放。"
        return (
            f"每局固定投入 {self.config.high_low_stake} 积分。\n"
            f"每人每天最多 {self.config.high_low_daily_limit} 次。\n"
            "1–50 为小，51–100 为大；猜中返还双倍，猜错只扣投入积分。\n"
            "点击大或小后立即扣分并开奖。",
            self._high_low_choice_keyboard(message.sender_id),
        )

    async def _play_high_low(
        self,
        message: Message,
        choice: str,
    ) -> str:
        event_id = str(message.raw.get("event_id") or message.id or "")
        async with self._game_lock, self._provider()() as repo:
            result = await CommunityService(repo.session).play_high_low(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                choice=choice,
                event_id=event_id,
                config=self.config,
            )
        if result["won"]:
            outcome = (
                f"猜中了！返还 {result['payout']} 积分，"
                f"本局净赚 {result['net_points']} 积分。"
            )
        else:
            outcome = f"没猜中，本局扣除 {result['amount']} 积分。"
        prefix = "本次点击已经结算。" if result["duplicate"] else "开奖结果"
        return (
            f"{prefix}：{result['roll']}（{result['result_side']}）。{outcome}\n"
            f"当前积分 {result['balance']}，今天还可玩 {result['remaining']} 次。"
        )

    def _is_qq_admin(self, message: Message) -> bool:
        settings = getattr(self.ctx, "settings", None)
        qq = getattr(getattr(settings, "adapters", None), "qq", None)
        admin_ids = {
            str(item).strip() for item in (getattr(qq, "admin_openids", None) or []) if str(item).strip()
        }
        admin_ids.update(self.config.red_packet_admin_user_ids)
        candidates = {
            str(message.sender_id or "").strip(),
            str(message.raw.get("sender_openid") or "").strip(),
            str(message.raw.get("member_openid") or "").strip(),
        }
        candidates.discard("")
        return bool(admin_ids.intersection(candidates))

    async def _create_red_packet(
        self, message: Message
    ) -> tuple[str, dict[str, Any]]:
        system_funded = self._is_qq_admin(message)
        async with self._provider()() as repo:
            packet = await CommunityService(repo.session).create_red_packet(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                system_funded=system_funded,
            )
        if system_funded:
            content = (
                f"{message.sender_name or '管理员'}发了一个积分红包！\n"
                f"共 {packet['packet_count']} 份，每份 1–10 积分。\n"
                "先到先得，点击立即领取。"
            )
            return content, self._red_packet_keyboard(str(packet["packet_id"]))
        content = (
            "红包待确认\n"
            f"共 {packet['packet_count']} 份，合计 {packet['total_points']} 积分。\n"
            "确认后将从你的积分余额扣除，再发布到当前群。"
        )
        return content, self._red_packet_confirm_keyboard(
            str(packet["packet_id"]), message.sender_id
        )

    async def _confirm_red_packet(
        self, message: Message, packet_id: str
    ) -> tuple[str, dict[str, Any]]:
        async with self._provider()() as repo:
            packet = await CommunityService(repo.session).confirm_red_packet(
                packet_id=packet_id,
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                config=self.config,
            )
        content = (
            f"{message.sender_name or '群友'}发了一个积分红包！\n"
            f"共 {packet['packet_count']} 份，每份 1–10 积分。\n"
            "先到先得，点击立即领取。"
        )
        return content, self._red_packet_keyboard(packet_id)

    async def _claim_red_packet(self, message: Message, packet_id: str) -> str:
        async with self._provider()() as repo:
            result = await CommunityService(repo.session).claim_red_packet(
                packet_id=packet_id,
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                config=self.config,
            )
        if result["duplicate"]:
            return f"你已经抢过了，获得 {result['amount']} 积分。当前 {result['balance']} 积分。"
        tail = "红包已抢完。" if result["remaining_count"] == 0 else f"还剩 {result['remaining_count']} 份。"
        return (
            f"手气不错，抢到 {result['amount']} 积分！"
            f"当前 {result['balance']} 积分，{tail}"
        )

    async def _bind(self, message: Message, invite_code: str) -> str:
        if not _INVITE_CODE.fullmatch(invite_code):
            return "请输入有效的 8 位永久邀请码。"
        validation = await anyio.to_thread.run_sync(self._query_weiban, invite_code)
        if validation.get("success") is not True:
            error = validation.get("error")
            if error == "account_not_found":
                return "没有找到这个邀请码，请检查后重试。"
            return "邀请码验证暂时失败，请稍后再试。"
        provider = self._provider()
        async with provider() as repo:
            result = await CommunityService(repo.session).bind(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                invite_code=invite_code,
            )
        if result["already_bound"]:
            return f"已经绑定过了，当前积分 {result['balance']}。"
        return f"绑定成功，当前积分 {result['balance']}。现在可以签到和玩游戏了。"

    async def _checkin(self, message: Message) -> str:
        async with self._provider()() as repo:
            result = await CommunityService(repo.session).checkin(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                config=self.config,
            )
        if result["already"]:
            return f"今天已经签过了。连续 {result['streak']} 天，积分 {result['balance']}。"
        return (
            f"签到成功，连续 {result['streak']} 天，获得 {result['reward']} 积分。"
            f"当前 {result['balance']} 积分。"
        )

    async def _points(self, message: Message) -> str:
        async with self._provider()() as repo:
            result = await CommunityService(repo.session).account_summary(
                message.platform,
                message.adapter,
                message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
            )
        return f"你现在有 {result['balance']} 积分。"

    async def _ledger(self, message: Message) -> str:
        async with self._provider()() as repo:
            rows = await CommunityService(repo.session).ledger_for_user(
                message.platform, message.adapter, message.sender_id, limit=8
            )
        if not rows:
            return "还没有积分记录。"
        lines = ["最近积分明细："]
        for item in rows:
            sign = "+" if item["delta"] > 0 else ""
            label = _REASON_LABELS.get(item["reason"], item["reason"])
            lines.append(f"{sign}{item['delta']}  {label}  余额 {item['balance_after']}")
        return "\n".join(lines)

    async def _account_status(self, message: Message) -> str:
        async with self._provider()() as repo:
            account = await CommunityService(repo.session).account_summary(
                message.platform, message.adapter, message.sender_id
            )
        result = await anyio.to_thread.run_sync(self._query_weiban, account["invite_code"])
        if result.get("success") is not True:
            return f"账号已绑定，积分 {account['balance']}。微伴状态暂时查询失败。"
        data = result.get("account") or {}
        return self._format_member_card(data, account["balance"])

    def _token_exchange_offer(self) -> str:
        if not self.config.token_exchange_enabled:
            return "Token 加油包暂未开放，请稍后再来。"
        return (
            "Token 加油包\n"
            "100 积分兑换 100,000 Token\n"
            "200 积分兑换 210,000 Token\n"
            "500 积分兑换 550,000 Token\n"
            "1,000 积分兑换 1,100,000 Token\n"
            "手动生图：200 积分兑换 1 次，1,000 积分兑换 5 次\n"
            "Token 进入独立钱包，会员额度用完后继续抵扣，永久有效。\n"
            "点击档位后立即兑换，请勿重复点击。"
        )

    async def _exchange_tokens(
        self,
        message: Message,
        *,
        points_cost: int,
        token_amount: int,
    ) -> str:
        if not self.config.token_exchange_enabled:
            return "Token 加油包暂未开放，请稍后再来。"
        provider = self._provider()
        async with provider() as repo:
            exchange = await CommunityService(repo.session).begin_token_exchange(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                points_cost=points_cost,
                token_amount=token_amount,
                config=self.config,
            )
        self._load_weiban_env()
        try:
            wallet = await grant_token_pack(
                invite_code=str(exchange["invite_code"]),
                amount_tokens=int(exchange["token_amount"]),
                idempotency_key=str(exchange["idempotency_key"]),
                reason=f"QQ群积分兑换 {exchange['exchange_id']}",
            )
        except TokenGrantError as exc:
            if exc.retryable:
                return (
                    "兑换请求正在确认中，积分已暂时锁定。"
                    "稍后发送“兑换状态”会使用同一订单继续确认，不会重复到账。"
                )
            async with provider() as repo:
                await CommunityService(repo.session).fail_token_exchange(
                    str(exchange["exchange_id"]), exc.error_code
                )
            return "Token 接口暂不可用，本次兑换未完成，积分已自动退回。"
        async with provider() as repo:
            await CommunityService(repo.session).complete_token_exchange(
                str(exchange["exchange_id"])
            )
        available = wallet.get("available_tokens")
        balance_text = f"，钱包余额 {int(available):,} Token" if isinstance(available, int) else ""
        return (
            f"兑换成功！已到账 {int(exchange['token_amount']):,} Token{balance_text}。"
            f"本次消耗 {int(exchange['points_cost'])} 积分。"
        )

    async def _exchange_character_images(
        self,
        message: Message,
        *,
        points_cost: int,
        image_amount: int,
    ) -> str:
        if not self.config.token_exchange_enabled:
            return "加油站暂未开放，请稍后再来。"
        provider = self._provider()
        async with provider() as repo:
            exchange = await CommunityService(repo.session).begin_character_image_exchange(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                nickname=message.sender_name,
                conversation_id=message.conversation_id,
                points_cost=points_cost,
                image_amount=image_amount,
                config=self.config,
            )
        self._load_weiban_env()
        try:
            grant = await grant_character_image_count(
                invite_code=str(exchange["invite_code"]),
                amount=int(exchange["image_amount"]),
                idempotency_key=str(exchange["idempotency_key"]),
                reason=f"QQ群积分兑换手动生图 {exchange['exchange_id']}",
            )
        except TokenGrantError as exc:
            if exc.retryable:
                return "兑换请求正在确认中，积分已暂时锁定；再次点击原档位会复用同一订单。"
            async with provider() as repo:
                await CommunityService(repo.session).fail_character_image_exchange(
                    str(exchange["exchange_id"]), exc.error_code
                )
            return "手动生图接口暂不可用，本次兑换未完成，积分已自动退回。"
        async with provider() as repo:
            await CommunityService(repo.session).complete_character_image_exchange(
                str(exchange["exchange_id"])
            )
        after = grant.get("after") if isinstance(grant.get("after"), dict) else {}
        remaining = after.get("remaining")
        remaining_text = f"，当前剩余 {int(remaining)} 次" if isinstance(remaining, int) else ""
        return (
            f"兑换成功！已增加 {int(exchange['image_amount'])} 次手动生图{remaining_text}。"
            f"本次消耗 {int(exchange['points_cost'])} 积分。"
        )

    @staticmethod
    def _format_member_card(data: dict[str, Any], balance: int) -> str:
        active_value = data.get("is_active")
        active = "✅ 正常" if active_value is True else "⛔ 已停用" if active_value is False else "❔ 未知"
        plan_code = str(data.get("plan_code") or "").strip().lower()
        plan = {"free": "Free", "lite": "Lite", "pro": "Pro"}.get(
            plan_code, plan_code.upper() or "未配置"
        )
        expires = str(data.get("plan_expires_at") or "").strip()
        if "T" in expires:
            expires = expires.split("T", 1)[0]
        usage = data.get("token_usage") if isinstance(data.get("token_usage"), dict) else {}
        lines = [
            "会员中心",
            f"账号状态：{active}",
            f"会员等级：👑 {plan}",
            f"有效期至：{expires or '长期有效'}",
            "额度使用：",
            WeibanCommunityPlugin._format_quota("5 小时", usage.get("five_hour")),
            WeibanCommunityPlugin._format_quota("本周", usage.get("weekly")),
            WeibanCommunityPlugin._format_quota("本月", usage.get("monthly")),
            WeibanCommunityPlugin._format_quota("加油包 TOKEN", data.get("token_wallet")),
            WeibanCommunityPlugin._format_character_image(data.get("character_image")),
            f"社区积分：🪙 {balance}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_character_image(quota: object) -> str:
        if not isinstance(quota, dict):
            return "手动生图：暂未配置"
        limit = quota.get("limit")
        used = quota.get("used")
        remaining = quota.get("remaining")
        if not isinstance(limit, (int, float)):
            return "手动生图：暂未配置"
        used_text = f"{used:,}" if isinstance(used, (int, float)) else "--"
        remaining_text = f"，剩余 {remaining:,} 次" if isinstance(remaining, (int, float)) else ""
        return f"手动生图：已用 {used_text} / {limit:,} 次{remaining_text}"

    @staticmethod
    def _format_quota(label: str, window: object) -> str:
        if not isinstance(window, dict):
            return f"{label}：暂未配置"
        usage = window.get("usage")
        limit = window.get("limit")
        if window.get("unlimited") is True:
            suffix = f"（已用 {usage:,}）" if isinstance(usage, (int, float)) else ""
            line = f"{label}：不限量{suffix}"
            return line
        if not isinstance(limit, (int, float)):
            return f"{label}：暂未配置"
        used = f"{usage:,}" if isinstance(usage, (int, float)) else "--"
        remaining = window.get("remaining")
        suffix = f"，剩余 {remaining:,}" if isinstance(remaining, (int, float)) else ""
        line = f"{label}：{used} / {limit:,}{suffix}"
        reset_line = WeibanCommunityPlugin._format_reset_time(label, window)
        return f"{line}\n↳ {reset_line}" if reset_line else line

    @staticmethod
    def _format_reset_time(label: str, window: dict[str, Any]) -> str:
        if window.get("reset_known") is not True:
            return "" if label == "加油包 TOKEN" else "重置时间暂不可用"
        raw = str(window.get("reset_at") or "").strip()
        if not raw:
            return "当前没有等待恢复的额度" if label == "5 小时" else "重置时间暂不可用"
        try:
            target = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            now = datetime.now(UTC)
        except ValueError:
            return "重置时间暂不可用"
        total_minutes = max(0, int((target.astimezone(UTC) - now).total_seconds() + 59) // 60)
        days, remainder = divmod(total_minutes, 1440)
        hours, minutes = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days}天")
        if hours:
            parts.append(f"{hours}小时")
        if minutes:
            parts.append(f"{minutes}分钟")
        relative = "".join(parts) + "后" if parts else "即将"
        action = "恢复" if label == "5 小时" else "重置"
        local_time = target.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m/%d %H:%M")
        return f"{relative}{action} · {local_time}"

    async def _points_ranking(self, message: Message) -> str:
        if not self.config.leaderboard_enabled:
            return "积分排行榜当前未开放。"
        async with self._provider()() as repo:
            service = CommunityService(repo.session)
            payload = {
                period: await service.points_leaderboard(
                    message.conversation_id, self.config, period=period, limit=5
                )
                for period in ("day", "week", "month", "total")
            }
        return json.dumps(payload, ensure_ascii=False)

    async def _activity_ranking(self, message: Message, days_ago: int) -> str:
        target = local_date(self.config) - timedelta(days=days_ago)
        async with self._provider()() as repo:
            rows = await CommunityService(repo.session).activity_ranking(
                message.conversation_id, target, self.config, limit=5
            )
        if not rows:
            return "还没有达到最低发言数的已绑定用户。"
        title = "今日发言榜" if days_ago == 0 else "昨日发言榜"
        return "\n".join(
            [title, *[f"{index}. {row['nickname']}  {row['message_count']}条" for index, row in enumerate(rows, 1)]]
        )

    async def _rps(self, message: Message, choice: str) -> str:
        async with self._provider()() as repo:
            result = await CommunityService(repo.session).rock_paper_scissors(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                conversation_id=message.conversation_id,
                choice=choice,
                message_id=message.id,
                config=self.config,
            )
        labels = {"win": "你赢了", "draw": "平局", "lose": "你输了"}
        return (
            f"你出{choice}，小x出{result['bot_choice']}，{labels[result['outcome']]}。"
            f"奖励 {result['reward']} 积分，当前 {result['balance']}，今天剩 {result['remaining']} 次。"
        )

    async def _fortune(self, message: Message) -> str:
        async with self._provider()() as repo:
            result = await CommunityService(repo.session).fortune(
                platform=message.platform,
                adapter=message.adapter,
                user_id=message.sender_id,
                conversation_id=message.conversation_id,
                config=self.config,
            )
        if result.get("duplicate"):
            return f"今天的运势看过了：{result['score']} 分，当前积分 {result['balance']}。"
        return (
            f"今日运势 {result['score']} 分，获得 {result['reward']} 积分。"
            f"当前 {result['balance']} 积分。"
        )

    async def _settlement_loop(self) -> None:
        while True:
            await self._run_settlement_cycle()
            await asyncio.sleep(60)

    async def _run_settlement_cycle(self) -> None:
        failures: list[str] = []
        try:
            await self._settle_due_activity()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("WeibanCommunity 发言榜结算失败: {}", exc)
            failures.append("activity")
        try:
            await self._process_horse_races()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("WeibanCommunity 群体赛马处理失败: {}", exc)
            failures.append("horse_race")
        if failures:
            raise RuntimeError(
                "WeibanCommunity settlement failed: " + ",".join(failures)
            )

    async def _process_horse_races(self) -> None:
        if not self.ctx or not self.config.enabled or not self.config.horse_race_enabled:
            return
        async with self._game_lock, self._provider()() as repo:
            service = CommunityService(repo.session)
            settled = await service.settle_due_horse_races(self.config)
            opened = await service.open_current_horse_races(self.config)
            if self.ctx.scheduler is not None:
                for result in settled:
                    await enqueue_reply(
                        repo.session,
                        self._horse_race_result_reply(result),
                        idempotency_key=f"weiban:horse:{result['race_id']}:result",
                        source=self.name,
                    )
                for result in opened:
                    await enqueue_reply(
                        repo.session,
                        self._horse_race_opened_reply(result),
                        idempotency_key=f"weiban:horse:{result['race_id']}:opened",
                        source=self.name,
                    )
                return
        if not self.ctx.send_reply:
            return
        for result in settled:
            await self._send_horse_race_result(result)
        for result in opened:
            await self._send_horse_race_opened(result)

    async def _send_horse_race_opened(self, result: dict[str, Any]) -> None:
        if not self.ctx or not self.ctx.send_reply:
            return
        await self.ctx.send_reply(self._horse_race_opened_reply(result))

    def _horse_race_opened_reply(self, result: dict[str, Any]) -> Reply:
        plain = "群体赛马开赛！\n" + self._horse_race_status_text(result)
        if result["adapter"] != "qq":
            return Reply(
                platform=result["platform"],
                adapter=result["adapter"],
                conversation_id=result["conversation_id"],
                type="text",
                content=plain + "\n发送“支持赛马 1”到“支持赛马 4”参与。",
            )
        current = datetime.now(ZoneInfo(self.config.timezone))
        recall_seconds = max(
            (result["draw_minute"] - current.minute) * 60 - current.second,
            10,
        )
        return Reply(
            platform=result["platform"],
            adapter=result["adapter"],
            conversation_id=result["conversation_id"],
            type="keyboard",
            content=self._markdown("群体赛马", plain),
            metadata={
                "keyboard": self._horse_race_keyboard(),
                "fallback_text": plain,
                "auto_recall_seconds": recall_seconds,
            },
        )

    async def _send_horse_race_result(self, result: dict[str, Any]) -> None:
        if not self.ctx or not self.ctx.send_reply:
            return
        await self.ctx.send_reply(self._horse_race_result_reply(result))

    def _horse_race_result_reply(self, result: dict[str, Any]) -> Reply:
        horse = int(result["winning_horse"])
        base, remainder = divmod(result["payout_total"], result["winner_count"])
        reward_text = (
            f"每人获得 {base} 积分"
            if remainder == 0
            else f"每人获得 {base}–{base + 1} 积分"
        )
        winners = [row for row in result.get("winners", []) if isinstance(row, dict)]
        visible_winners = winners[:10]
        winner_lines = [
            f"{index}. {str(row.get('nickname') or '群成员')}　+{int(row.get('reward') or 0)} 积分"
            for index, row in enumerate(visible_winners, start=1)
        ]
        hidden_count = max(int(result["winner_count"]) - len(visible_winners), 0)
        if hidden_count:
            winner_lines.append(f"另有 {hidden_count} 人中奖")
        plain = (
            f"群体赛马开奖结果：{horse}号 · {_HORSE_NAMES[horse]} 获胜！\n"
            f"{result['winner_count']} 人平分 {result['payout_total']} 积分，{reward_text}。\n"
            "中奖名单：\n"
            + ("\n".join(winner_lines) if winner_lines else "暂无中奖名单")
        )
        if result["adapter"] == "qq":
            return Reply(
                platform=result["platform"],
                adapter=result["adapter"],
                conversation_id=result["conversation_id"],
                type="keyboard",
                content="**🏁 群体赛马 · 开奖结果**\n\n" + plain.replace("\n", "  \n"),
                metadata={
                    "keyboard": self._back_to_menu_keyboard(),
                    "fallback_text": plain,
                },
            )
        return Reply(
            platform=result["platform"],
            adapter=result["adapter"],
            conversation_id=result["conversation_id"],
            type="text",
            content=plain,
        )

    async def _settle_due_activity(self) -> None:
        if not self.ctx or not self.config.enabled or not self.config.activity_enabled:
            return
        now_local = datetime.now(ZoneInfo(self.config.timezone))
        cutoff = time(self.config.activity_settle_hour, self.config.activity_settle_minute)
        latest = now_local.date() - timedelta(days=1 if now_local.time() >= cutoff else 2)
        first = local_date(self.config, self.config_created_at)
        start = max(first, latest - timedelta(days=6))
        if latest < start:
            return
        async with self._provider()() as repo:
            service = CommunityService(repo.session)
            settlements: list[dict[str, Any]] = []
            current = start
            while current <= latest:
                settlements.extend(await service.settle_activity_day(current, self.config))
                current += timedelta(days=1)
            if self.config.activity_announce and self.ctx.scheduler is not None:
                for settlement in settlements:
                    reply = self._activity_settlement_reply(settlement)
                    if reply is None:
                        continue
                    identity = (
                        f"{settlement['conversation_id']}:{settlement['date'].isoformat()}"
                    )
                    await enqueue_reply(
                        repo.session,
                        reply,
                        idempotency_key=(
                            "weiban:activity:"
                            + sha256(identity.encode()).hexdigest()[:40]
                        ),
                        source=self.name,
                    )
                return
        if not self.config.activity_announce or not self.ctx.send_reply:
            return
        for settlement in settlements:
            reply = self._activity_settlement_reply(settlement)
            if reply is None:
                continue
            await self.ctx.send_reply(reply)

    @staticmethod
    def _activity_settlement_reply(settlement: dict[str, Any]) -> Reply | None:
        awards = settlement["awards"]
        if not awards:
            return None
        lines = [f"{settlement['date'].isoformat()} 群发言榜奖励："]
        lines.extend(
            f"{item['rank']}. {item['nickname']}  {item['message_count']}条  +{item['reward']}积分"
            for item in awards
        )
        return Reply(
            platform=settlement["platform"],
            adapter=settlement["adapter"],
            conversation_id=settlement["conversation_id"],
            type="text",
            content="\n".join(lines),
        )

    def _provider(self):
        provider = getattr(getattr(self.ctx, "conversations", None), "repository_provider", None)
        if provider is None:
            raise CommunityError("积分数据库暂时不可用。")
        return provider

    @staticmethod
    def _query_weiban(invite_code: str) -> dict[str, Any]:
        from xbot.agent.hermes_runtime import _ensure_hermes_import_path, hermes_home_dir

        _ensure_hermes_import_path()
        from hermes_cli.env_loader import load_hermes_dotenv

        load_hermes_dotenv(hermes_home=hermes_home_dir())
        from xbot.agent.tools.hermes_weiban import query_account

        try:
            return json.loads(query_account({"invite_code": invite_code}))
        except (TypeError, json.JSONDecodeError):
            return {"success": False, "error": "weiban_query_failed"}

    @staticmethod
    def _load_weiban_env() -> None:
        from xbot.agent.hermes_runtime import _ensure_hermes_import_path, hermes_home_dir

        _ensure_hermes_import_path()
        from hermes_cli.env_loader import load_hermes_dotenv

        load_hermes_dotenv(hermes_home=hermes_home_dir())

    @staticmethod
    def _help() -> str:
        return (
            "微伴社区玩法：\n"
            "绑定 邀请码｜签到｜我的积分｜积分明细｜我的账号\n"
            "猜拳 石头/剪刀/布｜今日运势｜幸运宝箱｜每日 Boss｜群体赛马\n"
            "押大小 大/小（每局固定 5 积分）\n"
            "积分排行｜周榜｜月榜｜今日发言排行｜兑换Token"
        )
