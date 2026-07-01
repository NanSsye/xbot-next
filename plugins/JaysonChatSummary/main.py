from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from loguru import logger
from sqlalchemy import and_, func, select

from xbot.adapters.wechat869.client import Wechat869Client
from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase
from xbot.plugins.context import PluginContext
from xbot.storage.models import ContactRecord, ConversationMemberRecord, ConversationMessageRecord, ConversationRecord

SYSTEM_PROMPT = """你是一名中文群聊总结助手。请根据群聊记录输出严格 JSON，不要解释。
字段：vibe, quote, topics。topics 为数组，每项包含 title, heat(1-5), time_range, participants, process, rating。
要求忠于记录，不编造；topics 最多 {max_topics} 个；中文输出。
"""

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

class UserError(Exception):
    pass

class JaysonChatSummary(PluginBase):
    name = "JaysonChatSummary"
    version = "2.0.0"

    def __init__(self) -> None:
        self.plugin_dir = Path(__file__).resolve().parent
        self.data_dir = self.plugin_dir / "data"
        self.enable = True
        self.commands = ["群聊总结", "总结群聊", "聊天总结"]
        self.default_hours = 24
        self.max_messages = 600
        self.max_topics = 4
        self.random_template_enable = True
        self.template_paths: list[Path] = []
        self.api_base_url = ""
        self.api_key = ""
        self.model = ""
        self.request_timeout = 90
        self.llm_max_retries = 3
        self.llm_retry_base_delay_seconds = 1.0
        self.html2image_url = ""
        self.schedule_enable = False
        self.schedule_hour = 22
        self.schedule_minute = 30
        self.schedule_second = 0
        self.schedule_summary_hours = 24
        self.schedule_random_delay_seconds = 0
        self.target_groups: list[str] = []
        self._ctx: PluginContext | None = None
        self._client: Wechat869Client | None = None
        self._schedule_task: asyncio.Task | None = None
        self._last_schedule_fire_key = ""

    async def on_load(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self.data_dir = ctx.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        cfg = ctx.config or {}
        basic = cfg.get("basic", {}) if isinstance(cfg.get("basic"), dict) else {}
        pcfg = cfg.get("JaysonChatSummary", cfg)
        self.enable = bool(basic.get("enable", pcfg.get("enable", True)))
        self.commands = [str(x).strip() for x in pcfg.get("commands", self.commands) if str(x).strip()] or self.commands
        self.default_hours = int(pcfg.get("default_hours", self.default_hours))
        self.max_messages = int(pcfg.get("max_messages", self.max_messages))
        self.max_topics = int(pcfg.get("max_topics", self.max_topics))
        self.random_template_enable = bool(pcfg.get("random_template_enable", True))
        self.template_paths = self._load_template_paths(pcfg)
        self.api_base_url = self._pick(pcfg, "minimax_base_url", "openai_base_url", "base_url") or getattr(getattr(ctx.settings, "llm", None), "base_url", "") or ""
        self.api_key = self._pick(pcfg, "minimax_api_key", "openai_api_key", "api_key") or getattr(getattr(ctx.settings, "llm", None), "api_key", "") or ""
        self.model = self._pick(pcfg, "minimax_model", "openai_model", "model") or getattr(getattr(ctx.settings, "llm", None), "model", "") or ""
        self.request_timeout = int(pcfg.get("request_timeout", self.request_timeout))
        self.llm_max_retries = int(pcfg.get("llm_max_retries", self.llm_max_retries))
        self.llm_retry_base_delay_seconds = float(pcfg.get("llm_retry_base_delay_seconds", self.llm_retry_base_delay_seconds))
        self.html2image_url = str(pcfg.get("html2image_url", self.html2image_url)).strip()
        self.schedule_enable = bool(pcfg.get("schedule_enable", False))
        self.schedule_hour = int(pcfg.get("schedule_hour", self.schedule_hour))
        self.schedule_minute = int(pcfg.get("schedule_minute", self.schedule_minute))
        self.schedule_second = int(pcfg.get("schedule_second", self.schedule_second))
        self.schedule_summary_hours = int(pcfg.get("schedule_summary_hours", self.schedule_summary_hours))
        self.schedule_random_delay_seconds = int(pcfg.get("schedule_random_delay_seconds", self.schedule_random_delay_seconds))
        self.target_groups = [str(x).strip() for x in pcfg.get("target_groups", []) if str(x).strip().endswith("@chatroom")]
        self._client = self._create_client(ctx)
        if self.schedule_enable:
            self._schedule_task = asyncio.create_task(self._schedule_loop(), name="JaysonChatSummary.schedule")
        logger.info("<green>JaysonChatSummary</green> 已加载 enable={} commands={} schedule={} groups={}", self.enable, self.commands, self.schedule_enable, len(self.target_groups))

    async def on_unload(self) -> None:
        if self._schedule_task:
            self._schedule_task.cancel()

    async def on_message(self, message: Message, ctx: PluginContext) -> bool:
        if not self.enable or message.platform != "wechat" or message.adapter != "wechat869" or message.type not in {"text", "event"}:
            return False
        if not self._is_group(message):
            return False
        content = str(message.content or "").strip()
        matched = self._match_command(content)
        if not matched:
            return False
        hours = self._parse_hours(matched[1])
        group_raw = self._raw_group_id(message.conversation_id)
        try:
            conversation_id = await self._resolve_conversation_id(ctx, message.conversation_id, group_raw)
            image_path, text_summary = await self._build_summary_artifact(ctx, conversation_id, hours)
            if image_path:
                await self._send_image(group_raw, image_path)
            else:
                await self._send_text(group_raw, text_summary)
        except UserError as exc:
            await self._send_text(group_raw, f"群聊总结失败：{exc}")
        except Exception as exc:
            logger.exception("[JaysonChatSummary] 生成失败: {}", exc)
            await self._send_text(group_raw, "群聊总结失败：发生未预期错误，请查看日志。")
        return True

    async def _schedule_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(1)
                if not self.enable or not self.schedule_enable or not self._ctx:
                    continue
                now = datetime.now()
                if (now.hour, now.minute, now.second) != (self.schedule_hour, self.schedule_minute, self.schedule_second):
                    continue
                key = now.strftime("%Y%m%d-%H%M%S")
                if self._last_schedule_fire_key == key:
                    continue
                self._last_schedule_fire_key = key
                if self.schedule_random_delay_seconds > 0:
                    await asyncio.sleep(random.randint(0, self.schedule_random_delay_seconds))
                for raw_group in self.target_groups:
                    conversation_id = await self._find_conversation_id(self._ctx, raw_group)
                    if not conversation_id:
                        await self._send_text(raw_group, f"群聊总结失败：数据库中找不到群 {raw_group}")
                        continue
                    image_path, text_summary = await self._build_summary_artifact(self._ctx, conversation_id, max(1, self.schedule_summary_hours))
                    if image_path:
                        await self._send_image(raw_group, image_path)
                    else:
                        await self._send_text(raw_group, text_summary)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("[JaysonChatSummary] 定时任务异常: {}", exc)

    def _match_command(self, content: str) -> tuple[str, str] | None:
        text = re.sub(r"@\S+", "", content).strip()
        for command in self.commands:
            if text == command:
                return command, ""
            if text.startswith(command + " "):
                return command, text[len(command):].strip()
        return None

    def _parse_hours(self, text: str) -> int:
        if not text:
            return self.default_hours
        m = re.search(r"(\d{1,3})\s*(小时|h|H)?", text)
        if not m:
            return self.default_hours
        return max(1, min(168, int(m.group(1))))

    async def _build_summary_artifact(self, ctx: PluginContext, conversation_id: str, hours: int) -> tuple[str, str]:
        messages, group_name = await self._load_messages(ctx, conversation_id, hours)
        if len(messages) < 3:
            raise UserError(f"最近 {hours} 小时可总结文本不足。")
        prompt = self._build_user_prompt(group_name, messages)
        data = await asyncio.to_thread(self._call_llm_summary, prompt)
        topics = self._normalize_topics(data.get("topics", []))
        vibe = str(data.get("vibe") or "群内讨论较为分散，但仍有可总结的信息。")[:80]
        quote = str(data.get("quote") or "信息沉淀下来，才真正变成知识。")[:80]
        text_summary = self._build_text_summary(group_name, hours, vibe, topics, quote)
        html = self._render_html(group_name, hours, vibe, quote, topics, messages)
        image_bytes = await asyncio.to_thread(self._render_html_to_image, html)
        if not image_bytes:
            return "", text_summary
        out = self.data_dir / "cards" / f"{datetime.now():%Y%m%d}"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"summary_{uuid4().hex}.png"
        path.write_bytes(image_bytes)
        return str(path), text_summary

    async def _load_messages(self, ctx: PluginContext, conversation_id: str, hours: int) -> tuple[list[dict[str, Any]], str]:
        end = datetime.now()
        start = end - timedelta(hours=hours)
        if not ctx.conversations or not getattr(ctx.conversations, "repository_provider", None):
            raise UserError("会话数据库未启用，无法读取群聊记录。")
        async with ctx.conversations.repository_provider() as repo:
            session = repo.session
            conv = await session.get(ConversationRecord, conversation_id)
            group_name = (conv.title if conv else "") or (conv.raw_id if conv else conversation_id)
            rows = list((await session.execute(
                select(ConversationMessageRecord)
                .where(ConversationMessageRecord.conversation_id == conversation_id, ConversationMessageRecord.created_at >= start, ConversationMessageRecord.type.in_(["text", "event", "image", "file"]))
                .order_by(ConversationMessageRecord.created_at.desc())
                .limit(max(1, self.max_messages))
            )).scalars().all())
            rows.reverse()
            ids = {r.sender_id for r in rows if r.sender_id}
            contacts = {}
            if ids:
                for c in (await session.execute(select(ContactRecord).where(ContactRecord.platform == "wechat", ContactRecord.user_id.in_(ids)))).scalars().all():
                    contacts[c.user_id] = c
                members = (await session.execute(select(ConversationMemberRecord).where(ConversationMemberRecord.conversation_id == conversation_id, ConversationMemberRecord.user_id.in_(ids)))).scalars().all()
                for m in members:
                    if m.user_id not in contacts and m.display_name:
                        contacts[m.user_id] = type("C", (), {"nickname": m.display_name})()
        result = []
        for r in rows:
            content = str(r.content or "").strip()
            if not content or content.startswith("[非文本消息"):
                continue
            contact = contacts.get(r.sender_id)
            name = str(getattr(contact, "nickname", "") or r.sender_name or r.sender_id or "未知")
            result.append({"time": r.created_at, "name": name, "sender_id": r.sender_id, "content": content, "type": r.type})
        return result, group_name

    def _build_user_prompt(self, group_name: str, messages: list[dict[str, Any]]) -> str:
        lines = [f"群名：{group_name}", "聊天记录："]
        for m in messages:
            lines.append(f"[{m['time']:%H:%M}] {m['name']}: {m['content'][:500]}")
        return "\n".join(lines)

    def _call_llm_summary(self, user_prompt: str) -> dict[str, Any]:
        if not self.api_base_url or not self.api_key or not self.model:
            return self._fallback_summary(user_prompt)
        url = self._chat_url(self.api_base_url)
        payload = {"model": self.model, "messages": [{"role": "system", "content": SYSTEM_PROMPT.format(max_topics=self.max_topics)}, {"role": "user", "content": user_prompt}], "temperature": 0.3}
        last = None
        for i in range(max(1, self.llm_max_retries)):
            try:
                resp = httpx.post(url, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, json=payload, timeout=self.request_timeout)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return self._parse_json(content)
            except Exception as exc:
                last = exc
                time_sleep = self.llm_retry_base_delay_seconds * (i + 1)
                import time as _time
                _time.sleep(time_sleep)
        logger.warning("[JaysonChatSummary] LLM 失败，使用本地降级总结: {}", last)
        return self._fallback_summary(user_prompt)

    def _fallback_summary(self, prompt: str) -> dict[str, Any]:
        lines = [x for x in prompt.splitlines() if ":" in x][-200:]
        words = Counter()
        participants = []
        for line in lines:
            name = line.split("]", 1)[-1].split(":", 1)[0].strip()
            if name and name not in participants:
                participants.append(name)
            for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", line):
                if token not in {"聊天记录", "群名"}:
                    words[token] += 1
        common = "、".join(x for x, _ in words.most_common(5)) or "日常交流"
        return {"vibe": f"群内围绕 {common} 展开了多轮讨论。", "quote": "把零散的信息整理好，就是下一步行动的开始。", "topics": [{"title": common[:12], "heat": min(5, max(1, len(lines)//20)), "time_range": "--:--–--:--", "participants": participants[:5], "process": f"最近记录中多次出现 {common} 等内容，群成员围绕这些信息进行了交流。", "rating": "值得继续跟进。"}]}

    def _normalize_topics(self, raw: Any) -> list[Topic]:
        accents = ["#22c55e", "#3b82f6", "#f97316", "#a855f7"]
        topics = []
        if not isinstance(raw, list):
            raw = []
        for idx, item in enumerate(raw[: self.max_topics], 1):
            if not isinstance(item, dict):
                continue
            topics.append(Topic(idx, str(item.get("title") or f"话题{idx}")[:30], max(1, min(5, int(item.get("heat") or 1))), str(item.get("time_range") or "--:--–--:--")[:20], [str(x)[:20] for x in (item.get("participants") or [])][:5], str(item.get("process") or "")[:240], str(item.get("rating") or "")[:80], accents[(idx - 1) % len(accents)]))
        return topics or self._normalize_topics(self._fallback_summary("").get("topics"))

    def _render_html(self, group_name: str, hours: int, vibe: str, quote: str, topics: list[Topic], messages: list[dict[str, Any]]) -> str:
        template = self._pick_template().read_text(encoding="utf-8")
        top = Counter(m["name"] for m in messages).most_common(5)
        top_html = "".join(
            "<li class='speaker'>"
            f"<div class='speaker__left'><span class='rank'>{idx}</span><span class='name'>{escape(n)}</span></div>"
            f"<span class='count'>{c} msgs</span>"
            "</li>"
            for idx, (n, c) in enumerate(top, 1)
        )
        msg_count = len(messages)
        people_count = len({m.get("sender_id") or m.get("name") for m in messages})
        first_time = min((m["time"] for m in messages), default=datetime.now())
        last_time = max((m["time"] for m in messages), default=datetime.now())
        overview_html = (
            "<p class='overview-greeting'>下午好，</p>"
            f"<p class='overview-date'>{datetime.now():%Y年%m月%d日}</p>"
            f"<p class='overview-stats'>最近 {hours} 小时，群内共有 <b>{people_count}</b> 人参与，沉淀 <b>{msg_count}</b> 条可总结消息。</p>"
            f"<p class='overview-quote'>「{escape(quote)}」</p>"
        )
        topics_html = "".join(
            "<section class='topic' style='--topic-accent:%s'>"
            "<div class='topic__left'><div class='topic__index'>%s</div><div class='topic__heat'>%s</div></div>"
            "<div class='topic__main'>"
            "<h3 class='topic__title'>%s</h3>"
            "<div class='topic__meta'><span class='pill'>Time&nbsp; %s</span><span class='pill'>People&nbsp; %s</span></div>"
            "<p class='topic__process'>%s</p>"
            "<p class='topic__rating'><b>评价：</b>%s</p>"
            "</div></section>"
            % (
                t.accent,
                t.index,
                " ".join("<span class='flame'>🔥</span>" for _ in range(max(1, min(5, t.heat)))),
                escape(t.title),
                escape(t.time_range),
                escape(" / ".join(t.participants) or "群成员"),
                escape(t.process),
                escape(t.rating),
            )
            for t in topics
        )
        now = datetime.now()
        report_date = now.strftime("%Y年%m月%d日，星期") + "一二三四五六日"[now.weekday()]
        return (
            template.replace("{{group_name}}", escape(group_name))
            .replace("{{report_date}}", report_date)
            .replace("{{vibe_line}}", escape(vibe))
            .replace("{{top_speakers_html}}", top_html)
            .replace("{{overview_html}}", overview_html)
            .replace("{{topics_html}}", topics_html)
            .replace("{{quote}}", escape(quote))
            .replace("{{footer_note}}", f"最近 {hours} 小时 · {msg_count} 条记录 · {first_time:%H:%M}-{last_time:%H:%M} · {now:%H:%M} 生成")
        )

    def _render_html_to_image(self, html: str) -> bytes:
        if not self.html2image_url:
            return b""
        payload = {"html": html, "image_type": "png", "element_id": "card", "viewport": {"width": 900, "height": 1400}, "render_wait_ms": 500}
        for url in self._html2image_urls(self.html2image_url):
            try:
                r = httpx.post(url, json=payload, timeout=self.request_timeout)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                data = r.json()
                b64 = data.get("image_base64") or data.get("base64") or data.get("data")
                if isinstance(b64, str):
                    return base64.b64decode(b64.split(",")[-1])
            except Exception as exc:
                logger.warning("[JaysonChatSummary] html2image 失败 url={} err={}", url, exc)
        return b""

    async def _send_text(self, raw_group: str, text: str) -> None:
        if self._ctx and self._ctx.send_reply:
            await self._ctx.send_reply(Reply(platform="wechat", adapter="wechat869", conversation_id=raw_group, type="text", content=text))

    async def _send_image(self, raw_group: str, image_path: str) -> None:
        client = self._client or (self._create_client(self._ctx) if self._ctx else None)
        if client:
            await client.send_image_message(raw_group, image_path)
        elif self._ctx and self._ctx.send_reply:
            await self._ctx.send_reply(Reply(platform="wechat", adapter="wechat869", conversation_id=raw_group, type="image", content=image_path))

    def _create_client(self, ctx: PluginContext | None) -> Wechat869Client | None:
        if not ctx or not ctx.settings:
            return None
        w = getattr(getattr(ctx.settings, "adapters", None), "wechat869", None)
        client = Wechat869Client(host=str(getattr(w, "host", "127.0.0.1")), port=int(getattr(w, "port", 5253)), admin_key=str(getattr(w, "admin_key", "")), token_key=str(getattr(w, "token_key", "")), ws_url=str(getattr(w, "ws_url", "")))
        client.wxid = str(getattr(w, "bot_wxid", "") or "")
        return client

    async def _find_conversation_id(self, ctx: PluginContext, raw_group: str) -> str:
        if not ctx.conversations or not getattr(ctx.conversations, "repository_provider", None):
            return ""
        async with ctx.conversations.repository_provider() as repo:
            session = repo.session
            row = (await session.execute(select(ConversationRecord).where(ConversationRecord.platform == "wechat", ConversationRecord.raw_id == raw_group).limit(1))).scalar_one_or_none()
            return row.id if row else ""

    async def _resolve_conversation_id(self, ctx: PluginContext, conversation_id: str, raw_group: str) -> str:
        if conversation_id.startswith("wechat:"):
            return conversation_id
        found = await self._find_conversation_id(ctx, raw_group)
        return found or f"wechat:wechat869:group:{raw_group}"

    def _is_group(self, message: Message) -> bool:
        return ":group:" in message.conversation_id or str(message.conversation_id).endswith("@chatroom") or str(message.raw.get("scope") if isinstance(message.raw, dict) else "") == "group"

    def _raw_group_id(self, conversation_id: str) -> str:
        return conversation_id.split(":")[-1] if conversation_id.startswith("wechat:") else conversation_id

    def _load_template_paths(self, cfg: dict[str, Any]) -> list[Path]:
        names = cfg.get("template_files") if isinstance(cfg.get("template_files"), list) else []
        paths = [self.plugin_dir / str(x) for x in names if str(x).strip()] or sorted(self.plugin_dir.glob("group_chat_summary_card_template*.html"))
        return [p for p in paths if p.exists()]

    def _pick_template(self) -> Path:
        if not self.template_paths:
            raise UserError("找不到卡片模板文件。")
        return random.choice(self.template_paths) if self.random_template_enable else self.template_paths[0]

    @staticmethod
    def _pick(cfg: dict[str, Any], *keys: str) -> str:
        for k in keys:
            v = str(cfg.get(k, "")).strip()
            if v:
                return v
        return ""

    @staticmethod
    def _chat_url(base: str) -> str:
        base = base.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        candidates = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.S)
        for item in reversed(candidates):
            try:
                return json.loads(item)
            except Exception:
                continue
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0) if m else raw)

    @staticmethod
    def _html2image_urls(url: str) -> list[str]:
        url = re.sub(r"(?<!:)//+", "/", str(url or "").strip()).rstrip("/")
        parsed = urlparse(url)
        if parsed.path and parsed.path not in {"", "/"}:
            base = f"{parsed.scheme}://{parsed.netloc}"
            return [url, f"{base}/api/html2image", f"{base}/html2image", f"{base}/api/render", f"{base}/render"]
        return [f"{url}/api/html2image", f"{url}/html2image", f"{url}/api/render", f"{url}/render"]

    @staticmethod
    def _build_text_summary(group_name: str, hours: int, vibe: str, topics: list[Topic], quote: str) -> str:
        lines = [f"【{group_name}】最近 {hours} 小时群聊总结", vibe, ""]
        for t in topics:
            lines.append(f"{t.index}. {t.title}（热度 {t.heat}/5）")
            lines.append(f"   {t.process}")
        lines.append("")
        lines.append(f"{quote}")
        return "\n".join(lines)
