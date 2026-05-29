from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid4

import anyio
from pydantic import BaseModel, Field

from xbot.agent.background import BackgroundTaskManager
from xbot.agent.background import BackgroundTaskRecord
from xbot.agent.cache import TTLCache
from xbot.agent.compression import MemoryCompressor
from xbot.agent.llm import LLMMessage, LLMResponse, create_llm_provider
from xbot.agent.memory import MemoryStore
from xbot.agent.mcp import MCPClientManager
from xbot.agent.planner import AgentPlanner
from xbot.agent.policy import PolicyEngine
from xbot.agent.tool_executor import ToolExecutor
from xbot.agent.tool_registry import ToolRegistry
from xbot.agent.tools import register_builtin_tools
from xbot.agent.tools.browser_provider import register_browser_tools
from xbot.agent.tools.cache_policy import ToolCachePolicy
from xbot.agent.tools.environment_provider import register_environment_tools
from xbot.agent.tools.fallback_policy import ToolError, ToolFallbackPolicy
from xbot.agent.tools.git_provider import register_git_tools
from xbot.agent.tools.plugin_provider import register_plugin_tools
from xbot.agent.tools.skill_provider import SkillToolProvider
from xbot.agent.tools.task_provider import register_task_tools
from xbot.agent.tools.toolsets import source_context, toolsets_for_source
from xbot.agent.workspace import Workspace
from xbot.core.config import AgentConfig
from xbot.core.exceptions import PolicyDeniedError, XBotError
from xbot.core.logging import logger


class AgentResult(BaseModel):
    task_id: str
    source: str
    status: str
    output: str
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
        self.memory = MemoryStore()
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
        register_builtin_tools(
            self.tools,
            workspace=self.workspace,
            skills=self.skills,
            run_skill=self.skill_tools.run_skill,
        )
        register_environment_tools(self.tools, workspace=self.workspace)
        register_browser_tools(self.tools, workspace=self.workspace)
        register_git_tools(self.tools, workspace=self.workspace)
        register_task_tools(self.tools, background=self.background, execute_tool=self._execute_tool_for_task)

    async def start(self) -> None:
        register_plugin_tools(self.tools, self.plugins)
        self._static_prompt_cache = None
        await self._restore_background_tasks()
        await self.mcp.start()

    async def stop(self) -> None:
        await self.background.stop()
        await self.mcp.stop()

    def attach_reply_sender(self, send_reply) -> None:
        self.background.attach_reply_sender(send_reply)

    def subscribe_events(self, subscriber: AgentEventSubscriber) -> Callable[[], None]:
        self._event_subscribers.add(subscriber)

        def unsubscribe() -> None:
            self._event_subscribers.discard(subscriber)

        return unsubscribe

    async def run_task(self, input_text: str, source: str = "api") -> AgentResult:
        task_id = str(uuid4())
        logger.info("Agent 任务开始: task_id={} source={} input_chars={}", task_id, source, len(input_text))
        if self.repository_provider:
            logger.info("Agent 任务写入存储开始: task_id={}", task_id)
            async with self.repository_provider() as repo:
                await repo.create_task(task_id, source, input_text)
            await self._add_event(task_id, "task.received", input_text)
            logger.info("Agent 任务写入存储完成: task_id={}", task_id)
        else:
            await self._add_event(task_id, "task.received", input_text)
        memory_item = await self.memory.add("episodic", f"Task received from {source}: {input_text}")
        logger.info("Agent 任务进入 LLM: task_id={}", task_id)
        output = await self._run_llm(task_id, input_text, source=source)
        result = AgentResult(
            task_id=task_id,
            source=source,
            status="completed",
            output=output,
        )
        if self.repository_provider:
            logger.info("Agent 任务结果写入存储开始: task_id={}", task_id)
            async with self.repository_provider() as repo:
                await repo.save_memory(memory_item, source=source)
                await repo.finish_task(result)
            await self._add_event(task_id, "task.completed", result.output)
            logger.info("Agent 任务结果写入存储完成: task_id={}", task_id)
        else:
            await self._add_event(task_id, "task.completed", result.output)
        return result

    async def continue_task(self, task_id: str, user_input: str) -> AgentResult:
        output = await self._run_llm(task_id, user_input, source="api")
        return AgentResult(task_id=task_id, source="api", status="completed", output=output)

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
            raise XBotError(f"Tool not found: {tool_name}")
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

    async def _run_llm(self, task_id: str, input_text: str, *, source: str = "api") -> str:
        messages = [
            LLMMessage(role="system", content=self._agent_system_prompt(source=source)),
            LLMMessage(role="user", content=input_text),
        ]
        last_content = ""
        used_tool = False
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
                with anyio.fail_after(max(1, int(self.config.llm.timeout_seconds) + 5)):
                    response = await self._complete_llm(
                        messages,
                        task_id=task_id,
                        iteration=iteration,
                        source=source,
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
            plan = self.planner.parse_llm_response(response.content)
            logger.info(
                "Agent LLM 解析结果: task_id={} iteration={} tool_calls={} final_chars={}",
                task_id,
                iteration,
                len(plan.tool_calls),
                len(plan.final or ""),
            )
            if not plan.tool_calls:
                cleaned = self.planner.clean_final_output(plan.final or response.content)
                if (
                    (
                        self.planner.contains_tool_call_intent(response.content)
                        and not cleaned.strip()
                    )
                    or
                    self.planner.is_empty_final_response(response.content)
                    or not cleaned.strip()
                    or self._must_continue_for_missing_tool(input_text, cleaned, used_tool)
                ):
                    if self.config.max_tool_iterations > 0 and iteration >= self.config.max_tool_iterations:
                        return "这个请求需要继续调用工具，但已达到配置的工具循环上限。"
                    missing_tool_reprompts += 1
                    if missing_tool_reprompts > 3:
                        logger.warning(
                            "Agent 连续未发起必要工具调用: task_id={} reprompts={}",
                            task_id,
                            missing_tool_reprompts,
                        )
                        return "这个请求需要调用工具读取当前状态，但模型连续没有发起工具调用，请换一种更明确的说法再试。"
                    messages.append(LLMMessage(role="assistant", content=response.content))
                    messages.append(
                        LLMMessage(
                            role="user",
                            content=(
                                "Your previous response was empty, incomplete, or did not call required tools. "
                                "If the request depends on current project files, directories, plugins, skills, "
                                "config, logs, or runtime state, you must call tools first. "
                                "Do not say you are checking; actually request tool_calls. "
                                "If you return tool_calls, the JSON must be valid and complete. "
                                "Otherwise return JSON with a non-empty final answer."
                            ),
                        )
                    )
                    iteration += 1
                    continue
                return cleaned
            missing_tool_reprompts = 0
            if self.config.max_tool_iterations > 0 and iteration >= self.config.max_tool_iterations:
                return self.planner.clean_final_output(
                    plan.final or "工具调用次数达到上限，任务没有完成。"
                )

            tool_results = []
            background_started = False
            for call in plan.tool_calls:
                tool_name, payload = self._prepare_tool_call(call.tool, call.payload, source, input_text)
                result = await self.execute_tool(
                    tool_name,
                    payload,
                    task_id=task_id,
                    source="agent",
                )
                used_tool = True
                if tool_name == "task.start" and result.status == "completed":
                    background_started = True
                tool_results.append(result.model_dump(mode="json"))
            if background_started and self._should_return_after_background(source):
                return self._background_started_message(tool_results)
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
        if self._request_requires_current_state_tool(input_text) and not used_tool:
            return "这个请求需要读取当前项目状态，但我没有成功调用工具，请稍后重试。"
        cleaned = self.planner.clean_final_output(last_content)
        return cleaned if cleaned and not self.planner.is_empty_final_response(cleaned) else "我没有生成有效回复，请换一种说法再试。"

    async def _complete_llm(
        self,
        messages: list[LLMMessage],
        *,
        task_id: str,
        iteration: int,
        source: str,
    ) -> LLMResponse:
        stream = getattr(self.llm, "stream", None)
        if not source.startswith("terminal:") or stream is None:
            return await self.llm.complete(messages)

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
                return await self.llm.complete(messages)
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

    def _must_continue_for_missing_tool(self, input_text: str, output: str, used_tool: bool) -> bool:
        if used_tool:
            return False
        if not self._request_requires_current_state_tool(input_text):
            return False
        if not output.strip():
            return True
        transitional_patterns = (
            r"正在.*(查看|读取|检查|列出|获取|查询)",
            r"我(先|将|会|来).*(查看|读取|检查|列出|获取|查询)",
            r"(稍等|请稍等|马上|现在).*(查看|读取|检查|列出|获取|查询)",
        )
        if any(re.search(pattern, output) for pattern in transitional_patterns):
            return True
        return True

    def _request_requires_current_state_tool(self, input_text: str) -> bool:
        text = self._actual_user_request_text(input_text).lower()
        current_state_terms = (
            "目录",
            "文件",
            "插件",
            "plugin",
            "plugins",
            "skill",
            "skills",
            "配置",
            "日志",
            "运行状态",
            "当前项目",
            "列出",
            "读取",
            "查看",
            "检查",
        )
        return any(term in text for term in current_state_terms)

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

    def _should_auto_background(self, tool_name: str, payload: dict, source: str) -> bool:
        if tool_name == "task.start" or source == "background":
            return False
        if not source.startswith("channel:"):
            return False
        if isinstance(payload, dict) and payload.get("foreground") is True:
            return False
        tool = self.tools.get(tool_name)
        if tool is None:
            return False
        return bool((tool.metadata or {}).get("background_candidate"))

    def _background_started_message(self, tool_results: list[dict]) -> str:
        task_ids = []
        for result in tool_results:
            if result.get("tool") != "task.start" or result.get("status") != "completed":
                continue
            output = result.get("output")
            if isinstance(output, dict) and output.get("id"):
                task_ids.append(str(output["id"]))
        if task_ids:
            return f"后台任务已开始，完成后会自动回发结果。任务ID：{', '.join(task_ids)}"
        return "后台任务已开始，完成后会自动回发结果。"

    def _should_return_after_background(self, source: str) -> bool:
        return not self._is_wechat869_source(source)

    def _is_wechat869_source(self, source: str) -> bool:
        parts = source.split(":", 3)
        return len(parts) >= 3 and parts[0] == "channel" and parts[2] == "wechat869"

    def _notification_target(self, source: str, input_text: str) -> dict | None:
        if not source.startswith("channel:"):
            return None
        parts = source.split(":", 3)
        if len(parts) < 4:
            return None
        if parts[2] == "wechat869":
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
        return static_prompt + current_time

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
            "You are xbot's backend agent. You can request tool calls through JSON only.\n"
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
            "- If a tool result contains fallback guidance or suggested_tool, use that guidance before retrying.\n"
            "- To run a skill script or local command, call shell.exec only when policy allows it.\n"
            "- Browser GUI control and screenshots are not available unless a browser/screenshot skill or tool is listed.\n"
            "- If the user asks for an unavailable capability, explain that it is not currently available instead of waiting or pretending to do it.\n"
            "When a tool is needed, respond with JSON exactly like:\n"
            '{"tool_calls":[{"tool":"filesystem.read_file","payload":{"path":"README.md"}}]}\n'
            "When the task is complete, respond with JSON exactly like:\n"
            '{"final":"your concise final answer"}\n'
            "Do not expose tool_calls, tools JSON, tool execution logs, or internal planning to the user.\n"
            "Do not invent tool results. Request tools first, then use returned results."
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
