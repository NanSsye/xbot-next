from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid4

import anyio
import httpx
from pydantic import BaseModel, Field

from xbot.agent.background import BackgroundTaskManager
from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.cache import TTLCache
from xbot.agent.compression import MemoryCompressor
from xbot.agent.llm import LLMContentBlock, LLMMessage, LLMResponse, LLMToolCall, create_llm_provider
from xbot.agent.memory import MemoryStore
from xbot.agent.mcp import MCPClientManager
from xbot.agent.planner import AgentPlanner
from xbot.agent.policy import PolicyEngine
from xbot.agent.scheduler import ScheduledJobManager
from xbot.agent.tool_executor import ToolExecutor
from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.agent.tools import register_builtin_tools
from xbot.agent.tools.browser_provider import register_browser_tools
from xbot.agent.tools.cache_policy import ToolCachePolicy
from xbot.agent.tools.environment_provider import register_environment_tools
from xbot.agent.tools.fallback_policy import ToolError, ToolFallbackPolicy
from xbot.agent.tools.git_provider import register_git_tools
from xbot.agent.tools.plugin_provider import register_plugin_tools
from xbot.agent.tools.schedule_provider import register_schedule_tools
from xbot.agent.tools.skill_provider import SkillToolProvider
from xbot.agent.tools.task_provider import register_task_tools
from xbot.agent.tools.toolsets import source_context, toolsets_for_source
from xbot.agent.wiki import WikiStore
from xbot.agent.workspace import Workspace
from xbot.core.config import AgentConfig
from xbot.core.exceptions import PolicyDeniedError, XBotError
from xbot.core.logging import logger
from xbot.messaging.models import Reply


class AgentResult(BaseModel):
    task_id: str
    source: str
    status: str
    output: str
    suppress_channel_reply: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ToolCallResult(BaseModel):
    task_id: str
    tool: str
    status: str
    output: object | None = None
    error: str | None = None
    error_type: str | None = None
    fallback: dict | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentRuntimeEvent(BaseModel):
    task_id: str
    type: str
    content: object
    created_at: datetime = Field(default_factory=datetime.utcnow)


AgentEventSubscriber = Callable[[AgentRuntimeEvent], Awaitable[None] | None]


class AgentRuntime:
    def __init__(
        self,
        config: AgentConfig,
        plugins,
        skills,
        repository_provider=None,
        llm_provider=None,
    ) -> None:
        self.config = config
        self.plugins = plugins
        self.skills = skills
        self.repository_provider = repository_provider
        self.policy = PolicyEngine(config)
        self.workspace = Workspace(config.workspace_root, self.policy)
        self.tools = ToolRegistry()
        self.executor = ToolExecutor(self.tools)
        self.mcp = MCPClientManager(config.mcp, self.tools)
        self.background = BackgroundTaskManager(repository_provider=repository_provider)
        self.scheduler = ScheduledJobManager(
            background=self.background,
            run_agent=self._run_agent_for_task,
            repository_provider=repository_provider,
            timezone_name=config.timezone,
            tick_seconds=config.schedule.tick_seconds,
            max_due_per_tick=config.schedule.max_due_per_tick,
        )
        self.memory = MemoryStore(
            config.memory.directory,
            memory_char_limit=config.memory.memory_char_limit,
            user_char_limit=config.memory.user_char_limit,
        )
        self.wiki = WikiStore(
            config.wiki.directory,
            default_wiki=config.wiki.default_wiki,
            query_max_chars=config.wiki.query_max_chars,
        ) if config.wiki.enabled else None
        self.compressor = MemoryCompressor()
        self.planner = AgentPlanner()
        self.llm = llm_provider or create_llm_provider(config.llm)
        self._tool_result_cache = TTLCache(config.cache.tool_result_ttl_seconds)
        self.cache_policy = ToolCachePolicy(config, self.workspace, self.policy, self.skills)
        self.fallback_policy = ToolFallbackPolicy(policy=self.policy)
        self.skill_tools = SkillToolProvider(workspace=self.workspace, skills=self.skills)
        self._static_prompt_cache: tuple[tuple[object, ...], str] | None = None
        self._skill_prompt_cache: tuple[int, str] | None = None
        self._event_subscribers: set[AgentEventSubscriber] = set()
        self._turns_since_memory_review = 0
        self._completed_turns = 0
        self._turns_since_curator = 0
        self._session_histories: dict[str, list[LLMMessage]] = {}
        self._session_summaries: dict[str, str] = {}
        self._suppress_channel_reply_task_ids: set[str] = set()
        self.background.subscribe(self._on_background_task_completed)
        register_builtin_tools(
            self.tools,
            workspace=self.workspace,
            skills=self.skills,
            memory=self.memory,
            wiki=self.wiki,
            run_skill=self.skill_tools.run_skill,
        )
        register_environment_tools(self.tools, workspace=self.workspace)
        register_browser_tools(self.tools, workspace=self.workspace)
        register_git_tools(self.tools, workspace=self.workspace)
        register_task_tools(
            self.tools,
            background=self.background,
            execute_tool=self._execute_tool_for_task,
            run_agent=self._run_agent_for_task,
        )
        register_schedule_tools(self.tools, scheduler=self.scheduler)
        self._register_wechat_send_tools()

    async def start(self) -> None:
        register_plugin_tools(self.tools, self.plugins)
        self._static_prompt_cache = None
        await self._restore_background_tasks()
        if self.config.schedule.enabled:
            await self.scheduler.start()
        await self.mcp.start()

    async def stop(self) -> None:
        await self.flush_memory(reason="runtime stop")
        await self.scheduler.stop()
        await self.background.stop()
        await self.mcp.stop()

    def attach_reply_sender(self, send_reply) -> None:
        self.background.attach_reply_sender(send_reply)

    def subscribe_events(self, subscriber: AgentEventSubscriber) -> Callable[[], None]:
        self._event_subscribers.add(subscriber)

        def unsubscribe() -> None:
            self._event_subscribers.discard(subscriber)

        return unsubscribe

    async def run_task(
        self,
        input_text: str,
        source: str = "api",
        attachments: list[dict] | None = None,
    ) -> AgentResult:
        task_id = str(uuid4())
        logger.info("Agent 任务开始: task_id={} source={} input_chars={}", task_id, source, len(input_text))
        memory_input_text = self._memory_eligible_input_text(input_text)
        if self.repository_provider:
            logger.info("Agent 任务写入存储开始: task_id={}", task_id)
            async with self.repository_provider() as repo:
                await repo.create_task(task_id, source, input_text)
            await self._add_event(task_id, "task.received", input_text)
            logger.info("Agent 任务写入存储完成: task_id={}", task_id)
        else:
            await self._add_event(task_id, "task.received", input_text)
        logger.info("Agent 任务进入 LLM: task_id={}", task_id)
        output = await self._run_llm(task_id, input_text, source=source, attachments=attachments)
        suppress_channel_reply = task_id in self._suppress_channel_reply_task_ids
        self._suppress_channel_reply_task_ids.discard(task_id)
        result = AgentResult(
            task_id=task_id,
            source=source,
            status="completed",
            output=output,
            suppress_channel_reply=suppress_channel_reply,
        )
        if self.repository_provider:
            logger.info("Agent 任务结果写入存储开始: task_id={}", task_id)
            async with self.repository_provider() as repo:
                await repo.finish_task(result)
            await self._add_event(task_id, "task.completed", result.output)
            logger.info("Agent 任务结果写入存储完成: task_id={}", task_id)
        else:
            await self._add_event(task_id, "task.completed", result.output)
        self._completed_turns += 1
        self._maybe_start_memory_review(
            parent_task_id=task_id,
            input_text=memory_input_text,
            output_text=result.output,
            source=source,
        )
        self._maybe_start_curator()
        return result

    async def flush_memory(self, *, reason: str = "manual") -> dict:
        if not self.config.memory.enabled or not self.config.memory.review_enabled:
            return {"success": True, "skipped": True, "reason": "memory review disabled"}
        if self._completed_turns < int(self.config.memory.flush_min_turns or 0):
            return {"success": True, "skipped": True, "reason": "below flush_min_turns"}
        return await self._run_memory_review(
            parent_task_id=str(uuid4()),
            input_text=f"Memory flush requested: {reason}",
            output_text="Review recent durable facts before context/session boundary.",
            source="memory_flush",
        )

    async def run_curator(self) -> dict:
        if not self.skills or not hasattr(self.skills, "run_curator"):
            return {"success": False, "error": "Skill manager is not available."}
        return await self.skills.run_curator()

    async def generate_curator_report(self, *, use_llm: bool = True) -> dict:
        if not self.skills or not hasattr(self.skills, "build_curator_report"):
            return {"success": False, "error": "Skill manager is not available."}
        llm_proposals: list[dict] = []
        llm_error = ""
        if use_llm and self.config.llm.enabled:
            try:
                response = await self.llm.complete(
                    [
                        LLMMessage(
                            role="system",
                            content=(
                                "You are xbot's skill curator. Analyze agent-owned procedural "
                                "skills and propose maintenance actions. This is dry-run only. "
                                "Never ask to delete skills. Prefer archive, mark_stale, merge, "
                                "pin, or unpin. For merge, choose target as the skill to keep and "
                                "source_skill as the skill to archive. Return JSON only."
                            ),
                        ),
                        LLMMessage(role="user", content=self._curator_report_prompt()),
                    ]
                )
                llm_proposals = self._parse_curator_llm_proposals(response.content)
            except Exception as exc:
                llm_error = str(exc)
        report = self.skills.build_curator_report(llm_proposals=llm_proposals)
        if llm_error:
            report["llm_error"] = llm_error
            self.skills.save_curator_report(report)
        return report

    async def apply_curator_report(
        self,
        *,
        report_id: str = "latest",
        proposal_ids: list[str] | None = None,
    ) -> dict:
        if not self.skills or not hasattr(self.skills, "apply_curator_report"):
            return {"success": False, "error": "Skill manager is not available."}
        return await self.skills.apply_curator_report(
            report_id=report_id,
            proposal_ids=proposal_ids,
        )

    def _maybe_start_curator(self) -> BackgroundTaskRecord | None:
        if not self.skills or not getattr(self.skills.config, "curator_enabled", False):
            return None
        interval = int(getattr(self.skills.config, "curator_interval_turns", 0) or 0)
        if interval <= 0:
            return None
        self._turns_since_curator += 1
        if self._turns_since_curator < interval:
            return None
        self._turns_since_curator = 0

        async def runner():
            return await self.run_curator()

        return self.background.start(
            kind="curator",
            runner=runner,
            source="agent",
            description="Run agent-owned skill curator transitions",
            metadata={},
        )

    async def continue_task(self, task_id: str, user_input: str) -> AgentResult:
        output = await self._run_llm(task_id, user_input, source="api")
        suppress_channel_reply = task_id in self._suppress_channel_reply_task_ids
        self._suppress_channel_reply_task_ids.discard(task_id)
        return AgentResult(
            task_id=task_id,
            source="api",
            status="completed",
            output=output,
            suppress_channel_reply=suppress_channel_reply,
        )

    async def cancel_task(self, task_id: str) -> None:
        item = await self.memory.add("episodic", f"Task cancelled: {task_id}")
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.save_memory(item)
                await repo.add_event(task_id, "task.cancelled", item.summary)

    async def execute_tool(
        self,
        tool_name: str,
        payload: dict,
        *,
        task_id: str | None = None,
        source: str = "api",
    ) -> ToolCallResult:
        task_id = task_id or str(uuid4())
        tool = self.tools.get(tool_name)
        if tool is None:
            result = ToolCallResult(
                task_id=task_id,
                tool=tool_name,
                status="failed",
                error=f"Tool not found: {tool_name}",
                error_type="tool_not_found",
                fallback={
                    "error_type": "tool_not_found",
                    "message": f"Tool not found: {tool_name}",
                    "suggestion": "Use a visible registered tool name exactly as listed in the tool catalog.",
                },
            )
            logger.warning("Agent 工具不存在: task_id={} tool={}", task_id, tool_name)
            await self._add_event(
                task_id,
                "tool.failed",
                {
                    "tool": tool_name,
                    "risk_level": "unknown",
                    "error": result.error,
                    "fallback": result.fallback,
                },
            )
            return result
        logger.info("Agent 工具调用开始: task_id={} tool={} source={}", task_id, tool_name, source)
        await self._add_event(
            task_id,
            "tool.started",
            {
                "source": source,
                "tool": tool_name,
                "risk_level": tool.risk_level,
                "input": self._summarize_payload(payload),
            },
        )
        try:
            cache_key = self.cache_policy.key_for(tool, payload)
            if cache_key:
                cached_output = self._tool_result_cache.get(cache_key)
                if cached_output is not None:
                    logger.info("Agent 工具缓存命中: task_id={} tool={}", task_id, tool_name)
                    result = ToolCallResult(
                        task_id=task_id,
                        tool=tool_name,
                        status="completed",
                        output=cached_output,
                    )
                    await self._add_event(
                        task_id,
                        "tool.cache_hit",
                        {"tool": tool_name, "risk_level": tool.risk_level},
                    )
                    return result
            output = await self.executor.execute(tool_name, payload)
        except PolicyDeniedError as exc:
            fallback = self.fallback_policy.explain(
                ToolError(tool=tool_name, payload=payload, error=exc, denied=True)
            )
            logger.warning(
                "Agent 工具调用被策略拒绝: task_id={} tool={} error={}",
                task_id,
                tool_name,
                exc,
            )
            result = ToolCallResult(
                task_id=task_id,
                tool=tool_name,
                status="denied",
                error=str(exc),
                error_type=fallback["error_type"],
                fallback=fallback,
            )
            await self._add_event(
                task_id,
                "tool.denied",
                {
                    "tool": tool_name,
                    "risk_level": tool.risk_level,
                    "error": str(exc),
                    "fallback": fallback,
                },
            )
            return result
        except Exception as exc:
            fallback = self.fallback_policy.explain(
                ToolError(tool=tool_name, payload=payload, error=exc)
            )
            auto_result = await self._auto_fallback(task_id, fallback)
            if auto_result is not None:
                fallback["auto_result"] = auto_result
            logger.warning(
                "Agent 工具调用失败: task_id={} tool={} error={}",
                task_id,
                tool_name,
                exc,
            )
            result = ToolCallResult(
                task_id=task_id,
                tool=tool_name,
                status="failed",
                error=str(exc),
                error_type=fallback["error_type"],
                fallback=fallback,
            )
            await self._add_event(
                task_id,
                "tool.failed",
                {
                    "tool": tool_name,
                    "risk_level": tool.risk_level,
                    "error": str(exc),
                    "fallback": fallback,
                },
            )
            return result
        result = ToolCallResult(task_id=task_id, tool=tool_name, status="completed", output=output)
        logger.info("Agent 工具调用完成: task_id={} tool={}", task_id, tool_name)
        if cache_key:
            self._tool_result_cache.set(cache_key, output)
            logger.info("Agent 工具缓存写入: task_id={} tool={}", task_id, tool_name)
        if tool.invalidates_cache:
            self._tool_result_cache.clear()
            logger.info("Agent 工具缓存已清空: task_id={} tool={}", task_id, tool_name)
        await self._add_event(
            task_id,
            "tool.completed",
            {
                "tool": tool_name,
                "risk_level": tool.risk_level,
                "output": self._summarize_payload(output),
            },
        )
        return result

    def _register_wechat_send_tools(self) -> None:
        self.tools.register(
            ToolDefinition(
                name="wechat.send_text",
                description=(
                    "Send a text message back through the current WeChat channel. "
                    "The runtime automatically routes to the current adapter and conversation."
                ),
                risk_level="execute",
                handler=self._wechat_send_text_tool,
                toolset="wechat",
                source="wechat",
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "required": ["text"],
                    "properties": {"text": {"type": "string"}},
                },
            )
        )
        self.tools.register(
            ToolDefinition(
                name="wechat.send_image",
                description=(
                    "Send an image file through the current WeChat channel. "
                    "The runtime automatically routes to the current adapter and conversation."
                ),
                risk_level="execute",
                handler=self._wechat_send_image_tool,
                toolset="wechat",
                source="wechat",
                timeout_seconds=300,
                metadata={"background_candidate": True, "background_reason": "media sending may take time"},
                input_schema={
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            )
        )
        self.tools.register(
            ToolDefinition(
                name="wechat.send_file",
                description=(
                    "Send a file through the current WeChat channel. "
                    "The runtime automatically routes to the current adapter and conversation."
                ),
                risk_level="execute",
                handler=self._wechat_send_file_tool,
                toolset="wechat",
                source="wechat",
                timeout_seconds=300,
                metadata={"background_candidate": True, "background_reason": "media sending may take time"},
                input_schema={
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "name": {"type": "string"},
                    },
                },
            )
        )

    async def _wechat_send_text_tool(self, payload: dict) -> dict:
        source = str(payload.get("_source") or "")
        target = self._wechat_reply_target_from_payload(payload)
        text = str(payload.get("text") or "")
        if not text:
            raise XBotError("wechat.send_text requires text.")
        if not target:
            raise XBotError("wechat.send_text can only be used from a WeChat channel context.")
        if self.background.send_reply:
            await self.background.send_reply(
                Reply(
                    platform=target["platform"],
                    adapter=target["adapter"],
                    conversation_id=target["conversation_id"],
                    type="text",
                    content=text,
                    quote_message_id=target.get("quote_message_id") or None,
                )
            )
            return {"sent": True, "adapter": target["adapter"], "type": "text"}
        if target["adapter"] == "wechat869":
            return await self._run_wechat869_media_action("send-text", payload, target)
        raise XBotError(f"Reply sender is not available for {source}.")

    async def _wechat_send_image_tool(self, payload: dict) -> dict:
        target = self._wechat_reply_target_from_payload(payload)
        if not target:
            raise XBotError("wechat.send_image can only be used from a WeChat channel context.")
        if target["adapter"] == "wechat869":
            return await self._run_wechat869_media_action("send-image", payload, target)
        if target["adapter"] == "wechat_ilink":
            return await self._send_wechat_reply_media("image", payload, target)
        raise XBotError(f"Unsupported WeChat adapter for image sending: {target['adapter']}")

    async def _wechat_send_file_tool(self, payload: dict) -> dict:
        target = self._wechat_reply_target_from_payload(payload)
        if not target:
            raise XBotError("wechat.send_file can only be used from a WeChat channel context.")
        if target["adapter"] == "wechat869":
            return await self._run_wechat869_media_action("send-file", payload, target)
        if target["adapter"] == "wechat_ilink":
            return await self._send_wechat_reply_media("file", payload, target)
        raise XBotError(f"Unsupported WeChat adapter for file sending: {target['adapter']}")

    async def _send_wechat_reply_media(self, reply_type: str, payload: dict, target: dict) -> dict:
        path = str(payload.get("path") or "")
        if not path:
            raise XBotError(f"wechat.send_{reply_type} requires path.")
        if not self.background.send_reply:
            raise XBotError(f"Reply sender is not available for {target['adapter']}.")
        await self.background.send_reply(
            Reply(
                platform=target["platform"],
                adapter=target["adapter"],
                conversation_id=target["conversation_id"],
                type=reply_type,
                content=path,
                quote_message_id=target.get("quote_message_id") or None,
            )
        )
        return {"sent": True, "adapter": target["adapter"], "type": reply_type, "path": path}

    async def _run_wechat869_media_action(self, action: str, payload: dict, target: dict) -> dict:
        args = {
            "to": str(payload.get("to") or target["raw_conversation_id"]),
        }
        if action == "send-text":
            args["text"] = str(payload.get("text") or "")
        else:
            args["path"] = str(payload.get("path") or "")
            if payload.get("name"):
                args["name"] = str(payload["name"])
        for key in ("thumb", "thumb_mode", "format", "seconds", "url", "title", "desc", "thumb_url"):
            if payload.get(key):
                args[key] = payload[key]
        if payload.get("at"):
            args["at"] = payload["at"]
        return await self.skill_tools.run_skill(
            {
                "skill": "wechat-869-media-sender",
                "action": action,
                "args": args,
            }
        )

    def _wechat_reply_target_from_payload(self, payload: dict) -> dict | None:
        source = str(payload.get("_source") or "")
        input_text = str(payload.get("_input_text") or "")
        notify = self._notification_target(source, input_text, include_wechat=True)
        if not notify or notify.get("platform") != "wechat":
            return None
        conversation_id = str(notify["conversation_id"])
        raw_conversation_id = conversation_id
        if str(notify["adapter"]) == "wechat869":
            raw_conversation_id = self._raw_wechat869_conversation_id(conversation_id)
            match = re.search(r"(?m)^reply_target_wxid:\s*(.+)$", input_text)
            if match:
                raw_conversation_id = match.group(1).strip()
        return {
            **notify,
            "conversation_id": conversation_id,
            "raw_conversation_id": raw_conversation_id,
        }

    def llm_status(self) -> dict:
        return self.llm.status()

    def mcp_status(self) -> dict:
        return self.mcp.status()

    def visible_tools(self, *, source: str = "api") -> list[dict]:
        toolsets = toolsets_for_source(self.config, source)
        context = source_context(source)
        return self.tools.list_tools(
            toolsets=toolsets,
            platform=context.get("platform"),
            scope=context.get("scope"),
            mode=self.config.mode,
        )

    async def reload_mcp(self) -> dict:
        await self.mcp.reload()
        self._static_prompt_cache = None
        return self.mcp.status()

    async def list_background_tasks(self, limit: int = 50) -> list[BackgroundTaskRecord]:
        if not self.repository_provider:
            return self.background.list(limit)
        async with self.repository_provider() as repo:
            records = await repo.list_background_tasks(limit)
        memory = {item.id: item for item in self.background.list(limit)}
        items = [memory.get(record.id) or BackgroundTaskRecord.from_storage(record) for record in records]
        memory_ids = {item.id for item in items}
        items.extend(item for item in self.background.list(limit) if item.id not in memory_ids)
        return sorted(items, key=lambda item: item.created_at, reverse=True)[:limit]

    async def get_background_task(self, task_id: str) -> BackgroundTaskRecord | None:
        item = self.background.get(task_id)
        if item is not None or not self.repository_provider:
            return item
        async with self.repository_provider() as repo:
            record = await repo.get_background_task(task_id)
        return BackgroundTaskRecord.from_storage(record) if record else None

    async def list_events(self, task_id: str | None = None, limit: int = 100) -> list[dict]:
        if not self.repository_provider:
            return []
        async with self.repository_provider() as repo:
            records = await repo.list_events(task_id=task_id, limit=limit)
        return [
            {
                "id": record.id,
                "task_id": record.task_id,
                "type": record.type,
                "content": self._event_content(record.content),
                "created_at": record.created_at.isoformat(),
            }
            for record in records
        ]

    def _event_content(self, content: str) -> object:
        try:
            return json.loads(content)
        except Exception:
            return content

    async def background_task_overview(self, limit: int = 20) -> dict:
        tasks = await self.list_background_tasks(limit)
        counts: dict[str, int] = {}
        replayable = []
        for item in tasks:
            counts[item.status] = counts.get(item.status, 0) + 1
            if self._can_replay_background_task(item):
                replayable.append(item.model_dump(mode="json"))
        candidates = [
            item
            for item in self.tools.list_tools(mode=self.config.mode)
            if item.get("metadata", {}).get("background_candidate")
        ]
        return {
            "counts": counts,
            "recent": [item.model_dump(mode="json") for item in tasks],
            "replayable": replayable,
            "background_candidate_tools": candidates,
        }

    async def replay_background_task(self, task_id: str) -> BackgroundTaskRecord:
        record = await self.get_background_task(task_id)
        if record is None:
            raise XBotError(f"Background task not found: {task_id}")
        if record.status == "completed":
            raise XBotError(f"Background task already completed: {task_id}")
        if not self._can_replay_background_task(record):
            raise XBotError(f"Background task is not safely replayable: {task_id}")
        tool_name = str(record.metadata.get("tool") or "")
        payload = record.metadata.get("payload") or {}

        async def runner(tool_name=tool_name, payload=payload):
            return await self._execute_tool_for_task(tool_name, payload)

        return self.background.replay(record, runner)

    async def _execute_tool_for_task(self, tool_name: str, payload: dict) -> dict:
        result = await self.execute_tool(tool_name, payload, source="background")
        return result.model_dump(mode="json")

    async def _run_agent_for_task(self, input_text: str, source: str = "background") -> dict:
        result = await self.run_task(input_text, source=source or "background")
        return result.model_dump(mode="json")

    async def _on_background_task_completed(self, record: BackgroundTaskRecord) -> None:
        if record.kind != "agent" or record.status not in {"completed", "failed"}:
            return
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        if metadata.get("notify_mode") != "parent_agent":
            return
        notify = metadata.get("notify") if isinstance(metadata.get("notify"), dict) else None
        if not notify or not self.background.send_reply:
            return
        source = self._source_from_notification_target(notify)
        if not source:
            return
        parent_input = self._child_agent_completion_input(record)
        try:
            result = await self.run_task(parent_input, source=source)
            if result.suppress_channel_reply:
                return
            content = (result.output or "").strip()
        except Exception as exc:
            logger.warning("Parent agent child-result synthesis failed: task_id={} error={}", record.id, exc)
            content = self.background._notification_content(record)
        if not content:
            content = self.background._notification_content(record)
        if not content:
            return
        await self.background.send_reply(
            Reply(
                platform=str(notify["platform"]),
                adapter=str(notify["adapter"]),
                conversation_id=str(notify["conversation_id"]),
                type="text",
                content=content,
                quote_message_id=notify.get("quote_message_id"),
            )
        )

    def _source_from_notification_target(self, notify: dict) -> str:
        platform = str(notify.get("platform") or "")
        adapter = str(notify.get("adapter") or "")
        conversation_id = str(notify.get("conversation_id") or "")
        if not platform or not adapter or not conversation_id:
            return ""
        return f"channel:{platform}:{adapter}:{conversation_id}"

    def _child_agent_completion_input(self, record: BackgroundTaskRecord) -> str:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        child_output = self.background._notification_content(record)
        if record.status == "failed":
            child_output = f"子代理执行失败：{record.error or child_output}"
        return (
            "Child agent task completed.\n"
            "You are the parent agent. Review the child agent result, merge it with the user context, "
            "and produce the final user-facing reply in Chinese. Do not mention internal task IDs unless the user asks.\n"
            f"child_task_id: {record.id}\n"
            f"child_status: {record.status}\n"
            f"original_user_request: {metadata.get('input') or ''}\n"
            f"child_result:\n{child_output or '- empty'}\n"
        )

    def _maybe_start_memory_review(
        self,
        *,
        parent_task_id: str,
        input_text: str,
        output_text: str,
        source: str,
    ) -> BackgroundTaskRecord | None:
        if not self.config.memory.enabled or not self.config.memory.review_enabled:
            return None
        if source == "background" or not output_text.strip():
            return None
        if source == "memory_flush":
            return None
        interval = int(self.config.memory.review_interval or 0)
        if interval <= 0:
            return None
        self._turns_since_memory_review += 1
        if self._turns_since_memory_review < interval:
            return None
        self._turns_since_memory_review = 0

        async def runner():
            return await self._run_memory_review(
                parent_task_id=parent_task_id,
                input_text=input_text,
                output_text=output_text,
                source=source,
            )

        return self.background.start(
            kind="memory_review",
            runner=runner,
            source="agent",
            description="Review completed task for durable memory",
            metadata={"parent_task_id": parent_task_id, "source": source},
        )

    async def _run_memory_review(
        self,
        *,
        parent_task_id: str,
        input_text: str,
        output_text: str,
        source: str,
    ) -> dict:
        prompt = self._memory_review_prompt(input_text=input_text, output_text=output_text, source=source)
        response = await self.llm.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You are xbot's background memory reviewer. "
                        "You may only request memory.read, memory.add, memory.replace, memory.remove, or skill.manage tool calls. "
                        "Save only durable user preferences, corrections, stable environment facts, and project conventions. "
                        "Use skill.manage only for reusable procedures in agent-owned skills under skills/.agent. "
                        "Do not save temporary task progress, one-off outputs, secrets, tokens, or raw logs. "
                        "Return JSON tool_calls when memory should change; otherwise return {\"final\":\"Nothing to save.\"}."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ]
        )
        plan = self.planner.parse_llm_response(response.content)
        allowed_tools = {"memory.read", "memory.add", "memory.replace", "memory.remove", "skill.manage"}
        tool_results = []
        for call in plan.tool_calls[:4]:
            if call.tool not in allowed_tools:
                tool_results.append({"tool": call.tool, "status": "skipped", "error": "not allowed in memory review"})
                continue
            result = await self.execute_tool(
                call.tool,
                call.payload,
                task_id=parent_task_id,
                source="background",
            )
            tool_results.append(result.model_dump(mode="json"))
        return {
            "parent_task_id": parent_task_id,
            "tool_calls": len(plan.tool_calls),
            "results": tool_results,
            "final": self.planner.clean_final_output(plan.final or response.content),
        }

    def _memory_review_prompt(self, *, input_text: str, output_text: str, source: str) -> str:
        return (
            "Review this completed xbot turn for long-term memory value.\n"
            f"source: {source}\n\n"
            "Memory boundary:\n"
            "- Save facts only from the current explicitly triggered user request and the assistant output.\n"
            "- Do not save facts found only in conversation_summaries or recent_conversation_messages.\n"
            "- For group/channel sources, treat unmentioned room chatter as passive context, not as user memory, unless the triggering user explicitly asks to remember it.\n\n"
            "User/input:\n"
            f"{input_text[:4000]}\n\n"
            "Assistant/output:\n"
            f"{output_text[:4000]}\n\n"
            "Targets:\n"
            "- target=user: durable user preferences, corrections, communication style, personal workflow.\n"
            "- target=memory: stable environment facts, project conventions, reusable tool quirks.\n"
            "- skill.manage: create or patch reusable agent-owned procedural skills only when a durable workflow emerged.\n"
            "Skip temporary progress, one-off results, and anything sensitive."
        )

    def _memory_eligible_input_text(self, input_text: str) -> str:
        return re.sub(
            r"conversation_summaries:\n.*?\nrecent_conversation_messages:\n.*?\nmessage_attachments:",
            (
                "conversation_summaries:\n[passive context omitted from memory]\n"
                "recent_conversation_messages:\n[passive context omitted from memory]\n"
                "message_attachments:"
            ),
            input_text,
            flags=re.DOTALL,
        )

    def _curator_report_prompt(self) -> str:
        snapshot = self.skills.curator_snapshot() if self.skills else []
        compact = [
            {
                "name": item.get("name"),
                "state": item.get("state"),
                "pinned": item.get("pinned"),
                "use_count": item.get("use_count"),
                "view_count": item.get("view_count"),
                "patch_count": item.get("patch_count"),
                "age_days": item.get("age_days"),
                "description": item.get("description"),
                "instructions_preview": item.get("instructions_preview"),
            }
            for item in snapshot
        ]
        return (
            "Agent-owned skill snapshot as JSON:\n"
            f"{json.dumps(compact, ensure_ascii=False)}\n"
            "Return JSON in this shape only:\n"
            '{"proposals":[{"action":"archive|mark_stale|merge|pin|unpin",'
            '"target":"skill-to-keep-or-change",'
            '"source_skill":"skill-to-archive-for-merge",'
            '"reason":"short reason","confidence":0.0,'
            '"merged_content":"optional full SKILL.md only when confidently merging"}]}'
        )

    def _parse_curator_llm_proposals(self, content: str) -> list[dict]:
        for data in self.planner._extract_json_objects(content):
            if not isinstance(data, dict):
                continue
            proposals = data.get("proposals") or data.get("actions") or []
            if isinstance(proposals, list):
                return [item for item in proposals if isinstance(item, dict)]
        return []

    async def _auto_fallback(self, task_id: str, fallback: dict) -> dict | None:
        suggested_tool_name = fallback.get("suggested_tool")
        suggested_payload = fallback.get("suggested_payload")
        if not suggested_tool_name or not isinstance(suggested_payload, dict):
            return None
        suggested_tool = self.tools.get(str(suggested_tool_name))
        if suggested_tool is None:
            return None
        if suggested_tool_name == "task.start":
            nested_tool = self.tools.get(str(suggested_payload.get("tool") or ""))
            if nested_tool is None or nested_tool.risk_level not in {"read"}:
                return None
        elif suggested_tool.risk_level not in {"read"}:
            return None
        try:
            output = await self.executor.execute(str(suggested_tool_name), suggested_payload)
        except Exception as exc:
            return {
                "tool": suggested_tool_name,
                "payload": suggested_payload,
                "status": "failed",
                "error": str(exc),
            }
        await self._add_event(
            task_id,
            "tool.fallback_completed",
            {"tool": suggested_tool_name, "payload": suggested_payload, "output": self._summarize_payload(output)},
        )
        return {
            "tool": suggested_tool_name,
            "payload": suggested_payload,
            "status": "completed",
            "output": output,
        }

    async def _restore_background_tasks(self) -> None:
        if not self.repository_provider:
            return
        try:
            async with self.repository_provider() as repo:
                records = await repo.list_background_tasks(200)
        except Exception as exc:
            logger.warning("Background task restore failed: {}", exc)
            return
        for storage_record in records:
            record = BackgroundTaskRecord.from_storage(storage_record)
            if record.status in {"completed", "cancelled"}:
                self.background.remember(record)
                continue
            if self._can_replay_background_task(record):
                tool_name = str(record.metadata.get("tool") or "")
                payload = record.metadata.get("payload") or {}

                async def runner(tool_name=tool_name, payload=payload):
                    return await self._execute_tool_for_task(tool_name, payload)

                self.background.replay(record, runner)
                logger.info("Background task replay queued: task_id={} tool={}", record.id, tool_name)
            else:
                record.status = "failed"
                record.error = record.error or "Background task was interrupted and is not replayable."
                record.finished_at = datetime.utcnow()
                self.background.remember(record)
                self.background._persist_later(record)

    def _can_replay_background_task(self, record: BackgroundTaskRecord) -> bool:
        metadata = record.metadata or {}
        if not metadata.get("replayable", False):
            return False
        if int(metadata.get("replay_count") or 0) >= 1:
            return False
        tool_name = str(metadata.get("tool") or "")
        payload = metadata.get("payload") or {}
        if not tool_name or not isinstance(payload, dict):
            return False
        tool = self.tools.get(tool_name)
        if tool is None:
            return False
        return tool.risk_level in {"read"}

    async def _add_event(
        self,
        task_id: str,
        event_type: str,
        content: object,
        *,
        persist: bool = True,
    ) -> None:
        event = AgentRuntimeEvent(task_id=task_id, type=event_type, content=content)
        await self._publish_event(event)
        if not persist or not self.repository_provider:
            return
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        async with self.repository_provider() as repo:
            await repo.add_event(task_id, event_type, content)

    async def _publish_event(self, event: AgentRuntimeEvent) -> None:
        for subscriber in list(self._event_subscribers):
            try:
                result = subscriber(event)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.warning(
                    "Agent event subscriber failed: task_id={} type={} error={}",
                    event.task_id,
                    event.type,
                    exc,
                )

    def _summarize_payload(self, value: object) -> object:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if len(text) <= 1200:
            return value
        return {"truncated": True, "chars": len(text), "preview": text[:1200]}

    async def _run_llm(
        self,
        task_id: str,
        input_text: str,
        *,
        source: str = "api",
        attachments: list[dict] | None = None,
    ) -> str:
        history_key = self._session_history_key(source)
        native_tools, native_tool_map = self._native_tools_for_source(source)
        messages = [
            LLMMessage(role="system", content=self._agent_system_prompt(source=source)),
        ]
        if history_key:
            messages.extend(self._session_history(history_key))
        messages.append(
            LLMMessage(
                role="user",
                content=input_text,
                content_blocks=self._llm_content_blocks(input_text, attachments or []),
            )
        )
        last_content = ""
        iteration = 0
        missing_tool_reprompts = 0
        while True:
            await self._add_event(
                task_id,
                "llm.started",
                {"status": self.llm_status(), "iteration": iteration},
            )
            try:
                logger.info(
                    "Agent LLM 调用开始: task_id={} iteration={} provider={} model={}",
                    task_id,
                    iteration,
                    self.llm_status().get("provider"),
                    self.llm_status().get("model"),
                )
                response = await self._complete_llm_with_retries(
                    messages,
                    task_id=task_id,
                    iteration=iteration,
                    source=source,
                    tools=native_tools,
                )
            except XBotError as exc:
                await self._add_event(task_id, "llm.unavailable", {"error": str(exc)})
                logger.warning("Agent LLM 不可用: task_id={} error={}", task_id, exc)
                return f"LLM provider is not available: {exc}"
            except TimeoutError:
                await self._add_event(task_id, "llm.timeout", {"iteration": iteration})
                logger.warning("Agent LLM 调用超时: task_id={} iteration={}", task_id, iteration)
                return "LLM provider call timed out, please try again later."
            except Exception as exc:
                await self._add_event(task_id, "llm.failed", {"error": str(exc)})
                logger.warning("Agent LLM 调用失败: task_id={} error={}", task_id, exc)
                return f"LLM provider call failed: {exc}"
            last_content = response.content
            logger.info(
                "Agent LLM 调用完成: task_id={} iteration={} chars={}",
                task_id,
                iteration,
                len(response.content or ""),
            )
            await self._add_event(
                task_id,
                "llm.completed",
                {
                    "provider": response.provider,
                    "model": response.model,
                    "usage": response.usage,
                    "raw_id": response.raw_id,
                    "iteration": iteration,
                },
            )
            plan = self._response_plan(response, native_tool_map)
            logger.info(
                "Agent LLM 解析结果: task_id={} iteration={} tool_calls={} final_chars={}",
                task_id,
                iteration,
                len(plan.tool_calls),
                len(plan.final or ""),
            )
            if not plan.tool_calls:
                cleaned = self.planner.clean_final_output(plan.final or response.content)
                requires_tools = self._source_can_force_tool_use(source) and self._request_requires_tools(input_text)
                if (
                    (
                        self.planner.contains_tool_call_intent(response.content)
                        and not cleaned.strip()
                    )
                    or
                    self.planner.is_empty_final_response(response.content)
                    or not cleaned.strip()
                    or (requires_tools and iteration == 0)
                ):
                    if self.config.max_tool_iterations > 0 and iteration >= self.config.max_tool_iterations:
                        output = "这个请求需要继续调用工具，但已达到配置的工具循环上限。"
                        if history_key:
                            await self._append_session_turn(history_key, input_text, output, response=response)
                        return output
                    missing_tool_reprompts += 1
                    if missing_tool_reprompts > 3:
                        logger.warning(
                            "Agent 连续未发起必要工具调用: task_id={} reprompts={}",
                            task_id,
                            missing_tool_reprompts,
                        )
                        output = "模型连续返回空内容或不完整的工具调用，请换一种更明确的说法再试。"
                        if history_key:
                            await self._append_session_turn(history_key, input_text, output, response=response)
                        return output
                    messages.append(LLMMessage(role="assistant", content=response.content))
                    messages.append(
                        LLMMessage(
                            role="user",
                            content=(
                                "Your previous response was empty, incomplete, or did not call required tools. "
                                "If the request depends on current project files, directories, plugins, skills, "
                                "config, logs, or runtime state, you must call tools first. "
                                "This request appears to need live tool data, so do not answer from memory. "
                                "Do not say you are checking; actually request tool_calls. "
                                "If you return tool_calls, the JSON must be valid and complete. "
                                "Otherwise return JSON with a non-empty final answer."
                            ),
                        )
                    )
                    iteration += 1
                    continue
                if history_key:
                    await self._append_session_turn(history_key, input_text, cleaned, response=response)
                return cleaned
            missing_tool_reprompts = 0
            if self.config.max_tool_iterations > 0 and iteration >= self.config.max_tool_iterations:
                output = self.planner.clean_final_output(
                    plan.final or "工具调用次数达到上限，任务没有完成。"
                )
                if history_key:
                    await self._append_session_turn(history_key, input_text, output, response=response)
                return output

            tool_results = []
            background_started = False
            explicit_wechat_send = False
            for call in plan.tool_calls:
                tool_name, payload = self._prepare_tool_call(call.tool, call.payload, source, input_text)
                result = await self.execute_tool(
                    tool_name,
                    payload,
                    task_id=task_id,
                    source="agent",
                )
                if tool_name in {"task.start", "task.agent_start"} and result.status == "completed":
                    background_started = True
                if (
                    tool_name == "wechat.send_text"
                    and result.status == "completed"
                    and source.startswith("channel:wechat:")
                ):
                    explicit_wechat_send = True
                tool_results.append(result.model_dump(mode="json"))
            if explicit_wechat_send:
                self._suppress_channel_reply_task_ids.add(task_id)
                output = "已发送。"
                if history_key:
                    await self._append_session_turn(history_key, input_text, output, response=response)
                return output
            if background_started and (
                self._should_return_after_background(source)
                or self._has_child_agent_started(tool_results)
            ):
                output = self._background_started_message(tool_results, plan_final=plan.final)
                if history_key:
                    await self._append_session_turn(history_key, input_text, output, response=response)
                return output
            if response.tool_calls:
                messages.append(self._assistant_tool_call_message(response))
                messages.extend(self._native_tool_result_messages(response.tool_calls, tool_results))
            else:
                messages.append(LLMMessage(role="assistant", content=response.content))
                messages.append(
                    LLMMessage(
                        role="user",
                        content=(
                            "Tool execution results as JSON:\n"
                            f"{json.dumps(tool_results, ensure_ascii=False)}\n"
                            "Continue. If no more tools are needed, return JSON with only final."
                        ),
                    )
                )
            iteration += 1
        cleaned = self.planner.clean_final_output(last_content)
        output = cleaned if cleaned and not self.planner.is_empty_final_response(cleaned) else "我没有生成有效回复，请换一种说法再试。"
        if history_key:
            await self._append_session_turn(history_key, input_text, output)
        return output

    def _llm_content_blocks(self, input_text: str, attachments: list[dict]) -> list[LLMContentBlock] | None:
        if not self.config.llm.multimodal_enabled:
            return None
        blocks = [LLMContentBlock(type="text", text=input_text)]
        for attachment in attachments:
            image_block = self._attachment_image_block(attachment)
            if image_block:
                blocks.append(image_block)
        return blocks if len(blocks) > 1 else None

    def _attachment_image_block(self, attachment: dict) -> LLMContentBlock | None:
        if not self.config.llm.image_input_enabled:
            return None
        mime_type = str(attachment.get("mime") or attachment.get("mime_type") or "").strip()
        local_path = str(attachment.get("local_path") or attachment.get("path") or "").strip()
        url = str(attachment.get("url") or "").strip()
        if not mime_type and local_path:
            mime_type = mimetypes.guess_type(local_path)[0] or ""
        if not mime_type.startswith("image/"):
            return None
        size = self._attachment_size(attachment, local_path=local_path)
        if size and size > int(self.config.llm.max_image_bytes):
            logger.info(
                "跳过超限图片输入: path={} size={} max={}",
                local_path or url,
                size,
                self.config.llm.max_image_bytes,
            )
            return None
        if local_path and Path(local_path).is_file():
            return LLMContentBlock(type="image", path=local_path, mime_type=mime_type)
        if url:
            return LLMContentBlock(type="image", url=url, mime_type=mime_type)
        return None

    def _attachment_size(self, attachment: dict, *, local_path: str) -> int:
        raw_size = attachment.get("size")
        try:
            size = int(raw_size or 0)
        except (TypeError, ValueError):
            size = 0
        if size:
            return size
        if local_path:
            try:
                return Path(local_path).stat().st_size
            except OSError:
                return 0
        return 0

    def _session_history_key(self, source: str) -> str:
        if not self.config.memory.short_term_enabled:
            return ""
        if source.startswith("terminal:") or source.startswith("channel:"):
            return source
        return ""

    def _session_history(self, key: str) -> list[LLMMessage]:
        messages = []
        summary = self._session_summaries.get(key, "").strip()
        if summary:
            messages.append(
                LLMMessage(
                    role="system",
                    content=(
                        "Short-term session summary from earlier turns. "
                        "Use it as prior conversation context, not as a new user request.\n"
                        f"{summary}"
                    ),
                )
            )
        messages.extend(self._session_histories.get(key, []))
        return messages

    async def _append_session_turn(
        self,
        key: str,
        user_input: str,
        assistant_output: str,
        *,
        response: LLMResponse | None = None,
    ) -> None:
        if not key:
            return
        history = self._session_histories.setdefault(key, [])
        history.extend(
            [
                LLMMessage(role="user", content=self._short_term_user_content(user_input)),
                LLMMessage(role="assistant", content=assistant_output),
            ]
        )
        self._compress_session_history(key)
        await self._maybe_compact_session_history_for_context(key, response=response)

    def clear_session_history(self, source: str | None = None) -> None:
        if source is None:
            self._session_histories.clear()
            self._session_summaries.clear()
            return
        self._session_histories.pop(source, None)
        self._session_summaries.pop(source, None)

    def _compress_session_history(self, key: str) -> None:
        if not self.config.memory.auto_compress:
            self._session_histories[key] = self._trim_session_history(
                self._session_histories.get(key, []),
                summarize=False,
            )
            return
        self._session_histories[key] = self._trim_session_history(
            self._session_histories.get(key, []),
            summarize=True,
            key=key,
        )

    def _trim_session_history(
        self,
        history: list[LLMMessage],
        *,
        summarize: bool = False,
        key: str = "",
    ) -> list[LLMMessage]:
        max_turns = max(0, int(self.config.memory.short_term_recent_turns or 0))
        older: list[LLMMessage] = []
        if max_turns > 0:
            older.extend(history[: -(max_turns * 2)])
            history = history[-(max_turns * 2) :]
        token_budget = max(0, int(getattr(self.config.memory, "short_term_max_tokens", 0) or 0))
        char_budget = max(0, int(self.config.memory.short_term_max_chars or 0))
        if token_budget <= 0 and char_budget <= 0:
            if summarize and key and older:
                self._append_session_summary(key, older)
            return history
        total = 0
        kept: list[LLMMessage] = []
        for message in reversed(history):
            total += self._short_term_size(message.content or "", token_budget=token_budget)
            if kept and (
                (token_budget > 0 and total > token_budget)
                or (char_budget > 0 and sum(len(item.content or "") for item in kept) > char_budget)
            ):
                break
            kept.append(message)
        trimmed = list(reversed(kept))
        keep_ids = {id(item) for item in trimmed}
        older.extend(item for item in history if id(item) not in keep_ids)
        if summarize and key and older:
            self._append_session_summary(key, older)
        return trimmed

    def _append_session_summary(self, key: str, messages: list[LLMMessage]) -> None:
        if not messages:
            return
        previous = self._session_summaries.get(key, "").strip()
        addition = self._summarize_short_term_messages(messages)
        combined = "\n".join(item for item in (previous, addition) if item)
        token_limit = max(0, int(getattr(self.config.memory, "short_term_summary_max_tokens", 0) or 0))
        char_limit = max(0, int(self.config.memory.short_term_summary_max_chars or 0))
        limit = char_limit or (token_limit * 4 if token_limit > 0 else 6000)
        limit = max(1000, limit)
        if self._short_term_size(combined, token_budget=token_limit) > (token_limit or limit) or len(combined) > limit:
            combined = combined[-limit:]
            first_line = combined.find("\n")
            if first_line > 0:
                combined = combined[first_line + 1 :]
            combined = "[Earlier summary truncated]\n" + combined
        self._session_summaries[key] = combined

    async def _maybe_compact_session_history_for_context(
        self,
        key: str,
        *,
        response: LLMResponse | None,
    ) -> None:
        if not key or not self.config.memory.auto_compress:
            return
        context_window = int(self.config.llm.context_window_tokens or 0)
        if context_window <= 0:
            return
        used_tokens = self._usage_context_tokens(response.usage if response else {})
        if used_tokens <= 0:
            return
        reserve = max(0, int(self.config.memory.compaction_reserve_tokens or 0))
        if used_tokens <= max(0, context_window - reserve):
            return
        keep_tokens = max(1000, int(self.config.memory.compaction_keep_recent_tokens or 0))
        history = self._session_histories.get(key, [])
        older, recent = self._split_history_for_compaction(history, keep_tokens=keep_tokens)
        if not older:
            return
        summary = await self._summarize_compaction_messages(older)
        previous = self._session_summaries.get(key, "").strip()
        marker = (
            f"Context checkpoint: compressed {len(older)} older messages because "
            f"context usage reached {used_tokens}/{context_window} tokens."
        )
        self._session_summaries[key] = "\n".join(
            item for item in (previous, marker, summary) if item
        )
        self._session_histories[key] = recent

    def _usage_context_tokens(self, usage: dict) -> int:
        for key in ("total_tokens", "totalTokens", "total"):
            value = usage.get(key)
            if isinstance(value, int) and value > 0:
                return value
        total = 0
        for key in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value > 0:
                total += value
        return total

    def _split_history_for_compaction(
        self,
        history: list[LLMMessage],
        *,
        keep_tokens: int,
    ) -> tuple[list[LLMMessage], list[LLMMessage]]:
        total = 0
        recent_reversed: list[LLMMessage] = []
        for message in reversed(history):
            total += self._short_term_size(message.content or "", token_budget=keep_tokens)
            if recent_reversed and total > keep_tokens:
                break
            recent_reversed.append(message)
        recent = list(reversed(recent_reversed))
        older = history[: max(0, len(history) - len(recent))]
        return older, recent

    async def _summarize_compaction_messages(self, messages: list[LLMMessage]) -> str:
        fallback = self._summarize_short_term_messages(messages)
        if not self.config.memory.compaction_llm_enabled:
            return fallback
        transcript = "\n".join(
            f"{message.role}: {' '.join((message.content or '').split())[:1200]}"
            for message in messages
        )
        try:
            response = await self.llm.complete(
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "You are a context compaction assistant. Summarize older xbot conversation "
                            "history into a compact checkpoint. Preserve durable user requests, decisions, "
                            "files/tools used, unresolved tasks, and facts needed to continue. Do not add new facts."
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            "Summarize these older messages for future context. Keep it concise and structured.\n\n"
                            f"{transcript[:24000]}"
                        ),
                    ),
                ],
                tools=None,
            )
        except Exception as exc:
            logger.warning("Agent context compaction LLM summary failed: error={}", exc)
            return fallback
        summary = self.planner.clean_final_output(response.content or "").strip()
        return summary or fallback

    def _short_term_size(self, text: str, *, token_budget: int) -> int:
        if token_budget <= 0:
            return len(text)
        # Conservative approximation without tokenizer dependency:
        # CJK chars are close to one token; ASCII text is roughly four chars/token.
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        other = max(0, len(text) - cjk)
        return cjk + max(1, other // 4)

    def _summarize_short_term_messages(self, messages: list[LLMMessage]) -> str:
        lines = ["Compressed earlier turns:"]
        pair: list[str] = []
        for message in messages:
            text = " ".join((message.content or "").split())
            if len(text) > 500:
                text = text[:500] + "..."
            pair.append(f"{message.role}: {text}")
            if len(pair) >= 2:
                lines.append("- " + " | ".join(pair))
                pair = []
        if pair:
            lines.append("- " + " | ".join(pair))
        return "\n".join(lines)

    def _short_term_user_content(self, input_text: str) -> str:
        match = re.search(r"(?m)^content:\s*(.*)$", input_text)
        if match:
            return match.group(1).strip()
        return input_text

    def _request_requires_tools(self, input_text: str) -> bool:
        text = self._short_term_user_content(input_text).lower()
        if not text.strip():
            return False
        tool_required_patterns = [
            r"\b(read|open|inspect|list|check|show|find|search|grep|scan|status|log|logs|config|env|database|db|git|test|pytest|npm|pnpm)\b",
            r"(看一下|看看|检查|读取|打开|列出|搜索|查找|日志|配置|环境|数据库|当前状态|运行状态|文件|目录|插件|skill|技能|前端|后端|代码|报错|错误|测试|提交|上传|同步|生产环境)",
            r"(为什么.*(失败|报错|没有|不能|不行|没反应))",
        ]
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in tool_required_patterns)

    def _source_can_force_tool_use(self, source: str) -> bool:
        return source.startswith("terminal:") or source.startswith("channel:")

    def _response_plan(self, response: LLMResponse, native_tool_map: dict[str, str]):
        if not response.tool_calls:
            return self.planner.parse_llm_response(response.content)
        return self.planner.parse_llm_response(
            json.dumps(
                {
                    "tool_calls": [
                        {
                            "tool": native_tool_map.get(call.name, call.name),
                            "payload": call.arguments,
                        }
                        for call in response.tool_calls
                    ],
                    "final": response.content or None,
                },
                ensure_ascii=False,
            )
        )

    def _native_tools_for_source(self, source: str) -> tuple[list[dict], dict[str, str]]:
        toolsets = toolsets_for_source(self.config, source)
        context = source_context(source)
        tools = self.tools.list_tools(
            toolsets=toolsets,
            platform=context.get("platform"),
            scope=context.get("scope"),
            mode=self.config.mode,
            include_metadata=False,
        )
        native_tools = []
        native_tool_map: dict[str, str] = {}
        used_names: set[str] = set()
        for tool in tools:
            original_name = str(tool.get("name") or "").strip()
            if not original_name:
                continue
            native_name = self._native_tool_name(original_name, used_names)
            native_tool_map[native_name] = original_name
            native_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": native_name,
                        "description": f"{tool.get('description') or ''}\nOriginal xbot tool name: {original_name}",
                        "parameters": tool.get("input_schema") or {"type": "object"},
                    },
                }
            )
        return native_tools, native_tool_map

    def _native_tool_name(self, name: str, used_names: set[str]) -> str:
        base = re.sub(r"[^a-zA-Z0-9_-]", "__", name).strip("_") or "tool"
        base = base[:64]
        candidate = base
        index = 2
        while candidate in used_names:
            suffix = f"_{index}"
            candidate = f"{base[: 64 - len(suffix)]}{suffix}"
            index += 1
        used_names.add(candidate)
        return candidate

    def _assistant_tool_call_message(self, response: LLMResponse) -> LLMMessage:
        return LLMMessage(
            role="assistant",
            content=response.content or None,
            tool_calls=[
                call.raw
                if call.raw
                else {
                    "id": call.id or f"call_{index}",
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for index, call in enumerate(response.tool_calls)
            ],
        )

    def _native_tool_result_messages(
        self,
        calls: list[LLMToolCall],
        tool_results: list[dict],
    ) -> list[LLMMessage]:
        messages = []
        for index, result in enumerate(tool_results):
            call = calls[index] if index < len(calls) else None
            messages.append(
                LLMMessage(
                    role="tool",
                    tool_call_id=(call.id if call else None) or f"call_{index}",
                    content=json.dumps(result, ensure_ascii=False),
                )
            )
        return messages

    async def _complete_llm(
        self,
        messages: list[LLMMessage],
        *,
        task_id: str,
        iteration: int,
        source: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        stream = getattr(self.llm, "stream", None)
        if tools or not source.startswith("terminal:") or stream is None:
            return await self.llm.complete(messages, tools=tools)

        collected = ""
        visible_started = False
        visible_disabled = False
        visible_buffer = ""
        try:
            async for raw_chunk in stream(messages):
                chunk = self._append_stream_chunk(collected, raw_chunk)
                if not chunk:
                    continue
                collected += chunk
                if visible_disabled:
                    continue
                visible_buffer += chunk
                decision = self._terminal_stream_decision(visible_buffer)
                if decision == "block":
                    visible_disabled = True
                    continue
                if decision == "wait":
                    continue
                if not visible_started:
                    visible_started = True
                    await self._add_event(
                        task_id,
                        "llm.delta",
                        {"text": visible_buffer, "iteration": iteration},
                        persist=False,
                    )
                    visible_buffer = ""
                    continue
                await self._add_event(
                    task_id,
                    "llm.delta",
                    {"text": chunk, "iteration": iteration},
                    persist=False,
                )
        except Exception:
            if not collected:
                return await self.llm.complete(messages, tools=tools)
            raise

        if visible_started and visible_buffer:
            await self._add_event(
                task_id,
                "llm.delta",
                {"text": visible_buffer, "iteration": iteration},
                persist=False,
            )
        collected = self._dedupe_repeated_suffix(collected)
        status = self.llm_status()
        return LLMResponse(
            content=collected,
            model=str(status.get("model") or ""),
            provider=str(status.get("provider") or "unknown"),
        )

    async def _complete_llm_with_retries(
        self,
        messages: list[LLMMessage],
        *,
        task_id: str,
        iteration: int,
        source: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        max_attempts = max(1, int(self.config.llm.max_attempts or 1))
        base_delay = max(0.0, float(self.config.llm.retry_backoff_seconds or 0.0))
        for attempt in range(1, max_attempts + 1):
            try:
                with anyio.fail_after(max(1, int(self.config.llm.timeout_seconds) + 5)):
                    return await self._complete_llm(
                        messages,
                        task_id=task_id,
                        iteration=iteration,
                        source=source,
                        tools=tools,
                    )
            except XBotError:
                raise
            except Exception as exc:
                if attempt >= max_attempts or not self._is_retryable_llm_error(exc):
                    raise
                delay = base_delay * (2 ** (attempt - 1))
                await self._add_event(
                    task_id,
                    "llm.retry",
                    {
                        "iteration": iteration,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "delay_seconds": delay,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                logger.warning(
                    "Agent LLM 调用失败，准备重试: task_id={} iteration={} attempt={}/{} delay={}s error={}",
                    task_id,
                    iteration,
                    attempt,
                    max_attempts,
                    delay,
                    exc,
                )
                if delay > 0:
                    await anyio.sleep(delay)
        raise RuntimeError("LLM retry loop exited unexpectedly.")

    def _is_retryable_llm_error(self, exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        return False

    def _append_stream_chunk(self, current: str, chunk: str) -> str:
        if not chunk:
            return ""
        if chunk in current:
            return ""
        if chunk.startswith(current):
            return chunk[len(current) :]
        if current and current in chunk:
            return chunk.split(current, 1)[1]
        if current.endswith(chunk):
            return ""
        max_overlap = min(len(current), len(chunk), 2000)
        for size in range(max_overlap, 0, -1):
            if current.endswith(chunk[:size]):
                return chunk[size:]
        return chunk

    def _dedupe_repeated_suffix(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return text
        max_unit = len(stripped) // 2
        for size in range(max_unit, 12, -1):
            first = stripped[-(size * 2) : -size]
            second = stripped[-size:]
            if first == second:
                return stripped[:-size]
        for size in range(min(len(stripped) // 2, 2000), 12, -1):
            prefix = stripped[:size]
            idx = stripped.find(prefix, 1)
            if idx > 0 and idx + size < len(stripped):
                before = stripped[:idx].rstrip()
                after = stripped[idx:].rstrip()
                if len(after) >= size and after.startswith(prefix):
                    return before
        return text

    def _terminal_stream_decision(self, text: str) -> str:
        stripped = text.lstrip()
        if not stripped:
            return "wait"
        lowered = stripped[:240].lower()
        if stripped[0] in {"{", "[", "`"}:
            return "block"
        if '"tool_calls"' in lowered or '"final"' in lowered or "tool_calls" in lowered:
            return "block"
        if len(stripped) < 24 and not re.search(r"[。！？.!?\n]", stripped):
            return "wait"
        return "show"

    def _actual_user_request_text(self, input_text: str) -> str:
        match = re.search(r"(?m)^content:\s*(.*)$", input_text)
        if match:
            return match.group(1).strip()
        return input_text

    def _prepare_tool_call(
        self,
        tool_name: str,
        payload: dict,
        source: str,
        input_text: str,
    ) -> tuple[str, dict]:
        tool_name = self._canonical_tool_name(tool_name)
        if tool_name == "schedule.create":
            enriched = dict(payload)
            enriched.setdefault("_source", source)
            if "source" not in enriched:
                enriched["source"] = source if source.startswith("channel:") else "schedule"
            if not isinstance(enriched.get("notify"), dict):
                notify = self._notification_target(source, input_text, include_wechat=True)
                if notify:
                    enriched["notify"] = notify
            return tool_name, enriched
        if tool_name.startswith("wechat.send_"):
            enriched = dict(payload)
            enriched["_source"] = source
            enriched["_input_text"] = input_text
            return tool_name, enriched
        if tool_name == "task.start":
            nested_tool = str(payload.get("tool") or "")
            nested_payload = payload.get("payload") or {}
            if (
                nested_tool == "skill.run"
                and isinstance(nested_payload, dict)
                and self._is_fast_skill_run(nested_payload)
            ):
                return nested_tool, nested_payload
        if tool_name == "task.agent_start":
            enriched = dict(payload)
            if "input" not in enriched:
                enriched["input"] = self._actual_user_request_text(input_text)
            if "ack" not in enriched and "message" not in enriched:
                final_text = str(enriched.get("final") or "").strip()
                if final_text:
                    enriched["ack"] = final_text
            if not isinstance(enriched.get("notify"), dict):
                notify = self._notification_target(source, input_text, include_wechat=True)
                if notify:
                    enriched["notify"] = notify
            return tool_name, enriched
        if self._should_auto_background(tool_name, payload, source):
            payload = {
                "tool": tool_name,
                "payload": payload,
                "description": f"Run {tool_name} in background",
                "replayable": True,
            }
            tool_name = "task.start"
        if tool_name != "task.start":
            return tool_name, payload
        enriched = dict(payload)
        if self._is_wechat869_source(source):
            enriched.pop("notify", None)
            return tool_name, enriched
        if not isinstance(enriched.get("notify"), dict):
            notify = self._notification_target(source, input_text)
            if notify:
                enriched["notify"] = notify
        return tool_name, enriched

    def _canonical_tool_name(self, tool_name: str) -> str:
        if self.tools.get(tool_name):
            return tool_name
        aliases = {
            "read_file": "filesystem.read_file",
            "write_file": "filesystem.write_file",
            "list_dir": "filesystem.list_dir",
            "delete_file": "filesystem.delete_path",
            "delete_path": "filesystem.delete_path",
            "shell": "shell.exec",
            "exec": "shell.exec",
            "run_shell": "shell.exec",
            "send_text": "wechat.send_text",
            "send_image": "wechat.send_image",
            "send_file": "wechat.send_file",
        }
        canonical = aliases.get(tool_name)
        if canonical and self.tools.get(canonical):
            logger.info("Agent 工具别名映射: {} -> {}", tool_name, canonical)
            return canonical
        return tool_name

    def _should_auto_background(self, tool_name: str, payload: dict, source: str) -> bool:
        if tool_name == "task.start" or source == "background":
            return False
        if not source.startswith("channel:"):
            return False
        if isinstance(payload, dict) and payload.get("foreground") is True:
            return False
        if tool_name == "skill.run" and self._is_fast_skill_run(payload):
            return False
        tool = self.tools.get(tool_name)
        if tool is None:
            return False
        return bool((tool.metadata or {}).get("background_candidate"))

    def _is_fast_skill_run(self, payload: dict) -> bool:
        return (
            str(payload.get("skill") or "") == "wechat-869-media-sender"
            and str(payload.get("action") or "") == "send-text"
        )

    def _background_started_message(self, tool_results: list[dict], *, plan_final: str = "") -> str:
        cleaned_final = self.planner.clean_final_output(plan_final or "").strip()
        if cleaned_final:
            return cleaned_final
        task_ids = []
        has_child_agent = False
        for result in tool_results:
            if result.get("tool") not in {"task.start", "task.agent_start"} or result.get("status") != "completed":
                continue
            if result.get("tool") == "task.agent_start":
                has_child_agent = True
            output = result.get("output")
            if isinstance(output, dict):
                metadata = output.get("metadata") if isinstance(output.get("metadata"), dict) else {}
                ack = str(metadata.get("ack") or metadata.get("message") or "").strip()
                if ack:
                    return ack
            if isinstance(output, dict) and output.get("id"):
                task_ids.append(str(output["id"]))
        if has_child_agent:
            return "我先安排子代理继续处理，完成后会把结果发回来。"
        prefix = "子代理任务" if has_child_agent else "后台任务"
        if task_ids:
            return f"{prefix}已开始，完成后会自动回发结果。任务ID：{', '.join(task_ids)}"
        return f"{prefix}已开始，完成后会自动回发结果。"

    def _has_child_agent_started(self, tool_results: list[dict]) -> bool:
        return any(
            result.get("tool") == "task.agent_start" and result.get("status") == "completed"
            for result in tool_results
        )

    def _should_return_after_background(self, source: str) -> bool:
        return not self._is_wechat869_source(source)

    def _is_wechat869_source(self, source: str) -> bool:
        parts = source.split(":", 3)
        return len(parts) >= 3 and parts[0] == "channel" and parts[2] == "wechat869"

    def _raw_wechat869_conversation_id(self, conversation_id: str) -> str:
        marker = "wechat:wechat869:"
        if conversation_id.startswith(marker):
            return conversation_id.split(":", 3)[-1]
        return conversation_id

    def _notification_target(self, source: str, input_text: str, *, include_wechat: bool = False) -> dict | None:
        if not source.startswith("channel:"):
            return None
        parts = source.split(":", 3)
        if len(parts) < 4:
            return None
        if parts[2] == "wechat869" and not include_wechat:
            return None
        message_id = ""
        match = re.search(r"(?m)^message_id:\s*(.+)$", input_text)
        if match:
            message_id = match.group(1).strip()
        return {
            "platform": parts[1],
            "adapter": parts[2],
            "conversation_id": parts[3],
            "quote_message_id": message_id or None,
        }

    def _agent_system_prompt(self, *, source: str = "api") -> str:
        current_time = self._current_time_prompt()
        static_prompt = self._static_agent_prompt(source=source)
        memory_prompt = self._memory_prompt()
        return static_prompt + memory_prompt + current_time

    def _static_agent_prompt(self, *, source: str = "api") -> str:
        if self.config.cache.enabled and self.config.cache.static_prompt:
            version = (self.tools.revision, self._skills_revision(), source)
            if self._static_prompt_cache and self._static_prompt_cache[0] == version:
                return self._static_prompt_cache[1]
            prompt = self._build_static_agent_prompt(source=source)
            self._static_prompt_cache = (version, prompt)
            return prompt
        return self._build_static_agent_prompt(source=source)

    def _build_static_agent_prompt(self, *, source: str = "api") -> str:
        skill_instructions = self._skill_instructions_prompt()
        toolsets = toolsets_for_source(self.config, source)
        context = source_context(source)
        tools = self.tools.list_tools(
            toolsets=toolsets,
            platform=context.get("platform"),
            scope=context.get("scope"),
            mode=self.config.mode,
        )
        return (
            "You are xbot's backend agent. Prefer native structured tool calls when tools are available from the model API. "
            "If native tool calls are unavailable, use the JSON fallback format exactly.\n"
            "Available tools:\n"
            f"{json.dumps(tools, ensure_ascii=False)}\n"
            f"{skill_instructions}"
            "Important tool-use rules:\n"
            "- If the user asks about current project state, files, directories, plugins, skills, config, logs, or runtime data, you MUST call tools first.\n"
            "- Do not answer project/file/plugin/skill inventory questions from memory.\n"
            "- To list plugin names, call filesystem.list_dir with path \"plugins\" first, then summarize the directory names.\n"
            "- To inspect a file, call filesystem.read_file first.\n"
            "- To inspect a directory, call filesystem.list_dir. Never call filesystem.read_file on a directory.\n"
            "- If the user asks about installed commands, browser availability, ports, proxies, or runtime environment, call environment.snapshot or environment.which first.\n"
            "- Tools marked with metadata.background_candidate are good candidates for task.start when the request may take time or the user does not need an immediate result.\n"
            "- For long-running screenshots, browser interactions, downloads, GitHub Actions logs, or skill execution, prefer task.start so the request can run in the background.\n"
            "- For longer multi-step work where the user can receive an immediate acknowledgement and a later result, prefer task.agent_start to delegate a full child Agent task in the background. When using task.agent_start, include an ack/message in your own voice for the user; do not rely on a system-generated task-id notice.\n"
            "- For reminders, recurring checks, daily summaries, scheduled follow-ups, or any task that should run later/periodically, use schedule.create. For channel-origin schedules, keep the current channel source and notification target so future results return to the same user or group.\n"
            "- If a tool result contains fallback guidance or suggested_tool, use that guidance before retrying.\n"
            "- Use memory.add proactively for durable user preferences, corrections, stable environment facts, and project conventions. Keep entries compact. Do not save temporary task progress.\n"
            "- If the user changes your name, identity, persona, or 'soul', save it to memory target=memory, not target=user. target=user is only for facts about the user.\n"
            "- Use memory.replace or memory.remove when a memory becomes outdated or too broad.\n"
            "- Use wiki.manage for structured project knowledge, architecture notes, research notes, design decisions, procedures, and reusable documentation. Query the wiki before answering from knowledge base content.\n"
            "- Do not put user preferences or temporary chat state in the wiki; use memory.* for durable preferences and short-term history for active task context.\n"
            "- When creating or using skills for channel requests, keep data/query/action logic separate from channel delivery. Skills should return results to the main Agent by default; the main Agent should compose the final answer in its own voice and let the runtime/channel tools handle sending. Do not make a query skill directly send WeChat messages unless the user explicitly asks for a sending skill.\n"
            "- To run a skill script or local command, call shell.exec only when policy allows it.\n"
            "- Browser GUI control and screenshots are not available unless a browser/screenshot skill or tool is listed.\n"
            "- If the user asks for an unavailable capability, explain that it is not currently available instead of waiting or pretending to do it.\n"
            "JSON fallback when native tool calls are unavailable:\n"
            '{"tool_calls":[{"tool":"filesystem.read_file","payload":{"path":"README.md"}}]}\n'
            "When the task is complete without more tool calls, respond with JSON exactly like:\n"
            '{"final":"your concise final answer"}\n'
            "Do not expose tool_calls, tools JSON, tool execution logs, or internal planning to the user.\n"
            "Do not invent tool results. Request tools first, then use returned results."
        )

    def _memory_prompt(self) -> str:
        if not self.config.memory.enabled:
            return ""
        block = self.memory.format_for_system_prompt()
        if not block:
            return ""
        return (
            "\nLong-term memory snapshot from session start. Treat it as background context, "
            "not as a new user message. Current-session memory writes refresh in future sessions.\n"
            f"{block}\n"
        )

    def _skill_instructions_prompt(self) -> str:
        if not self.skills:
            return ""
        revision = self._skills_revision()
        if self.config.cache.enabled and self.config.cache.skills:
            if self._skill_prompt_cache and self._skill_prompt_cache[0] == revision:
                return self._skill_prompt_cache[1]
        items = []
        for item in self.skills.list_skills():
            name = item.get("name")
            if not name:
                continue
            instructions = self.skills.get_instructions(str(name))
            if not instructions:
                continue
            items.append(
                {
                    "name": name,
                    "description": item.get("description"),
                    "instructions": instructions[:4000],
                }
            )
        if not items:
            return ""
        prompt = (
            "Available skills. Follow these instructions when relevant:\n"
            f"{json.dumps(items, ensure_ascii=False)}\n"
        )
        if self.config.cache.enabled and self.config.cache.skills:
            self._skill_prompt_cache = (revision, prompt)
        return prompt

    def _skills_revision(self) -> int:
        return int(getattr(self.skills, "revision", 0) or 0)

    def _current_time_prompt(self) -> str:
        timezone_name = getattr(self.config, "timezone", None) or "Asia/Shanghai"
        try:
            now = datetime.now(ZoneInfo(str(timezone_name)))
        except ZoneInfoNotFoundError:
            if str(timezone_name) in {"Asia/Shanghai", "Asia/Chongqing"}:
                now = datetime.now(timezone(timedelta(hours=8), name="Asia/Shanghai"))
                timezone_name = "Asia/Shanghai"
            else:
                timezone_name = "UTC"
                now = datetime.now(timezone.utc)
        return (
            "Current runtime time:\n"
            f"- timezone: {timezone_name}\n"
            f"- datetime: {now.isoformat()}\n"
            f"- date: {now.date().isoformat()}\n"
        )
