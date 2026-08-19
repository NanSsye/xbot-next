from __future__ import annotations

import asyncio
import inspect
import re

import anyio
from loguru import logger

from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase


class AgentChatPlugin(PluginBase):
    name = "agent_chat"
    version = "0.1.0"

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()
        self._task_conversations: dict[asyncio.Task, str] = {}
        self._conversation_locks: dict[str, asyncio.Lock] = {}

    async def on_unload(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._task_conversations.clear()
        self._conversation_locks.clear()

    async def on_message(self, message: Message, ctx):
        if not ctx.agent or not ctx.send_reply:
            logger.warning("AgentChatPlugin 未配置 agent 或 send_reply，跳过消息: {}", message.id)
            return False
        if message.type not in {"text", "image", "file", "voice", "video", "event"} or not message.content:
            logger.info("AgentChatPlugin 跳过不支持或空消息: id={} type={}", message.id, message.type)
            return False
        if self._should_defer_unquoted_wechat_media(message):
            logger.info(
                "AgentChatPlugin 跳过微信私聊未引用媒体消息: id={} adapter={} type={}",
                message.id,
                message.adapter,
                message.type,
            )
            return False
        if not self._should_handle(message):
            logger.info(
                "AgentChatPlugin 跳过未命中消息: id={} scope={} mentions_bot={}",
                message.id,
                message.raw.get("scope"),
                message.raw.get("mentions_bot"),
            )
            return False

        telegram_command, telegram_argument = self._telegram_group_command(message)
        if telegram_command in {"help", "status"} or (
            telegram_command == "xbot" and not telegram_argument
        ):
            await self._send_telegram_group_command_reply(message, ctx, telegram_command)
            return True

        content = self._clean_content(message)
        if not content:
            logger.info("AgentChatPlugin 清理后内容为空，跳过消息: {}", message.id)
            return False

        self._schedule_message(message, ctx, content)
        return True

    def _schedule_message(self, message: Message, ctx, content: str) -> None:
        conversation_key = self._conversation_key(message)
        lock = self._conversation_locks.setdefault(conversation_key, asyncio.Lock())
        task = asyncio.create_task(
            self._process_message(message, ctx, content, lock),
            name=f"xbot-agent-{message.id}",
        )
        self._tasks.add(task)
        self._task_conversations[task] = conversation_key
        task.add_done_callback(self._on_task_done)

    async def _process_message(
        self,
        message: Message,
        ctx,
        content: str,
        lock: asyncio.Lock,
    ) -> None:
        async with lock:
            if self._is_new_session_command(content):
                await self._handle_new_session_command(message, ctx)
                return
            await self._handle_agent_message(message, ctx, content)

    async def _handle_agent_message(self, message: Message, ctx, content: str) -> None:
        logger.info(
            "AgentChatPlugin 调用 Agent: adapter={} content_chars={}",
            message.adapter,
            len(content),
        )
        try:
            timeout_seconds = self._agent_timeout_seconds(ctx)
            logger.info("AgentChatPlugin 准备上下文: id={} timeout={}s", message.id, timeout_seconds)
            if timeout_seconds > 0:
                with anyio.fail_after(timeout_seconds):
                    result = await self._run_agent(message, ctx, content)
            else:
                result = await self._run_agent(message, ctx, content)
        except TimeoutError:
            logger.warning("AgentChatPlugin Agent 超时: id={} timeout={}s", message.id, timeout_seconds)
            await self._send_error_reply(message, ctx, "Agent 处理超时，请稍后重试。")
            return
        except Exception as exc:
            logger.warning("AgentChatPlugin Agent 失败: id={} error={}", message.id, exc)
            await self._send_error_reply(message, ctx, f"Agent 处理失败：{exc}")
            return
        logger.info("AgentChatPlugin Agent 完成: id={} task_id={}", message.id, getattr(result, "task_id", ""))
        if getattr(result, "suppress_channel_reply", False):
            logger.info(
                "AgentChatPlugin 跳过自动回发: id={} task_id={} reason=explicit_channel_send",
                message.id,
                getattr(result, "task_id", ""),
            )
            return
        output = (getattr(result, "output", "") or "").strip()
        if not output:
            output = "Agent 没有生成有效回复，请换一种说法再试。"
        output = self._address_qq_sender(message, output)
        await ctx.send_reply(
            Reply(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                type="markdown" if message.adapter == "telegram" else "text",
                content=output,
                **self._reply_reference(message),
            )
        )

    def _on_task_done(self, task: asyncio.Task) -> None:
        conversation_key = self._task_conversations.pop(task, None)
        self._tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                logger.error(
                    "AgentChatPlugin 后台任务异常: task={} error={}",
                    task.get_name(),
                    error,
                )
        if conversation_key is None:
            return
        if conversation_key in self._task_conversations.values():
            return
        lock = self._conversation_locks.get(conversation_key)
        if lock is not None and not lock.locked():
            self._conversation_locks.pop(conversation_key, None)

    @staticmethod
    def _conversation_key(message: Message) -> str:
        return f"{message.platform}:{message.adapter}:{message.conversation_id}"

    async def _run_agent(self, message: Message, ctx, content: str):
        if self._should_use_xbot_context(ctx):
            summaries, history = await self._conversation_context(message, ctx)
        else:
            summaries, history = "", ""
        tool_permission = self._tool_permission_profile(message, ctx)
        agent_input = self._build_agent_input(message, content, history, summaries, tool_permission)
        conversation_overrides = await self._conversation_agent_overrides(message, ctx)
        persona = conversation_overrides.get("persona_prompt", "")
        logger.info(
            "AgentChatPlugin 上下文完成: id={} input_chars={} history_chars={} summary_chars={} persona_chars={}",
            message.id,
            len(agent_input),
            len(history),
            len(summaries),
            len(persona),
        )
        source = self._source_for_message(message, ctx)
        attachments = self._llm_attachments(message)
        kwargs = {"source": source}
        if self._agent_accepts_attachments(ctx.agent):
            kwargs["attachments"] = attachments
        if self._agent_accepts_channel_context(ctx.agent):
            channel_context = self._channel_context(message, ctx)
            channel_context.update(conversation_overrides)
            kwargs["channel_context"] = channel_context
        return await ctx.agent.run_task(agent_input, **kwargs)

    async def _conversation_agent_overrides(self, message: Message, ctx) -> dict[str, str]:
        if message.platform != "wechat" or message.raw.get("scope") not in {"group", "private"}:
            return {}
        conversations = getattr(ctx, "conversations", None)
        if conversations is None:
            return {}
        conversation_id = message.conversation_id
        scope = message.raw["scope"]
        normalized_id = (
            conversation_id
            if ":" in conversation_id
            else f"{message.platform}:{message.adapter}:{scope}:{conversation_id}"
        )
        try:
            conversation = await conversations.get_conversation(normalized_id)
        except Exception as exc:
            logger.warning(
                "AgentChatPlugin 读取会话人设失败: conversation={} error={}",
                normalized_id,
                exc,
            )
            return {}
        if not conversation:
            return {}
        overrides: dict[str, str] = {}
        if conversation.agent_persona_enabled:
            prompt = str(conversation.agent_persona_prompt or "").strip()[:8000]
            if prompt:
                overrides["persona_prompt"] = prompt
        model = str(getattr(conversation, "agent_model", None) or "").strip()[:256]
        if model:
            overrides["conversation_model"] = model
        return overrides

    def _channel_context(self, message: Message, ctx) -> dict:
        profile = self._tool_permission_profile(message, ctx)
        # Resolve media policy from the message's adapter.  A WeChat turn must
        # never inherit QQ media roots (and vice versa).
        config = self._adapter_config(ctx, message.adapter)
        media_roots = []
        if profile == "guest":
            # Guests may only resend an attachment that was normalized for the
            # current message.  Do not inherit member workspace/media roots.
            attachments = message.raw.get("attachments") if isinstance(message.raw, dict) else None
            if isinstance(attachments, list):
                media_roots.extend(
                    str(item.get("local_path"))
                    for item in attachments
                    if isinstance(item, dict) and item.get("local_path")
                )
        elif config is not None:
            media_roots.append(str(getattr(config, "media_dir", "data/qq/media")))
            media_roots.extend(str(item) for item in getattr(config, "media_allowed_roots", []) or [])
            settings = getattr(ctx, "settings", None)
            member_policy = getattr(getattr(settings, "agent", None), "member_policy", None)
            if member_policy is not None:
                media_roots.extend(str(item) for item in getattr(member_policy, "workspace_roots", []) or [])
        adapters = getattr(ctx, "adapters", None)
        channel_adapter = (
            adapters.get(message.adapter)
            if adapters is not None and hasattr(adapters, "get")
            else None
        )
        return {
            "conversation_id": message.conversation_id,
            "message_id": None if message.raw.get("qq_event_type") == "INTERACTION_CREATE" else message.id,
            "event_id": message.raw.get("event_id") if message.raw.get("qq_event_type") == "INTERACTION_CREATE" else None,
            "scope": str(message.raw.get("scope") or "private"),
            "sender_id": str(message.sender_id or ""),
            "sender_name": str(message.sender_name or ""),
            "profile": profile,
            "media_roots": media_roots,
            "recall": getattr(channel_adapter, "recall", None) if message.adapter == "qq" else None,
            "react": getattr(channel_adapter, "react", None) if message.adapter == "qq" else None,
        }

    async def _handle_new_session_command(self, message: Message, ctx) -> None:
        source = self._source_for_message(message, ctx)
        try:
            result = ctx.agent.clear_session_history(source)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            logger.warning("AgentChatPlugin 新会话重置失败: id={} error={}", message.id, exc)
            await self._send_error_reply(message, ctx, f"新会话重置失败：{exc}")
            return
        session_id = result.get("session_id") if isinstance(result, dict) else ""
        logger.info(
            "AgentChatPlugin 已重置当前会话: id={} source={} session_id={}",
            message.id,
            source,
            session_id,
        )
        await ctx.send_reply(
            Reply(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                type="text",
                content=self._address_qq_sender(
                    message, "已开启新会话，会重新读取当前人格配置。"
                ),
                **self._reply_reference(message),
            )
        )

    def _is_new_session_command(self, content: str) -> bool:
        command = content.strip().split(maxsplit=1)[0].lower()
        return command in {"/new", "/reset"}

    def _source_for_message(self, message: Message, ctx=None) -> str:
        source = f"channel:{message.platform}:{message.adapter}:{message.conversation_id}"
        profile = self._tool_permission_profile(message, ctx)
        if profile in {"member", "guest"}:
            return f"{source}:{profile}"
        return source

    def _should_use_xbot_context(self, ctx) -> bool:
        settings = getattr(ctx, "settings", None)
        agent = getattr(settings, "agent", None)
        return not (agent is not None and getattr(agent, "uses_hermes_runtime", False))

    def _agent_timeout_seconds(self, ctx) -> int:
        settings = getattr(ctx, "settings", None)
        runtime_timeout = getattr(
            getattr(getattr(settings, "runtime", None), "timeout", None),
            "agent_task_seconds",
            180,
        )
        return int(runtime_timeout)

    async def _send_error_reply(self, message: Message, ctx, content: str) -> None:
        if not ctx.send_reply:
            return
        await ctx.send_reply(
            Reply(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                type="text",
                content=self._address_qq_sender(message, content),
                **self._reply_reference(message),
            )
        )

    def _reply_reference(self, message: Message) -> dict[str, object]:
        if message.raw.get("qq_event_type") == "INTERACTION_CREATE":
            return {"metadata": {"event_id": message.raw.get("event_id")}}
        return {"quote_message_id": message.id}

    def _should_handle(self, message: Message) -> bool:
        scope = message.raw.get("scope")
        qq_event_type = message.raw.get("qq_event_type")
        if qq_event_type == "INTERACTION_CREATE":
            try:
                interaction_type = int(message.raw.get("interaction_type") or 0)
            except (TypeError, ValueError):
                interaction_type = 0
            return interaction_type in {11, 12}
        if qq_event_type in {
            "MESSAGE_REACTION_ADD", "MESSAGE_REACTION_REMOVE", "PUBLIC_GUILD_MESSAGES",
            "AUDIT_PASS", "AUDIT_FAIL", "GUILD_CREATE",
        } or message.raw.get("agent_route") is False:
            return False
        if scope == "private":
            return True
        if scope == "group":
            return bool(message.raw.get("mentions_bot"))
        if scope == "channel":
            return bool(message.raw.get("mentions_bot")) or message.raw.get("qq_event_type") == "MESSAGE_CREATE"
        return message.platform == "web"

    def _should_defer_unquoted_wechat_media(self, message: Message) -> bool:
        return (
            message.platform == "wechat"
            and message.raw.get("scope") == "private"
            and message.type in {"image", "file", "voice", "video"}
            and not isinstance(message.raw.get("quote"), dict)
        )

    def _clean_content(self, message: Message) -> str:
        content = message.content or ""
        telegram_command, telegram_argument = self._telegram_group_command(message)
        if telegram_command == "xbot":
            return telegram_argument
        if telegram_command in {"new", "reset"}:
            return f"/{telegram_command}"
        for candidate in (
            message.raw.get("bot_nickname"),
            message.raw.get("bot_wxid"),
            message.raw.get("bot_id") if message.adapter == "qq" else None,
            message.raw.get("bot_username") if message.adapter == "telegram" else None,
        ):
            if candidate:
                content = (
                    content.replace(f"@{candidate}", "")
                    .replace(f"<@{candidate}>", "")
                    .replace(str(candidate), "")
                )
        return content.strip()

    @staticmethod
    def _telegram_group_command(message: Message) -> tuple[str, str]:
        if message.adapter != "telegram" or message.raw.get("scope") != "group":
            return "", ""
        match = re.match(
            r"^\s*/(xbot|new|reset|status|help)(?:@[A-Za-z0-9_]+)?(?:\s+(.*))?$",
            str(message.content or ""),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return "", ""
        return match.group(1).lower(), str(match.group(2) or "").strip()

    async def _send_telegram_group_command_reply(
        self,
        message: Message,
        ctx,
        command: str,
    ) -> None:
        if command == "status":
            content = "*xbot 已连接本群*\n\n发送 `/xbot 内容`、@机器人，或回复机器人消息即可对话。"
        else:
            content = (
                "*小X · 群聊助手*\n\n"
                "• `/xbot 内容` — 和小X对话\n"
                "• `/new` — 开启本群新会话\n"
                "• `/status` — 查看连接状态\n"
                "• 也可以直接 @机器人 或回复机器人消息"
            )
        await ctx.send_reply(
            Reply(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                type="markdown",
                content=content,
                **self._reply_reference(message),
            )
        )

    async def _conversation_context(self, message: Message, ctx) -> tuple[str, str]:
        if not getattr(ctx, "conversations", None):
            return "", ""
        scope = message.raw.get("scope") or "private"
        conversation_id = message.conversation_id
        normalized_id = (
            conversation_id
            if ":" in conversation_id
            else f"{message.platform}:{message.adapter}:{scope}:{conversation_id}"
        )
        try:
            context = await ctx.conversations.get_context(normalized_id, limit=0)
        except Exception as exc:
            logger.warning("AgentChatPlugin 读取会话上下文失败: id={} error={}", message.id, exc)
            return "", ""
        if not context:
            return "", ""
        summary_lines = [
            (
                f"- range={summary.from_message_id}->{summary.to_message_id} created_at={summary.created_at.isoformat()} summary={summary.summary}"
            )
            for summary in context.summaries
        ]
        message_lines = []
        for item in context.messages:
            identity = self._message_identity_fields(item)
            sender = "current_sender" if item.sender_id == message.sender_id else item.sender_id
            message_lines.append(
                f"- id={item.id} sender={sender} sender_wxid={identity['sender_wxid']} "
                f"sender_name={identity['sender_name'] or ''} scope={identity['scope']} "
                f"conversation_wxid={identity['conversation_wxid']} "
                f"group_wxid={identity['group_wxid']} private_wxid={identity['private_wxid']} "
                f"group_member_wxid={identity['group_member_wxid']} type={item.type} "
                f"content={item.content or ''}"
            )
        return "\n".join(summary_lines), "\n".join(message_lines)

    def _message_identity_fields(self, message: Message) -> dict[str, str]:
        scope = str(message.raw.get("scope") or "unknown")
        conversation_id = message.conversation_id
        sender_id = message.sender_id
        return {
            "scope": scope,
            "sender_wxid": str(message.raw.get("sender_wxid") or sender_id),
            "sender_name": str(message.raw.get("sender_name") or message.sender_name or ""),
            "conversation_wxid": str(message.raw.get("conversation_wxid") or conversation_id),
            "private_wxid": str(
                message.raw.get("private_wxid") or (sender_id if scope == "private" else "")
            ),
            "group_wxid": str(
                message.raw.get("group_wxid") or (conversation_id if scope == "group" else "")
            ),
            "group_member_wxid": str(
                message.raw.get("group_member_wxid") or (sender_id if scope == "group" else "")
            ),
        }

    def _build_agent_input(
        self,
        message: Message,
        content: str,
        history: str = "",
        summaries: str = "",
        tool_permission: str = "allowed",
    ) -> str:
        scope = message.raw.get("scope") or "unknown"
        conversation_id = message.conversation_id
        sender_id = message.sender_id
        identity = self._message_identity_fields(message)
        reply_target = conversation_id
        private_wxid = identity["private_wxid"]
        group_wxid = identity["group_wxid"]
        group_member_wxid = identity["group_member_wxid"]
        return (
            "Channel message received.\n"
            f"platform: {message.platform}\n"
            f"adapter: {message.adapter}\n"
            f"scope: {scope}\n"
            f"conversation_id: {conversation_id}\n"
            f"sender_id: {sender_id}\n"
            f"sender_wxid: {identity['sender_wxid']}\n"
            f"sender_name: {identity['sender_name']}\n"
            f"conversation_wxid: {identity['conversation_wxid']}\n"
            f"reply_target_wxid: {reply_target}\n"
            f"private_wxid: {private_wxid}\n"
            f"group_wxid: {group_wxid}\n"
            f"group_member_wxid: {group_member_wxid}\n"
            f"qq_sender_openid: {message.raw.get('sender_openid') or ''}\n"
            f"qq_conversation_openid: {message.raw.get('conversation_openid') or ''}\n"
            f"qq_channel_id: {message.raw.get('channel_id') or ''}\n"
            f"qq_guild_id: {message.raw.get('guild_id') or ''}\n"
            f"message_id: {message.id}\n"
            f"mentions_bot: {bool(message.raw.get('mentions_bot'))}\n"
            f"tool_permission: {tool_permission}\n"
            f"telegram_reply_style: {'Use concise Telegram Markdown: bold text uses one asterisk on each side, lists use short bullet lines; avoid hash headings, double-asterisk bold, and Markdown tables.' if message.adapter == 'telegram' else 'not applicable'}\n"
            "memory_scope: Hermes owns long-term memory, session history, context compression, and task trajectory. "
            "Only the current triggered message, its attachments/quote, and the assistant reply should affect memory. "
            "Do not infer durable memory from unrelated channel traffic.\n"
            f"current_trigger_message:\n{content}\n"
            f"xbot_conversation_summaries:\n{summaries or '- disabled; Hermes session memory is authoritative'}\n"
            f"xbot_recent_conversation_messages:\n{history or '- disabled; Hermes session memory is authoritative'}\n"
            f"message_attachments:\n{self._attachments_block(message) or '- none'}\n"
            f"quoted_message:\n{self._quote_block(message) or '- none'}\n"
            f"content: {content}\n"
            "When sending WeChat content proactively, prefer wechat_send_text/image/file/voice/video/link/music_card; the runtime routes to the current adapter automatically.\n"
            "Do not call adapter-specific WeChat media skills directly unless the generic wechat_send_* tool is unavailable.\n"
            "When using older WeChat sending skills/tools, use reply_target_wxid as --to.\n"
            "For private chat, reply_target_wxid equals private_wxid.\n"
            "For group chat, reply_target_wxid equals group_wxid, and group_member_wxid is the sender in the group.\n"
            "Do not ask the user for wxid/chatroom id when these fields are already present.\n"
            "When this is a QQ conversation, use qq_send_text/markdown/image/file/voice/video/stream/input_notify/qq_recall/qq_react. "
            "QQ guest/member tools default to the current conversation; do not invent or request arbitrary OpenIDs. "
            "Use the explicit message_id/event_id carried in channel context for passive replies; never parse IDs from prompt text. "
            "QQ channel conversations use qq:channel:{channel_id}; channel DMs use qq:dms:{guild_id}. "
            "QQ media URLs must be public http(s), local paths must stay in configured media/workspace roots, and channel file uploads are unsupported.\n"
            "When any user asks to create a Markdown, Word, Excel, PowerPoint, or PDF file, call artifact_create with format md/docx/xlsx/pptx/pdf. It writes only to the current user's isolated output directory and sends the file automatically by default. Do not use write_file or terminal to create these deliverables, do not write under /app or a channel media directory, and do not send the same file again when artifact_create returns sent=true. "
            "For a Weiban account read-only query, use weiban_query_account with exactly one of the user's email or permanent invite code; never pass both fields and omit the unused field entirely; do not say that an administrator must enable query access. "
            "For public questions about Weiban or Lyvu features, setup, community commands, memory, images, voice, quotas, or troubleshooting, call weiban_search_knowledge before answering. "
            "Binding, check-in, points, games, rankings, and Token exchange are handled by the deterministic community plugin; tell the user the exact community command instead of claiming that guest permission blocks it. "
            "Plan changes, token quota changes, expiry extensions, and manual character-image grants are write operations: only admin may perform them; guest and member must refuse them. Before a manual image grant, show the exact user, amount, and reason and require explicit confirmation; reuse the same idempotency key on retry. "
            "Tool permission profiles: admin can use the full Hermes toolset; member can use public web search/extraction, can read files attached to the current or quoted message, and can use file/terminal tools inside the configured member workspace roots; channel guests can use the current channel's send tools, weiban_query_account, weiban_search_knowledge, and artifact_create. "
            "For member requests about recent news, current events, public websites, public documentation, or public package/project information, use web_search/web_extract normally. "
            "Members must not inspect unrelated local files, scan LAN/private network targets, access localhost/internal IPs/private IPs/.local hosts, manage processes, create cron jobs, delegate tasks, or execute arbitrary Python. "
            "For a member request about a current or quoted attachment, read its local_path directly and do not ask for administrator authorization. Keep all other reads/writes under the authorized workspace roots. If a request needs unrelated local host access, private network access, LAN discovery, or broader filesystem access, explain that it is unavailable.\n"
            "If the content asks about real project files, directories, plugins, skills, config, or runtime state, use tools before answering.\n"
            "Reply to the user in Chinese unless the user clearly asks for another language."
        )

    @staticmethod
    def _address_qq_sender(message: Message, content: str) -> str:
        if (
            message.adapter != "qq"
            or str(message.raw.get("scope") or "") != "group"
            or message.raw.get("qq_event_type") != "INTERACTION_CREATE"
        ):
            return content
        nickname = str(message.sender_name or "").strip()
        return f"@{nickname} {content}" if nickname else content

    def _is_restricted_channel_user(self, message: Message, ctx=None) -> bool:
        return self._tool_permission_profile(message, ctx) != "admin"

    def _tool_permission_profile(self, message: Message, ctx=None) -> str:
        if message.adapter == "wechat869":
            return self._configured_channel_profile(
                message,
                ctx,
                adapter_name="wechat869",
                admin_field="admin_wxids",
                member_field="member_wxids",
            )
        if message.adapter == "qq":
            return self._configured_channel_profile(
                message,
                ctx,
                adapter_name="qq",
                admin_field="admin_openids",
                member_field="member_openids",
            )
        if message.adapter == "telegram":
            return self._configured_channel_profile(
                message,
                ctx,
                adapter_name="telegram",
                admin_field="admin_user_ids",
                member_field="member_user_ids",
            )
        return "admin"

    def _configured_channel_profile(
        self,
        message: Message,
        ctx,
        *,
        adapter_name: str,
        admin_field: str,
        member_field: str,
    ) -> str:
        config = self._adapter_config(ctx, adapter_name)
        admin_ids = self._configured_ids(config, admin_field)
        candidates = {
            str(message.sender_id or "").strip(),
            str(message.raw.get("sender_wxid") or "").strip(),
            str(message.raw.get("group_member_wxid") or "").strip(),
            str(message.raw.get("private_wxid") or "").strip(),
            str(message.raw.get("sender_openid") or "").strip(),
            str(message.raw.get("member_openid") or "").strip(),
            str(message.raw.get("user_openid") or "").strip(),
            str(message.raw.get("user_id") or "").strip(),
        }
        candidates.discard("")
        if admin_ids and candidates.intersection(admin_ids):
            return "admin"
        member_ids = self._configured_ids(config, member_field)
        if member_ids:
            return "member" if candidates.intersection(member_ids) else "guest"
        profile = str(getattr(config, "default_profile", "guest") or "guest").strip().lower()
        return profile if profile in {"member", "guest"} else "guest"

    def _adapter_config(self, ctx, adapter_name: str):
        settings = getattr(ctx, "settings", None)
        adapters = getattr(settings, "adapters", None)
        return getattr(adapters, adapter_name, None)

    def _configured_ids(self, config, field: str) -> set[str]:
        configured = getattr(config, field, None)
        if configured is None:
            return set()
        return {str(item).strip() for item in configured if str(item).strip()}

    def _wechat869_admin_wxids(self, ctx=None) -> set[str]:
        return self._configured_ids(self._adapter_config(ctx, "wechat869"), "admin_wxids")

    def _wechat869_member_wxids(self, ctx=None) -> set[str]:
        return self._configured_ids(self._adapter_config(ctx, "wechat869"), "member_wxids")

    def _wechat869_default_profile(self, ctx=None) -> str:
        settings = getattr(ctx, "settings", None)
        adapters = getattr(settings, "adapters", None)
        wechat869 = getattr(adapters, "wechat869", None)
        profile = str(getattr(wechat869, "default_profile", "member") or "member").strip().lower()
        return profile if profile in {"member", "guest"} else "member"

    def _attachments_block(self, message: Message) -> str:
        attachments = message.raw.get("attachments") if isinstance(message.raw, dict) else None
        if not isinstance(attachments, list) or not attachments:
            return ""
        return "\n".join(self._attachment_line(item) for item in attachments if isinstance(item, dict))

    def _quote_block(self, message: Message) -> str:
        quote = message.raw.get("quote") if isinstance(message.raw, dict) else None
        if not isinstance(quote, dict):
            return ""
        lines = [
            f"message_id: {quote.get('message_id') or ''}",
            f"sender_wxid: {quote.get('sender_wxid') or ''}",
            f"sender_name: {quote.get('sender_name') or ''}",
            f"type: {quote.get('msg_type') or ''}",
            f"content: {quote.get('content') or ''}",
        ]
        attachments = quote.get("attachments") if isinstance(quote.get("attachments"), list) else []
        if attachments:
            lines.append("attachments:")
            lines.extend(self._attachment_line(item) for item in attachments if isinstance(item, dict))
        return "\n".join(lines)

    def _llm_attachments(self, message: Message) -> list[dict]:
        attachments: list[dict] = []
        raw_attachments = message.raw.get("attachments") if isinstance(message.raw, dict) else None
        if isinstance(raw_attachments, list):
            attachments.extend(item for item in raw_attachments if isinstance(item, dict))
        quote = message.raw.get("quote") if isinstance(message.raw, dict) else None
        quote_attachments = quote.get("attachments") if isinstance(quote, dict) else None
        if isinstance(quote_attachments, list):
            attachments.extend(item for item in quote_attachments if isinstance(item, dict))
        return attachments

    def _agent_accepts_attachments(self, agent) -> bool:
        try:
            signature = inspect.signature(agent.run_task)
        except (TypeError, ValueError):
            return False
        return "attachments" in signature.parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )

    def _agent_accepts_channel_context(self, agent) -> bool:
        try:
            signature = inspect.signature(agent.run_task)
        except (TypeError, ValueError):
            return False
        return "channel_context" in signature.parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )

    def _attachment_line(self, attachment: dict) -> str:
        fields = [
            f"- kind={attachment.get('kind') or ''}",
            f"filename={attachment.get('filename') or ''}",
            f"mime={attachment.get('mime') or ''}",
            f"size={attachment.get('size') or 0}",
            f"status={attachment.get('download_status') or ''}",
        ]
        local_path = attachment.get("local_path")
        if local_path:
            fields.append(f"local_path={local_path}")
        sha256 = attachment.get("sha256")
        if sha256:
            fields.append(f"sha256={sha256}")
        asr_text = attachment.get("asr_refer_text")
        if asr_text is None and isinstance(attachment.get("metadata"), dict):
            asr_text = attachment["metadata"].get("asr_refer_text")
        if asr_text:
            fields.append(f"asr_refer_text={asr_text}")
        return " ".join(fields)
