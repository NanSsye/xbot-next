from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import io
import json
import math
import re
import sqlite3
import time
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiohttp
from loguru import logger
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import select

from xbot.adapters.wechat869.client import Wechat869Client
from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext
from xbot.storage.models import ContactRecord, ConversationMemberRecord, ConversationMessageRecord

try:
    import networkx as nx
except ImportError:  # 插件可立即热加载，重建镜像后自动使用 NetworkX。
    nx = None


@dataclass(slots=True)
class MessageRow:
    msg_id: str
    sender: str
    msg_type: int
    content: str
    timestamp: datetime


@dataclass(slots=True)
class Interaction:
    key: str
    source: str
    target: str
    kind: str
    weight: float
    timestamp: datetime


@dataclass(slots=True)
class RelationEdge:
    left: str
    right: str
    score: float
    direct_weight: float
    interaction_count: int
    active_days: int
    reciprocity: float


class SocialGraphError(Exception):
    pass


class GroupSocialGraph(PluginBase):
    name = "GroupSocialGraph"
    description = "根据群聊直接互动生成群友社交关系图"
    author = "Codex"
    version = "1.0.0"

    def __init__(self):
        self.plugin_dir = Path(__file__).resolve().parent
        with (self.plugin_dir / "config.toml").open("rb") as file:
            self.config = tomllib.load(file)

        basic = self.config.get("GroupSocialGraph", {})
        self.enable = bool(basic.get("enable", True))
        self.priority = int(basic.get("priority", 0))
        self.command = str(basic.get("command", "社交关系图") or "社交关系图").strip()
        self.commands = [self.command]
        self.trigger_words = [self.command]
        self.history_days = max(1, int(basic.get("history_days", 30)))
        self.max_nodes = max(8, min(100, int(basic.get("max_nodes", 50))))
        self.max_source_messages = max(500, int(basic.get("max_source_messages", 15000)))
        self.min_active_messages = max(1, int(basic.get("min_active_messages", 2)))
        self.min_edge_score = max(0.05, float(basic.get("min_edge_score", 1.15)))
        self.max_edges = max(10, int(basic.get("max_edges", 100)))
        self.edge_density = max(1.0, min(4.0, float(basic.get("edge_density", 1.5))))
        self.max_connections_per_node = max(
            2, min(12, int(basic.get("max_connections_per_node", 5)))
        )
        self.half_life_days = max(1.0, float(basic.get("half_life_days", 14)))
        self.admins = self._normalize_set(basic.get("admins", []))
        self.allowed_groups = self._normalize_set(basic.get("allowed_groups", ["*"])) or {"*"}
        self.send_progress = bool(basic.get("send_progress", True))
        self.event_database_path = self._resolve_path(
            str(
                basic.get(
                    "event_database_path",
                    "plugins/GroupSocialGraph/data/social_graph_events.db",
                )
                or ""
            )
        )
        self.font_path = self._resolve_path(
            str(basic.get("font_path", "plugins/GroupSocialGraph/fonts/NotoSansCJK-Regular.otf") or "")
        )

        cache = basic.get("Cache", {})
        self.cache_enable = bool(cache.get("enable", True))
        self.cache_dir = self._resolve_path(
            str(cache.get("path", "plugins/GroupSocialGraph/cache") or "")
        )
        self.cache_ttl_hours = max(1, int(cache.get("ttl_hours", 6)))

        self._running: set[str] = set()
        self._font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
        self._ctx: PluginContext | None = None
        self._client: Wechat869Client | None = None
        self._init_event_database()
        logger.info(
            "[GroupSocialGraph] 初始化完成: event_db={} networkx={}",
            self.event_database_path,
            bool(nx),
        )

    @staticmethod
    def _normalize_set(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value.strip()} if value.strip() else set()
        if isinstance(value, list):
            return {str(item).strip() for item in value if str(item).strip()}
        return set()

    @staticmethod
    def _resolve_path(value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else Path.cwd() / path

    def _init_event_database(self) -> None:
        self.event_database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.event_database_path), timeout=10)
        try:
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS relation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_wxid TEXT NOT NULL,
                    msg_key TEXT NOT NULL,
                    source_wxid TEXT NOT NULL,
                    target_wxid TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    base_weight REAL NOT NULL,
                    occurred_at TEXT NOT NULL,
                    UNIQUE(group_wxid, msg_key, source_wxid, target_wxid, event_type)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_relation_events_group_time "
                "ON relation_events(group_wxid, occurred_at)"
            )
            connection.commit()
        finally:
            connection.close()

    async def on_load(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._client = self._create_client(ctx)

    async def on_unload(self) -> None:
        self._ctx = None
        self._client = None

    async def on_message(self, message: Message, ctx: PluginContext) -> bool:
        if not self.enable or message.platform != "wechat" or message.adapter != "wechat869":
            return False
        raw = message.raw if isinstance(message.raw, dict) else {}
        group_wxid = str(raw.get("group_wxid") or raw.get("conversation_wxid") or message.conversation_id or "").strip()
        if not group_wxid.endswith("@chatroom"):
            return False
        conversation_id = await self._resolve_conversation_id(ctx, message.conversation_id, group_wxid)
        await self._collect_events(message, raw, group_wxid, conversation_id, ctx)
        content = str(message.content or raw.get("content") or "").strip()
        if not self._matches_command(content):
            return False
        logger.info(
            "[GroupSocialGraph] 命令命中: group={} sender={} message_id={}",
            group_wxid,
            message.sender_id,
            message.id,
        )
        sender_wxid = str(message.sender_id or raw.get("sender_wxid") or "").strip()
        if not self._is_admin(sender_wxid):
            await self._send_text(group_wxid, "社交关系图仅限管理员生成")
            return True
        if not self._is_group_allowed(group_wxid):
            return False
        if group_wxid in self._running:
            logger.info("[GroupSocialGraph] 命中运行锁: group={}", group_wxid)
            await self._send_text(group_wxid, "本群社交关系图正在生成，请稍候")
            return True

        cached = await asyncio.to_thread(self._read_cache, group_wxid)
        if cached:
            logger.info("[GroupSocialGraph] 命中缓存: group={} bytes={}", group_wxid, len(cached))
            await asyncio.wait_for(self._send_image(group_wxid, cached), timeout=30)
            return True
        logger.info("[GroupSocialGraph] 未命中缓存: group={}", group_wxid)

        self._running.add(group_wxid)
        try:
            if self.send_progress:
                logger.info("[GroupSocialGraph] 发送生成进度: group={}", group_wxid)
                await asyncio.wait_for(
                    self._send_text(group_wxid, "正在分析群友互动并绘制社交关系图，请稍候..."),
                    timeout=15,
                )
            image = await self._build_graph_image(ctx, conversation_id, group_wxid)
            await asyncio.to_thread(self._write_cache, group_wxid, image)
            await self._send_image(group_wxid, image)
        except SocialGraphError as error:
            await self._send_text(group_wxid, f"社交关系图生成失败：{error}")
        except Exception as error:
            logger.exception("[GroupSocialGraph] 生成异常: {}", error)
            await self._send_text(group_wxid, "社交关系图生成失败：发生未预期错误，请查看日志")
        finally:
            self._running.discard(group_wxid)
        return True

    def _matches_command(self, content: str) -> bool:
        index = content.find(self.command)
        if index < 0:
            return False
        prefix = content[:index].strip()
        suffix = content[index + len(self.command) :].strip()
        return (not prefix or prefix.startswith("@")) and not suffix

    def _is_admin(self, sender_wxid: str) -> bool:
        return bool(sender_wxid and ("*" in self.admins or sender_wxid in self.admins))

    def _is_group_allowed(self, group_wxid: str) -> bool:
        return "*" in self.allowed_groups or group_wxid in self.allowed_groups

    async def _collect_events(
        self, message: Message, raw: dict[str, Any], group_wxid: str,
        conversation_id: str, ctx: PluginContext
    ) -> None:
        source = str(message.sender_id or raw.get("sender_wxid") or "").strip()
        if not source:
            return
        raw_ats = raw.get("at_user_list") or raw.get("Ats") or []
        if isinstance(raw_ats, str):
            targets = [item.strip() for item in raw_ats.strip(",").split(",") if item.strip()]
        elif isinstance(raw_ats, list):
            targets = [str(item).strip() for item in raw_ats if str(item).strip()]
        else:
            targets = []
        bot_wxid = str(raw.get("bot_wxid") or getattr(self._client, "wxid", "") or "").strip()
        msg_key = str(message.id)
        timestamp = message.timestamp
        tasks = []
        for target in dict.fromkeys(targets):
            if target in {source, bot_wxid, "notify@all", "@all"}:
                continue
            tasks.append(
                asyncio.to_thread(
                    self._store_event,
                    group_wxid,
                    msg_key,
                    source,
                    target,
                    "at",
                    5.0,
                    timestamp,
                )
            )
        if tasks:
            await asyncio.gather(*tasks)
        patter = str(raw.get("Patter") or raw.get("patter") or "").strip()
        patted = str(raw.get("Patted") or raw.get("patted") or "").strip()
        if patter and patted and patter != patted:
            await asyncio.to_thread(
                self._store_event, group_wxid, msg_key, patter, patted, "pat", 4.0, timestamp
            )
        quote = raw.get("quote") if isinstance(raw.get("quote"), dict) else {}
        target = str(quote.get("sender_id") or quote.get("sender_wxid") or "").strip()
        if not target:
            target = self._extract_quote_target(self._message_xml(raw), source)
        if not target:
            nickname = str(quote.get("sender_name") or quote.get("nickname") or "").strip()
            if nickname:
                members = await self._load_members(ctx, conversation_id)
                matches = [wxid for wxid, info in members.items() if info["name"] == nickname]
                target = matches[0] if len(matches) == 1 else ""
        if target and target != source:
            await asyncio.to_thread(
                self._store_event,
                group_wxid,
                msg_key,
                source,
                target,
                "quote",
                6.0,
                timestamp,
            )

    @staticmethod
    def _message_key(message: dict) -> str:
        for key in ("MsgId", "MsgID", "NewMsgId", "NewMsgID"):
            value = str(message.get(key, "") or "").strip()
            if value:
                return value
        raw = "\n".join(
            str(message.get(key, "") or "")
            for key in ("FromWxid", "SenderWxid", "Content", "CreateTime")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _message_timestamp(message: dict) -> datetime:
        for key in ("CreateTime", "Timestamp", "timestamp"):
            value = message.get(key)
            if value in (None, ""):
                continue
            try:
                number = float(value)
                if number > 10_000_000_000:
                    number /= 1000
                return datetime.fromtimestamp(number)
            except (TypeError, ValueError, OSError):
                try:
                    return datetime.fromisoformat(str(value))
                except ValueError:
                    pass
        return datetime.now()

    @staticmethod
    def _message_xml(message: dict) -> str:
        parts = []
        for key in ("Content", "Xml", "XML", "RawContent", "QuoteContent", "ReferContent"):
            value = message.get(key)
            if isinstance(value, str) and "<" in value:
                parts.append(value)
        return "\n".join(dict.fromkeys(parts))

    def _store_event(
        self,
        group_wxid: str,
        msg_key: str,
        source: str,
        target: str,
        kind: str,
        weight: float,
        timestamp: datetime,
    ) -> None:
        connection = sqlite3.connect(str(self.event_database_path), timeout=10)
        try:
            connection.execute(
                """
                INSERT OR IGNORE INTO relation_events
                    (group_wxid, msg_key, source_wxid, target_wxid,
                     event_type, base_weight, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_wxid,
                    msg_key,
                    source,
                    target,
                    kind,
                    weight,
                    timestamp.isoformat(sep=" "),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    async def _build_graph_image(
        self, ctx: PluginContext, conversation_id: str, group_wxid: str
    ) -> bytes:
        messages, members = await asyncio.gather(
            self._query_messages(ctx, conversation_id),
            self._load_members(ctx, conversation_id),
        )
        logger.info(
            "[GroupSocialGraph] 数据读取完成: group={} messages={} members={}",
            group_wxid,
            len(messages),
            len(members),
        )
        if not messages:
            raise SocialGraphError(f"最近 {self.history_days} 天没有可统计的群聊记录")

        interactions = await asyncio.to_thread(self._build_interactions, group_wxid, messages)
        edges, message_counts = await asyncio.to_thread(
            self._score_relations, interactions, messages
        )
        if not edges:
            raise SocialGraphError("有效直接互动不足，暂时无法形成关系图")

        selected_edges, node_ids = self._select_graph(edges, message_counts)
        for wxid in node_ids:
            members.setdefault(
                wxid,
                {"name": f"群友 {wxid[-6:]}", "avatar": ""},
            )
        avatars = await self._download_avatars({wxid: members[wxid] for wxid in node_ids})
        return await asyncio.to_thread(
            self._render_graph,
            group_wxid,
            selected_edges,
            node_ids,
            members,
            avatars,
            message_counts,
            len(messages),
        )

    async def _resolve_conversation_id(
        self, ctx: PluginContext, conversation_id: str, group_wxid: str
    ) -> str:
        if conversation_id.startswith("wechat:"):
            return conversation_id
        return f"wechat:wechat869:group:{group_wxid}"

    async def _query_messages(
        self, ctx: PluginContext, conversation_id: str
    ) -> list[MessageRow]:
        if not ctx.conversations or not getattr(ctx.conversations, "repository_provider", None):
            raise SocialGraphError("会话存储不可用")
        cutoff = datetime.now() - timedelta(days=self.history_days)
        async with ctx.conversations.repository_provider() as repo:
            rows = list((await repo.session.execute(
                select(ConversationMessageRecord)
                .where(
                    ConversationMessageRecord.conversation_id == conversation_id,
                    ConversationMessageRecord.created_at >= cutoff,
                )
                .order_by(ConversationMessageRecord.created_at.desc())
                .limit(self.max_source_messages)
            )).scalars().all())

        result = []
        seen = set()
        for row in rows:
            sender = str(row.sender_id or "").strip()
            if not sender or sender.endswith("@chatroom"):
                continue
            key = str(row.message_id or "") or f"{sender}:{row.created_at}:{row.content}"
            if key in seen:
                continue
            seen.add(key)
            try:
                raw = json.loads(row.raw_json or "{}")
            except (TypeError, ValueError):
                raw = {}
            msg_type = int(raw.get("MsgType") or raw.get("msg_type") or (1 if row.type == "text" else 0))
            result.append(
                MessageRow(
                    msg_id=key,
                    sender=sender,
                    msg_type=msg_type,
                    content=str(raw.get("raw_content") or row.content or ""),
                    timestamp=self._parse_datetime(row.created_at),
                )
            )
        result.reverse()
        return result

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return datetime.now()

    def _build_interactions(
        self, group_wxid: str, messages: list[MessageRow]
    ) -> list[Interaction]:
        interactions: dict[str, Interaction] = {}
        previous: MessageRow | None = None
        for message in messages:
            if message.msg_type == 49 and "<refermsg" in message.content:
                target = self._extract_quote_target(message.content, message.sender)
                if target:
                    interaction = Interaction(
                        key=f"{message.msg_id}:quote:{message.sender}:{target}",
                        source=message.sender,
                        target=target,
                        kind="quote",
                        weight=6.0,
                        timestamp=message.timestamp,
                    )
                    interactions[interaction.key] = interaction

            if self._eligible_for_adjacency(message):
                if previous and previous.sender != message.sender:
                    gap = (message.timestamp - previous.timestamp).total_seconds()
                    weight = 0.0
                    if 0 <= gap <= 45:
                        weight = 1.4
                    elif gap <= 90:
                        weight = 1.1
                    elif gap <= 300:
                        weight = 0.45
                    if weight:
                        interaction = Interaction(
                            key=f"{message.msg_id}:adjacent:{message.sender}:{previous.sender}",
                            source=message.sender,
                            target=previous.sender,
                            kind="adjacent",
                            weight=weight,
                            timestamp=message.timestamp,
                        )
                        interactions[interaction.key] = interaction
                previous = message

        cutoff = datetime.now() - timedelta(days=self.history_days)
        connection = sqlite3.connect(str(self.event_database_path), timeout=10)
        try:
            rows = connection.execute(
                """
                SELECT msg_key, source_wxid, target_wxid, event_type,
                       base_weight, occurred_at
                FROM relation_events
                WHERE group_wxid = ? AND occurred_at >= ?
                """,
                (group_wxid, cutoff.isoformat(sep=" ")),
            ).fetchall()
        finally:
            connection.close()
        for msg_key, source, target, kind, weight, occurred_at in rows:
            key = f"{msg_key}:{kind}:{source}:{target}"
            interactions[key] = Interaction(
                key=key,
                source=str(source),
                target=str(target),
                kind=str(kind),
                weight=float(weight),
                timestamp=self._parse_datetime(occurred_at),
            )
        return list(interactions.values())

    def _eligible_for_adjacency(self, message: MessageRow) -> bool:
        if message.msg_type not in {1, 49}:
            return False
        text = html.unescape(message.content).strip()
        if not text or text.startswith("<sysmsg") or self.command in text:
            return False
        if len(text) > 4000:
            return False
        return True

    @staticmethod
    def _extract_quote_target(xml_text: str, source: str) -> str:
        if "<refermsg" not in xml_text:
            return ""
        candidates = [xml_text, html.unescape(xml_text)]
        for candidate in candidates:
            try:
                root = ET.fromstring(candidate.strip())
            except ET.ParseError:
                continue
            refer = root.find(".//refermsg")
            if refer is None:
                continue
            for tag in ("chatusr", "fromusr"):
                value = str(refer.findtext(tag, "") or "").strip()
                if value and value != source and not value.endswith("@chatroom"):
                    return value
        match = re.search(r"<refermsg>[\s\S]*?<chatusr>([^<]+)</chatusr>", xml_text)
        if match:
            value = html.unescape(match.group(1)).strip()
            if value and value != source and not value.endswith("@chatroom"):
                return value
        return ""

    def _score_relations(
        self, interactions: list[Interaction], messages: list[MessageRow]
    ) -> tuple[list[RelationEdge], Counter[str]]:
        message_counts: Counter[str] = Counter(item.sender for item in messages)
        pair_events: dict[tuple[str, str], list[tuple[Interaction, float]]] = defaultdict(list)
        now = datetime.now()
        for event in interactions:
            if not event.source or not event.target or event.source == event.target:
                continue
            age_days = max(0.0, (now - event.timestamp).total_seconds() / 86400)
            decayed = event.weight * (0.5 ** (age_days / self.half_life_days))
            pair = tuple(sorted((event.source, event.target)))
            pair_events[pair].append((event, decayed))

        edges = []
        for (left, right), events in pair_events.items():
            if message_counts[left] < self.min_active_messages or message_counts[right] < self.min_active_messages:
                continue
            weighted = sum(value for _, value in events)
            direct_weight = sum(
                value for event, value in events if event.kind in {"quote", "at", "pat"}
            )
            soft_events = [event for event, _ in events if event.kind == "adjacent"]
            active_days = len({event.timestamp.date() for event, _ in events})
            if direct_weight < 4.5 and (len(soft_events) < 5 or active_days < 2):
                continue

            forward = sum(value for event, value in events if event.source == left)
            backward = sum(value for event, value in events if event.source == right)
            reciprocity = 0.0
            if forward + backward > 0:
                reciprocity = 2 * min(forward, backward) / (forward + backward)
            activity = max(1.0, (message_counts[left] * message_counts[right]) ** 0.25)
            score = weighted * (1 + 0.35 * reciprocity) / (1 + 0.18 * activity)
            if score < self.min_edge_score:
                continue
            edges.append(
                RelationEdge(
                    left=left,
                    right=right,
                    score=score,
                    direct_weight=direct_weight,
                    interaction_count=len(events),
                    active_days=active_days,
                    reciprocity=reciprocity,
                )
            )
        edges.sort(key=lambda item: item.score, reverse=True)
        return edges, message_counts

    def _select_graph(
        self, edges: list[RelationEdge], message_counts: Counter[str]
    ) -> tuple[list[RelationEdge], list[str]]:
        degree: Counter[str] = Counter()
        for edge in edges:
            degree[edge.left] += edge.score
            degree[edge.right] += edge.score
        ranked_nodes = sorted(
            degree,
            key=lambda wxid: (degree[wxid], math.log1p(message_counts[wxid])),
            reverse=True,
        )[: self.max_nodes]
        selected = set(ranked_nodes)
        candidates = [
            edge for edge in edges if edge.left in selected and edge.right in selected
        ]
        edge_limit = min(
            self.max_edges,
            max(len(ranked_nodes), round(len(ranked_nodes) * self.edge_density)),
        )
        strongest_for_node: dict[str, tuple[str, str]] = {}
        for edge in candidates:
            key = tuple(sorted((edge.left, edge.right)))
            strongest_for_node.setdefault(edge.left, key)
            strongest_for_node.setdefault(edge.right, key)
        mandatory = set(strongest_for_node.values())
        selected_edges: list[RelationEdge] = []
        selected_keys: set[tuple[str, str]] = set()
        visible_degree: Counter[str] = Counter()

        def add_edge(edge: RelationEdge) -> bool:
            key = tuple(sorted((edge.left, edge.right)))
            if key in selected_keys or len(selected_edges) >= edge_limit:
                return False
            if (
                visible_degree[edge.left] >= self.max_connections_per_node
                or visible_degree[edge.right] >= self.max_connections_per_node
            ):
                return False
            selected_edges.append(edge)
            selected_keys.add(key)
            visible_degree[edge.left] += 1
            visible_degree[edge.right] += 1
            return True

        for edge in candidates:
            if tuple(sorted((edge.left, edge.right))) in mandatory:
                add_edge(edge)
        for edge in candidates:
            add_edge(edge)
        connected = {node for edge in selected_edges for node in (edge.left, edge.right)}
        ranked_nodes = [node for node in ranked_nodes if node in connected]
        return selected_edges, ranked_nodes

    async def _load_members(
        self, ctx: PluginContext, conversation_id: str
    ) -> dict[str, dict[str, str]]:
        if not ctx.conversations or not getattr(ctx.conversations, "repository_provider", None):
            return {}
        async with ctx.conversations.repository_provider() as repo:
            session = repo.session
            member_rows = list((await session.execute(
                select(ConversationMemberRecord).where(
                    ConversationMemberRecord.conversation_id == conversation_id
                )
            )).scalars().all())
            ids = [row.user_id for row in member_rows]
            contacts = {}
            if ids:
                contact_rows = (await session.execute(
                    select(ContactRecord).where(
                        ContactRecord.platform == "wechat",
                        ContactRecord.adapter == "wechat869",
                        ContactRecord.user_id.in_(ids),
                    )
                )).scalars().all()
                contacts = {row.user_id: row for row in contact_rows}
        members = {}
        for row in member_rows:
            contact = contacts.get(row.user_id)
            name = str(row.display_name or getattr(contact, "remark", "") or getattr(contact, "nickname", "") or f"群友 {row.user_id[-6:]}")
            members[row.user_id] = {
                "name": name,
                "avatar": str(getattr(contact, "avatar_url", "") or ""),
            }
        return members

    async def _download_avatars(
        self, members: dict[str, dict[str, str]]
    ) -> dict[str, bytes]:
        timeout = aiohttp.ClientTimeout(total=18)
        semaphore = asyncio.Semaphore(8)

        async def download(session: aiohttp.ClientSession, wxid: str, url: str) -> tuple[str, bytes]:
            if not url.startswith(("http://", "https://")):
                return wxid, b""
            try:
                async with semaphore:
                    async with session.get(url) as response:
                        if response.status < 400:
                            return wxid, await response.read()
            except Exception as error:
                logger.debug("[GroupSocialGraph] 头像下载失败 {}: {}", wxid, error)
            return wxid, b""

        async with aiohttp.ClientSession(timeout=timeout) as session:
            results = await asyncio.gather(
                *(download(session, wxid, info.get("avatar", "")) for wxid, info in members.items())
            )
        return dict(results)

    def _layout_graph(
        self, nodes: list[str], edges: list[RelationEdge]
    ) -> tuple[dict[str, tuple[float, float]], dict[str, int]]:
        if len(nodes) <= 8:
            return self._small_graph_layout(nodes, edges)
        if nx is not None:
            graph = nx.Graph()
            graph.add_nodes_from(nodes)
            for edge in edges:
                graph.add_edge(edge.left, edge.right, weight=max(0.1, edge.score))
            positions = nx.spring_layout(
                graph,
                weight="weight",
                seed=20260716,
                iterations=220,
                k=max(0.22, 1.35 / math.sqrt(max(1, len(nodes)))),
            )
            communities = list(nx.community.greedy_modularity_communities(graph, weight="weight"))
            community_map = {
                node: index for index, group in enumerate(communities) for node in group
            }
            return {node: (float(value[0]), float(value[1])) for node, value in positions.items()}, community_map
        return self._fallback_layout(nodes, edges)

    @staticmethod
    def _small_graph_layout(
        nodes: list[str], edges: list[RelationEdge]
    ) -> tuple[dict[str, tuple[float, float]], dict[str, int]]:
        community_map = GroupSocialGraph._label_communities(nodes, edges)
        degree: Counter[str] = Counter()
        for edge in edges:
            degree[edge.left] += edge.score
            degree[edge.right] += edge.score
        ranked = sorted(nodes, key=lambda node: degree[node], reverse=True)
        count = len(ranked)
        if count == 1:
            return {ranked[0]: (0.0, 0.0)}, community_map
        if count == 2:
            return {
                ranked[0]: (-0.43, 0.0),
                ranked[1]: (0.43, 0.0),
            }, community_map

        radius = 0.48 if count <= 4 else 0.60
        positions = {}
        for index, node in enumerate(ranked):
            angle = -math.pi / 2 + 2 * math.pi * index / count
            positions[node] = (radius * math.cos(angle), radius * math.sin(angle))
        return positions, community_map

    @staticmethod
    def _fallback_layout(
        nodes: list[str], edges: list[RelationEdge]
    ) -> tuple[dict[str, tuple[float, float]], dict[str, int]]:
        community_map = GroupSocialGraph._label_communities(nodes, edges)
        degree: Counter[str] = Counter()
        for edge in edges:
            degree[edge.left] += edge.score
            degree[edge.right] += edge.score

        ranked = sorted(nodes, key=lambda node: degree[node], reverse=True)
        core_count = 3 if len(ranked) <= 32 else 4
        core = ranked[: min(core_count, len(ranked))]
        remaining = sorted(
            ranked[len(core) :],
            key=lambda node: (community_map.get(node, 0), -degree[node]),
        )
        positions: dict[str, tuple[float, float]] = {}
        for index, node in enumerate(core):
            angle = -math.pi / 2 + 2 * math.pi * index / max(1, len(core))
            radius = 0.12 if len(core) > 1 else 0.0
            positions[node] = (radius * math.cos(angle), radius * math.sin(angle))

        if len(nodes) <= 16:
            rings = [(0.68, 20)]
        elif len(nodes) <= 32:
            rings = [(0.52, 8), (0.88, 24)]
        else:
            rings = [(0.36, 8), (0.60, 12), (0.81, 16), (0.98, 24)]
        cursor = 0
        for ring_index, (radius, capacity) in enumerate(rings):
            ring_nodes = remaining[cursor : cursor + capacity]
            cursor += len(ring_nodes)
            if not ring_nodes:
                continue
            offset = -math.pi / 2 + (ring_index % 2) * math.pi / max(1, len(ring_nodes))
            for index, node in enumerate(ring_nodes):
                angle = offset + 2 * math.pi * index / len(ring_nodes)
                positions[node] = (radius * math.cos(angle), radius * math.sin(angle))
        return positions, community_map

    @staticmethod
    def _label_communities(nodes: list[str], edges: list[RelationEdge]) -> dict[str, int]:
        labels = {node: index for index, node in enumerate(nodes)}
        neighbors: dict[str, list[tuple[str, float]]] = defaultdict(list)
        ordered = sorted(edge.score for edge in edges)
        threshold = ordered[int((len(ordered) - 1) * 0.72)] if ordered else 0
        for edge in edges:
            if edge.score < threshold:
                continue
            neighbors[edge.left].append((edge.right, edge.score))
            neighbors[edge.right].append((edge.left, edge.score))
        for _ in range(12):
            changed = False
            next_labels = dict(labels)
            for node in nodes:
                scores: Counter[int] = Counter()
                for neighbor, weight in neighbors[node]:
                    scores[labels[neighbor]] += weight
                if not scores:
                    continue
                best = max(scores, key=lambda label: (scores[label], -label))
                if labels[node] != best:
                    next_labels[node] = best
                    changed = True
            labels = next_labels
            if not changed:
                break
        compact = {label: index for index, label in enumerate(sorted(set(labels.values())))}
        return {node: compact[label] for node, label in labels.items()}

    @staticmethod
    def _separate_positions(
        positions: dict[str, tuple[float, float]], graph_box: tuple[int, int, int, int]
    ) -> None:
        nodes = list(positions)
        mutable = {node: [float(value[0]), float(value[1])] for node, value in positions.items()}
        anchors = {node: tuple(value) for node, value in mutable.items()}
        node_count = len(nodes)
        if node_count <= 2:
            minimum_distance = 320.0
        elif node_count <= 5:
            minimum_distance = 210.0
        elif node_count <= 8:
            minimum_distance = 160.0
        elif node_count <= 16:
            minimum_distance = 125.0
        elif node_count <= 32:
            minimum_distance = 118.0
        else:
            minimum_distance = 102.0
        for _ in range(140):
            shifts = {node: [0.0, 0.0] for node in nodes}
            overlap_found = False
            for index, left in enumerate(nodes):
                for right in nodes[index + 1 :]:
                    dx = mutable[right][0] - mutable[left][0]
                    dy = mutable[right][1] - mutable[left][1]
                    distance = math.hypot(dx, dy)
                    if distance >= minimum_distance:
                        continue
                    overlap_found = True
                    if distance < 0.01:
                        angle = (index * 2.399963) % (2 * math.pi)
                        dx, dy, distance = math.cos(angle), math.sin(angle), 1.0
                    push = (minimum_distance - distance) * 0.22
                    ux, uy = dx / distance, dy / distance
                    shifts[left][0] -= ux * push
                    shifts[left][1] -= uy * push
                    shifts[right][0] += ux * push
                    shifts[right][1] += uy * push
            for node in nodes:
                shifts[node][0] += (anchors[node][0] - mutable[node][0]) * 0.012
                shifts[node][1] += (anchors[node][1] - mutable[node][1]) * 0.012
                mutable[node][0] = min(
                    graph_box[2] - 58,
                    max(graph_box[0] + 58, mutable[node][0] + shifts[node][0]),
                )
                mutable[node][1] = min(
                    graph_box[3] - 64,
                    max(graph_box[1] + 58, mutable[node][1] + shifts[node][1]),
                )
            if not overlap_found:
                break
        positions.update({node: (value[0], value[1]) for node, value in mutable.items()})

    def _render_graph(
        self,
        group_wxid: str,
        edges: list[RelationEdge],
        nodes: list[str],
        members: dict[str, dict[str, str]],
        avatars: dict[str, bytes],
        message_counts: Counter[str],
        source_message_count: int,
    ) -> bytes:
        width, height = 1600, 1200
        image = Image.new("RGB", (width, height), (10, 11, 13))
        draw = ImageDraw.Draw(image, "RGBA")
        self._draw_background(draw, width, height)

        draw.rounded_rectangle((34, 24, 1566, 150), radius=6, fill=(20, 22, 25, 255), outline=(62, 65, 69, 255), width=2)
        draw.rectangle((34, 24, 44, 150), fill=(255, 71, 51, 255))
        draw.text((68, 45), "群友社交关系图", font=self._font(40), fill=(246, 244, 239, 255))
        draw.text((70, 96), "SOCIAL NETWORK / LIVE ANALYSIS", font=self._font(14), fill=(255, 184, 48, 255))
        generated = datetime.now().strftime("%Y-%m-%d %H:%M")
        stats = [
            (f"近 {self.history_days} 天", "统计窗口"),
            (str(len(nodes)), "活跃成员"),
            (str(len(edges)), "有效关系"),
            (str(source_message_count), "分析消息"),
        ]
        chip_x = 650
        for value, label in stats:
            draw.rounded_rectangle((chip_x, 46, chip_x + 172, 126), radius=4, fill=(31, 33, 37, 255), outline=(74, 76, 80, 255))
            draw.text((chip_x + 16, 57), value, font=self._font(25), fill=(246, 244, 239, 255))
            draw.text((chip_x + 16, 94), label, font=self._font(14), fill=(154, 155, 158, 255))
            chip_x += 188
        draw.text((1360, 130), generated, font=self._font(13), fill=(126, 127, 130, 255))

        panel = (34, 170, 1566, 1128)
        draw.rounded_rectangle(panel, radius=6, fill=(15, 17, 19, 255), outline=(58, 61, 65, 255), width=2)
        draw.text((58, 190), "RELATION FIELD  /  01", font=self._font(13), fill=(116, 118, 121, 255))
        positions, communities = self._layout_graph(nodes, edges)
        graph_box = (105, 245, 1495, 1025)
        screen = {
            node: (
                graph_box[0] + (x + 1) / 2 * (graph_box[2] - graph_box[0]),
                graph_box[1] + (y + 1) / 2 * (graph_box[3] - graph_box[1]),
            )
            for node, (x, y) in positions.items()
        }
        self._separate_positions(screen, graph_box)

        palette = [
            (255, 71, 51),
            (255, 184, 48),
            (232, 91, 61),
            (203, 205, 207),
            (255, 132, 42),
            (151, 153, 157),
            (244, 205, 74),
            (219, 69, 43),
        ]
        degree: Counter[str] = Counter()
        relation_count: Counter[str] = Counter()
        for edge in edges:
            degree[edge.left] += edge.score
            degree[edge.right] += edge.score
            relation_count[edge.left] += 1
            relation_count[edge.right] += 1

        scores = sorted(edge.score for edge in edges)
        q20 = self._percentile(scores, 0.20)
        q95 = self._percentile(scores, 0.95)
        edge_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        edge_draw = ImageDraw.Draw(edge_layer, "RGBA")
        for edge in reversed(edges):
            left = screen[edge.left]
            right = screen[edge.right]
            ratio = max(0.0, min(1.0, (edge.score - q20) / max(0.01, q95 - q20)))
            line_width = max(1, round(1 + 5 * (ratio ** 0.75)))
            alpha = int(65 + 165 * ratio)
            left_color = palette[communities.get(edge.left, 0) % len(palette)]
            right_color = palette[communities.get(edge.right, 0) % len(palette)]
            color = tuple((left_color[i] + right_color[i]) // 2 for i in range(3)) + (alpha,)
            points = self._curved_points(left, right, edge.left, edge.right)
            edge_draw.line(points, fill=color, width=line_width, joint="curve")
        image = Image.alpha_composite(image.convert("RGBA"), edge_layer)
        draw = ImageDraw.Draw(image, "RGBA")

        score_label_limit = 5 if len(nodes) <= 10 else 0
        for edge in edges[:score_label_limit]:
            x = (screen[edge.left][0] + screen[edge.right][0]) / 2
            y = (screen[edge.left][1] + screen[edge.right][1]) / 2
            label = f"{edge.score:.1f}"
            box = draw.textbbox((0, 0), label, font=self._font(14))
            label_width = box[2] - box[0] + 14
            draw.rounded_rectangle(
                (x - label_width / 2, y - 11, x + label_width / 2, y + 11),
                radius=6,
                fill=(24, 25, 28, 235),
                outline=(102, 103, 106, 220),
            )
            draw.text((x - label_width / 2 + 7, y - 8), label, font=self._font(14), fill=(255, 255, 255, 240))

        max_degree = max(degree.values(), default=1)
        for node in sorted(nodes, key=lambda item: degree[item]):
            center = screen[node]
            ratio = math.sqrt(degree[node] / max_degree) if max_degree else 0
            radius = int(34 + 20 * ratio)
            color = palette[communities.get(node, 0) % len(palette)]
            self._draw_node(
                image,
                center,
                radius,
                color,
                avatars.get(node, b""),
                members[node]["name"],
                relation_count[node],
                ratio,
            )

        draw = ImageDraw.Draw(image, "RGBA")
        draw.ellipse((48, 1152, 64, 1168), fill=(255, 71, 51, 255))
        draw.text((74, 1148), "颜色 = 互动社区", font=self._font(16), fill=(188, 189, 191, 255))
        draw.line((250, 1160, 300, 1160), fill=(255, 184, 48, 255), width=6)
        draw.text((312, 1148), "粗细 = 关系强度", font=self._font(16), fill=(188, 189, 191, 255))
        draw.ellipse((510, 1149, 532, 1171), outline=(255, 71, 51, 255), width=4)
        draw.text((544, 1148), "大小 = 中心度", font=self._font(16), fill=(188, 189, 191, 255))
        draw.text((1080, 1148), "PRIVATE / LOCAL ANALYSIS", font=self._font(14), fill=(105, 106, 109, 255))
        output = io.BytesIO()
        image.convert("RGB").save(output, format="PNG", optimize=True)
        return output.getvalue()

    @staticmethod
    def _draw_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
        for x in range(0, width, 80):
            draw.line((x, 170, x, height - 72), fill=(255, 255, 255, 12), width=1)
        for y in range(170, height - 70, 80):
            draw.line((34, y, width - 34, y), fill=(255, 255, 255, 12), width=1)
        for x, y in ((34, 170), (1566, 170), (34, 1128), (1566, 1128)):
            draw.line((x - 14, y, x + 14, y), fill=(255, 71, 51, 180), width=2)
            draw.line((x, y - 14, x, y + 14), fill=(255, 71, 51, 180), width=2)

    def _draw_node(
        self,
        image: Image.Image,
        center: tuple[float, float],
        radius: int,
        color: tuple[int, int, int],
        avatar_bytes: bytes,
        name: str,
        relation_count: int,
        centrality: float,
    ) -> None:
        x, y = int(center[0]), int(center[1])
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer, "RGBA")
        if centrality > 0.72:
            halo = radius + 13
            draw.ellipse((x - halo, y - halo, x + halo, y + halo), fill=(*color, 18), outline=(*color, 70), width=2)
        draw.ellipse((x - radius - 7, y - radius + 3, x + radius + 7, y + radius + 17), fill=(0, 0, 0, 100))
        draw.ellipse(
            (x - radius - 5, y - radius - 5, x + radius + 5, y + radius + 5),
            fill=(*color, 42),
            outline=(*color, 245),
            width=4,
        )
        avatar = self._avatar_image(avatar_bytes, radius * 2, name, color)
        layer.alpha_composite(avatar, (x - radius, y - radius))

        safe_name = self._short_name(name, 9)
        font = self._font(20)
        text_box = draw.textbbox((0, 0), safe_name, font=font)
        label_width = min(180, max(72, text_box[2] - text_box[0] + 22))
        label_y = y + radius + 7
        draw.rounded_rectangle(
            (x - label_width / 2, label_y, x + label_width / 2, label_y + 34),
            radius=7,
            fill=(25, 27, 30, 245),
            outline=(*color, 210),
        )
        draw.text((x - (text_box[2] - text_box[0]) / 2, label_y + 4), safe_name, font=font, fill=(255, 255, 255, 250))

        badge = str(relation_count)
        badge_radius = 11
        badge_x, badge_y = x + radius - 2, y - radius + 2
        draw.ellipse(
            (badge_x - badge_radius, badge_y - badge_radius, badge_x + badge_radius, badge_y + badge_radius),
            fill=(20, 21, 23, 255),
            outline=(255, 255, 255, 245),
            width=2,
        )
        badge_font = self._font(12)
        badge_box = draw.textbbox((0, 0), badge, font=badge_font)
        draw.text(
            (badge_x - (badge_box[2] - badge_box[0]) / 2, badge_y - 7),
            badge,
            font=badge_font,
            fill=(255, 255, 255, 255),
        )
        image.alpha_composite(layer)

    def _avatar_image(
        self,
        avatar_bytes: bytes,
        size: int,
        name: str,
        color: tuple[int, int, int],
    ) -> Image.Image:
        try:
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
            avatar = ImageOps.fit(avatar, (size, size), method=Image.Resampling.LANCZOS)
        except Exception:
            avatar = Image.new("RGB", (size, size), color)
            draw = ImageDraw.Draw(avatar)
            initial = self._short_name(name)[:1] or "?"
            font = self._font(max(18, size // 2))
            box = draw.textbbox((0, 0), initial, font=font)
            draw.text(
                ((size - (box[2] - box[0])) / 2, (size - (box[3] - box[1])) / 2 - 3),
                initial,
                font=font,
                fill=(255, 255, 255),
            )
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result.paste(avatar, (0, 0), mask)
        return result

    @staticmethod
    def _short_name(name: str, limit: int = 12) -> str:
        clean = re.sub(r"\s+", " ", str(name or "群友")).strip()
        return clean if len(clean) <= limit else clean[: max(1, limit - 1)] + "…"

    @staticmethod
    def _curved_points(
        left: tuple[float, float], right: tuple[float, float], left_id: str, right_id: str
    ) -> list[tuple[float, float]]:
        dx, dy = right[0] - left[0], right[1] - left[1]
        distance = max(1.0, math.hypot(dx, dy))
        sign = -1 if int(hashlib.sha256(f"{left_id}:{right_id}".encode()).hexdigest()[:2], 16) % 2 else 1
        bend = min(24.0, distance * 0.055) * sign
        control = ((left[0] + right[0]) / 2 - dy / distance * bend, (left[1] + right[1]) / 2 + dx / distance * bend)
        points = []
        for index in range(17):
            t = index / 16
            one = 1 - t
            points.append(
                (
                    one * one * left[0] + 2 * one * t * control[0] + t * t * right[0],
                    one * one * left[1] + 2 * one * t * control[1] + t * t * right[1],
                )
            )
        return points

    @staticmethod
    def _percentile(values: list[float], ratio: float) -> float:
        if not values:
            return 0.0
        position = (len(values) - 1) * ratio
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return values[lower]
        return values[lower] * (upper - position) + values[upper] * (position - lower)

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        if size not in self._font_cache:
            try:
                self._font_cache[size] = ImageFont.truetype(str(self.font_path), size)
            except Exception:
                self._font_cache[size] = ImageFont.load_default()
        return self._font_cache[size]

    def _cache_path(self, group_wxid: str) -> Path:
        bucket = int(time.time() // (self.cache_ttl_hours * 3600))
        digest = hashlib.sha256(
            f"layout-v7-industrial:{group_wxid}:{self.history_days}:{bucket}".encode()
        ).hexdigest()[:24]
        return self.cache_dir / f"{digest}.png"

    def _read_cache(self, group_wxid: str) -> bytes:
        if not self.cache_enable:
            return b""
        path = self._cache_path(group_wxid)
        try:
            if path.exists() and time.time() - path.stat().st_mtime <= self.cache_ttl_hours * 3600:
                return path.read_bytes()
        except Exception as error:
            logger.warning("[GroupSocialGraph] 读取缓存失败: {}", error)
        return b""

    def _write_cache(self, group_wxid: str, image: bytes) -> None:
        if not self.cache_enable or not image:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_path(group_wxid)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(image)
            temporary.replace(path)
        except Exception as error:
            logger.warning("[GroupSocialGraph] 写入缓存失败: {}", error)

    async def _send_text(self, group_wxid: str, content: str) -> None:
        if self._client:
            await self._client.send_text_message(group_wxid, content)
        elif self._ctx and self._ctx.send_reply:
            await self._ctx.send_reply(Reply(platform="wechat", adapter="wechat869", conversation_id=group_wxid, type="text", content=content))

    async def _send_image(self, group_wxid: str, image: bytes) -> None:
        output_dir = self.plugin_dir / "data" / "outgoing"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"social-graph-{hashlib.sha256(image).hexdigest()[:24]}.png"
        if not path.exists():
            path.write_bytes(image)
        if not self._client:
            raise RuntimeError("Wechat869 客户端不可用")
        encoded = base64.b64encode(image).decode("ascii")
        payload = {"MsgItem": [{"ToUserName": group_wxid, "MsgType": 2, "ImageContent": encoded}]}
        last_error: Exception | None = None
        for endpoint in ("/message/SendImageNewMessage", "/message/SendImageMessage"):
            try:
                logger.info("[GroupSocialGraph] 调用图片接口: endpoint={} group={}", endpoint, group_wxid)
                result = await asyncio.wait_for(
                    self._client.call_path(endpoint, body=payload), timeout=12
                )
                logger.info("[GroupSocialGraph] 图片接口完成: endpoint={} result={}", endpoint, result)
                return
            except Exception as exc:
                last_error = exc
                logger.warning("[GroupSocialGraph] 图片接口失败: endpoint={} error={}", endpoint, exc)
        raise RuntimeError(f"869 图片发送失败: {last_error}")

    @staticmethod
    def _create_client(ctx: PluginContext) -> Wechat869Client | None:
        if not ctx.settings:
            return None
        wechat = getattr(getattr(ctx.settings, "adapters", None), "wechat869", None)
        if not wechat:
            return None
        client = Wechat869Client(
            host=str(getattr(wechat, "host", "127.0.0.1")), port=int(getattr(wechat, "port", 5253)),
            admin_key=str(getattr(wechat, "admin_key", "")), token_key=str(getattr(wechat, "token_key", "")),
            ws_url=str(getattr(wechat, "ws_url", "")),
        )
        client.wxid = str(getattr(wechat, "bot_wxid", "") or "")
        return client
