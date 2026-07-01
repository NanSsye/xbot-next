from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import random
import re
import sqlite3
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from WechatAPI import WechatAPIClient
from database.contacts_db import get_contact_from_db
from database.group_members_db import get_group_members_from_db
from database.messsagDB import MessageDB
from utils.decorators import on_at_message, on_text_message, schedule
from utils.plugin_base import PluginBase


SYSTEM_PROMPT = """你是一名中文群聊总结助手。

请根据用户提供的群聊消息记录，输出严格 JSON，不要输出任何额外解释。
JSON 必须包含以下字段：
{{
  "vibe": "一句话概括本群讨论风格（中文，20-40字）",
  "quote": "一句与今日话题相关或有启发性的名言/格言（中文，15-30字，不要加引号和出处）",
  "topics": [
    {{
      "title": "话题标题（中文，尽量短）",
      "heat": 1,
      "time_range": "HH:MM–HH:MM",
      "participants": ["参与者1", "参与者2"],
      "process": "只写发生了什么（中文，60-120字，忠于记录，不要脑补）",
      "rating": "一句评价（中文，10-30字）"
    }}
  ]
}}

要求：
1) 只输出 JSON（必须可被 json.loads 解析）。
2) topics 输出 1 到 {max_topics} 个，按热度从高到低排序。
3) heat 为 1-5 的整数（热度越高越“吵/热”）。
4) time_range 必须是 HH:MM–HH:MM（用中文破折号也可以，但优先用这个）。
5) participants 最多 5 个，用消息中出现的称呼即可。
6) 过程描述必须忠于聊天记录，不能编造不存在的信息。
"""


class UserError(Exception):
    """给最终用户看的清晰错误。"""


@dataclass(frozen=True)
class Topic:
    index: int
    title: str
    heat: int
    time_range: str
    participants: list[str]
    process: str
    rating: str
    accent: str


class JaysonChatSummary(PluginBase):
    description = "群聊总结：生成图片卡片并发送"
    author = "Jayson"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self.plugin_dir = Path(__file__).resolve().parent
        self.config = self._load_config()

        basic_config = self.config.get("basic", {})
        plugin_config = self.config.get("JaysonChatSummary", {})

        self.enable = bool(basic_config.get("enable", False))
        self.commands = [
            str(item).strip() for item in plugin_config.get("commands", ["群聊总结"]) if str(item).strip()
        ] or ["群聊总结"]

        self.default_hours = int(plugin_config.get("default_hours", 12))
        self.max_messages = int(plugin_config.get("max_messages", 600))
        self.max_topics = int(plugin_config.get("max_topics", 4))
        self.random_template_enable = bool(plugin_config.get("random_template_enable", True))
        self.template_paths = self._load_template_paths(plugin_config)
        self.template_path = self.template_paths[0] if self.template_paths else (
            self.plugin_dir / "group_chat_summary_card_template.html"
        )

        self.api_base_url = self._pick_api_config_value(
            plugin_config,
            "minimax_base_url",
            "openai_base_url",
        )
        self.api_key = self._pick_api_config_value(
            plugin_config,
            "minimax_api_key",
            "openai_api_key",
        )
        self.model = self._pick_api_config_value(
            plugin_config,
            "minimax_model",
            "openai_model",
        )
        self.request_timeout = int(plugin_config.get("request_timeout", 60))
        self.llm_max_retries = int(plugin_config.get("llm_max_retries", 3))
        self.llm_retry_base_delay_seconds = float(plugin_config.get("llm_retry_base_delay_seconds", 1.0))

        self.html2image_url = str(
            plugin_config.get("html2image_url", "http://127.0.0.1:8000/api/html2image")
        ).strip()

        self.schedule_enable = bool(plugin_config.get("schedule_enable", False))
        self.schedule_hour = int(plugin_config.get("schedule_hour", 22))
        self.schedule_minute = int(plugin_config.get("schedule_minute", 30))
        self.schedule_second = int(plugin_config.get("schedule_second", 0))
        self.schedule_summary_hours = int(plugin_config.get("schedule_summary_hours", 12))
        self.schedule_random_delay_seconds = int(plugin_config.get("schedule_random_delay_seconds", 0))

        self.target_groups = [
            str(item).strip() for item in plugin_config.get("target_groups", []) if str(item).strip()
        ]

        self._last_schedule_fire_key: str | None = None
        self._chatroom_member_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
        self._groupmonitor_member_cache: dict[str, tuple[datetime, dict[str, str]]] = {}

    def _load_config(self) -> dict[str, Any]:
        config_path = self.plugin_dir / "config.toml"
        with open(config_path, "rb") as file:
            return tomllib.load(file)

    @staticmethod
    def _pick_api_config_value(plugin_config: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = str(plugin_config.get(key, "")).strip()
            if value:
                return value
        return ""

    def _load_template_paths(self, plugin_config: dict[str, Any]) -> list[Path]:
        configured_templates = plugin_config.get("template_files", [])
        if isinstance(configured_templates, list):
            template_paths = [
                self.plugin_dir / str(name).strip()
                for name in configured_templates
                if str(name).strip()
            ]
        else:
            template_paths = []

        if not template_paths:
            template_paths = sorted(self.plugin_dir.glob("group_chat_summary_card_template*.html"))

        return [path for path in template_paths if path.exists() and path.is_file()]

    def _pick_template_path(self) -> Path:
        if not self.template_paths:
            raise UserError("找不到可用的卡片模板文件。")
        if self.random_template_enable:
            return random.choice(self.template_paths)
        return self.template_paths[0]

    @on_text_message(priority=70)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        return await self._handle_message(bot, message, is_at=False)

    @on_at_message(priority=70)
    async def handle_at(self, bot: WechatAPIClient, message: dict):
        return await self._handle_message(bot, message, is_at=True)

    async def _handle_message(self, bot: WechatAPIClient, message: dict, *, is_at: bool) -> bool:
        if not self.enable:
            return True

        content = str(message.get("Content", "")).strip()
        if not content:
            return True

        matched = self._match_command(content, is_at=is_at)
        if not matched:
            return True

        to_wxid = str(message.get("FromWxid", "")).strip()
        if not to_wxid:
            return False

        args = matched[1]
        try:
            hours = self._parse_hours(args)
            image_bytes = await self._build_summary_image(bot=bot, chat_wxid=to_wxid, hours=hours)
            await bot.send_image_message(to_wxid, image=image_bytes)
        except UserError as exc:
            await bot.send_text_message(to_wxid, f"群聊总结失败：{exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("[JaysonChatSummary] 处理失败: {}", exc)
            await bot.send_text_message(to_wxid, "群聊总结失败：发生未预期错误，请查看日志。")

        return False

    def _match_command(self, content: str, *, is_at: bool) -> tuple[str, str] | None:
        if is_at:
            parts = [p for p in re.split(r"[\s\u2005]+", content.strip()) if p]
            if len(parts) >= 2:
                possible_command = parts[1]
                for command in self.commands:
                    if possible_command == command:
                        return command, " ".join(parts[2:]).strip()

        for command in self.commands:
            if content == command:
                return command, ""
            prefix = f"{command} "
            if content.startswith(prefix):
                return command, content[len(prefix) :].strip()
        return None

    def _parse_hours(self, args: str) -> int:
        args = str(args or "").strip()
        if not args:
            return max(1, int(self.default_hours))

        if not re.fullmatch(r"\d{1,3}", args):
            raise UserError("参数格式不对，请使用：群聊总结 或 群聊总结 7（数字代表小时）。")

        hours = int(args)
        if hours <= 0:
            raise UserError("小时数必须大于 0。")
        if hours > 72:
            raise UserError("小时数太大了，建议不超过 72 小时。")
        return hours

    def validate_runtime_config(self) -> None:
        if not self.api_base_url or not self.api_key or not self.model:
            raise UserError(
                "请先在 JaysonChatSummary/config.toml 中填写 minimax_base_url/minimax_api_key/minimax_model，"
                "或继续使用 openai_base_url/openai_api_key/openai_model。"
            )
        if not self.html2image_url:
            raise UserError("请先在 JaysonChatSummary/config.toml 中填写 html2image_url。")
        if not self.template_paths:
            raise UserError("找不到卡片模板文件，请检查 GroupChatSummary 目录中的模板文件。")

    def _extract_contact_name(self, contact: dict[str, Any] | None) -> str:
        if not isinstance(contact, dict):
            return ""

        candidates = [
            contact.get("remark"),
            contact.get("Remark"),
            contact.get("display_name"),
            contact.get("DisplayName"),
            contact.get("ChatRoomNickName"),
            contact.get("chat_room_nick_name"),
            contact.get("nickname"),
            contact.get("NickName"),
            contact.get("ChatRoomName"),
            contact.get("chatroom_name"),
            contact.get("name"),
        ]

        for value in candidates:
            if isinstance(value, dict):
                value = value.get("string")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _extract_person_display_name(self, payload: dict[str, Any] | None) -> str:
        """提取“人”的显示名（群名片/备注/昵称），避免误用 ChatRoomName 之类的群 ID 字段。"""
        if not isinstance(payload, dict):
            return ""
        candidates = [
            payload.get("remark"),
            payload.get("Remark"),
            payload.get("display_name"),
            payload.get("DisplayName"),
            payload.get("ChatRoomNickName"),
            payload.get("chat_room_nick_name"),
            payload.get("nickname"),
            payload.get("NickName"),
        ]
        for value in candidates:
            extracted = self._extract_text_value(value)
            if extracted:
                return extracted
        return ""

    @staticmethod
    def _extract_text_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("string", "String", "text", "value", "Value"):
                inner = value.get(key)
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
        return ""

    def _extract_member_wxid(self, member: dict[str, Any]) -> str:
        return self._extract_text_value(
            member.get("UserName")
            or member.get("Username")
            or member.get("user_name")
            or member.get("wxid")
            or member.get("Wxid")
            or member.get("FromUserName")
        )

    @staticmethod
    def _normalize_member_payload(member: dict[str, Any]) -> dict[str, Any]:
        """把不同接口/字段风格的成员数据规范化，尽量补齐 UserName/NickName 字段。"""
        if not isinstance(member, dict):
            return {}
        item = dict(member)
        user_name = item.get("UserName") or item.get("user_name") or item.get("Wxid") or item.get("wxid") or ""
        nick_name = item.get("NickName") or item.get("nick_name") or item.get("display_name") or ""
        if user_name and not item.get("UserName"):
            item["UserName"] = user_name
        if nick_name and not item.get("NickName"):
            item["NickName"] = nick_name
        return item

    def _extract_members_from_payload(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        """从 869 的群信息接口返回里提取成员列表（兼容多种嵌套结构）。"""
        if not isinstance(payload, dict):
            return []

        direct_candidates = [
            payload.get("ChatRoomMember"),
            payload.get("MemberList"),
            payload.get("chatroom_member_list"),
            payload.get("ChatRoomMemberList"),
        ]
        for candidate in direct_candidates:
            if isinstance(candidate, list) and candidate:
                return [
                    self._normalize_member_payload(item)
                    for item in candidate
                    if isinstance(item, dict)
                ]

        for nested_key in ("NewChatroomData", "newChatroomData", "member_data"):
            nested = payload.get(nested_key)
            members = self._extract_members_from_payload(nested) if isinstance(nested, dict) else []
            if members:
                return members

        for list_key in ("ChatRoomInfo", "chatroomInfo", "ContactList", "contactList"):
            container = payload.get(list_key)
            if isinstance(container, list):
                for item in container:
                    members = self._extract_members_from_payload(item) if isinstance(item, dict) else []
                    if members:
                        return members

        return []

    def _build_groupmonitor_db_candidates(self) -> list[Path]:
        """GroupMonitor 的 sqlite 可能位置（尽量不依赖 CWD）。"""
        candidates: list[Path] = []
        try:
            candidates.append(self.plugin_dir.parent / "GroupMonitor" / "group_monitor.db")
        except Exception:
            pass
        candidates.append(Path("plugins/GroupMonitor/group_monitor.db"))

        unique: list[Path] = []
        seen: set[str] = set()
        for item in candidates:
            key = str(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _get_groupmonitor_member_name_map(self, group_wxid: str) -> dict[str, str]:
        """从 GroupMonitor 插件的 sqlite（group_monitor.db）读取群成员昵称映射。"""
        group_wxid = str(group_wxid or "").strip()
        if not group_wxid:
            return {}

        cache_ttl = timedelta(minutes=10)
        cached = self._groupmonitor_member_cache.get(group_wxid)
        if cached and (datetime.now() - cached[0] <= cache_ttl):
            return dict(cached[1])

        db_path: Path | None = None
        for candidate in self._build_groupmonitor_db_candidates():
            if candidate.exists() and candidate.is_file():
                db_path = candidate
                break
        if db_path is None:
            self._groupmonitor_member_cache.pop(group_wxid, None)
            return {}

        name_map: dict[str, str] = {}
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute(
                "SELECT member_id, member_name FROM group_members WHERE group_id = ?",
                (group_wxid,),
            )
            for member_id, member_name in cur.fetchall() or []:
                member_id = str(member_id or "").strip()
                member_name = str(member_name or "").strip()
                if member_id and member_name and member_name != member_id:
                    name_map[member_id] = member_name
            conn.close()
        except Exception as exc:
            logger.warning(
                "[JaysonChatSummary] 读取 GroupMonitor 昵称失败，db_path={} group_wxid={} 原因：{}",
                db_path,
                group_wxid,
                exc,
            )
            self._groupmonitor_member_cache.pop(group_wxid, None)
            return {}

        if name_map:
            self._groupmonitor_member_cache[group_wxid] = (datetime.now(), dict(name_map))
        else:
            self._groupmonitor_member_cache.pop(group_wxid, None)
        return name_map

    async def _get_chatroom_members(self, bot: WechatAPIClient, group_wxid: str) -> list[dict[str, Any]]:
        cache_ttl = timedelta(minutes=10)
        cached = self._chatroom_member_cache.get(group_wxid)
        if cached and (datetime.now() - cached[0] <= cache_ttl):
            return cached[1]

        members: list[dict[str, Any]] = []
        try:
            if hasattr(bot, "get_chatroom_member_list"):
                result = await bot.get_chatroom_member_list(group_wxid)  # type: ignore[attr-defined]
                if isinstance(result, list):
                    members = [item for item in result if isinstance(item, dict)]
            elif hasattr(bot, "get_chatroom_members"):
                result = await bot.get_chatroom_members(group_wxid)  # type: ignore[attr-defined]
                if isinstance(result, list):
                    members = [item for item in result if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("[JaysonChatSummary] 获取群成员列表失败，group_wxid={}，原因：{}", group_wxid, exc)

        # 兜底：参考 GroupMonitor 插件的取数方式（869 call_path），避免客户端不支持 get_chatroom_member_list 导致一直拿不到群成员信息
        if not members and hasattr(bot, "call_path"):
            try:
                detail_data = await bot.call_path(  # type: ignore[attr-defined]
                    "/group/GetChatroomMemberDetail",
                    body={"ChatRoomName": group_wxid},
                )
                members = self._extract_members_from_payload(detail_data)
            except Exception as exc:
                logger.warning(
                    "[JaysonChatSummary] GetChatroomMemberDetail 兜底失败，group_wxid={}，原因：{}",
                    group_wxid,
                    exc,
                )

        if not members and hasattr(bot, "call_path"):
            try:
                info_data = await bot.call_path(  # type: ignore[attr-defined]
                    "/group/GetChatRoomInfo",
                    body={"ChatRoomWxIdList": [group_wxid]},
                )
                members = self._extract_members_from_payload(info_data)
            except Exception as exc:
                logger.warning(
                    "[JaysonChatSummary] GetChatRoomInfo 兜底失败，group_wxid={}，原因：{}",
                    group_wxid,
                    exc,
                )

        # 空列表大概率是接口/权限异常或临时问题，这里不做长时间缓存，避免“永远是 0 人”的假象。
        if members:
            self._chatroom_member_cache[group_wxid] = (datetime.now(), members)
        else:
            self._chatroom_member_cache.pop(group_wxid, None)
        return members

    def _build_group_member_name_map(self, members: list[dict[str, Any]]) -> dict[str, str]:
        name_map: dict[str, str] = {}
        for item in members or []:
            if not isinstance(item, dict):
                continue
            wxid = self._extract_member_wxid(item)
            if not wxid:
                continue

            display_name = self._extract_text_value(
                item.get("DisplayName")
                or item.get("display_name")
                or item.get("ChatRoomNickName")
                or item.get("chat_room_nick_name")
            )
            nick_name = self._extract_text_value(item.get("NickName") or item.get("nickname"))
            chosen = display_name or nick_name
            if chosen and chosen != wxid:
                name_map[wxid] = chosen
        return name_map

    async def _resolve_chatroom_name(self, bot: WechatAPIClient, chat_wxid: str) -> str:
        chat_wxid = str(chat_wxid or "").strip()
        if not chat_wxid:
            return ""

        # 1) 先从本地 contacts.db 拿（最快）
        try:
            local_contact = get_contact_from_db(chat_wxid)
            local_name = self._extract_contact_name(local_contact)
            if local_name and local_name != chat_wxid:
                return local_name
        except Exception:
            pass

        # 2) 你指定的方式：直接用 get_nickname(chat_wxid) 拿群名
        try:
            if hasattr(bot, "get_nickname"):
                nickname = await bot.get_nickname(chat_wxid)
                if isinstance(nickname, str) and nickname.strip() and nickname.strip() != chat_wxid:
                    return nickname.strip()
                # 有的实现可能返回 list
                if isinstance(nickname, list) and nickname:
                    first = str(nickname[0] or "").strip()
                    if first and first != chat_wxid:
                        return first
        except Exception:
            pass

        # 3) 869：群信息通常不在 contacts 里，尝试 GetChatRoomInfo 拿群名
        if chat_wxid.endswith("@chatroom") and hasattr(bot, "call_path"):
            try:
                data = await bot.call_path("/group/GetChatRoomInfo", body={"ChatRoomWxIdList": [chat_wxid]})  # type: ignore[attr-defined]
                room_info: dict[str, Any] | None = None
                if isinstance(data, dict):
                    if isinstance(data.get("ChatRoomInfo"), list) and data.get("ChatRoomInfo"):
                        first = data["ChatRoomInfo"][0]
                        if isinstance(first, dict):
                            room_info = first
                    else:
                        room_info = data
                if room_info:
                    name = self._extract_contact_name(room_info) or self._extract_text_value(
                        room_info.get("NickName") or room_info.get("nickname") or room_info.get("DisplayName")
                    )
                    if name and name != chat_wxid:
                        return name
            except Exception:
                pass

        return chat_wxid

    async def _build_summary_image(self, *, bot: WechatAPIClient, chat_wxid: str, hours: int) -> bytes:
        self.validate_runtime_config()

        is_group = bool(str(chat_wxid).endswith("@chatroom"))
        now = datetime.now()
        start_time = now - timedelta(hours=hours)

        msg_db = MessageDB()
        messages = await msg_db.get_messages(
            start_time=start_time,
            end_time=now,
            from_wxid=chat_wxid,
            msg_type=1,
            is_group=is_group,
            limit=max(1, self.max_messages),
        )

        if not messages:
            raise UserError("这段时间内没有找到可总结的文本消息。")

        messages = list(reversed(messages))

        group_name = await self._resolve_chatroom_name(bot, chat_wxid)

        members: list[dict[str, Any]] = []
        group_member_name_map: dict[str, str] = {}
        if is_group:
            # 1) 主路径：尽量从客户端/接口实时拿群成员（含兜底 call_path）
            live_members = await self._get_chatroom_members(bot, chat_wxid)
            live_member_name_map = self._build_group_member_name_map(live_members)

            # 2) 兜底：从 GroupMonitor 插件数据库读取（你提到的 groupmonitor）
            groupmonitor_member_name_map = self._get_groupmonitor_member_name_map(chat_wxid)

            # 3) 兜底：从 contacts.db 的 group_members 表读取（若有其它插件写入/同步）
            db_members: list[dict[str, Any]] = []
            db_member_name_map: dict[str, str] = {}
            try:
                db_members = get_group_members_from_db(chat_wxid)
                db_member_name_map = self._build_group_member_name_map(db_members)
            except Exception as exc:
                logger.warning(
                    "[JaysonChatSummary] 从群成员数据库加载昵称失败，group_wxid={}，原因：{}",
                    chat_wxid,
                    exc,
                )

            # 昵称映射优先级：实时接口 > contacts.db(group_members) > GroupMonitor DB
            # 说明：实时接口通常更新最快；GroupMonitor 依赖定时/周期性刷新。
            group_member_name_map = {
                **groupmonitor_member_name_map,
                **db_member_name_map,
                **live_member_name_map,
            }

            # 用于后续成员数量/进出群统计：尽量选择“最像完整成员列表”的来源
            if live_members:
                members = live_members
            elif db_members:
                members = db_members
            elif groupmonitor_member_name_map:
                members = [
                    {"wxid": wxid, "UserName": wxid, "NickName": name}
                    for wxid, name in groupmonitor_member_name_map.items()
                ]

        unique_senders = {
            str(getattr(msg, "sender_wxid", "") or "").strip()
            for msg in messages
            if str(getattr(msg, "sender_wxid", "") or "").strip()
        }

        display_name_map: dict[str, str] = {}
        unresolved: set[str] = set()

        # 1) 同步优先：群成员显示名 / 本地 contacts.db
        for sender_wxid in unique_senders:
            name = ""

            if is_group:
                name = str(group_member_name_map.get(sender_wxid, "") or "").strip()

            if is_group:
                try:
                    if hasattr(bot, "get_local_nickname"):
                        local_name = bot.get_local_nickname(sender_wxid, chat_wxid)
                        local_name = str(local_name or "").strip()
                        if local_name:
                            name = local_name
                except Exception:
                    pass

            if not name:
                try:
                    contact = get_contact_from_db(sender_wxid)
                    extracted = self._extract_person_display_name(contact) or self._extract_contact_name(contact)
                    if extracted and extracted != sender_wxid:
                        name = extracted
                except Exception:
                    pass

            if name:
                display_name_map[sender_wxid] = name
            else:
                unresolved.add(sender_wxid)

        unresolved_before_detail = len(unresolved)

        # 2) 兜底：用 get_contract_detail(chatroom=群id) 批量拉取“群名片/备注”
        if unresolved and hasattr(bot, "get_contract_detail"):
            unresolved_list = sorted(unresolved)
            try:
                details = await bot.get_contract_detail(unresolved_list, chatroom=(chat_wxid if is_group else ""))  # type: ignore[attr-defined]
                if isinstance(details, list):
                    for item in details:
                        if not isinstance(item, dict):
                            continue
                        wxid = self._extract_text_value(
                            item.get("UserName")
                            or item.get("Username")
                            or item.get("user_name")
                            or item.get("wxid")
                            or item.get("Wxid")
                        )
                        if not wxid:
                            continue
                        extracted = self._extract_person_display_name(item)
                        if extracted and extracted != wxid:
                            display_name_map[wxid] = extracted
                            unresolved.discard(wxid)
            except Exception:
                pass

        unresolved_before_nickname = len(unresolved)

        # 3) 异步兜底：批量走 get_nickname
        if unresolved and hasattr(bot, "get_nickname"):
            unresolved_list = sorted(unresolved)
            try:
                nicknames = await bot.get_nickname(unresolved_list)
                if isinstance(nicknames, list):
                    for wxid, nickname in zip(unresolved_list, nicknames, strict=False):
                        nickname = str(nickname or "").strip()
                        if nickname:
                            display_name_map[wxid] = nickname
            except Exception:
                pass

        if unique_senders:
            logger.info(
                "[JaysonChatSummary] 昵称解析：总发言者 {}，初始未解析 {}，合约详情后未解析 {}，最终未解析 {}",
                len(unique_senders),
                unresolved_before_detail,
                unresolved_before_nickname,
                len(unresolved),
            )

        for wxid in unique_senders:
            display_name_map.setdefault(wxid, wxid)

        def _display_name(wxid: str) -> str:
            wxid = str(wxid or "").strip()
            if not wxid:
                return "未知"
            return display_name_map.get(wxid) or wxid

        speaker_counts: dict[str, int] = {}
        for msg in messages:
            sender = str(getattr(msg, "sender_wxid", "") or "").strip()
            if not sender:
                continue
            speaker_counts[sender] = speaker_counts.get(sender, 0) + 1

        top_speakers = sorted(speaker_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_speakers_html = "".join(
            self._build_speaker_item(rank=i + 1, name=_display_name(wxid), count=count)
            for i, (wxid, count) in enumerate(top_speakers)
        )

        chat_lines: list[str] = []
        for msg in messages:
            sender_wxid = str(getattr(msg, "sender_wxid", "") or "").strip()
            content = str(getattr(msg, "content", "") or "").strip()
            ts = getattr(msg, "timestamp", None)
            if not content:
                continue
            if isinstance(ts, datetime):
                hhmm = ts.strftime("%H:%M")
            else:
                hhmm = "--:--"
            content = re.sub(r"\s+", " ", content)
            chat_lines.append(f"[{hhmm}] {_display_name(sender_wxid)}: {content}")

        prompt_header = (
            f"群聊：{group_name}\n"
            f"统计窗口：过去 {hours} 小时（{start_time.strftime('%Y-%m-%d %H:%M')} ~ {now.strftime('%Y-%m-%d %H:%M')}）\n"
            f"消息条数：{len(chat_lines)}\n"
            "请基于下面的消息记录完成总结：\n"
        )
        user_prompt = prompt_header + "\n".join(chat_lines)

        summary_data = self._call_llm_summary(user_prompt)
        vibe = str(summary_data.get("vibe", "")).strip()
        quote = str(summary_data.get("quote", "")).strip()
        topics_raw = summary_data.get("topics", [])
        if not vibe:
            raise UserError("AI 返回的 vibe 为空。")
        if not isinstance(topics_raw, list) or not topics_raw:
            raise UserError("AI 返回的 topics 为空。")

        accents = ["--a-cyan", "--a-violet", "--a-lime", "--a-amber"]
        topics: list[Topic] = []
        for idx, item in enumerate(topics_raw[: max(1, self.max_topics)], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            process = str(item.get("process", "")).strip()
            rating = str(item.get("rating", "")).strip()
            time_range = str(item.get("time_range", "")).strip() or "--:--–--:--"
            participants_raw = item.get("participants", [])
            participants = (
                [str(p).strip() for p in participants_raw if str(p).strip()][:5]
                if isinstance(participants_raw, list)
                else []
            )

            heat = item.get("heat", 1)
            try:
                heat_int = int(heat)
            except Exception:
                heat_int = 1
            heat_int = max(1, min(heat_int, 5))

            if not title:
                title = f"话题 {idx}"
            if not process:
                process = "（过程缺失）"
            if not rating:
                rating = "（评价缺失）"

            topics.append(
                Topic(
                    index=idx,
                    title=title,
                    heat=heat_int,
                    time_range=time_range,
                    participants=participants,
                    process=process,
                    rating=rating,
                    accent=accents[(idx - 1) % len(accents)],
                )
            )

        if not topics:
            raise UserError("AI 返回的 topics 解析失败。")

        topics_html = "".join(self._build_topic_section(t) for t in topics)

        # ── 群聊速览面板数据 ──
        # 1) 问候语：根据当前小时判断
        hour = now.hour
        if 0 <= hour < 10:
            greeting = "早上好"
        elif 10 <= hour < 12:
            greeting = "中午好"
        elif 12 <= hour < 18:
            greeting = "下午好"
        else:
            greeting = "晚上好"

        # 2) 中文日期格式：2026年3月11日，星期三
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        cn_date = f"{now.year}年{now.month}月{now.day}日，{weekday_names[now.weekday()]}"

        # 3) 群成员总数 + 新增/离开人数
        member_count = 0
        joined_count = 0
        left_count = 0
        if is_group:
            try:
                if members:
                    member_count = len(members)
                    # 当前成员 wxid 集合
                    current_wxids = {self._extract_member_wxid(m) for m in members}
                    current_wxids.discard("")

                    # 从数据库获取之前记录的成员列表进行对比
                    try:
                        old_members = get_group_members_from_db(chat_wxid)
                        if old_members:
                            old_wxids = {
                                str(m.get("wxid", "")).strip()
                                for m in old_members
                            }
                            old_wxids.discard("")
                            # 新加入 = 当前有但旧记录没有
                            joined_count = len(current_wxids - old_wxids)
                            # 离开 = 旧记录有但当前没有
                            left_count = len(old_wxids - current_wxids)
                    except Exception:
                        pass
            except Exception:
                pass

        # 4) 发言人数和消息条数
        speaker_count = len(unique_senders)
        msg_count = len(chat_lines)

        # 5) 熬夜大王：凌晨 0:00-5:59 发消息最多的人
        night_owl_counts: dict[str, int] = {}
        for msg in messages:
            ts = getattr(msg, "timestamp", None)
            if isinstance(ts, datetime) and 0 <= ts.hour < 6:
                sender = str(getattr(msg, "sender_wxid", "") or "").strip()
                if sender:
                    night_owl_counts[sender] = night_owl_counts.get(sender, 0) + 1
        night_owl_name = ""
        if night_owl_counts:
            night_owl_wxid = max(night_owl_counts, key=night_owl_counts.get)
            night_owl_name = _display_name(night_owl_wxid)

        # 6) 组装 overview HTML
        overview_html = self._build_overview_html(
            greeting=greeting,
            cn_date=cn_date,
            member_count=member_count,
            joined_count=joined_count,
            left_count=left_count,
            speaker_count=speaker_count,
            msg_count=msg_count,
            night_owl_name=night_owl_name,
            quote=quote,
        )

        template_path = self._pick_template_path()
        logger.info("[JaysonChatSummary] 本次使用模板: {}", template_path.name)
        template = template_path.read_text(encoding="utf-8")
        footer_note = f"生成时间 {now.strftime('%H:%M')} · 仅总结，不代表观点"
        html = (
            template.replace("{{group_name}}", escape(group_name))
            .replace("{{report_date}}", cn_date)
            .replace("{{vibe_line}}", escape(vibe))
            .replace("{{top_speakers_html}}", top_speakers_html)
            .replace("{{topics_html}}", topics_html)
            .replace("{{overview_html}}", overview_html)
            .replace("{{footer_note}}", escape(footer_note))
        )

        return self._render_html_to_image(html)

    def _call_llm_summary(self, user_prompt: str) -> dict[str, Any]:
        max_retries = max(1, int(self.llm_max_retries or 3))
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                data = self._call_llm_summary_once(user_prompt)
                self._validate_llm_summary_data(data)
                return data
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                should_retry = attempt < max_retries and self._is_retryable_llm_error(exc)
                if not should_retry:
                    break
                delay = self._compute_llm_retry_delay_seconds(attempt=attempt, exc=exc)
                logger.warning(
                    "[JaysonChatSummary] AI 总结失败，准备重试 {}/{}（等待 {:.1f}s），原因：{}",
                    attempt,
                    max_retries,
                    delay,
                    exc,
                )
                time.sleep(delay)

        if isinstance(last_exc, httpx.HTTPError):
            raise self._format_service_error("调用 AI 总结服务", last_exc) from last_exc
        if isinstance(last_exc, json.JSONDecodeError):
            raise UserError("AI 返回内容不是合法 JSON，请稍后重试或切换模型/接口。") from last_exc
        if isinstance(last_exc, UserError):
            raise last_exc
        raise UserError("调用 AI 总结服务失败，请稍后重试。") from last_exc

    def _call_llm_summary_once(self, user_prompt: str) -> dict[str, Any]:
        prompt = SYSTEM_PROMPT.format(max_topics=max(1, self.max_topics))
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }
        endpoint = self._build_chat_completions_endpoint(self.api_base_url)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = httpx.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=self.request_timeout,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            content_type = str(exc.response.headers.get("content-type", "") or "")
            request_id = (
                exc.response.headers.get("x-request-id")
                or exc.response.headers.get("request-id")
                or exc.response.headers.get("x-trace-id")
                or ""
            )
            raw_body = str(exc.response.text or "")
            body_snip = raw_body.strip().replace("\r", " ").replace("\n", " ")
            if len(body_snip) > 800:
                body_snip = body_snip[:800] + "…"
            prompt_text = str(user_prompt or "")
            prompt_len = len(prompt_text)
            prompt_hash = hashlib.sha256(prompt_text.encode("utf-8", errors="ignore")).hexdigest()[:12]
            prompt_head = prompt_text.splitlines()[0].strip() if prompt_text.splitlines() else ""
            if len(prompt_head) > 120:
                prompt_head = prompt_head[:120] + "…"
            logger.warning(
                "[JaysonChatSummary] AI 接口 HTTP 异常 status={} content_type={} request_id={} prompt_len={} prompt_hash={} prompt_head={} body={}",
                status_code,
                content_type,
                str(request_id or ""),
                prompt_len,
                prompt_hash,
                prompt_head,
                body_snip,
            )
            raise

        content = self._extract_message_text_from_llm_response(response)
        return self._extract_json_object(content)

    def _extract_message_text_from_llm_response(self, response: httpx.Response) -> str:
        """从 LLM HTTP 响应中提取文本（兼容普通 JSON 与 text/event-stream/SSE）。"""
        content_type = str(response.headers.get("content-type", "") or "").lower()
        raw_text = str(response.text or "")

        if "text/event-stream" in content_type or raw_text.lstrip().startswith("data:"):
            sse_text = self._extract_text_from_sse(raw_text)
            if sse_text.strip():
                return sse_text

        data = response.json()
        message_content = self._extract_message_from_response(data)
        return self._get_text_content(message_content)

    def _extract_text_from_sse(self, raw_text: str) -> str:
        """从 SSE 输出中拼接文本（适配 OpenAI 兼容的 chunk 格式）。"""
        parts: list[str] = []
        for line in str(raw_text or "").splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                chunk = json.loads(payload)
            except Exception:
                continue
            if not isinstance(chunk, dict):
                continue
            choices = chunk.get("choices")
            if isinstance(choices, list) and choices:
                choice0 = choices[0] if isinstance(choices[0], dict) else {}
                delta = choice0.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    parts.append(delta["content"])
                    continue
                message = choice0.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    parts.append(message["content"])
                    continue
            if isinstance(chunk.get("text"), str):
                parts.append(chunk["text"])
        return "".join(parts)

    def _validate_llm_summary_data(self, data: dict[str, Any]) -> None:
        vibe = str(data.get("vibe", "")).strip()
        topics = data.get("topics")
        if not vibe:
            raise UserError("AI 返回的 vibe 为空。")
        if not isinstance(topics, list) or not topics:
            raise UserError("AI 返回的 topics 为空。")

    def _is_retryable_llm_error(self, exc: Exception) -> bool:
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.RequestError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        if isinstance(exc, (json.JSONDecodeError, UserError)):
            return True
        return True

    def _compute_llm_retry_delay_seconds(self, *, attempt: int, exc: Exception) -> float:
        base = max(0.2, float(self.llm_retry_base_delay_seconds or 1.0))
        # 指数退避 + 抖动：base, 2*base, 4*base...
        delay = min(12.0, base * (2 ** (max(1, int(attempt)) - 1)))
        # 429/503 等场景稍微多等一会儿
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {429, 503}:
            delay = min(20.0, delay + base)
        delay += random.random() * 0.3
        return max(0.2, delay)

    def _extract_message_from_response(self, data: dict[str, Any]) -> Any:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict) and "content" in message:
                    return message.get("content")
                if "text" in first_choice:
                    return first_choice.get("text")

        output = data.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content_list = item.get("content")
                if isinstance(content_list, list):
                    for content_item in content_list:
                        if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                            parts.append(content_item["text"])
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "\n".join(parts)

        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        if isinstance(data.get("text"), str):
            return data["text"]

        raise UserError("AI 返回结构异常，无法读取总结结果。")

    def _get_text_content(self, message_content: Any) -> str:
        if isinstance(message_content, str):
            return message_content
        if isinstance(message_content, list):
            parts: list[str] = []
            for item in message_content:
                if isinstance(item, dict):
                    if isinstance(item.get("text"), str):
                        parts.append(item["text"])
                    elif item.get("type") == "text" and isinstance(item.get("content"), str):
                        parts.append(item["content"])
            return "\n".join(parts)
        if isinstance(message_content, dict):
            if isinstance(message_content.get("text"), str):
                return message_content["text"]
            if isinstance(message_content.get("content"), str):
                return message_content["content"]
        raise UserError("AI 返回内容格式无法识别。")

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        text = str(text or "").strip()
        if text.startswith("{") and text.endswith("}"):
            return json.loads(text)
        matched = re.search(r"\{[\s\S]*\}", text)
        if not matched:
            raise UserError("AI 没有返回合法的 JSON 内容。")
        return json.loads(matched.group(0))

    @staticmethod
    def _build_chat_completions_endpoint(configured_url: str) -> str:
        url = str(configured_url or "").strip()
        if not url:
            return ""

        trimmed = url.rstrip("/")
        try:
            parsed = urlparse(trimmed)
        except Exception:
            parsed = None

        if parsed and parsed.path.rstrip("/").endswith("/chat/completions"):
            return trimmed
        return trimmed + "/chat/completions"

    def _format_service_error(self, service_name: str, exc: httpx.HTTPError) -> UserError:
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 404:
                hint = ""
                if "图片" in service_name:
                    hint = "请检查 html2image_url 是否为完整接口地址（例如 http://127.0.0.1:8000/api/html2image）。"
                elif "AI" in service_name:
                    hint = (
                        "请检查 minimax_base_url/openai_base_url 是否为 API 根地址"
                        "（例如 https://api.minimax.io/v1），"
                        "或直接填写完整的 /chat/completions 地址。"
                    )
                return UserError(f"{service_name}失败：接口不存在（状态码 404）。{hint}")
            return UserError(f"{service_name}失败：服务暂时异常（状态码 {status_code}）。")
        if isinstance(exc, httpx.TimeoutException):
            return UserError(f"{service_name}失败：请求超时，请稍后重试。")
        if isinstance(exc, httpx.RequestError):
            return UserError(f"{service_name}失败：网络连接异常，请稍后重试。")
        return UserError(f"{service_name}失败：请求异常，请稍后重试。")

    @staticmethod
    def _build_html2image_candidate_urls(configured_url: str) -> list[str]:
        """把用户配置的图片服务地址规范化，并在 404 时提供候选兜底地址。"""
        url = str(configured_url or "").strip()
        if not url:
            return []

        normalized: list[str] = []
        url_no_trailing_slash = url.rstrip("/")
        if url_no_trailing_slash:
            normalized.append(url_no_trailing_slash)
        normalized.append(url)

        try:
            parsed = urlparse(url)
        except Exception:
            parsed = None

        if parsed and parsed.scheme and parsed.netloc:
            base = f"{parsed.scheme}://{parsed.netloc}"
            path = (parsed.path or "").strip() or "/"

            if path in ("", "/"):
                # 用户只配了域名/端口：优先尝试常见 API 路径
                normalized.extend(
                    [
                        f"{base}/api/html2image",
                        f"{base}/html2image",
                        f"{base}/api/render",
                        f"{base}/render",
                    ]
                )
            else:
                # 用户配了具体路径：也给一个“回退到根路径”的机会
                normalized.append(f"{base}/")

        # 保序去重 + 去空
        seen: set[str] = set()
        candidates: list[str] = []
        for item in normalized:
            item = str(item or "").strip()
            if not item:
                continue
            if item in seen:
                continue
            seen.add(item)
            candidates.append(item)
        return candidates

    def _render_html_to_image(self, html: str) -> bytes:
        payload = {
            "html": html,
            "image_type": "png",
            "element_id": "card",
            "element_padding": 24,
            "device_scale_factor": 2,
            "viewport_width": 1080,
            "viewport_height": 1920,
            "render_wait_ms": 450,
        }
        candidate_urls = self._build_html2image_candidate_urls(self.html2image_url)
        last_exc: httpx.HTTPError | None = None
        for idx, url in enumerate(candidate_urls):
            try:
                response = httpx.post(
                    url,
                    json=payload,
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                if url != self.html2image_url:
                    logger.warning(
                        "[JaysonChatSummary] 图片服务地址自动切换: {} -> {}",
                        self.html2image_url,
                        url,
                    )
                    self.html2image_url = url
                break
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                # 仅在 404 时尝试下一个候选 URL（大概率是路径配错）
                if exc.response.status_code == 404 and idx + 1 < len(candidate_urls):
                    continue
                raise self._format_service_error("调用图片生成服务", exc) from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                raise self._format_service_error("调用图片生成服务", exc) from exc
        else:
            if last_exc is None:
                raise UserError("调用图片生成服务失败：没有可用的 html2image_url 配置。")
            raise self._format_service_error("调用图片生成服务", last_exc) from last_exc

        result = response.json()
        image_base64 = result.get("image_base64")
        if not image_base64:
            raise UserError("图片服务返回成功，但没有拿到 image_base64 字段。")

        return base64.b64decode(image_base64)

    def _build_speaker_item(self, *, rank: int, name: str, count: int) -> str:
        return (
            "<li class=\"speaker\">"
            "  <div class=\"speaker__left\">"
            f"    <div class=\"rank\">{rank}</div>"
            f"    <div class=\"name\">{escape(name)}</div>"
            "  </div>"
            f"  <div class=\"count\">{count} msgs</div>"
            "</li>"
        )

    def _build_topic_section(self, topic: Topic) -> str:
        heat_marks = "".join("<span class=\"flame\" aria-hidden=\"true\">🔥</span>" for _ in range(topic.heat))
        participants = " / ".join(escape(p) for p in topic.participants[:5])

        return (
            f"<section class=\"topic\" style=\"--topic-accent: var({topic.accent})\">"
            "  <div class=\"topic__left\">"
            f"    <div class=\"topic__index\">{topic.index}</div>"
            f"    <div class=\"topic__heat\" aria-label=\"热度\">{heat_marks}</div>"
            "  </div>"
            "  <div class=\"topic__body\">"
            f"    <div class=\"topic__title\">{escape(topic.title)}</div>"
            "    <div class=\"topic__meta\">"
            f"      <span class=\"pill\">Time {escape(topic.time_range)}</span>"
            f"      <span class=\"pill\">People {participants}</span>"
            "    </div>"
            f"    <div class=\"topic__process\">{escape(topic.process)}</div>"
            f"    <div class=\"topic__rating\">评价：{escape(topic.rating)}</div>"
            "  </div>"
            "</section>"
        )

    def _build_overview_html(
        self,
        *,
        greeting: str,
        cn_date: str,
        member_count: int,
        joined_count: int,
        left_count: int,
        speaker_count: int,
        msg_count: int,
        night_owl_name: str,
        quote: str,
    ) -> str:
        """生成"群聊速览"面板的 HTML 片段。"""
        # 问候语 + 日期
        parts = [
            f'<p class="overview-greeting">{escape(greeting)}，</p>',
            f'<p class="overview-date">{escape(cn_date)}</p>',
        ]

        # 群成员统计 + 新增/离开
        if member_count > 0:
            # 成员变动描述
            if joined_count > 0 and left_count > 0:
                change_text = f'{joined_count} 人加入，{left_count} 人离开，'
            elif joined_count > 0:
                change_text = f'{joined_count} 人加入，没有人离开，'
            elif left_count > 0:
                change_text = f'没有人加入，{left_count} 人离开，'
            else:
                change_text = '没有人加入，也没有人离开，'

            stats_line = (
                f'群内成员一共 <span class="highlight">{member_count}</span> 名，'
                f'{change_text}'
                f'共有 <span class="highlight">{speaker_count}</span> 人侃侃而谈 '
                f'<span class="highlight">{msg_count}</span> 句。'
            )
        else:
            stats_line = (
                f'共有 <span class="highlight">{speaker_count}</span> 人侃侃而谈 '
                f'<span class="highlight">{msg_count}</span> 句。'
            )
        parts.append(f'<p class="overview-stats">{stats_line}</p>')

        # 熬夜大王
        if night_owl_name:
            parts.append(
                f'<p class="overview-nightowl">🌙 熬夜大王：{escape(night_owl_name)}</p>'
            )

        # 每日名言
        if quote:
            parts.append(f'<p class="overview-quote">「{escape(quote)}」</p>')

        return "\n".join(parts)

    @schedule("cron", hour="*", minute="*", second="*")
    async def scheduled_summary(self, bot: WechatAPIClient):
        if not self.enable or not self.schedule_enable:
            return

        now = time.localtime()
        if now.tm_hour != self.schedule_hour or now.tm_min != self.schedule_minute or now.tm_sec != self.schedule_second:
            return

        fire_key = time.strftime("%Y%m%d-%H%M%S", now)
        if self._last_schedule_fire_key == fire_key:
            return
        self._last_schedule_fire_key = fire_key

        if self.schedule_random_delay_seconds > 0:
            delay_seconds = random.randint(0, self.schedule_random_delay_seconds)
            await asyncio.sleep(delay_seconds)

        groups = [g for g in self.target_groups if g.endswith("@chatroom")]
        if not groups:
            return

        success_count = 0
        failed_count = 0
        logger.info("[JaysonChatSummary] 定时任务开始，目标群数量: {}", len(groups))

        for group_wxid in groups:
            logger.info("[JaysonChatSummary] 开始处理群: {}", group_wxid)
            try:
                image_bytes = await self._build_summary_image(
                    bot=bot,
                    chat_wxid=group_wxid,
                    hours=max(1, int(self.schedule_summary_hours)),
                )
                await bot.send_image_message(group_wxid, image=image_bytes)
                success_count += 1
                logger.info("[JaysonChatSummary] 群 {} 定时发送成功", group_wxid)
            except UserError as exc:
                failed_count += 1
                logger.warning("[JaysonChatSummary] 群 {} 定时发送失败: {}", group_wxid, exc)
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                logger.exception("[JaysonChatSummary] 群 {} 定时发送异常: {}", group_wxid, exc)

        logger.info(
            "[JaysonChatSummary] 定时任务结束，成功 {} 个，失败 {} 个",
            success_count,
            failed_count,
        )
