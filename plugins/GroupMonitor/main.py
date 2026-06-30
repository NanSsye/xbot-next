from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from loguru import logger

from xbot.adapters.wechat869.client import Wechat869Client
from xbot.messaging.models import Message
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext


class GroupMonitorPlugin(PluginBase):
    name = "GroupMonitor"
    version = "1.2.0"

    def __init__(self) -> None:
        self.check_interval = 60
        self.monitor_groups: list[str] = []
        self.message_template = "群成员变动提醒：{member_name}（{member_id}） 已退出群聊"
        self.debug = False
        self.use_card = True
        self.card_title_template = "👋 {member_name} 已退出群聊"
        self.card_description_template = "⌚退出时间：{time}\n用户ID：{member_id}"
        self.card_url = "https://example.com"
        self.db_path = Path("plugins/GroupMonitor/group_monitor.db")
        self._client: Wechat869Client | None = None
        self._task: asyncio.Task | None = None
        self.is_first_run = True

    async def on_load(self, ctx: PluginContext) -> None:
        raw_cfg = ctx.config or {}
        cfg = raw_cfg.get("Config", raw_cfg) if isinstance(raw_cfg.get("Config"), dict) else raw_cfg
        self.check_interval = max(3, int(cfg.get("check_interval", self.check_interval)))
        self.monitor_groups = [str(x).strip() for x in (cfg.get("monitor_groups") or []) if str(x).strip()]
        self.message_template = str(cfg.get("message_template") or self.message_template)
        self.debug = bool(cfg.get("debug", False))
        card = cfg.get("Card") if isinstance(cfg.get("Card"), dict) else cfg.get("card", {})
        self.use_card = bool(card.get("enable", self.use_card)) if isinstance(card, dict) else self.use_card
        self.card_title_template = str(card.get("title_template") or self.card_title_template) if isinstance(card, dict) else self.card_title_template
        self.card_description_template = str(card.get("description_template") or self.card_description_template) if isinstance(card, dict) else self.card_description_template
        self.card_url = str(card.get("url") or self.card_url) if isinstance(card, dict) else self.card_url
        db_cfg = cfg.get("Database") if isinstance(cfg.get("Database"), dict) else cfg.get("database", {})
        db_file = str(db_cfg.get("path") or "group_monitor.db") if isinstance(db_cfg, dict) else "group_monitor.db"
        self.db_path = Path(ctx.data_dir) / db_file
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = self._create_client(ctx)
        self._init_db()
        self.is_first_run = self._count_members() == 0
        self._task = asyncio.create_task(self._monitor_loop(), name="group-monitor-loop")
        logger.info("<cyan>GroupMonitor</cyan> 已加载: groups={} interval={}s first_run={}", len(self.monitor_groups), self.check_interval, self.is_first_run)

    async def on_unload(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def on_message(self, message: Message, ctx: PluginContext) -> bool:
        return False

    def _create_client(self, ctx: PluginContext) -> Wechat869Client:
        wechat = getattr(getattr(ctx.settings, "adapters", None), "wechat869", None) if ctx.settings else None
        return Wechat869Client(
            host=str(getattr(wechat, "host", "127.0.0.1")),
            port=int(getattr(wechat, "port", 5253)),
            admin_key=str(getattr(wechat, "admin_key", "")),
            token_key=str(getattr(wechat, "token_key", "")),
            ws_url=str(getattr(wechat, "ws_url", "")),
        )

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS group_members ("
                "group_id TEXT, member_id TEXT, member_name TEXT, avatar_url TEXT, last_seen TEXT, "
                "PRIMARY KEY (group_id, member_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS group_snapshots ("
                "group_id TEXT PRIMARY KEY, member_count INTEGER NOT NULL, last_seen TEXT)"
            )
            conn.execute("DELETE FROM group_members WHERE member_id LIKE '%@chatroom'")
            conn.commit()

    def _count_members(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM group_members WHERE member_id NOT LIKE '%@chatroom'").fetchone()[0])

    async def _monitor_loop(self) -> None:
        while True:
            try:
                await self._run_once()
                if self.is_first_run:
                    self.is_first_run = False
                    logger.info("<cyan>GroupMonitor</cyan> 首次运行完成")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("<red>GroupMonitor</red> 循环异常: {}", exc)
            await asyncio.sleep(self.check_interval)

    async def _run_once(self) -> None:
        if not self.monitor_groups:
            if self.debug:
                logger.info("<yellow>GroupMonitor</yellow> 未配置 monitor_groups")
            return
        client = self._client
        if not client:
            return
        for group_id in self.monitor_groups:
            try:
                members = await self._fetch_members(client, group_id)
                if not members:
                    logger.warning("<yellow>GroupMonitor</yellow> 获取群成员为空: {}", group_id)
                    continue
                left = await self._update_members(client, group_id, members)
                if self.debug and left:
                    logger.debug("<cyan>GroupMonitor</cyan> 更新完成: group={} members={} left={}", group_id, len(members), len(left))
            except Exception as exc:
                logger.error("<red>GroupMonitor</red> 更新群失败: group={} error={}", group_id, exc)
            await asyncio.sleep(1)

    async def _fetch_members(self, client: Wechat869Client, group_id: str) -> list[dict[str, Any]]:
        members = await client.get_chatroom_member_list(group_id)
        if self.debug:
            logger.debug(
                "<cyan>GroupMonitor</cyan> 实时获取群成员: group={} members={} sample={}",
                group_id,
                len(members),
                [self._member_id(x) for x in members[:5]],
            )
        return members

    def _payload_keys(self, payload: Any) -> str:
        if isinstance(payload, dict):
            return ",".join(str(k) for k in list(payload.keys())[:20])
        if isinstance(payload, list):
            return f"list[{len(payload)}]"
        return type(payload).__name__

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
        direct_candidates = [
            payload.get("ChatRoomMember"),
            payload.get("MemberList"),
            payload.get("memberList"),
            payload.get("member_list"),
            payload.get("chatroom_member_list"),
            payload.get("ChatRoomMemberList"),
        ]
        for candidate in direct_candidates:
            if isinstance(candidate, list) and candidate:
                return [item for item in candidate if isinstance(item, dict) and self._member_id(item)]
        for nested_key in ("NewChatroomData", "newChatroomData", "member_data", "Data", "data"):
            members = self._extract_members(payload.get(nested_key))
            if members:
                return members
        for list_key in ("ChatRoomInfo", "chatroomInfo", "ContactList", "contactList"):
            container = payload.get(list_key)
            if isinstance(container, list):
                for item in container:
                    members = self._extract_members(item)
                    if members:
                        return members
        return []

    def _member_id(self, member: dict[str, Any]) -> str:
        for key in (
            "UserName", "UserNameStr", "UserId", "UserID", "userId", "user_id",
            "Wxid", "WxId", "wxid", "userName", "username",
            "member_wxid", "MemberWxid", "MemberId", "MemberID", "memberId", "member_id",
            "ChatUser", "FromUserName",
        ):
            value = self._scalar(member.get(key))
            if value:
                wxid = str(value).strip()
                if wxid.endswith("@chatroom"):
                    continue
                return wxid
        return ""

    def _member_name(self, member: dict[str, Any], member_id: str) -> str:
        for key in ("NickName", "NickNameStr", "nickname", "nickName", "DisplayName", "DisplayNameStr", "display_name", "Remark", "RemarkName", "remark", "MemberName", "name"):
            value = self._scalar(member.get(key))
            if value:
                return str(value).strip()
        return member_id or "未知用户"

    def _avatar_url(self, member: dict[str, Any]) -> str:
        for key in ("BigHeadImgUrl", "bigHeadImgUrl", "SmallHeadImgUrl", "smallHeadImgUrl", "HeadImgUrl", "headImgUrl", "avatar"):
            value = self._scalar(member.get(key))
            if value:
                return str(value).strip()
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

    async def _update_members(self, client: Wechat869Client, group_id: str, members: list[dict[str, Any]]) -> list[tuple[str, str]]:
        now_iso = datetime.now().isoformat()
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            snapshot_row = conn.execute(
                "SELECT member_count FROM group_snapshots WHERE group_id=?",
                (group_id,),
            ).fetchone()
            old_snapshot_count = int(snapshot_row[0]) if snapshot_row else 0
            raw_count = len(members)
            old_rows = conn.execute("SELECT member_id, member_name, avatar_url FROM group_members WHERE group_id=?", (group_id,)).fetchall()
            old = {r[0]: {"name": r[1], "avatar": r[2] or ""} for r in old_rows if r[0] and not str(r[0]).endswith("@chatroom")}
            old_count = len(old)
            new_ids: set[str] = set()
            parsed_members = 0
            for member in members:
                member_id = self._member_id(member)
                if not member_id:
                    continue
                parsed_members += 1
                new_ids.add(member_id)
                member_name = self._member_name(member, member_id)
                avatar = self._avatar_url(member)
                conn.execute(
                    "INSERT OR REPLACE INTO group_members (group_id, member_id, member_name, avatar_url, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (group_id, member_id, member_name, avatar, now_iso),
                )
            if self.is_first_run and not old and not snapshot_row:
                conn.execute(
                    "INSERT OR REPLACE INTO group_snapshots (group_id, member_count, last_seen) VALUES (?, ?, ?)",
                    (group_id, raw_count, now_iso),
                )
                conn.commit()
                return []
            left_ids = set(old) - new_ids
            left = [(mid, old[mid]["name"]) for mid in left_ids]
            if self.debug and left:
                logger.debug(
                    "<cyan>GroupMonitor</cyan> 成员差异: group={} old={} new={} parsed={} left={} sample_old={} sample_new={}",
                    group_id,
                    old_count,
                    len(new_ids),
                    parsed_members,
                    len(left),
                    list(old.keys())[:5],
                    list(new_ids)[:5],
                )
                if parsed_members == 0 and members:
                    logger.debug("<cyan>GroupMonitor</cyan> 成员字段样本: {}", [list(x.keys())[:12] for x in members[:3] if isinstance(x, dict)])
            for member_id, member_name in left:
                await self._send_left_notice(client, group_id, member_id, member_name, old[member_id].get("avatar", ""), now_text)
                conn.execute("DELETE FROM group_members WHERE group_id=? AND member_id=?", (group_id, member_id))
            conn.execute(
                "INSERT OR REPLACE INTO group_snapshots (group_id, member_count, last_seen) VALUES (?, ?, ?)",
                (group_id, raw_count, now_iso),
            )
            conn.commit()
            return left

    async def _send_left_notice(self, client: Wechat869Client, group_id: str, member_id: str, member_name: str, avatar_url: str, now: str) -> None:
        if self.use_card:
            title = self.card_title_template.format(member_name=member_name, member_id=member_id, time=now)
            desc = self.card_description_template.format(member_name=member_name, member_id=member_id, time=now)
            xml = (
                "<appmsg>"
                f"<title>{escape(title)}</title>"
                f"<des>{escape(desc)}</des>"
                "<type>5</type>"
                f"<url>{escape(self.card_url)}</url>"
                f"<thumburl>{escape(avatar_url or '')}</thumburl>"
                "</appmsg>"
            )
            await client.send_app_message(group_id, xml, 5)
        else:
            text = self.message_template.format(member_name=member_name, member_id=member_id, time=now)
            await client.send_text_message(group_id, text)
        logger.info("<yellow><bold>GroupMonitor</bold></yellow> 已发送退群提醒: group={} member={}({})", group_id, member_name, member_id)
