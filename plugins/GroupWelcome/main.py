from __future__ import annotations

import asyncio
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from loguru import logger

from xbot.adapters.wechat869.client import Wechat869Client
from xbot.messaging.models import Message
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext


class GroupWelcome(PluginBase):
    name = "GroupWelcome"
    version = "1.4.0"

    def __init__(self) -> None:
        self.enable = True
        self.welcome_message = "欢迎进群。"
        self.url = "https://ai.lyvu.cn/"
        self.send_file = False
        self.pdf_path = Path("plugins/GroupWelcome/temp/allbot项目说明.pdf")
        self._client: Wechat869Client | None = None

    async def on_load(self, ctx: PluginContext) -> None:
        cfg = ctx.config or {}
        self.enable = bool(cfg.get("enable", True))
        self.welcome_message = str(cfg.get("welcome-message") or cfg.get("welcome_message") or self.welcome_message)
        self.url = str(cfg.get("url") or self.url)
        self.send_file = bool(cfg.get("send-file", cfg.get("send_file", False)))
        self.pdf_path = Path("plugins/GroupWelcome/temp/allbot项目说明.pdf")
        self._client = self._create_client(ctx)
        logger.info("<green>GroupWelcome</green> 已加载: enable={} send_file={}", self.enable, self.send_file)

    async def on_message(self, message: Message, ctx: PluginContext) -> bool:
        if not self.enable or message.platform != "wechat" or message.adapter != "wechat869":
            return False
        raw = message.raw if isinstance(message.raw, dict) else {}
        if raw.get("scope") != "group" and not str(message.conversation_id).endswith("@chatroom"):
            return False
        content = str(raw.get("raw_content") or raw.get("Content") or raw.get("content") or message.content or "").strip()
        if "<sysmsg" not in content and "sysmsgtemplate" not in content:
            return False
        group_wxid = str(raw.get("group_wxid") or raw.get("conversation_wxid") or message.conversation_id or "")
        members = self._parse_join_members(content)
        if not group_wxid or not members:
            return False
        client = self._client or self._create_client(ctx)
        self._client = client
        for member in members:
            await self._send_welcome(client, group_wxid, member)
        return False

    def _create_client(self, ctx: PluginContext) -> Wechat869Client:
        wechat = getattr(getattr(ctx.settings, "adapters", None), "wechat869", None) if ctx.settings else None
        client = Wechat869Client(
            host=str(getattr(wechat, "host", "127.0.0.1")),
            port=int(getattr(wechat, "port", 5253)),
            admin_key=str(getattr(wechat, "admin_key", "")),
            token_key=str(getattr(wechat, "token_key", "")),
            ws_url=str(getattr(wechat, "ws_url", "")),
        )
        client.wxid = str(getattr(wechat, "bot_wxid", "") or "")
        return client

    def _parse_join_members(self, xml_content: str) -> list[dict[str, str]]:
        xml_content = self._extract_xml(xml_content)
        try:
            root = ET.fromstring(xml_content.strip())
        except Exception as exc:
            logger.debug("<yellow>GroupWelcome</yellow> 解析 XML 失败: {}", exc)
            return []
        if root.tag != "sysmsg" or root.attrib.get("type") != "sysmsgtemplate":
            return []
        template = root.find(".//content_template/template")
        template_text = template.text if template is not None else ""
        link_name = "names"
        if '"$adder$"通过' in template_text:
            link_name = "adder"
        known = (
            '"$names$"加入了群聊',
            '"$username$"邀请"$names$"加入了群聊',
            '你邀请"$names$"加入了群聊',
            '"$adder$"通过扫描"$from$"分享的二维码加入群聊',
            '"$adder$"通过"$from$"的邀请二维码加入群聊',
        )
        if template_text and not any(item in template_text for item in known):
            logger.debug("<yellow>GroupWelcome</yellow> 未匹配入群模板: {}", template_text)
            return []
        result = []
        for member in root.findall(f".//link[@name='{link_name}']/memberlist/member"):
            wxid = (member.findtext("username") or "").strip()
            nickname = (member.findtext("nickname") or wxid).strip()
            if wxid:
                result.append({"wxid": wxid, "nickname": nickname})
        return result

    def _extract_xml(self, content: str) -> str:
        text = str(content or "").strip()
        idx = text.find("<sysmsg")
        if idx >= 0:
            return text[idx:]
        idx = text.find("<?xml")
        if idx >= 0:
            return text[idx:]
        if ":\n" in text:
            return text.split(":\n", 1)[1].strip()
        return text

    async def _send_welcome(self, client: Wechat869Client, group_wxid: str, member: dict[str, str]) -> None:
        wxid = member.get("wxid") or ""
        nickname = member.get("nickname") or member.get("wxid") or "新成员"
        avatar_url = await self._find_member_avatar(client, group_wxid, wxid)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = f"👏欢迎 {nickname} 加入群聊！🎉"
        description = f"{self.welcome_message}\n⌚时间：{now}"
        xml = (
            "<appmsg>"
            f"<title>{escape(title)}</title>"
            f"<des>{escape(description)}</des>"
            "<type>5</type>"
            f"<url>{escape(self.url)}</url>"
            f"<thumburl>{escape(avatar_url)}</thumburl>"
            "</appmsg>"
        )
        await client.send_app_message(group_wxid, xml, 5)
        logger.info("<green><bold>GroupWelcome</bold></green> 已发送欢迎卡片: group={} member={}", group_wxid, nickname)
        if self.send_file and self.pdf_path.exists():
            await client.send_file_message(group_wxid, str(self.pdf_path))

    async def _find_member_avatar(self, client: Wechat869Client, group_wxid: str, wxid: str) -> str:
        if not wxid:
            return ""
        # 入群 sysmsg 通常早于 869 群成员详情刷新；延迟重试，避免欢迎卡片头像为空。
        for attempt, delay in enumerate((0.0, 1.0, 2.0, 3.0), start=1):
            if delay:
                await asyncio.sleep(delay)
            members = await self._fetch_members(client, group_wxid)
            for item in members:
                if self._member_id(item) != wxid:
                    continue
                avatar = self._avatar_url(item)
                if avatar:
                    logger.info("<green>GroupWelcome</green> 获取头像成功: group={} member={} attempt={}", group_wxid, wxid, attempt)
                    return avatar
                logger.debug("<yellow>GroupWelcome</yellow> 找到新成员但头像为空: group={} member={} attempt={} keys={}", group_wxid, wxid, attempt, list(item.keys())[:20])
            logger.debug("<yellow>GroupWelcome</yellow> 未在群成员列表找到新成员: group={} member={} attempt={} members={}", group_wxid, wxid, attempt, len(members))
        return ""

    async def _fetch_members(self, client: Wechat869Client, group_wxid: str) -> list[dict[str, Any]]:
        try:
            return await client.get_chatroom_member_list(group_wxid)
        except Exception as exc:
            logger.debug("<yellow>GroupWelcome</yellow> 获取群成员头像失败: group={} error={}", group_wxid, exc)
            return []

    def _extract_members(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            direct = [item for item in payload if isinstance(item, dict) and self._member_id(item)]
            if direct:
                return direct
            for item in payload:
                members = self._extract_members(item)
                if members:
                    return members
        if not isinstance(payload, dict):
            return []
        for key in ("ChatRoomMember", "MemberList", "memberList", "member_list", "chatroom_member_list", "ChatRoomMemberList"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict) and self._member_id(x)]
        for key in ("NewChatroomData", "newChatroomData", "member_data", "Data", "data"):
            members = self._extract_members(payload.get(key))
            if members:
                return members
        for key in ("ChatRoomInfo", "chatroomInfo", "ContactList", "contactList"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    members = self._extract_members(item)
                    if members:
                        return members
        return []

    def _member_id(self, member: dict[str, Any]) -> str:
        for key in ("UserName", "UserNameStr", "Wxid", "WxId", "wxid", "userName", "username", "member_wxid", "MemberWxid", "MemberId"):
            value = self._scalar(member.get(key))
            if value:
                if value.endswith("@chatroom"):
                    continue
                return value
        return ""

    def _avatar_url(self, member: dict[str, Any]) -> str:
        for key in ("BigHeadImgUrl", "bigHeadImgUrl", "SmallHeadImgUrl", "smallHeadImgUrl", "HeadImgUrl", "headImgUrl", "avatar"):
            value = self._scalar(member.get(key))
            if value:
                return value
        return ""

    def _scalar(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            for key in ("str", "string", "value", "Value", "String", "Str", "text"):
                nested = self._scalar(value.get(key))
                if nested:
                    return nested
            return ""
        return str(value).strip()
