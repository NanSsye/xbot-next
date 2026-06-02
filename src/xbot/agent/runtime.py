from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel, Field

from xbot.agent.background import BackgroundTaskManager, BackgroundTaskRecord
from xbot.agent.hermes_runtime import run_hermes_agent
from xbot.agent.mcp import MCPClientManager
from xbot.agent.scheduler import ScheduledJobManager
from xbot.agent.tool_registry import ToolDefinition, ToolRegistry
from xbot.core.config import AgentConfig
from xbot.core.exceptions import XBotError
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


class _PolicyFacade:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def snapshot(self) -> dict:
        return {
            "mode": self.config.mode,
            "admin_mode_allowed": self.config.admin_mode_allowed,
            "uses_hermes_runtime": self.config.uses_hermes_runtime,
            "note": "xbot self-developed Agent tools are disabled; Hermes owns tool execution.",
        }


class AgentRuntime:
    """xbot framework wrapper around embedded Hermes.

    xbot keeps task/event/background/scheduler APIs stable. The agentic loop,
    tool execution, session history, memory, skills, and self-improvement are
    delegated to Hermes.
    """

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
        self.policy = _PolicyFacade(config)
        self.tools = ToolRegistry()
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
        self._event_subscribers: set[AgentEventSubscriber] = set()
        self._suppress_channel_reply_task_ids: set[str] = set()
        self.background.subscribe(self._on_background_task_completed)
        self._register_hermes_tool_catalog()

    async def start(self) -> None:
        await self._restore_background_tasks()
        if self.config.schedule.enabled:
            await self.scheduler.start()
        await self.mcp.start()

    async def stop(self) -> None:
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
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.create_task(task_id, source, input_text)
        await self._add_event(task_id, "task.received", input_text)
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
            async with self.repository_provider() as repo:
                await repo.finish_task(result)
        await self._add_event(task_id, "task.completed", result.output)
        return result

    async def continue_task(self, task_id: str, user_input: str) -> AgentResult:
        output = await self._run_llm(task_id, user_input, source="api")
        result = AgentResult(
            task_id=task_id,
            source="api",
            status="completed",
            output=output,
            suppress_channel_reply=task_id in self._suppress_channel_reply_task_ids,
        )
        self._suppress_channel_reply_task_ids.discard(task_id)
        return result

    async def cancel_task(self, task_id: str) -> None:
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.add_event(task_id, "task.cancelled", "cancelled")

    async def execute_tool(
        self,
        tool_name: str,
        payload: dict | None = None,
        *,
        task_id: str | None = None,
        source: str = "api",
        background_ok: bool = True,
    ) -> ToolCallResult:
        task_id = task_id or str(uuid4())
        payload = payload or {}
        tool = self.tools.get(tool_name)
        if tool and tool.source == "plugin":
            try:
                value = tool.handler(payload)
                if hasattr(value, "__await__"):
                    value = await value
                result = ToolCallResult(task_id=task_id, tool=tool_name, status="completed", output=value)
            except Exception as exc:
                result = ToolCallResult(
                    task_id=task_id,
                    tool=tool_name,
                    status="failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            await self._add_event(task_id, "tool.completed" if result.status == "completed" else "tool.failed", result.model_dump(mode="json"))
            return result
        result = ToolCallResult(
            task_id=task_id,
            tool=tool_name,
            status="failed",
            error="xbot self-developed tool execution has been removed. Ask Hermes to perform this task through agent.run_task.",
            error_type="HermesRuntimeOnly",
        )
        await self._add_event(task_id, "tool.failed", result.model_dump(mode="json"))
        return result

    async def flush_memory(self, *, reason: str = "manual") -> dict:
        return {
            "success": True,
            "reason": reason,
            "runtime": "hermes",
            "message": "Hermes manages memory and self-improvement in data/hermes.",
        }

    def clear_session_history(self, source: str | None = None) -> None:
        # Hermes owns session history in data/hermes/state.db.
        return None

    def llm_status(self) -> dict:
        return {
            "enabled": self.config.llm.enabled,
            "provider": self.config.llm.provider,
            "base_url": self.config.llm.base_url,
            "model": self.config.llm.model,
            "uses_hermes_runtime": True,
        }

    def mcp_status(self) -> dict:
        return self.mcp.status()

    def visible_tools(self, *, source: str = "api") -> list[dict]:
        return self.tools.list_tools(mode=self.config.mode)

    async def reload_mcp(self) -> dict:
        await self.mcp.reload()
        return self.mcp.status()

    async def list_background_tasks(self, limit: int = 50) -> list[BackgroundTaskRecord]:
        if not self.repository_provider:
            return self.background.list(limit)
        async with self.repository_provider() as repo:
            records = [BackgroundTaskRecord.from_storage(item) for item in await repo.list_background_tasks(limit)]
        memory = {item.id: item for item in self.background.list(limit)}
        for item in records:
            memory[item.id] = memory.get(item.id, item)
        return list(memory.values())[:limit]

    async def get_background_task(self, task_id: str) -> BackgroundTaskRecord | None:
        item = self.background.get(task_id)
        if item is not None or not self.repository_provider:
            return item
        async with self.repository_provider() as repo:
            record = await repo.get_background_task(task_id)
        return BackgroundTaskRecord.from_storage(record) if record else None

    async def background_task_overview(self, limit: int = 20) -> dict:
        tasks = await self.list_background_tasks(limit)
        return {
            "total": len(tasks),
            "running": len([item for item in tasks if item.status == "running"]),
            "failed": len([item for item in tasks if item.status == "failed"]),
            "completed": len([item for item in tasks if item.status == "completed"]),
            "tasks": [item.model_dump(mode="json") for item in tasks],
        }

    async def replay_background_task(self, task_id: str) -> BackgroundTaskRecord:
        record = await self.get_background_task(task_id)
        if record is None:
            raise XBotError(f"Background task not found: {task_id}")
        metadata = record.metadata or {}
        input_text = str(metadata.get("input") or metadata.get("prompt") or "")
        if not input_text:
            raise XBotError("Only agent background tasks with input can be replayed.")

        async def runner() -> dict:
            result = await self.run_task(input_text, source=str(metadata.get("source") or record.source or "background"))
            return result.model_dump(mode="json")

        return self.background.replay(record, runner)

    async def list_events(self, task_id: str | None = None, limit: int = 100) -> list[dict]:
        if not self.repository_provider:
            return []
        async with self.repository_provider() as repo:
            records = await repo.list_events(task_id=task_id, limit=limit)
        return [
            {
                "task_id": record.task_id,
                "type": record.type,
                "content": self._event_content(record.content),
                "created_at": record.created_at.isoformat() if record.created_at else None,
            }
            for record in records
        ]

    async def list_tasks(self, limit: int = 50) -> list[dict]:
        if not self.repository_provider:
            return []
        async with self.repository_provider() as repo:
            records = await repo.list_tasks(limit)
        return [self._task_record_to_dict(record) for record in records]

    async def get_task_detail(self, task_id: str, *, event_limit: int = 300) -> dict | None:
        if not self.repository_provider:
            return None
        async with self.repository_provider() as repo:
            task = await repo.get_task(task_id)
            if task is None:
                return None
            events = await repo.list_events(task_id=task_id, limit=event_limit)
            artifacts = await repo.list_artifacts(task_id=task_id, limit=100)
        parsed_events = [
            {
                "task_id": event.task_id,
                "type": event.type,
                "content": self._event_content(event.content),
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ]
        return {
            "task": self._task_record_to_dict(task),
            "timeline": parsed_events,
            "tool_calls": [event for event in parsed_events if str(event.get("type", "")).startswith("tool.")],
            "repairs": [],
            "artifacts": [self._artifact_record_to_dict(record) for record in artifacts],
            "summary": {
                "event_count": len(parsed_events),
                "artifact_count": len(artifacts),
                "last_event": parsed_events[-1] if parsed_events else None,
            },
        }

    async def resume_task(self, task_id: str, *, source: str | None = None) -> AgentResult:
        detail = await self.get_task_detail(task_id)
        if not detail:
            raise XBotError(f"Agent task not found: {task_id}")
        task = detail["task"]
        resume_source = source or task.get("source") or "api"
        resume_input = (
            "Continue this existing xbot task using Hermes session context.\n"
            f"task_id: {task_id}\n"
            f"previous_input: {task.get('input') or ''}\n"
            f"previous_result: {task.get('result') or ''}"
        )
        await self._add_event(task_id, "task.resume_requested", {"source": resume_source})
        output = await self._run_llm(task_id, resume_input, source=resume_source)
        result = AgentResult(task_id=task_id, source=resume_source, status="completed", output=output)
        if self.repository_provider:
            async with self.repository_provider() as repo:
                await repo.finish_task(result)
        await self._add_event(task_id, "task.resume_completed", output)
        return result

    async def _run_llm(
        self,
        task_id: str,
        input_text: str,
        *,
        source: str = "api",
        attachments: list[dict] | None = None,
    ) -> str:
        return await run_hermes_agent(
            config=self.config,
            task_id=task_id,
            input_text=input_text,
            source=source,
            attachments=attachments,
            add_event=self._add_event,
            llm_status=self.llm_status,
        )

    async def _run_agent_for_task(self, input_text: str, source: str = "background") -> AgentResult:
        return await self.run_task(input_text, source=source or "background")

    async def _restore_background_tasks(self) -> None:
        if not self.repository_provider:
            return
        async with self.repository_provider() as repo:
            records = await repo.list_background_tasks(100)
        for record in records:
            item = BackgroundTaskRecord.from_storage(record)
            if item.status == "running":
                item = self.background.mark_stale(item, reason="Backend restarted before task finished.")
            self.background.remember(item)

    async def _on_background_task_completed(self, record: BackgroundTaskRecord) -> None:
        notify = (record.metadata or {}).get("notify")
        if not notify or not self.background.send_reply:
            return
        content = self.background._notification_content(record)
        await self.background.send_reply(
            Reply(
                platform=str(notify.get("platform") or "wechat"),
                adapter=str(notify.get("adapter") or ""),
                conversation_id=str(notify.get("conversation_id") or ""),
                text=content,
                raw={"target": notify},
            )
        )

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
        serialized = json.dumps(self._redact_payload(content), ensure_ascii=False, default=str)
        async with self.repository_provider() as repo:
            await repo.add_event(task_id, event_type, serialized)

    async def _publish_event(self, event: AgentRuntimeEvent) -> None:
        for subscriber in list(self._event_subscribers):
            result = subscriber(event)
            if hasattr(result, "__await__"):
                await result

    def _register_hermes_tool_catalog(self) -> None:
        names = [
            "web_search", "web_extract", "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "vision_analyze", "image_generate",
            "skills_list", "skill_view", "skill_manage",
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images", "browser_vision",
            "browser_console", "browser_cdp", "browser_dialog",
            "todo", "memory", "session_search", "execute_code",
            "delegate_task", "cronjob",
        ]
        for name in names:
            self.tools.register(
                ToolDefinition(
                    name=name,
                    description=f"Hermes tool: {name}",
                    risk_level="medium",
                    handler=lambda payload, _name=name: {
                        "error": f"{_name} is executed inside Hermes, not through xbot direct tool API."
                    },
                    input_schema={"type": "object"},
                    toolset="hermes",
                    source="hermes",
                    metadata={"runtime": "hermes"},
                )
            )

    def _task_record_to_dict(self, record) -> dict:
        return {
            "id": record.id,
            "status": record.status,
            "source": record.source,
            "input": record.input,
            "result": record.result,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def _artifact_record_to_dict(self, record) -> dict:
        metadata = {}
        if getattr(record, "metadata_json", None):
            try:
                metadata = json.loads(record.metadata_json)
            except json.JSONDecodeError:
                metadata = {}
        return {
            "id": record.id,
            "task_id": record.task_id,
            "kind": record.kind,
            "path": record.path,
            "content_hash": record.content_hash,
            "summary": record.summary,
            "metadata": metadata,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def _event_content(self, content: str) -> object:
        try:
            return json.loads(content)
        except (TypeError, json.JSONDecodeError):
            return content

    def _redact_payload(self, value: object) -> object:
        if isinstance(value, str):
            return self._redact_sensitive_text(value)
        if isinstance(value, dict):
            return {key: self._redact_payload(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_payload(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_payload(item) for item in value)
        return value

    def _redact_sensitive_text(self, text: str) -> str:
        redacted = text
        patterns = [
            r"(?i)(MINIMAX_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|XBOT_LLM_API_KEY|API_KEY|TOKEN|SECRET|PASSWORD)=([^&\s\"']+)",
            r"(?i)(sk-[A-Za-z0-9_\-]{12,})",
        ]
        for pattern in patterns:
            redacted = re.sub(pattern, lambda match: match.group(1) + "=***" if match.lastindex and match.lastindex >= 2 else "***", redacted)
        return redacted
