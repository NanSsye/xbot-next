from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid4

import anyio
from pydantic import BaseModel, Field

from xbot.agent.cache import TTLCache
from xbot.agent.compression import MemoryCompressor
from xbot.agent.llm import LLMMessage, create_llm_provider
from xbot.agent.memory import MemoryStore
from xbot.agent.mcp import MCPClientManager
from xbot.agent.planner import AgentPlanner
from xbot.agent.policy import PolicyEngine
from xbot.agent.tool_executor import ToolExecutor
from xbot.agent.tool_registry import ToolRegistry
from xbot.agent.tools import register_builtin_tools
from xbot.agent.tools.browser_provider import register_browser_tools
from xbot.agent.tools.cache_policy import ToolCachePolicy
from xbot.agent.tools.git_provider import register_git_tools
from xbot.agent.tools.plugin_provider import register_plugin_tools
from xbot.agent.tools.skill_provider import SkillToolProvider
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
    created_at: datetime = Field(default_factory=datetime.utcnow)


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
        self.memory = MemoryStore()
        self.compressor = MemoryCompressor()
        self.planner = AgentPlanner()
        self.llm = llm_provider or create_llm_provider(config.llm)
        self._tool_result_cache = TTLCache(config.cache.tool_result_ttl_seconds)
        self.cache_policy = ToolCachePolicy(config, self.workspace, self.policy, self.skills)
        self.skill_tools = SkillToolProvider(workspace=self.workspace, skills=self.skills)
        self._static_prompt_cache: tuple[tuple[object, ...], str] | None = None
        self._skill_prompt_cache: tuple[int, str] | None = None
        register_builtin_tools(
            self.tools,
            workspace=self.workspace,
            skills=self.skills,
            run_skill=self.skill_tools.run_skill,
        )
        register_browser_tools(self.tools, workspace=self.workspace)
        register_git_tools(self.tools, workspace=self.workspace)

    async def start(self) -> None:
        register_plugin_tools(self.tools, self.plugins)
        self._static_prompt_cache = None
        await self.mcp.start()

    async def stop(self) -> None:
        await self.mcp.stop()

    async def run_task(self, input_text: str, source: str = "api") -> AgentResult:
        task_id = str(uuid4())
        logger.info("Agent 任务开始: task_id={} source={} input_chars={}", task_id, source, len(input_text))
        if self.repository_provider:
            logger.info("Agent 任务写入存储开始: task_id={}", task_id)
            async with self.repository_provider() as repo:
                await repo.create_task(task_id, source, input_text)
                await repo.add_event(task_id, "task.received", input_text)
            logger.info("Agent 任务写入存储完成: task_id={}", task_id)
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
                await repo.add_event(task_id, "task.completed", result.output)
            logger.info("Agent 任务结果写入存储完成: task_id={}", task_id)
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
            )
            await self._add_event(
                task_id,
                "tool.denied",
                {"tool": tool_name, "risk_level": tool.risk_level, "error": str(exc)},
            )
            return result
        except Exception as exc:
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
            )
            await self._add_event(
                task_id,
                "tool.failed",
                {"tool": tool_name, "risk_level": tool.risk_level, "error": str(exc)},
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

    async def reload_mcp(self) -> dict:
        await self.mcp.reload()
        self._static_prompt_cache = None
        return self.mcp.status()

    async def _add_event(self, task_id: str, event_type: str, content: object) -> None:
        if not self.repository_provider:
            return
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        async with self.repository_provider() as repo:
            await repo.add_event(task_id, event_type, content)

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
                    response = await self.llm.complete(messages)
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
            for call in plan.tool_calls:
                result = await self.execute_tool(
                    call.tool,
                    call.payload,
                    task_id=task_id,
                    source="agent",
                )
                used_tool = True
                tool_results.append(result.model_dump(mode="json"))
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
            timezone_name = "UTC"
            now = datetime.now(timezone.utc)
        return (
            "Current runtime time:\n"
            f"- timezone: {timezone_name}\n"
            f"- datetime: {now.isoformat()}\n"
            f"- date: {now.date().isoformat()}\n"
        )
