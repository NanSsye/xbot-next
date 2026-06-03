from __future__ import annotations

import inspect

import anyio
from loguru import logger

from xbot.messaging.models import Message, Reply
from xbot.plugins.base import PluginBase


class AgentChatPlugin(PluginBase):
    name = "agent_chat"
    version = "0.1.0"

    async def on_message(self, message: Message, ctx):
        if not ctx.agent or not ctx.send_reply:
            logger.warning("AgentChatPlugin 未配置 agent 或 send_reply，跳过消息: {}", message.id)
            return False
        if message.type not in {"text", "image", "file", "event"} or not message.content:
            logger.info("AgentChatPlugin 跳过不支持或空消息: id={} type={}", message.id, message.type)
            return False
        if self._should_defer_unquoted_ilink_media(message):
            logger.info(
                "AgentChatPlugin 跳过 iLink 未引用媒体消息: id={} type={}",
                message.id,
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

        content = self._clean_content(message)
        if not content:
            logger.info("AgentChatPlugin 清理后内容为空，跳过消息: {}", message.id)
            return False
        if self._is_new_session_command(content):
            await self._handle_new_session_command(message, ctx)
            return True

        logger.info(
            "AgentChatPlugin 调用 Agent: id={} conversation={} sender={} content={}",
            message.id,
            message.conversation_id,
            message.sender_id,
            content,
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
            return True
        except Exception as exc:
            logger.warning("AgentChatPlugin Agent 失败: id={} error={}", message.id, exc)
            await self._send_error_reply(message, ctx, f"Agent 处理失败：{exc}")
            return True
        logger.info("AgentChatPlugin Agent 完成: id={} task_id={}", message.id, getattr(result, "task_id", ""))
        if getattr(result, "suppress_channel_reply", False):
            logger.info(
                "AgentChatPlugin 跳过自动回发: id={} task_id={} reason=explicit_wechat_send",
                message.id,
                getattr(result, "task_id", ""),
            )
            return True
        output = (getattr(result, "output", "") or "").strip()
        if not output:
            output = "Agent 没有生成有效回复，请换一种说法再试。"
        await ctx.send_reply(
            Reply(
                platform=message.platform,
                adapter=message.adapter,
                conversation_id=message.conversation_id,
                type="text",
                content=output,
                quote_message_id=message.id,
            )
        )
        return True

    async def _run_agent(self, message: Message, ctx, content: str):
        if self._should_use_xbot_context(ctx):
            summaries, history = await self._conversation_context(message, ctx)
        else:
            summaries, history = "", ""
        tool_permission = self._tool_permission_profile(message, ctx)
        agent_input = self._build_agent_input(message, content, history, summaries, tool_permission)
        logger.info(
            "AgentChatPlugin 上下文完成: id={} input_chars={} history_chars={} summary_chars={}",
            message.id,
            len(agent_input),
            len(history),
            len(summaries),
        )
        source = self._source_for_message(message, ctx)
        attachments = self._llm_attachments(message)
        if self._agent_accepts_attachments(ctx.agent):
            return await ctx.agent.run_task(agent_input, source=source, attachments=attachments)
        return await ctx.agent.run_task(agent_input, source=source)

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
                content="已开启新会话，会重新读取当前人格配置。",
                quote_message_id=message.id,
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
        if agent is not None and getattr(agent, "uses_hermes_runtime", False):
            return False
        return True

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
                content=content,
                quote_message_id=message.id,
            )
        )

    def _should_handle(self, message: Message) -> bool:
        scope = message.raw.get("scope")
        if scope == "private":
            return True
        if scope == "group":
            return bool(message.raw.get("mentions_bot"))
        if message.platform == "web":
            return True
        return False

    def _should_defer_unquoted_ilink_media(self, message: Message) -> bool:
        return (
            message.adapter == "wechat_ilink"
            and message.type in {"image", "file"}
            and not isinstance(message.raw.get("quote"), dict)
        )

    def _clean_content(self, message: Message) -> str:
        content = message.content or ""
        for candidate in (
            message.raw.get("bot_nickname"),
            message.raw.get("bot_wxid"),
        ):
            if candidate:
                content = content.replace(f"@{candidate}", "").replace(str(candidate), "")
        return content.strip()

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
        summary_lines = []
        for summary in context.summaries:
            summary_lines.append(
                f"- range={summary.from_message_id}->{summary.to_message_id} created_at={summary.created_at.isoformat()} summary={summary.summary}"
            )
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
            f"message_id: {message.id}\n"
            f"mentions_bot: {bool(message.raw.get('mentions_bot'))}\n"
            f"tool_permission: {tool_permission}\n"
            "memory_scope: Hermes owns long-term memory, session history, context compression, and task trajectory. "
            "Only the current triggered message, its attachments/quote, and the assistant reply should affect memory. "
            "Do not infer durable memory from unrelated channel traffic.\n"
            f"current_trigger_message:\n{content}\n"
            f"xbot_conversation_summaries:\n{summaries or '- disabled; Hermes session memory is authoritative'}\n"
            f"xbot_recent_conversation_messages:\n{history or '- disabled; Hermes session memory is authoritative'}\n"
            f"message_attachments:\n{self._attachments_block(message) or '- none'}\n"
            f"quoted_message:\n{self._quote_block(message) or '- none'}\n"
            f"content: {content}\n"
            "When sending WeChat text/image/file proactively, prefer wechat.send_text, wechat.send_image, or wechat.send_file; the runtime routes to the current adapter automatically.\n"
            "Do not call adapter-specific WeChat media skills directly unless the generic wechat.send_* tool is unavailable.\n"
            "When using older WeChat sending skills/tools, use reply_target_wxid as --to.\n"
            "For private chat, reply_target_wxid equals private_wxid.\n"
            "For group chat, reply_target_wxid equals group_wxid, and group_member_wxid is the sender in the group.\n"
            "Do not ask the user for wxid/chatroom id when these fields are already present.\n"
            "Tool permission profiles: admin can use the full Hermes toolset; member can use tools only inside the configured member workspace roots and must not inspect unrelated local files, scan LAN/private network targets, access localhost/internal IPs, manage processes, create cron jobs, delegate tasks, execute arbitrary Python, or send proactive messages; guest must not call tools. "
            "If a member task needs files, keep all reads/writes under the authorized workspace roots. If a request needs broader host/network access, explain that it requires an 869 administrator.\n"
            "If the content asks about real project files, directories, plugins, skills, config, or runtime state, use tools before answering.\n"
            "Reply to the user in Chinese unless the user clearly asks for another language."
        )

    def _is_restricted_channel_user(self, message: Message, ctx=None) -> bool:
        return self._tool_permission_profile(message, ctx) != "admin"

    def _tool_permission_profile(self, message: Message, ctx=None) -> str:
        if message.adapter != "wechat869":
            return "admin"
        admin_wxids = self._wechat869_admin_wxids(ctx)
        candidates = {
            str(message.sender_id or "").strip(),
            str(message.raw.get("sender_wxid") or "").strip(),
            str(message.raw.get("group_member_wxid") or "").strip(),
            str(message.raw.get("private_wxid") or "").strip(),
        }
        candidates.discard("")
        if admin_wxids and candidates.intersection(admin_wxids):
            return "admin"
        member_wxids = self._wechat869_member_wxids(ctx)
        if member_wxids:
            return "member" if candidates.intersection(member_wxids) else "guest"
        return self._wechat869_default_profile(ctx)

    def _wechat869_admin_wxids(self, ctx=None) -> set[str]:
        settings = getattr(ctx, "settings", None)
        adapters = getattr(settings, "adapters", None)
        wechat869 = getattr(adapters, "wechat869", None)
        configured = getattr(wechat869, "admin_wxids", None)
        if configured is None:
            return set()
        return {str(item).strip() for item in configured if str(item).strip()}

    def _wechat869_member_wxids(self, ctx=None) -> set[str]:
        settings = getattr(ctx, "settings", None)
        adapters = getattr(settings, "adapters", None)
        wechat869 = getattr(adapters, "wechat869", None)
        configured = getattr(wechat869, "member_wxids", None)
        if configured is None:
            return set()
        return {str(item).strip() for item in configured if str(item).strip()}

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
        return " ".join(fields)
